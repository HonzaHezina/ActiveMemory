# Ověření před předáním · 2026-10-13

Provedeno v čisté projektové venv vytvořené pomocí `uv sync --frozen --extra dev --extra graphiti`.
Bez skutečných osobních dat a bez placených modelových volání.

| Kontrola | Výsledek |
|---|---|
| Zamčená instalace + editable build projektu | prošla |
| Ruff lint a format | prošly |
| Pytest behavior/contract suite | 19 passed, 2 skipped (live Neo4j/Graphiti) |
| Skutečný TCP start API, embedded worker, syntetický ingest | prošel |
| Demo mapa | 3 epizody ve 3 konverzacích, 3 uzly, 2 ABOUT vazby |
| Reviewed kontext | 3 položky, 2303 znaků, úplné citace |
| Export API | 3 živé zdroje |
| MCP stdio initialize + tools/list + tools/call přes oficiální klienta | prošlo, 4 read nástroje, context 3 položky |
| Graphiti 0.30.2 constructor + valid group ID + create-before-UUID-update | prošlo bez sítě, mock/contract test |
| LLM output quote validation | success i unsupported-quote failure ověřeny mockem |
| YAML/JSON syntax a interní markdown odkazy | staticky zkontrolováno |
| Git bundle a první commit | připraveno, bundle integrity verified |

Behavior testy zahrnují raw text včetně whitespace, idempotenci, změněný payload, role/práva,
scope injection rejection, přesné citace, candidate/rejected exclusion, znakový budget,
cross-conversation recurrence, různé claims se stejným labelem, current/historical validity,
source deletion, tombstone, restart s pending jobem, retry po backend failure a scope binding.

Docker daemon zde není dostupný. Neproběhl image build, `docker compose config`, živý Neo4j,
Graphiti inference, provider matrix ani skutečný Coolify deploy. CI obsahuje Docker build,
Compose validaci a live native Neo4j test; placený Graphiti test je explicitně opt-in.
Živé testy jsou dodané v `tests/test_live_graph.py`, nikoli předstírané jako provedené.

Příklad spuštění live Neo4j testu v místě, kde běží vlastní čistý testovací Neo4j:

```bash
export MEMORY_TEST_NEO4J=true
export MEMORY_TEST_NEO4J_URI=bolt://localhost:7687
export MEMORY_TEST_NEO4J_PASSWORD='TESTOVACI_HESLO'
uv run pytest -q tests/test_live_graph.py -k native
```

Graphiti test navíc potřebuje `MEMORY_TEST_GRAPHITI=true`, `MEMORY_TEST_MODEL_KEY`,
`MEMORY_TEST_EMBEDDING_KEY` a případně TEST_MODEL_URL/TEST_EMBEDDING_URL.
Pracuje se samostatným náhodným test scope. Může vyvolat modelové náklady, proto neběží implicitně.
