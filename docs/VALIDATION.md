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

## Doplnění po nahrání do GitHubu

[GitHub Actions run 38407785368](https://github.com/HonzaHezina/ActiveMemory/actions/runs/38407785368)
pro commit `ba466480c1675e7f6c47d9e01f06bdc92a1a9d14` úspěšně ověřil:

- zamčenou instalaci, lint, formát a 19 testů (2 live opt-in testy v běžné sadě přeskočené),
- `docker compose config` pro reference a Neo4j overlay,
- Docker image build `active-memory:ci`,
- samostatný native Neo4j integration test: **1 passed**, 1 Graphiti test deselected.

První běh CI odhalil chybějící `.env` pro Compose validaci. Workflow nyní před kontrolou
vytvoří neprodukční `.env` z `.env.example`; obsah není ukládán do Gitu.
Graphiti inference, provider matrix a skutečný Coolify deploy stále neproběhly.
Placený Graphiti test zůstává explicitně opt-in. Lokální pracovní prostředí Docker daemon nemá;
Docker a Neo4j kontroly proběhly na GitHub runneru.

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

## B�h 2026-10-13 (druh�, Windows pracovn� stanice)

Bez Dockeru a bez modelov�ch kl���. Neo4j 5.26.31 Community byl spu�t�n lok�ln� z ofici�ln�ho zipu (JDK 21).

| Kontrola | V�sledek |
|---|---|
| uv sync --frozen, ruff, ruff format, pytest | pro�ly; 19 passed, 4 skipped (opt-in) |
| Re�ln� `active-memory serve` + `init` + `scripts/demo.py` | pro�lo: 3 epizody, 3 uzly, 2 vazby, kontext 3 polo�ky |
| `tests/test_live_graph.py -k native` proti lok�ln�mu Neo4j | 1 passed |
| `tests/test_stack_integration.py` (bez modelu, API subprocess + Neo4j): ingest, hotov� joby, zdrojov� UUID v map�, restart API, restart, smaz�n�, purge z Neo4j | 1 passed |

**Neov��eno:** Docker Compose varianta stack testu (`MEMORY_TEST_DOCKER=true`, CI job `docker-stack`;
override pou��v� `!override`, tedy Compose >= 2.24) a Graphiti varianta
(`MEMORY_TEST_DOCKER_GRAPHITI=true`, CI job `graphiti-live`) � chyb� Docker daemon resp. modelov� kl��e.
Zb�vaj�c� krok: nastavit repo secrets `MEMORY_TEST_MODEL_KEY`, `MEMORY_TEST_EMBEDDING_KEY`
(voliteln� vars `MEMORY_TEST_MODEL_URL`/`_NAME`, `MEMORY_TEST_EMBEDDING_URL`/`_MODEL`/`_DIM`) a spustit
workflow ru�n� s `graphiti_live=true`. Graphiti-only aserce (Episodic UUID, scoped facts, ciz� group_id
p�e�ije rebuild, ��dn� text smazan�ho zdroje v odvozen�m grafu) nebyly dosud vykon�ny.
