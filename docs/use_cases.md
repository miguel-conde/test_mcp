# Use Cases (RLM / MCP)

Este documento recopila casos de uso prácticos donde un agente tipo RLM (Recursive Language Model) obtiene ventaja al **minar un corpus largo de forma programática** (REPL + búsqueda + agregación), en lugar de intentar “leerlo todo” en una sola ventana de contexto.

## Tabla de contenidos

1. [Use Case 1 — Scientific Paper Mining (Meta-Analytical Extraction)](#use-case-1--scientific-paper-mining-meta-analytical-extraction)
2. [Use Case 2 — Software System Spec → Extract Requirements + Assumptions](#use-case-2--software-system-spec--extract-requirements--assumptions)
3. [Use Case 3 — Legal / Policy / Regulatory Interpretation](#use-case-3--legal--policy--regulatory-interpretation)
4. [Use Case 4 — Technical Paper → Reconstruct Experimental Pipeline](#use-case-4--technical-paper--reconstruct-experimental-pipeline)
5. [Use Case 5 — Logs → Incident Analysis (Root Cause + Timeline Reconstruction)](#use-case-5--logs--incident-analysis-root-cause--timeline-reconstruction)
6. [Bonus: Mini Use Case (Muy Importante para RLM)](#bonus-mini-use-case-muy-importante-para-rlm)
7. [Si quieres llevar esto a MVP](#si-quieres-llevar-esto-a-mvp)

# **Use Case 1 — Scientific Paper Mining (Meta-Analytical Extraction)**

**Objetivo**
Responder preguntas de alto nivel sobre un conjunto de artículos largos (p.ej., “qué hipótesis se investigan”, “qué metodologías se comparan”, “qué limitaciones declaran”).

**Corpus**

* doc: 5–50 papers PDF convertidos a texto
* tamaño: 2M–20M chars
* estructura: sections (intro, methods, results, limitations, appendix)

**Por qué necesita RLM**
Un LLM con context window gigante puede leer uno, pero no comparar 50.
RAG falla porque chunking + embeddings diluye señales (methods ≠ limitations ≠ appendix).
RLM permite:

* map: localizar secciones relevantes por search
* recurse: filtrar + agrupar + comparar buffers
* subagents: un subagent por “axe” → (methods, results, limitations)
* reduce: síntesis comparativa final

**Herramientas usadas**

* `search_corpus("hypothesis")`
* `search_corpus("method")`
* `open_session(context_view=by_section)`
* `exec_repl` con pattern matching de secciones
* `runSubagent` para “methods synthesis” y “limitations synthesis”

**Output esperado**

* JSON / tabla
* reporte narrativo + bullets
* opcional: mapping: paper → método → resultado → limitación

**Evaluación**

* recall conceptual (captura de ideas)
* coherencia narrativa
* grounding (citas por sección)
* coverage de papers

---

# **Use Case 2 — Software System Spec → Extract Requirements + Assumptions**

**Objetivo**
Minería de especificaciones técnicas (RFCs, PRDs, docs de arquitectura) para:

* requisitos funcionales
* requisitos no funcionales
* supuestos (assumptions)
* dependencias
* constraints

**Corpus**

* 2–10 specs + ADRs + docs de arquitectura
* 500k–5M chars
* estilo técnico

**Por qué RLM**

* RAG: chunking destruye dependencia entre sections (requirements ↔ assumptions ↔ constraints).
* LLM-proxy: la respuesta es demasiado superficial sin minería.
* RLM puede:

  * search: “requirement”, “MUST”, “SHALL”, “assume”
  * REPL: filtrar patrones con regex tipo RFC
  * subagents: uno para functional, otro para non-functional, otro para constraints
  * synthesis: tabla final + narrativa

**Herramientas usadas**

* `search_corpus("must|shall|should")`
* `exec_repl` para filtrado RFC-style
* `runSubagent` para categorías

**Output esperado**

* matrices
* JSON
* compliance checklist (como haría un ISO/IEEE reviewer)

**Evaluación**

* completeness
* false positives vs false negatives
* section grounding

---

# **Use Case 3 — Legal / Policy / Regulatory Interpretation**

**Objetivo**
Responder preguntas complejas sobre normativas largas (p.ej. GDPR, PCI-DSS, HIPAA, tax code), como:

* “¿esta situación está cubierta?”
* “¿qué obligaciones surgen?”
* “¿qué excepciones aplican?”

**Corpus**

* 1–3 textos regulatorios largos
* 1M–10M chars

**Por qué RLM**

* RAG fracasa en la parte “exception resolution”
* Context window grande no basta si hay cross-references
* RLM permite:

  * recurse: buscar deficiones → exceptions → cross-links
  * subagents: uno inspecciona definiciones legales, otro excepciones, otro obligaciones
  * reduce: ruling argumentado

**Herramientas usadas**

* `search_corpus("exception|exemption|unless")`
* `exec_repl` para crossfilter + pattern grouping
* subagents para views jurídicos internos

**Output esperado**

* argumentación estructurada
* referencias a secciones
* decision tree legal (opcional)

**Evaluación**

* consistencia
* grounding
* exhaustividad en excepciones

---

# **Use Case 4 — Technical Paper → Reconstruct Experimental Pipeline**

**Objetivo**
Extraer del paper la pipeline real (datasets, preprocess, modelo, tuning, métricas) — tarea habitual en reproducibilidad científica y DS académico.

**Corpus**

* 1 paper + appendix + supplementary material
* 200k–2M chars

**Por qué RLM**
En ML research, la pipeline está **dispersa**:

* dataset en intro o appendix,
* preprocess en methods,
* hyperparams en supplementary o footnotes,
* métricas en results,
* limitaciones al final.

RAG + summarizers no reconstruyen pipeline porque es composición **across sections**.

RLM hace:

* map: localizar secciones con search (“dataset”, “preprocess”, “hyperparam”, “metric”)
* recurse: extraer valores, tablas, configs
* subagents: uno para dataset, otro para model, otro para training
* reduce: pipeline reconstruida

**Output esperado**

* YAML reproducible
* JSON
* block diagram (puede generar o describir)
* narrative summary

**Evaluación**

* fidelity vs paper
* completeness
* reproducibility

---

# **Use Case 5 — Logs → Incident Analysis (Root Cause + Timeline Reconstruction)**

**Objetivo**
Analizar logs de sistemas distribuidos para reconstruir:

* timeline
* symptom → cause → fix
* correlated events
* anomalies

**Corpus**

* logs + traces + event dumps
* 2M–50M chars

**Por qué RLM**
Logs tienen estructura *sparse* y dependen de correlación temporal.
RAG no sirve: embeddings ignoran temporalidad y causalidad.
REPL permite:

* regex
* bucketing
* grouping
* agregación
* pivots

Subagents pueden analizar streams distintos (ingest, compute, cache, db, network).

**Herramientas usadas**

* `exec_repl` con pandas o regex lightweight (si permitido por sandbox)
* `search_corpus` por “error”, “WARN”, “timeout”, “retry”
* `runSubagent` por subsystem

**Output esperado**

* timeline + RCA
* network of events
* recommended mitigations

**Evaluación**

* coherence
* causal plausibility
* coverage

---

# **Bonus: Mini Use Case (Muy Importante para RLM)**

**“Ask questions that weren’t in the corpus as sentences”**

Ejemplo:

> “Did the authors justify the experimental annealing schedule or did they treat it as a black box?”

Esto no es extractivo; requiere **lectura cambia-buscando** (“present? implied? absent?”).
Los RLM son buenos en estos *negative questions* porque pueden:

* map → recurse
* buscar evidencia faltante
* inferir ausencia
* reducir a conclusión

---

# **Si quieres llevar esto a MVP**

De los 5, los 2 con mejor ROI industrial para ti (DS senior + corporate + analytics) son:

✔ **Use Case 2 (Requirements Mining)**
✔ **Use Case 4 (Paper → Pipeline Reconstruction)**

y si pensamos en **RLM interno tipo “intelligence layer for internal docs”**:

✔ **Use Case 3 (Regulatory / Policy / Legal)**

