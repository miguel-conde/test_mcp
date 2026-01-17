## 1–3. Qué hace realmente el RLM según el paper

Leyendo el paper y, en particular, el apéndice de prompts y ejemplos de REPL, lo clave es:

* El RLM **no pasa el corpus como tokens** al modelo.

* Inicializa un **entorno Python REPL** con:

  1. Una variable `context` que contiene el corpus (string, lista de strings, etc.).
  2. Una función `llm_query(...)` que llama a un sub-LLM con hasta ~500k caracteres de contexto.
  3. Un bucle interactivo donde el modelo escribe código ` ```repl ... ``` `.

* El modelo **escribe código** para:

  * iterar sobre `context`
  * aplicar `regex`, filtros y agrupaciones
  * construir búferes intermedios
  * trocear y recombinar secciones
  * llamar recursivamente a `llm_query` sobre trozos grandes (batching, ~200k chars por llamada, etc.).

* El resultado final se devuelve con algo tipo `FINAL(...)` o `FINAL_VAR(variable)`, es decir, el REPL expone variables que el RLM puede devolver como salida.

En resumen: el **runtime del paper no es solo un índice navegable**; es:

> “un entorno de ejecución Python, stateful, con acceso al corpus vía `context` y a un sub-LLM vía `llm_query`, donde el modelo programa la minería del corpus”.

---

## 4. Qué hace ahora tu `spec_mcp_rlm.md`

Tu especificación actual de `rlm-corpus-server` es muy buena como **servidor de corpus** pero sólo cubre la mitad del entorno del paper:

* Modelo de datos: `Corpus`, `Document`, `Section`, `Chunk`, `SearchResult`.

* Tools MCP:

  * `load_corpus`
  * `list_corpus`
  * `describe_corpus`
  * `list_sections`
  * `list_chunks`
  * `get_chunk`
  * `search_corpus`
  * `delete_corpus`

* Requisitos no funcionales, flujo de uso, etc.

Es decir: tienes **RLM como “corpus navegable”**, pero aún no:

1. El **REPL / sesión de ejecución**.
2. El concepto de **contexto programático** (`context`) ligado a un corpus.
3. Una API para **ejecutar código cerca del corpus** con estado persistente.
4. La integración opcional con un sub-LLM (`llm_query`) desde dentro del código.

---

## 5. Propuesta de actualización del `.md` (sin tocarlo todavía)

Te propongo una **extensión incremental** de la especificación, manteniendo todo lo que ya tienes y añadiendo un “bloque 2” orientado a ejecución. La idea es que tu servidor pase a ser conceptualmente:

> `rlm-corpus-server`:
> **Corpus + Compute**, es decir, almacenamiento + entorno de ejecución RLM.

### 5.1. Cambios de alto nivel en la estructura

En el propio `.md`:

1. Mantener el título y la sección 1 tal cual, pero ampliar el objetivo:

   * De “API de navegación programática sobre corpus”
   * A “API de navegación programática **y ejecución de código tipo REPL** sobre corpus, emulando el entorno del paper”.

2. Ampliar el **modelo de datos** con dos nuevas entidades:

   * `Session` (sesión REPL ligada a un corpus).
   * (Opcional) `ExecutionResult` (estructura de salida estándar de la ejecución).

3. Añadir una **subsección nueva** tipo:

   * `2.2. Entorno de ejecución (REPL)`

4. Añadir nuevas tools MCP en la sección 3:

   * `3.9. open_session` (o `create_repl_session`)
   * `3.10. exec_repl` (ejecución de código)
   * `3.11. close_session`
   * (Opcional) `3.12. list_sessions`

5. Ampliar **Requisitos no funcionales** (seguridad / recursos):

   * timeouts de ejecución
   * límites de memoria
   * aislamiento por sesión
   * prohibir red, filesystem salvo lo controlado por el servidor

6. Añadir un **ejemplo completo de flujo REPL** que emule un snippet del paper (regex, chunking + buffers + agregación).

---

### 5.2. Nuevas entidades de modelo de datos

En la sección `2. Modelo de datos`, tras las entidades actuales, añadir:

#### `Session`

* `session_id: string`
* `corpus_id: string`
* `created_at: datetime`
* `last_activity_at: datetime`
* `context_view: string`
  (por ejemplo `"raw_string"`, `"list_of_chunks"`, `"by_section"`)
* `state_meta: object`
  (número de ejecuciones, tokens consumidos por `llm_query`, etc.)

La **semántica**:

* Cada `Session` corresponde a un entorno REPL aislado con:

  * variable `context` preinicializada (ligada a `corpus_id`).
  * acceso a las primitivas de Python estándar permitidas.
  * acceso opcional a una función `llm_query(prompt: str, **config)` implementada por el servidor.

#### (Opcional) `ExecutionResult`

No hace falta como entidad persistente, pero sí como **shape** de la respuesta de `exec_repl`:

* `stdout: string`
* `stderr: string`
* `truncated: boolean`
* `exported_variables: object` (map `nombre -> representación string/JSON`, si decides exponerlo)
* `cost_meta: object` (tokens y coste de sub-LLM, tiempo de CPU, etc.)

---

### 5.3. Nuevas herramientas MCP

#### 3.9. `open_session`

**Propósito**
Inicializar una sesión REPL asociada a un corpus, equivalente a crear el entorno `E` del paper con la variable `context` ya preparada.

**Input sugerido (JSON Schema–nivel alto)**

* `corpus_id: string`
* `context_view: string` (opcional; por ejemplo `"raw_text"`, `"by_document"`, `"by_chunk"`)
* `config`: objeto opcional con:

  * `max_runtime_ms_per_exec`
  * `max_memory_mb`
  * flags tipo `enable_llm_query: boolean`

**Salida**

* `session_id: string`
* `context_summary: string` (breve resumen de cómo está representado el `context`)
* `limits: { max_runtime_ms_per_exec, max_memory_mb, ... }`

#### 3.10. `exec_repl`

**Propósito**
Ejecutar código Python en el entorno asociado a una `session_id`, con acceso a `context` y, si está activado, a `llm_query`. Esto es lo que permite “escribir código para hacer minería del corpus”.

**Input sugerido**

* `session_id: string`
* `code: string` (bloque Python completo a ejecutar)
* `capture_variables: array[string]` (opcional: nombres de variables cuyo valor serializar)

**Salida**

* `stdout: string` (truncado a X caracteres)
* `stderr: string`
* `truncated: boolean`
* `exported_variables: object` (solo las pedidas en `capture_variables`, representadas como strings/JSON)
* `cost_meta: { sub_llm_calls: int, sub_llm_tokens: int, sub_llm_cost_usd: number }` (si se usa `llm_query`)

**Semántica clave**:

* El entorno mantiene **estado** entre llamadas (variables definidas en ejecuciones previas).
* `context` es **read-only** (o editable sólo por API explícita, según decidas).
* Si activas `llm_query`, el código puede hacer cosas como:

  ```python
  import re

  # filtrar secciones relevantes
  hits = [i for i, chunk in enumerate(context) if "festival" in chunk.lower()]
  buffers = []
  for i in hits:
      answer = llm_query(f"Analyze this part of the corpus: {context[i]}")
      buffers.append(answer)

  final = llm_query(
      "Given these partial analyses, answer the original question:\n" +
      "\n".join(buffers)
  )
  ```

  que es exactamente el patrón mostrado en el paper (regex + buffers + llm_query + agregación).

#### 3.11. `close_session`

**Propósito**
Cerrar y limpiar una sesión REPL (memoria, handles de corpus, etc.).

**Input**

* `session_id: string`

**Salida**

* `{ "closed": true }`

#### 3.12. (Opcional) `list_sessions`

Sólo si ves valor para debug / administración.

---

### 5.4. Cambios en “Requisitos no funcionales”

En el apartado `4.3. Seguridad` ampliaría:

* **Sandbox de Python**:

  * Sin acceso a red.
  * Sin acceso directo al filesystem (o muy controlado).
  * Sin `os.system`, `subprocess`, etc.
  * Lista blanca de módulos seguros (`re`, `math`, `statistics`, etc.).

* **Cuotas / límites**:

  * Tiempo máximo por `exec_repl` (`max_runtime_ms_per_exec`).
  * Memoria máxima por sesión.
  * Número máximo de ejecuciones por sesión.
  * Número máximo de llamadas `llm_query` por ejecución y por sesión (para controlar coste).

* **Observabilidad**:

  * Logs de errores.
  * Métricas agregadas (para saber si el agente está “burning compute” con loops tontos, como comentan los autores en las limitaciones).

---

### 5.5. Ejemplo de flujo RLM completo (a añadir al final del `.md`)

Yo añadiría una subsección en el flujo de uso:

> **5.x. Ejemplo de uso tipo RLM (inspirado en el paper)**

Con algo así (en pseudocódigo / narrativa):

1. Cliente llama a `load_corpus` y obtiene `corpus_id`.

2. Cliente llama a `open_session(corpus_id, context_view="by_chunk")` y recibe `session_id`.

3. El agente (LLM raíz) ejecuta `exec_repl` con código que:

   * inspecciona parcialmente `context`
   * aplica regex / filtros
   * construye `buffers`
   * llama a `llm_query` sobre agrupaciones de chunks
   * almacena un `final_answer` en una variable `final_answer`.

4. Última llamada a `exec_repl` pidiendo `capture_variables=["final_answer"]`.

5. El agente usa `exported_variables.final_answer` como respuesta final al usuario.

6. Se llama a `close_session(session_id)`.

Así dejas **documentado explícitamente** el patrón RLM “paper-faithful”.

---

## 6. ¿Próximo paso?

Si esta propuesta te encaja, el siguiente paso sería:

1. Insertar estas nuevas secciones en el `.md`:

   * 2.2 Entorno de ejecución (REPL)
   * Nuevas tools 3.9–3.11 (y 3.12 si quieres)
   * Ampliación de 4.3 Seguridad
   * Ejemplo de flujo 5.x

2. Escribir los JSON Schema de `open_session` y `exec_repl` con el mismo nivel de detalle que ya tienes para `load_corpus` y `search_corpus`.
