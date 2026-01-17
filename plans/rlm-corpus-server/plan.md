# RLM Corpus Server Implementation

**Branch:** `feature/rlm-corpus-server`
**Description:** Implementar servidor MCP completo según spec_mcp_rlm.md con runtime REPL stateful para minería programática de corpus

## Goal

Implementar un servidor MCP que replique fielmente el entorno RLM del paper: permite cargar corpus largos, navegarlos con tools (search/get_chunk), y ejecutar código Python stateful en sesiones REPL con acceso a `context`, `context_meta` y `llm_query`. El enfoque es incremental: primero verificar el concepto core del REPL con las 4 tools mínimas, luego añadir navegación y finalmente features avanzadas.

---

## Implementation Steps

### Step 1: REPL Foundation - Verificar contrato context/context_meta [CRITICAL FIRST]

**Commit:** `feat: implement REPL session with context exposure`

**Files:**
- `rlm_corpus_server.py` (nuevo)
- `test_repl_contract.py` (nuevo, tests)

**What:**
Implementar el núcleo del REPL stateful:
- Clase `REPLSession` con namespace persistente
- Construcción de `context` y `context_meta` según `context_view` (by_chunk/by_document/raw_text) conforme tabla de la spec
- Método `execute(code, capture_vars)` con captura stdout/stderr
- Stub de `llm_query(prompt: str) -> str` que retorna `"[STUB: sub-analysis needed for: {prompt[:50]}...]"`
  - **Nota:** La recursión real la implementa el Root LM externamente usando las tools de navegación (search_corpus, get_chunk, exec_repl múltiples veces). Este stub es para verificar que la función es callable dentro del REPL.
- Verificación: código tipo paper funciona copy-paste

**Testing:**
```python
# Crear sesión con corpus dummy
session = REPLSession(corpus_id="test", context_view="by_chunk")

# Verificar context es list[str]
code1 = "result = len(context)"
output = session.execute(code1, capture_vars=["result"])
assert output["exports"]["result"] == "3"  # 3 chunks dummy

# Verificar context_meta alineado
code2 = """
hits = []
for i, chunk in enumerate(context):
    if "festival" in chunk.lower():
        hits.append(context_meta[i]['chunk_id'])
"""
output = session.execute(code2, capture_vars=["hits"])
assert "chunk-000001" in output["exports"]["hits"]

# Verificar llm_query disponible
code3 = "answer = llm_query('test prompt')"
output = session.execute(code3, capture_vars=["answer"])
assert "[STUB:" in output["exports"]["answer"]
```

**Success Criteria:**
- `context` es exactamente `list[str]` para by_chunk/by_document, `str` para raw_text
- `context_meta` tiene estructura exacta de la tabla spec (chunk_id, document_id, offsets, etc.)
- Variables persisten entre llamadas `execute()`
- `llm_query` callable dentro del REPL

---

### Step 2: Core Corpus Tools - load_corpus y open_session [MVP MÍNIMO]

**Commit:** `feat: add load_corpus and open_session MCP tools`

**Files:**
- `rlm_corpus_server.py` (extend)
- `corpus_manager.py` (nuevo, data models + chunking)

**What:**
Implementar las 2 tools core para crear y abrir sesiones REPL sobre corpus reales:

1. **`load_corpus`**:
   - Dataclasses: `Corpus`, `Document`, `Chunk`
   - Chunking character-based (4000 chars, 400 overlap)
   - Storage in-memory: `dict[corpus_id, Corpus]`
   - Generación de chunk_id, offsets, metadata

2. **`open_session`**:
   - Crear `REPLSession` vinculada a `corpus_id`
   - Construir `context`/`context_meta` desde chunks reales
   - Almacenar en `sessions: dict[session_id, REPLSession]`
   - Retornar `session_id` + `context_summary`

**FastMCP Registration:**
```python
from mcp.server.fastmcp import FastMCP

app = FastMCP("rlm-corpus-server")

@app.tool()
def load_corpus(
    name: str,
    documents: list[dict],
    chunk_size_chars: int = 4000,
    chunk_overlap_chars: int = 400
) -> dict:
    """Registrar corpus y devolver corpus_id."""
    # Implementation
    pass

@app.tool()
def open_session(
    corpus_id: str,
    context_view: str = "by_chunk",
    enable_llm_query: bool = False
) -> dict:
    """Abrir sesión REPL stateful."""
    # Implementation
    pass
```

**Testing:**
```bash
# Manual via MCP inspector o Python REPL
corpus_result = load_corpus(
    name="Test Corpus",
    documents=[{"document_name": "doc1.txt", "text": "Lorem ipsum..." * 1000}]
)
# Verificar: corpus_id retornado, num_chunks correcto

session_result = open_session(corpus_id=corpus_result["corpus_id"])
# Verificar: session_id retornado, context_summary coherente
```

**Success Criteria:**
- Corpus se chunka correctamente con overlap
- `open_session` construye `context` list[str] con textos reales de chunks
- `context_meta[i]` tiene chunk_id/document_id/offsets correctos

---

### Step 3: Execute REPL - exec_repl y close_session [COMPLETAR MVP REPL]

**Commit:** `feat: add exec_repl and close_session tools`

**Files:**
- `rlm_corpus_server.py` (extend)

**What:**
Implementar las 2 tools que completan el ciclo REPL:

1. **`exec_repl`**:
   - Buscar sesión por `session_id`
   - Llamar `session.execute(code, capture_variables)`
   - Retornar stdout/stderr/exports/usage
   - Incrementar `exec_count`

2. **`close_session`**:
   - Eliminar sesión de `sessions` dict
   - Liberar recursos (namespace)

**Testing:**
Flujo end-to-end tipo paper:
```python
# 1. Load corpus
corpus = load_corpus(name="Paper", documents=[...])

# 2. Open session
session = open_session(corpus_id=corpus["corpus_id"], context_view="by_chunk")

# 3. Execute mining code
result1 = exec_repl(
    session_id=session["session_id"],
    code="""
hits = []
for i, chunk in enumerate(context):
    if "transformer" in chunk.lower():
        hits.append(context_meta[i]['chunk_id'])
print(f"Found {len(hits)} matches")
    """,
    capture_variables=["hits"]
)
assert "Found" in result1["stdout"]
assert len(result1["exports"]["hits"]) > 0

# 4. Second execution (verify state persistence)
result2 = exec_repl(
    session_id=session["session_id"],
    code="final_answer = f'Total hits: {len(hits)}'",
    capture_variables=["final_answer"]
)
assert "hits" still exists in namespace

# 5. Close
close_result = close_session(session_id=session["session_id"])
assert close_result["closed"] == True
```

**Success Criteria:**
- Código ejecuta sin errores
- stdout/stderr capturado correctamente
- Variables persisten entre llamadas `exec_repl`
- `capture_variables` exporta valores correctos
- Session cleanup funciona

---

### Step 4: Navigation Tools - search_corpus y get_chunk [PERMITIR MINERÍA DIRIGIDA]

**Commit:** `feat: add search_corpus and get_chunk navigation tools`

**Files:**
- `rlm_corpus_server.py` (extend)
- `search_engine.py` (nuevo, literal search)

**What:**
Implementar tools de navegación que el paper usa antes del REPL:

1. **`search_corpus`**:
   - Búsqueda literal case-insensitive
   - Regex pattern matching opcional
   - Top-k resultados con snippet
   - Score = número de matches en chunk

2. **`get_chunk`**:
   - Lookup directo por chunk_id
   - Retornar texto + metadata completa
   - `with_meta` flag para incluir/omitir metadatos

**Implementation:**
```python
@app.tool()
def search_corpus(
    corpus_id: str,
    query: str,
    top_k: int = 10,
    semantic: bool = False  # ignore por ahora, literal only
) -> dict:
    """Buscar chunks relevantes por query literal."""
    corpus = corpora[corpus_id]
    results = []
    
    query_lower = query.lower()
    for doc in corpus.documents:
        for chunk in doc.chunks:
            if query_lower in chunk.text.lower():
                # Extract snippet
                idx = chunk.text.lower().find(query_lower)
                snippet = chunk.text[max(0, idx-50):idx+len(query)+50]
                
                results.append({
                    'chunk_id': chunk.chunk_id,
                    'document_id': chunk.document_id,
                    'score': chunk.text.lower().count(query_lower),
                    'snippet': snippet
                })
    
    results.sort(key=lambda x: x['score'], reverse=True)
    return {'results': results[:top_k]}

@app.tool()
def get_chunk(corpus_id: str, chunk_id: str, with_meta: bool = True) -> dict:
    """Recuperar texto de chunk específico."""
    # Lookup implementation
    pass
```

**Testing:**
```python
# Search then read pattern
search_result = search_corpus(corpus_id="test", query="hypothesis")
assert len(search_result["results"]) > 0

first_chunk_id = search_result["results"][0]["chunk_id"]
chunk_data = get_chunk(corpus_id="test", chunk_id=first_chunk_id)
assert "hypothesis" in chunk_data["text"].lower()
assert chunk_data["meta"]["chunk_id"] == first_chunk_id
```

**Success Criteria:**
- Búsqueda literal encuentra matches correctamente
- Snippets tienen contexto suficiente (±50 chars)
- `get_chunk` retorna texto completo + metadata alineada
- Score ranking funciona (más matches = mayor score)

---

### Step 5: Corpus Management - list_corpus, describe_corpus, delete_corpus [GESTIÓN BÁSICA]

**Commit:** `feat: add corpus management tools`

**Files:**
- `rlm_corpus_server.py` (extend)

**What:**
Herramientas de gestión básica de corpus:

1. **`list_corpus`**: Listar todos los corpus registrados (corpus_id, name, created_at, num_documents)
2. **`describe_corpus`**: Detalle de un corpus (documentos, chunks, tokens estimados)
3. **`delete_corpus`**: Eliminar corpus y liberar memoria

**Implementation:**
```python
@app.tool()
def list_corpus() -> dict:
    """Listar corpus registrados."""
    return {
        'corpora': [
            {
                'corpus_id': c.corpus_id,
                'name': c.name,
                'created_at': c.created_at.isoformat(),
                'num_documents': len(c.documents)
            }
            for c in corpora.values()
        ]
    }

@app.tool()
def describe_corpus(corpus_id: str) -> dict:
    """Detalle de corpus."""
    corpus = corpora[corpus_id]
    return {
        'corpus_id': corpus.corpus_id,
        'name': corpus.name,
        'created_at': corpus.created_at.isoformat(),
        'documents': [
            {
                'document_id': doc.document_id,
                'document_name': doc.document_name,
                'num_chunks': len(doc.chunks),
                'estimated_tokens': sum(c.meta.get('estimated_tokens', 0) 
                                       for c in doc.chunks)
            }
            for doc in corpus.documents
        ]
    }

@app.tool()
def delete_corpus(corpus_id: str) -> dict:
    """Eliminar corpus."""
    if corpus_id in corpora:
        del corpora[corpus_id]
        # Also close any open sessions for this corpus
        for sid, sess in list(sessions.items()):
            if sess.corpus_id == corpus_id:
                del sessions[sid]
        return {'deleted': True}
    return {'deleted': False, 'error': 'Corpus not found'}
```

**Testing:**
```python
# Create 2 corpus
corpus1 = load_corpus(name="Corpus A", documents=[...])
corpus2 = load_corpus(name="Corpus B", documents=[...])

# List
list_result = list_corpus()
assert len(list_result["corpora"]) == 2

# Describe
desc = describe_corpus(corpus_id=corpus1["corpus_id"])
assert desc["name"] == "Corpus A"
assert len(desc["documents"]) > 0

# Delete
delete_result = delete_corpus(corpus_id=corpus1["corpus_id"])
assert delete_result["deleted"] == True

# Verify deleted
list_result2 = list_corpus()
assert len(list_result2["corpora"]) == 1
```

**Success Criteria:**
- `list_corpus` retorna array con todos los corpus
- `describe_corpus` incluye metadata completa
- `delete_corpus` elimina corpus y cierra sesiones asociadas

---

### Step 6: Chunks Listing - list_chunks [EXPLORACIÓN ESTRUCTURAL]

**Commit:** `feat: add list_chunks tool for structural exploration`

**Files:**
- `rlm_corpus_server.py` (extend)

**What:**
Implementar `list_chunks` para listar chunks con filtrado opcional por document/section y paginación:

```python
@app.tool()
def list_chunks(
    corpus_id: str,
    document_id: str = None,
    section_id: str = None,
    limit: int = 100,
    offset: int = 0
) -> dict:
    """Listar chunks con filtrado y paginación."""
    corpus = corpora[corpus_id]
    all_chunks = []
    
    for doc in corpus.documents:
        if document_id and doc.document_id != document_id:
            continue
        
        for chunk in doc.chunks:
            if section_id and chunk.section_id != section_id:
                continue
            
            all_chunks.append({
                'chunk_id': chunk.chunk_id,
                'document_id': chunk.document_id,
                'section_id': chunk.section_id,
                'index': chunk.meta['index'],
                'start_offset': chunk.start_offset,
                'end_offset': chunk.end_offset,
                'estimated_tokens': chunk.meta.get('estimated_tokens', 0)
            })
    
    return {
        'chunks': all_chunks[offset:offset+limit],
        'total': len(all_chunks)
    }
```

**Testing:**
```python
# List all chunks
result = list_chunks(corpus_id="test")
assert len(result["chunks"]) > 0

# Filter by document
result_filtered = list_chunks(corpus_id="test", document_id="doc-001")
assert all(c["document_id"] == "doc-001" for c in result_filtered["chunks"])

# Pagination
result_page1 = list_chunks(corpus_id="test", limit=10, offset=0)
result_page2 = list_chunks(corpus_id="test", limit=10, offset=10)
assert result_page1["chunks"][0]["chunk_id"] != result_page2["chunks"][0]["chunk_id"]
```

**Success Criteria:**
- Retorna metadatos de chunks sin texto completo (eficiente)
- Filtrado por document_id y section_id funciona
- Paginación limit/offset correcta

---

### Step 7: Integration Testing - Flujo paper-faithful completo [VALIDACIÓN E2E]

**Commit:** `test: add end-to-end RLM workflow tests`

**Files:**
- `tests/test_rlm_workflow.py` (nuevo)
- `tests/fixtures/sample_corpus.txt` (nuevo)

**What:**
Tests que replican el flujo completo descrito en la spec sección 5.1:

```python
def test_paper_faithful_workflow():
    """Test: Flujo REPL tipo paper con minería programática."""
    
    # 1. Load corpus
    corpus = load_corpus(
        name="Research Papers",
        documents=[{
            "document_name": "paper1.txt",
            "text": SAMPLE_PAPER_TEXT  # ~20k chars, multiple mentions of keywords
        }]
    )
    
    # 2. Open session with by_chunk view
    session = open_session(
        corpus_id=corpus["corpus_id"],
        context_view="by_chunk",
        enable_llm_query=True
    )
    
    # 3. Execute filtering code (regex + aggregation)
    exec_result1 = exec_repl(
        session_id=session["session_id"],
        code="""
import re

# Filter chunks with 'method' mentions
method_chunks = []
for i, chunk in enumerate(context):
    if re.search(r'\\bmethod(s)?\\b', chunk, re.IGNORECASE):
        method_chunks.append({
            'chunk_id': context_meta[i]['chunk_id'],
            'document_id': context_meta[i]['document_id'],
            'text': chunk[:200]  # Preview
        })

print(f"Found {len(method_chunks)} method chunks")
        """,
        capture_variables=["method_chunks"]
    )
    
    assert "Found" in exec_result1["stdout"]
    assert len(exec_result1["exports"]["method_chunks"]) > 0
    
    # 4. Second execution: call llm_query (stub) on aggregated chunks
    exec_result2 = exec_repl(
        session_id=session["session_id"],
        code="""
# Aggregate preview texts
aggregated = "\\n---\\n".join([c['text'] for c in method_chunks])

# Call llm_query (stub)
summary = llm_query(f"Summarize these method descriptions: {aggregated}")

final_answer = f"Methods summary: {summary}"
        """,
        capture_variables=["final_answer", "summary"]
    )
    
    assert "STUB" in exec_result2["exports"]["summary"]
    assert "final_answer" in exec_result2["exports"]
    # Note: llm_query returns stub placeholder. For real recursive analysis,
    # the Root LM must orchestrate multiple tool calls externally
    # (search_corpus → exec_repl → get_chunk → exec_repl, etc.)
    
    # 5. Close session
    close_result = close_session(session_id=session["session_id"])
    assert close_result["closed"] == True
```

**Testing:**
- Test 1: Flujo completo sin errores
- Test 2: Verificar exports contienen datos esperados
- Test 3: Estado persiste (method_chunks usable en exec 2)
- Test 4: llm_query callable y retorna string

**Success Criteria:**
- Test pasa sin modificar código de test (código tipo paper funciona)
- Exports contienen estructuras correctas
- llm_query stub funciona
- Session cleanup exitoso

---

### Step 8: MCP Configuration y Deployment [INTEGRACIÓN VSCODE]

**Commit:** `docs: add MCP configuration guide and server setup`

**Files:**
- `README.md` (update)
- `docs/setup_mcp.md` (nuevo)
- `.vscode/mcp.json.example` (nuevo)

**What:**
Documentar cómo configurar el servidor en VSCode:

1. **MCP Configuration Example:**
```json
{
  "servers": {
    "rlm-corpus-server": {
      "command": "/home/miguel/agentic_projects/ai-toolkit/test_mcp/.venv/bin/python",
      "args": ["/home/miguel/agentic_projects/ai-toolkit/test_mcp/rlm_corpus_server.py"],
      "env": {
        "OPENAI_API_KEY": "${env:OPENAI_API_KEY}"
      }
    }
  }
}
```

2. **Setup Instructions:**
   - Activar venv y instalar dependencias
   - Copiar `mcp.json.example` a `~/.config/Code/User/mcp.json`
   - Ajustar paths absolutos
   - Reiniciar VSCode
   - Verificar server en Copilot chat (mencionar @rlm-corpus-server)

3. **Usage Examples:**
```markdown
# En Copilot Chat:

User: "Load this document as a corpus"
[attach file]

Copilot: [calls load_corpus tool]

User: "Search for mentions of 'transformer architecture'"
Copilot: [calls search_corpus]

User: "Now analyze those chunks with Python code to extract the different transformer variants mentioned"
Copilot: [calls open_session, then exec_repl with mining code]
```

**Testing:**
Manual testing in VSCode:
1. Restart VSCode
2. Open Copilot chat
3. Type `@rlm-corpus-server` and verify tool suggestions appear
4. Try loading a small text file as corpus
5. Try search and REPL execution

**Success Criteria:**
- Server starts without errors
- Tools discoverable in Copilot
- Basic workflow (load → search → exec) funciona

---

### Step 9: Advanced Features - llm_query Integration (EXPERIMENTAL) [OPTIONAL]

**Commit:** `feat(experimental): integrate OpenAI API for automatic llm_query`

**Files:**
- `rlm_corpus_server.py` (update REPLSession)
- `requirements.txt` (add openai)
- `docs/llm_query_experimental.md` (nuevo, documentación)

**What:**

⚠️ **EXPERIMENTAL FEATURE - OPCIONAL:**

Esta funcionalidad permite recursión "automática" dentro del REPL pero tiene consideraciones importantes:

- **Costes:** Requiere `OPENAI_API_KEY` configurada y genera costes por cada llamada a `llm_query` dentro de `exec_repl`
- **Patrón Recomendado:** El enfoque estándar RLM es que el Root LM (Copilot/Claude) orqueste la recursión externamente usando múltiples llamadas a las tools de navegación (search_corpus, get_chunk, exec_repl)
- **Uso:** Solo habilitar con `enable_llm_query=True` en `open_session` para experimentación

Reemplazar stub de `llm_query` con llamada real a OpenAI API:

```python
import openai
import os

class REPLSession:
    def _make_llm_query_func(self):
        if not self.enable_llm_query:
            return None
        
        def llm_query(prompt: str) -> str:
            """Call OpenAI API for recursive analysis."""
            try:
                client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
                response = client.chat.completions.create(
                    model="gpt-4o-mini",  # Cheaper model for sub-calls
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=1024,
                    temperature=0.2
                )
                return response.choices[0].message.content
            except Exception as e:
                return f"ERROR: {str(e)}"
        
        return llm_query
```

**Testing:**
```python
# Requires OPENAI_API_KEY in env
session = open_session(corpus_id="test", enable_llm_query=True)

exec_result = exec_repl(
    session_id=session["session_id"],
    code="""
sample_text = context[0][:500]  # First chunk preview
analysis = llm_query(f"Extract the main topic from this text: {sample_text}")
    """,
    capture_variables=["analysis"]
)

assert "ERROR" not in exec_result["exports"]["analysis"]
assert len(exec_result["exports"]["analysis"]) > 10  # Got real response
```

**Success Criteria:**
- `llm_query` calls OpenAI API successfully cuando `enable_llm_query=True`
- Responses son coherentes (no stubs) con OPENAI_API_KEY válida
- Error handling para API failures (retorna mensaje de error sin romper REPL)
- Documentación clara sobre costes y cuándo usar esta feature vs. recursión externa
- Default behavior (enable_llm_query=False) sigue retornando stub

---

### Step 10: Section Detection - list_sections [ESTRUCTURA LÓGICA]

**Commit:** `feat: add heading detection and list_sections tool`

**Files:**
- `rlm_corpus_server.py` (extend)
- `section_detector.py` (nuevo)

**What:**
Detectar estructura lógica (headings) en documentos markdown/text:

```python
import re

def detect_sections(text: str) -> list[dict]:
    """Detect markdown headings or text patterns."""
    sections = []
    
    # Regex for markdown headings
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    
    for match in heading_pattern.finditer(text):
        level = len(match.group(1))  # Number of #
        title = match.group(2).strip()
        start_offset = match.start()
        
        sections.append({
            'level': level,
            'title': title,
            'start_offset': start_offset
        })
    
    # Calculate end_offset (start of next section or end of text)
    for i, section in enumerate(sections):
        if i + 1 < len(sections):
            section['end_offset'] = sections[i + 1]['start_offset']
        else:
            section['end_offset'] = len(text)
    
    return sections

@app.tool()
def list_sections(
    corpus_id: str,
    document_id: str = None,
    max_level: int = 3
) -> dict:
    """Listar secciones detectadas en documentos."""
    # Implementation using detect_sections
    pass
```

**Testing:**
```python
# Load markdown document with headings
corpus = load_corpus(
    name="Structured Doc",
    documents=[{
        "document_name": "doc.md",
        "text": """
# Introduction
Lorem ipsum...

## Background
More text...

### Subsection
Details...
        """
    }]
)

sections = list_sections(corpus_id=corpus["corpus_id"], max_level=2)
assert len(sections["sections"]) >= 2  # "Introduction" and "Background"
assert sections["sections"][0]["title"] == "Introduction"
assert sections["sections"][0]["level"] == 1
```

**Success Criteria:**
- Detecta headings markdown correctamente
- Calcula offsets start/end
- Filtra por max_level
- Asocia chunks a secciones (via offsets)

---

### Step 11: Persistent Storage - SQLite Backend [ESCALABILIDAD]

**Commit:** `feat: add SQLite persistent storage backend`

**Files:**
- `storage.py` (nuevo)
- `rlm_corpus_server.py` (update para usar storage)
- `tests/test_storage.py` (nuevo)

**What:**
Migrar de almacenamiento in-memory a backend persistente con arquitectura extensible:

**Arquitectura:** Usar patrón Strategy con Abstract Base Class para permitir múltiples backends (SQLite, PostgreSQL, MySQL, etc.) sin cambiar código del servidor.

Implementar SQLite como primer backend concreto:

```python
from abc import ABC, abstractmethod
import sqlite3
import json
from contextlib import contextmanager
from typing import Optional

# Abstract Base Class - Storage Backend Interface
class StorageBackend(ABC):
    """Abstract interface for corpus storage backends."""
    
    @abstractmethod
    def save_corpus(self, corpus: Corpus) -> None:
        """Save corpus with all documents and chunks."""
        pass
    
    @abstractmethod
    def load_corpus(self, corpus_id: str) -> Optional[Corpus]:
        """Load corpus by ID. Returns None if not found."""
        pass
    
    @abstractmethod
    def delete_corpus(self, corpus_id: str) -> bool:
        """Delete corpus. Returns True if deleted."""
        pass
    
    @abstractmethod
    def list_corpora(self) -> list[dict]:
        """List all corpus metadata."""
        pass
    
    @abstractmethod
    def get_chunk(self, corpus_id: str, chunk_id: str) -> Optional[dict]:
        """Get specific chunk by ID."""
        pass

# Concrete Implementation - SQLite Backend
class SQLiteStorage(StorageBackend):
    """SQLite implementation of storage backend."""
    
    def __init__(self, db_path: str = "rlm_corpus.db"):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        with self._connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS corpora (
                    corpus_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    meta TEXT
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    corpus_id TEXT NOT NULL,
                    document_name TEXT NOT NULL,
                    text TEXT NOT NULL,
                    meta TEXT,
                    FOREIGN KEY (corpus_id) REFERENCES corpora(corpus_id)
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    section_id TEXT,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    meta TEXT,
                    FOREIGN KEY (document_id) REFERENCES documents(document_id)
                )
            """)
            
            # Indices for search
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_text ON chunks(text)")
    
    @contextmanager
    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def save_corpus(self, corpus: Corpus) -> None:
        """Save corpus and all documents/chunks."""
        # Implementation
        pass
    
    def load_corpus(self, corpus_id: str) -> Optional[Corpus]:
        """Load corpus from DB."""
        # Implementation
        pass
    
    def delete_corpus(self, corpus_id: str) -> bool:
        """Delete corpus."""
        # Implementation
        pass
    
    def list_corpora(self) -> list[dict]:
        """List all corpora."""
        # Implementation
        pass
    
    def get_chunk(self, corpus_id: str, chunk_id: str) -> Optional[dict]:
        """Get chunk by ID."""
        # Implementation
        pass

# Factory function for easy backend creation
def create_storage_backend(backend_type: str = "sqlite", **kwargs) -> StorageBackend:
    """Factory to create storage backend instances."""
    if backend_type == "sqlite":
        return SQLiteStorage(**kwargs)
    # Future: elif backend_type == "postgresql": return PostgreSQLStorage(**kwargs)
    # Future: elif backend_type == "mysql": return MySQLStorage(**kwargs)
    else:
        raise ValueError(f"Unknown backend type: {backend_type}")

# Usage in server
# storage = create_storage_backend("sqlite", db_path="rlm_corpus.db")
# storage = create_storage_backend("postgresql", host="localhost", db="rlm")
```

**Testing:**
```python
def test_storage_persistence():
    storage = CorpusStorage(db_path=":memory:")  # In-memory for test
    
    # Save corpus
    corpus = Corpus(corpus_id="test", name="Test", ...)
    storage.save_corpus(corpus)
    
    # Load back
    loaded = storage.load_corpus("test")
    assert loaded.corpus_id == "test"
    assert len(loaded.documents) > 0
```

**Success Criteria:**
- Corpus persiste entre reinicios del servidor
- Queries eficientes (< 100ms para get_chunk)
- Transactions para data integrity
- Migration path desde in-memory
- **Arquitectura extensible:** Nuevo backend (PostgreSQL, MySQL) se puede añadir implementando `StorageBackend` sin modificar código del servidor
- Factory function permite seleccionar backend via config

---

### Step 12: Security Hardening - RestrictedPython Sandbox [PRODUCCIÓN]

**Commit:** `feat: add RestrictedPython sandbox for REPL execution`

**Files:**
- `rlm_corpus_server.py` (update REPLSession.execute)
- `requirements.txt` (add RestrictedPython)
- `docs/security.md` (nuevo)

**What:**
Reemplazar `exec()` plain por RestrictedPython para limitar operaciones peligrosas:

```python
from RestrictedPython import compile_restricted, safe_builtins
from RestrictedPython.Guards import guarded_inplacevar

class REPLSession:
    def execute(self, code: str, capture_vars: list[str]) -> dict:
        """Execute code with RestrictedPython sandbox."""
        
        # Compile with restrictions
        byte_code = compile_restricted(
            code,
            filename='<string>',
            mode='exec'
        )
        
        if byte_code.errors:
            return {
                'stdout': '',
                'stderr': '\n'.join(byte_code.errors),
                'exports': {},
                'truncated': False
            }
        
        # Restricted builtins
        restricted_globals = {
            '__builtins__': {
                **safe_builtins,
                're': __import__('re'),
                'math': __import__('math'),
                'json': __import__('json'),
                '_getattr_': getattr,
                '_inplacevar_': guarded_inplacevar
            },
            'context': self.namespace['context'],
            'context_meta': self.namespace['context_meta']
        }
        
        if self.enable_llm_query:
            restricted_globals['llm_query'] = self.namespace['llm_query']
        
        # Execute with restrictions
        stdout_capture = io.StringIO()
        sys.stdout = stdout_capture
        
        try:
            exec(byte_code.code, restricted_globals, self.namespace)
            # ... capture logic
        except Exception as e:
            return {'stderr': str(e), 'exports': {}}
        finally:
            sys.stdout = sys.__stdout__
```

**Testing:**
```python
def test_sandbox_blocks_dangerous_ops():
    session = REPLSession(...)
    
    # Should block file access
    result = session.execute("open('/etc/passwd', 'r')", [])
    assert "NotImplementedError" in result["stderr"] or "not allowed" in result["stderr"]
    
    # Should block subprocess
    result = session.execute("import subprocess; subprocess.call(['ls'])", [])
    assert "ImportError" in result["stderr"] or "not allowed" in result["stderr"]
    
    # Should allow safe operations
    result = session.execute("import re; x = re.search(r'test', 'testing')", ["x"])
    assert result["stderr"] == ""
```

**Success Criteria:**
- Blocks file I/O (`open`, `__import__('os')`)
- Blocks subprocess execution
- Allows whitelisted modules (re, math, json)
- `context`/`context_meta` still accessible

---

### Step 13: Semantic Search - Embeddings Integration [ADVANCED]

**Commit:** `feat: add semantic search with sentence-transformers`

**Files:**
- `search_engine.py` (update)
- `requirements.txt` (add sentence-transformers, faiss-cpu)
- `rlm_corpus_server.py` (update search_corpus)

**What:**
Implementar búsqueda semántica con embeddings:

```python
from sentence_transformers import SentenceTransformer
import numpy as np

class SemanticSearchEngine:
    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = SentenceTransformer(model_name)
        self.corpus_embeddings = {}  # {corpus_id: np.array}
    
    def index_corpus(self, corpus_id: str, chunks: list[str]):
        """Pre-compute embeddings for all chunks."""
        embeddings = self.model.encode(chunks, show_progress_bar=True)
        self.corpus_embeddings[corpus_id] = embeddings
    
    def search(self, corpus_id: str, query: str, top_k: int = 10) -> list[int]:
        """Return indices of top-k most similar chunks."""
        query_embedding = self.model.encode([query])[0]
        corpus_embs = self.corpus_embeddings[corpus_id]
        
        # Cosine similarity
        similarities = np.dot(corpus_embs, query_embedding) / (
            np.linalg.norm(corpus_embs, axis=1) * np.linalg.norm(query_embedding)
        )
        
        top_indices = np.argsort(similarities)[-top_k:][::-1]
        return top_indices.tolist()

# Update load_corpus to index embeddings
def load_corpus(...):
    # ... existing logic
    
    # Index for semantic search if available
    if semantic_search_engine:
        chunk_texts = [c.text for doc in corpus.documents for c in doc.chunks]
        semantic_search_engine.index_corpus(corpus.corpus_id, chunk_texts)
    
    return result

# Update search_corpus
def search_corpus(corpus_id: str, query: str, semantic: bool = True, ...):
    if semantic and semantic_search_engine:
        # Use semantic search
        top_indices = semantic_search_engine.search(corpus_id, query, top_k)
        # Map indices to chunks
        # ...
    else:
        # Fall back to literal search
        # ...
```

**Testing:**
```python
def test_semantic_search():
    corpus = load_corpus(
        name="Test",
        documents=[{
            "document_name": "doc.txt",
            "text": "The transformer architecture revolutionized NLP. " * 100 +
                    "Deep learning models achieve state-of-the-art results. " * 100
        }]
    )
    
    # Semantic search for synonym
    results = search_corpus(
        corpus_id=corpus["corpus_id"],
        query="neural network innovations",  # Not literal match
        semantic=True
    )
    
    assert len(results["results"]) > 0
    # Should match "transformer" and "deep learning" chunks semantically
```

**Success Criteria:**
- Embeddings indexados en `load_corpus`
- Búsqueda semántica retorna chunks relevantes sin match literal
- Performance aceptable (< 500ms para corpus ~1000 chunks)
- Fallback a literal si semantic=False

---

### Step 14: Documentation y Examples [USABILIDAD]

**Commit:** `docs: comprehensive usage guide and examples`

**Files:**
- `docs/usage_guide.md` (nuevo)
- `examples/paper_mining.py` (nuevo)
- `examples/requirements_extraction.py` (nuevo)
- `README.md` (update con quick start)

**What:**
Documentación completa y ejemplos de use cases:

**Usage Guide Structure:**
1. Installation & Setup
2. Basic Workflow (load → search → get_chunk)
3. REPL Workflow (open_session → exec_repl → capture_variables)
4. Advanced Patterns (recursive analysis, buffers, aggregation)
5. Best Practices (chunking strategies, search optimization)
6. Troubleshooting

**Example: Paper Mining**
```python
# examples/paper_mining.py
"""
Use Case 1: Scientific Paper Mining
Extract methodologies from research papers using RLM pattern.
"""

# 1. Load papers as corpus
papers_text = load_papers_from_pdfs(["paper1.pdf", "paper2.pdf", ...])
corpus = load_corpus(name="Research Papers", documents=papers_text)

# 2. Search for methodology sections
method_chunks = search_corpus(
    corpus_id=corpus["corpus_id"],
    query="methodology experimental setup procedure",
    semantic=True,
    top_k=20
)

# 3. Open REPL session for analysis
session = open_session(corpus_id=corpus["corpus_id"], enable_llm_query=True)

# 4. Execute mining code
exec_repl(
    session_id=session["session_id"],
    code="""
import re

# Filter and structure methodology mentions
methodologies = []
for chunk_id in [r['chunk_id'] for r in search_results]:
    chunk_text = [c for c in context if context_meta[context.index(c)]['chunk_id'] == chunk_id][0]
    
    # Extract structured info using llm_query
    structured = llm_query(f'''
Extract from this text:
- Dataset used
- Model architecture
- Training procedure
- Evaluation metrics

Text: {chunk_text}
''')
    
    methodologies.append({
        'chunk_id': chunk_id,
        'analysis': structured
    })

# Aggregate final answer
final_answer = llm_query(f'''
Synthesize these methodology extractions into a comparative table:
{json.dumps(methodologies, indent=2)}
''')
    """,
    capture_variables=["final_answer"]
)
```

**Testing:**
Manual review of:
- Documentation clarity
- Examples run without errors
- Cover all use cases from docs/use_cases

**Success Criteria:**
- Complete setup guide works for new users
- 3+ working examples covering different use cases
- Code samples tested and functional
- Troubleshooting section comprehensive

---

## Post-Implementation Checklist

- [ ] All 11 MCP tools implemented and tested
- [ ] REPL contract verified (context/context_meta structure)
- [ ] End-to-end workflow tests passing
- [ ] VSCode integration documented and tested
- [ ] Security hardening (RestrictedPython) in place
- [ ] Semantic search functional
- [ ] Documentation complete with examples
- [ ] Performance benchmarked (10k+ chunk corpus)

---

## Future Enhancements (Out of Scope for MVP)

1. **Multi-modal Support:** PDF parsing, image OCR, tables
2. **Collaborative Sessions:** Multiple users on same corpus
3. **Advanced Section Detection:** NLP-based (not just regex)
4. **Vector Store Integration:** ChromaDB, Pinecone
5. **Streaming Responses:** For long-running exec_repl
6. **Monitoring Dashboard:** Session analytics, usage stats
7. **API Rate Limiting:** Per-user quotas for llm_query
8. **Checkpoint/Resume:** Save REPL state for long analyses

---

## Implementation Notes

**Decisiones de diseño tomadas:**

1. **llm_query:** Stub por default (Steps 1-8). Step 9 añade integración OpenAI experimental y opcional. La recursión real la hace el Root LM externamente.

2. **Storage Backend:** SQLite (Step 11) como primer backend concreto. Arquitectura ABC + Strategy pattern permite añadir PostgreSQL/MySQL implementando interface `StorageBackend`. In-memory para Steps 1-10. Factory function `create_storage_backend()` facilita configuración.

3. **Semantic Search:** all-MiniLM-L6-v2 (Step 13) por balance velocidad/calidad. Fácil cambiar a mpnet-base después si necesario.

4. **Session Timeout:** 1 hora de inactividad antes de auto-cleanup. Configurable via variable de entorno.

5. **Testing Strategy:** Integration tests E2E prioritarios (Step 7). Unit tests donde tenga sentido (chunking, search). Pytest como framework.

6. **Cobertura por Fases:**
   - **Steps 1-3 (~45% usable):** REPL Foundation + MVP mínimo. 4 tools de 11. Permite verificar contrato context/context_meta y ejecutar código stateful, pero sin navegación ni búsqueda.
   - **Steps 1-5 (~75% usable):** MVP + Navegación + Gestión. 9 tools de 11. Funcionalidad completa para uso real: carga, búsqueda literal, lectura dirigida, gestión de corpus. **Sweet spot para primer PR funcional.**
   - **Steps 1-8 (~95% usable):** Funcionalidad completa testada. 10 tools de 11. Añade list_chunks, E2E tests y documentación VSCode. Listo para producción con in-memory storage.
   - **Steps 9-14 (mejoras avanzadas):** Persistencia SQLite, seguridad RestrictedPython, búsqueda semántica, llm_query experimental OpenAI, documentación extendida.
