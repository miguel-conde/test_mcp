# Especificación MCP RLM Server

## Tabla de contenidos

1. [Objetivo del servidor MCP](#1-objetivo-del-servidor-mcp)
2. [Modelo de datos](#2-modelo-de-datos)
   - 2.1. [Entidades principales](#21-entidades-principales)
  - 2.2. [Entorno de ejecución (REPL) y sesiones](#22-entorno-de-ejecución-repl-y-sesiones)
3. [Herramientas MCP (tools) a implementar](#3-herramientas-mcp-tools-a-implementar)
   - 3.1. [`load_corpus`](#31-load_corpus)
   - 3.2. [`list_corpus`](#32-list_corpus)
   - 3.3. [`describe_corpus`](#33-describe_corpus)
   - 3.4. [`list_sections`](#34-list_sections)
   - 3.5. [`list_chunks`](#35-list_chunks)
   - 3.6. [`get_chunk`](#36-get_chunk)
   - 3.7. [`search_corpus`](#37-search_corpus)
   - 3.8. [`delete_corpus`](#38-delete_corpus)
  - 3.9. [`open_session`](#39-open_session)
  - 3.10. [`exec_repl`](#310-exec_repl)
  - 3.11. [`close_session`](#311-close_session)
4. [Requisitos no funcionales](#4-requisitos-no-funcionales)
   - 4.1. [Escalabilidad](#41-escalabilidad)
   - 4.2. [Rendimiento](#42-rendimiento)
   - 4.3. [Seguridad](#43-seguridad)
5. [Flujo típico de uso](#5-flujo-típico-de-uso-para-el-equipo-de-desarrollo)
6. [Notas para implementación](#6-notas-para-implementación)

---

# 1. Objetivo del servidor MCP

Diseñar e implementar un servidor MCP llamado, por ejemplo, `rlm-corpus-server`, que proporcione a un LLM (usado vía VS Code Copilot u otro cliente MCP) una **API de navegación programática y un entorno de ejecución tipo REPL** sobre uno o varios corpus de texto largos, análogo al entorno descrito en el paper de Recursive Language Models.

El servidor debe permitir:

1. **Registrar corpus** (uno o varios documentos o textos largos) y obtener un `corpus_id`.
2. **Explorar su estructura**: documentos, secciones, chunks.
3. **Leer fragmentos concretos** (chunks) on-demand.
4. **Buscar** en el corpus (búsqueda literal y, opcionalmente, semántica).
5. **Gestionar sesiones**: permitir varias sesiones/usuarios, purgar corpus, etc.

Además, para replicar fielmente el runtime del paper, el servidor debe permitir:

6. **Abrir sesiones de ejecución (REPL) stateful** vinculadas a un `corpus_id`.
7. **Ejecutar código Python** en esa sesión para “minar” el corpus (iterar, filtrar, agrupar, regex, joins/aggregations, construir representaciones intermedias, extraer features, construir índices, etc.).
8. (Opcional) Exponer una función **`llm_query(...)`** dentro del REPL para llamadas recursivas a un sub-LLM con presupuesto/limitaciones configurables.

El LLM utilizará estas herramientas para implementar estrategias **recursivas** tipo RLM: planificar → seleccionar bloques → leer chunks → componer.

---

# 2. Modelo de datos

## 2.1. Entidades principales

* **Corpus**

  * `corpus_id: string`
  * `name: string`
  * `created_at: datetime`
  * `meta: object` (información adicional: origen, idioma, tipo de documento, etc.)

* **Document**

  * `document_id: string`
  * `corpus_id: string`
  * `path_or_name: string` (nombre de fichero, título, etc.)
  * `meta: object` (autor, tipo, etc.)

* **Section** (opcional, si se detecta estructura lógica: capítulos, headings, etc.)

  * `section_id: string`
  * `document_id: string`
  * `title: string`
  * `level: int` (1=h1, 2=h2, etc.)
  * `start_offset: int` (en caracteres o tokens dentro del documento)
  * `end_offset: int`
  * `meta: object`

* **Chunk**

  * `chunk_id: string`
  * `document_id: string`
  * `section_id: string | null`
  * `start_offset: int`
  * `end_offset: int`
  * `text: string` (puede no almacenarse completo en memoria si se recomputa on-demand)
  * `meta: object` (por ejemplo: índice de chunk, longitud en tokens, etc.)

* **SearchResult**

  * `query: string`
  * `corpus_id: string`
  * `results: array` de:

    * `chunk_id: string`
    * `score: number`
    * `snippet: string`

---

## 2.2. Entorno de ejecución (REPL) y sesiones

El paper presupone un runtime donde el modelo **no “lee” el corpus como tokens**, sino que **escribe y ejecuta código** contra una representación del corpus (`context`) dentro de un REPL. Para soportarlo en MCP, el servidor añade el concepto de **sesión de ejecución**.

### `Session`

* `session_id: string`
* `corpus_id: string`
* `created_at: datetime`
* `last_activity_at: datetime`
* `context_view: string` (p. ej. `"by_chunk"`, `"by_document"`, `"raw_text"`)
* `enable_llm_query: boolean`
* `limits: object`

  * `max_execs_per_session: int`

* `state_meta: object` (por ejemplo: número de ejecuciones, total de tiempo CPU consumido, contador de llamadas a `llm_query`, etc.)

**Semántica**:

* Cada `Session` corresponde a un entorno REPL aislado y stateful.
* El REPL expone una variable **`context`** que representa el corpus vinculado a `corpus_id` según `context_view`.
* El estado (variables definidas) persiste entre llamadas a `exec_repl`.

### Contrato de `context` y `context_meta`

Para alinearse con los ejemplos del paper/guía (donde el modelo itera sobre `context` y hace operaciones tipo `chunk.lower()`), el servidor debe exponer:

* `context`: **string** o **list[string]** (según `context_view`).
* `context_meta`: metadatos alineados con `context`.

| `context_view` | Tipo de `context` | Tipo de `context_meta` | Semántica |
|---|---|---|---|
| `raw_text` | `str` | `object` | `context` contiene el texto completo concatenado del corpus (con separadores entre documentos si aplica). `context_meta` incluye al menos `corpus_id`, `num_documents`, `length_chars`. |
| `by_document` | `list[str]` | `list[object]` | `context[i]` es el texto del documento i-ésimo. `context_meta[i]` incluye al menos `document_id`, `document_name`, `length_chars`, `num_chunks` (si existe). |
| `by_chunk` | `list[str]` | `list[object]` | `context[i]` es el texto del chunk i-ésimo. `context_meta[i]` incluye al menos `chunk_id`, `document_id`, `section_id`, `index`, `start_offset`, `end_offset`. |

Notas:

* `context` y `context_meta` deben tratarse como **read-only**; el modelo puede crear estructuras derivadas (buffers, índices) en variables propias.
* Esta elección (lista de strings + metadatos paralelos) permite código estilo `for i, chunk in enumerate(context): ...` sin obligar a indexar por clave (`item["text"]`).

### Contrato de `llm_query(...)`

Si `enable_llm_query=true`, el entorno REPL expone una función:

* `llm_query(prompt: str) -> str`

La implementación específica de `llm_query` se deja a criterio del servidor (puede usar un modelo configurado localmente, delegar la llamada de vuelta al cliente, o implementar un mecanismo simplificado).

### `ExecutionResult` (contrato de salida)

No es necesario persistirlo en el modelo, pero sirve como contrato de salida de `exec_repl`.

* `stdout: string`
* `stderr: string`
* `truncated: boolean`
* `exports: object` (mapa `nombre -> valor` serializado/representación segura)
* `usage: object` (tiempo de ejecución, llamadas a `llm_query`, tokens/coste si aplica)

---

# 3. Herramientas MCP (tools) a implementar

Cada herramienta MCP se define con:

* `name` (string)
* `description` (string)
* `inputSchema` (JSON Schema)
* **Salida**: objeto JSON libre (pero aquí definimos un contrato esperado).

A continuación, las herramientas mínimas que recomiendo para replicar el entorno del paper.

---

## 3.1. `load_corpus`

**Propósito**
Registrar uno o varios documentos (texto crudo) como un corpus y devolver un `corpus_id`. El origen real del texto (fichero, attachment, etc.) lo gestiona el lado servidor; el LLM solo ve el texto o el identificador que se le pase en la llamada.

**Nombre**
`load_corpus`

**Input schema** (ejemplo):

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Nombre del corpus (para referencia humana)."
    },
    "documents": {
      "type": "array",
      "description": "Lista de documentos a registrar en el corpus.",
      "items": {
        "type": "object",
        "properties": {
          "document_name": { "type": "string" },
          "text": {
            "type": "string",
            "description": "Contenido completo del documento en texto plano."
          },
          "meta": {
            "type": "object",
            "description": "Metadatos opcionales (autor, tipo, etc.)."
          }
        },
        "required": ["document_name", "text"]
      }
    },
    "chunk_size_chars": {
      "type": "integer",
      "description": "Tamaño de los chunks en caracteres.",
      "default": 4000,
      "minimum": 500
    },
    "chunk_overlap_chars": {
      "type": "integer",
      "description": "Solapamiento entre chunks en caracteres.",
      "default": 400,
      "minimum": 0
    }
  },
  "required": ["name", "documents"]
}
```

**Salida esperada**:

```json
{
  "corpus_id": "string",
  "documents": [
    {
      "document_id": "string",
      "document_name": "string",
      "num_chunks": 42
    }
  ]
}
```

---

## 3.2. `list_corpus`

**Propósito**
Listar los corpus registrados (útil cuando el LLM trabaja en varias tareas en paralelo).

**Nombre**
`list_corpus`

**Input schema**

```json
{
  "type": "object",
  "properties": {},
  "additionalProperties": false
}
```

**Salida esperada**:

```json
{
  "corpora": [
    {
      "corpus_id": "string",
      "name": "string",
      "created_at": "2025-01-17T12:34:56Z",
      "num_documents": 3
    }
  ]
}
```

---

## 3.3. `describe_corpus`

**Propósito**
Obtener un resumen de alto nivel de un corpus: documentos, longitudes, etc.

**Nombre**
`describe_corpus`

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "corpus_id": {
      "type": "string",
      "description": "Identificador del corpus."
    }
  },
  "required": ["corpus_id"]
}
```

**Salida esperada**:

```json
{
  "corpus_id": "string",
  "name": "string",
  "created_at": "2025-01-17T12:34:56Z",
  "documents": [
    {
      "document_id": "string",
      "document_name": "string",
      "num_chunks": 42,
      "estimated_tokens": 123456
    }
  ]
}
```

---

## 3.4. `list_sections` (opcional pero recomendable)

**Propósito**
Exponer la **estructura lógica** de los documentos (capítulos, headings). Muy útil para un RLM planner.

**Nombre**
`list_sections`

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "corpus_id": { "type": "string" },
    "document_id": {
      "type": "string",
      "description": "Si se omite, listar secciones de todos los documentos."
    },
    "max_level": {
      "type": "integer",
      "description": "Profundidad máxima (1=h1, 2=h2...).",
      "default": 3
    }
  },
  "required": ["corpus_id"]
}
```

**Salida esperada**:

```json
{
  "sections": [
    {
      "section_id": "string",
      "document_id": "string",
      "title": "Introducción",
      "level": 1,
      "start_offset": 0,
      "end_offset": 1234,
      "meta": {
        "chunk_ids": ["chunk-0001", "chunk-0002"]
      }
    }
  ]
}
```

---

## 3.5. `list_chunks`

**Propósito**
Listar los chunks de un corpus/documento (y, opcionalmente, filtrar por sección).

**Nombre**
`list_chunks`

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "corpus_id": { "type": "string" },
    "document_id": {
      "type": "string",
      "description": "Opcional: restringir a un documento concreto."
    },
    "section_id": {
      "type": "string",
      "description": "Opcional: restringir a una sección concreta."
    },
    "limit": {
      "type": "integer",
      "description": "Número máximo de chunks a devolver.",
      "default": 100
    },
    "offset": {
      "type": "integer",
      "description": "Desplazamiento para paginación.",
      "default": 0
    }
  },
  "required": ["corpus_id"]
}
```

**Salida esperada**:

```json
{
  "chunks": [
    {
      "chunk_id": "string",
      "document_id": "string",
      "section_id": "string",
      "index": 0,
      "start_offset": 0,
      "end_offset": 4096,
      "estimated_tokens": 900
    }
  ]
}
```

---

## 3.6. `get_chunk`

**Propósito**
Recuperar el texto de un chunk concreto (equivalente a “peek(start, end)” en el REPL del paper).

**Nombre**
`get_chunk`

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "corpus_id": { "type": "string" },
    "chunk_id": { "type": "string" },
    "with_meta": {
      "type": "boolean",
      "description": "Si true, incluye metadatos del chunk y su sección.",
      "default": true
    }
  },
  "required": ["corpus_id", "chunk_id"]
}
```

**Salida esperada**:

```json
{
  "corpus_id": "string",
  "chunk_id": "string",
  "document_id": "string",
  "section_id": "string",
  "text": "Lorem ipsum...",
  "meta": {
    "index": 0,
    "start_offset": 0,
    "end_offset": 4096,
    "section_title": "Introducción"
  }
}
```

---

## 3.7. `search_corpus`

**Propósito**
Permitir al modelo localizar **regiones relevantes** del corpus para una query, sin necesidad de escanearlo linealmente. Esto es clave en RLM.

**Nombre**
`search_corpus`

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "corpus_id": { "type": "string" },
    "query": {
      "type": "string",
      "description": "Consulta de búsqueda (texto libre)."
    },
    "top_k": {
      "type": "integer",
      "description": "Número máximo de resultados.",
      "default": 10,
      "minimum": 1
    },
    "semantic": {
      "type": "boolean",
      "description": "Si true, usar búsqueda semántica además de literal (si está disponible).",
      "default": true
    }
  },
  "required": ["corpus_id", "query"]
}
```

**Salida esperada**:

```json
{
  "results": [
    {
      "chunk_id": "string",
      "document_id": "string",
      "section_id": "string",
      "score": 0.87,
      "snippet": "Frase corta donde aparece el término...",
      "meta": {
        "position": 0
      }
    }
  ]
}
```

La implementación concreta de `semantic` (embeddings, ANN, etc.) se deja a criterio del equipo.

---

## 3.8. `delete_corpus` (gestión)

**Propósito**
Eliminar un corpus (para limpieza de recursos).

**Nombre**
`delete_corpus`

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "corpus_id": { "type": "string" }
  },
  "required": ["corpus_id"]
}
```

**Salida esperada**:

```json
{
  "deleted": true
}
```

---

## 3.9. `open_session`

**Propósito**
Abrir una sesión de ejecución (REPL) **stateful** asociada a un `corpus_id`. Esta sesión inicializa el runtime del paper exponiendo `context` (representación del corpus) y, opcionalmente, `llm_query`.

**Nombre**
`open_session`

**Input schema** (ejemplo):

```json
{
  "type": "object",
  "properties": {
    "corpus_id": { "type": "string" },
    "context_view": {
      "type": "string",
      "description": "Cómo representar el corpus dentro del REPL.",
      "default": "by_chunk",
      "enum": ["by_chunk", "by_document", "raw_text"]
    },
    "enable_llm_query": {
      "type": "boolean",
      "description": "Si true, expone llm_query(...) dentro del REPL con límites y budget.",
      "default": false
    },

    "limits": {
      "type": "object",
      "description": "Límites básicos de ejecución.",
      "properties": {
        "max_execs_per_session": { "type": "integer", "default": 200, "minimum": 1 }
      },
      "additionalProperties": false
    }
  },
  "required": ["corpus_id"],
  "additionalProperties": false
}
```

**Salida esperada**:

```json
{
  "session_id": "string",
  "corpus_id": "string",
  "context_view": "by_chunk",
  "enable_llm_query": false,
  "limits": {
    "max_execs_per_session": 200
  },
  "context_summary": "string"
}
```

---

## 3.10. `exec_repl`

**Propósito**
Ejecutar un bloque de código Python dentro de una sesión REPL previamente abierta. Este es el mecanismo central para que el modelo pueda **minar el corpus** (iterar/filtrar/agrupar/regex/crear índices/extraer features/crear buffers) sin leerlo completo como contexto.

**Nombre**
`exec_repl`

**Input schema** (ejemplo):

```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" },
    "code": {
      "type": "string",
      "description": "Código Python completo a ejecutar dentro del entorno stateful de la sesión."
    },
    "capture_variables": {
      "type": "array",
      "description": "Lista de variables a serializar y devolver como exports.",
      "items": { "type": "string" },
      "default": []
    }
  },
  "required": ["session_id", "code"],
  "additionalProperties": false
}
```

**Salida esperada**:

```json
{
  "session_id": "string",
  "stdout": "string",
  "stderr": "string",
  "truncated": false,
  "exports": {
    "final_answer": "string"
  },
  "usage": {
    "exec_count": 1
  }
}
```

**Semántica**

* El entorno mantiene estado entre ejecuciones (variables, resultados intermedios, índices, etc.).
* `context` debe estar disponible en la sesión y representar el corpus según `context_view`.
* Si `enable_llm_query=true`, el entorno expone `llm_query(prompt: str)`.

**Mecanismo de respuesta final (alineado con `FINAL_VAR`)**

La guía/paper usan señales tipo `FINAL(...)` / `FINAL_VAR(nombre_variable)`. En esta especificación, el mecanismo canónico para obtener la respuesta final es:

* `capture_variables=["final_answer"]` + lectura de `exports.final_answer`.

Esto es más robusto que parsear una señal textual. Si se desea compatibilidad adicional, el servidor *puede* soportar que el código imprima `FINAL(...)` en `stdout`, pero no debe ser el único mecanismo de salida.

---

## 3.11. `close_session`

**Propósito**
Cerrar una sesión REPL y liberar recursos asociados (memoria, handles, contadores, etc.).

**Nombre**
`close_session`

**Input schema**:

```json
{
  "type": "object",
  "properties": {
    "session_id": { "type": "string" }
  },
  "required": ["session_id"],
  "additionalProperties": false
}
```

**Salida esperada**:

```json
{
  "closed": true
}
```

---

# 4. Requisitos no funcionales

## 4.1. Escalabilidad

* Soportar corpus de **decenas de millones de tokens** (similar a lo descrito en el paper).
* Uso de almacenamiento en disco / base de datos para los textos y metadatos; no cargar todo en memoria.
* Indexado incremental:

  * Índice de chunks (posición, offsets).
  * Índice de búsqueda (inverted index / embeddings).

## 4.2. Rendimiento

* `get_chunk`: latencia baja (lectura directa por offset).
* `search_corpus`: puede ser más costoso; usar indexación eficiente.
* Soportar uso concurrente de múltiples sesiones/usuarios.

## 4.3. Seguridad

* Aislamiento básico:

  * Sesiones independientes por workspace.
  * Validación básica de entrada (tamaño razonable de documentos).

* Entorno REPL:

  * Uso responsable: el código ejecutado tiene acceso normal al entorno Python.
  * El administrador del workspace es responsable del código ejecutado.
  * **Modo sandbox opcional:** al definir `RLM_USE_RESTRICTED_PYTHON=1` el servidor compila el código con RestrictedPython, limitando builtins e imports. Sólo se permite importar `math`, `re`, `json` y se exponen helpers como `enumerate`, `range`, `len`, `sum`, `min`, `max`, `sorted`, `zip`, `map`, `filter`, `any`, `all`, `print`. Este modo es recomendable para despliegues productivos y está documentado en `plans/rlm-corpus-server/implementation.md`.

---

# 5. Flujo típico de uso (para el equipo de desarrollo)

Este es el flujo que un agente RLM (como el que definimos antes en `.agent.md`) seguiría usando este servidor:

1. El cliente (Copilot / agente) llama a `load_corpus` con uno o varios documentos de texto (derivados de ficheros adjuntos, PDFs ya convertidos, etc.).
2. El servidor devuelve `corpus_id` y lista de documentos.
3. El agente puede:

   * Llamar a `describe_corpus` para contextualizar.
   * Llamar a `list_sections` para construir un mapa de alto nivel.
4. El agente usa `search_corpus` para localizar zonas relevantes en función de la pregunta del usuario.
5. Para cada resultado relevante, el agente llama a `get_chunk` para leer en detalle ese fragmento.
6. El agente combina los análisis de varios chunks para componer la respuesta final.
7. Al acabar, el cliente puede llamar a `delete_corpus` para liberar recursos.

Este ciclo reproduce el patrón del paper en su parte de navegación: el LLM no recibe el corpus completo, sino **una interfaz de navegación estructurada**.

### 5.1. Ejemplo de uso tipo REPL (paper-faithful)

Para replicar el runtime descrito en el paper (minería programática), el flujo recomendado es:

1. El cliente llama a `load_corpus` y obtiene un `corpus_id`.
2. El agente llama a `open_session` con `corpus_id` y recibe un `session_id`.
3. El agente llama a `exec_repl` con código Python que:

  * inspecciona `context` (parcialmente o por lotes);
  * aplica filtros/regex/agregaciones;
  * construye buffers o índices intermedios;
  * (si está habilitado) llama a `llm_query` sobre trozos agregados;
  * deja el resultado final en una variable (p. ej. `final_answer`).

4. El agente hace una llamada final a `exec_repl` con `capture_variables=["final_answer"]`.
5. El cliente/agent responde al usuario usando `exports.final_answer`.
6. Al acabar, el agente llama a `close_session` y, opcionalmente, `delete_corpus`.

---

# 6. Notas para implementación

* El servidor MCP se puede implementar en **Python** o **TypeScript**, siguiendo la especificación de Model Context Protocol (registro de tools, JSON Schema, etc.).
* Para chunking:

  * empezar con chunk por caracteres (p.ej., 4000 + solape 400);
  * más adelante refinar con tokenización real y/o cortes por párrafos.
* Para `search_corpus`:

  * versión mínima: búsqueda literal con índice invertido simple;
  * versión avanzada: embeddings + ANN para búsqueda semántica.

* Para el REPL (`open_session/exec_repl`):

  * Usar un entorno Python estándar con acceso a módulos comunes.
  * Mantener el estado de variables entre ejecuciones.
  * Serializar `exports` de forma segura (strings/JSON).

