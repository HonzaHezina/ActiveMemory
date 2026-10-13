# API v1

Všechny `/v1/*` endpointy vyžadují `Authorization: Bearer TOKEN`.
Scope určuje server, request žádný scope/group/tenant nepřijímá.
Úplné request schema se generuje z implementace na `/openapi.json`.

| Endpoint | Právo | Význam |
|---|---|---|
| GET `/ui/review` | žádné (statický shell bez dat) | fronta kandidátů + časová osa; viz sekce Fronta ke schválení |
| GET `/ui` | žádné (statický shell bez dat) | prohlížeč mapy; token se zadává na stránce a drží jen v paměti záložky; přísné CSP |
| GET `/healthz` | žádné | proces žije |
| GET `/readyz` | žádné | journal a graph backend dostupné; neověřuje dostupnost modelu |
| POST `/v1/episodes` | write | queued ingest, 202, episode_id + duplicate |
| GET `/v1/episodes/{id}` | read | přesná původní zpráva |
| POST `/v1/search` | read | active items; volitelně Graphiti inferred facts |
| POST `/v1/context` | read | vybraný reviewed kontext s citacemi |
| GET `/v1/map?limit=500` | read | uzly, vazby a `clusters` (skupiny uzlů spojené potvrzeným ALIAS_OF); počet a truncated flag |
| GET `/v1/whoami` | libovolný platný token | `client_id` a `permissions` presentovaného tokenu (UI podle toho nabízí akce; server vynucuje vždy) |
| GET `/v1/events` | read | verzovaný veřejný log událostí, filtry, kurzor; viz [EVENTS.md](EVENTS.md) |
| GET `/v1/candidates` | read | stránkovaná fronta kandidátů (uzly/vazby) s evidencemi, původem příspěvků a stavem auditu |
| GET `/v1/candidates/{node\|link}/{id}` | read | jeden kandidát (po rozhodnutí slouží k ověření stavu) |
| POST `/v1/nodes/{id}/review` | admin | confirmed/rejected; volitelné `expected_status` (jiný aktuální stav → 409); opakované stejné rozhodnutí nic nemění a nezapíše událost |
| POST `/v1/links` | admin | kandidát vazby s citací ve zdroji |
| POST `/v1/links/{id}/review` | admin | review vazby (confirmed/rejected; odmítnutý návrh se znovu nenavrhne) |
| GET `/v1/links?status=&relation=` | read | vazby s krátkým popisem konců, citacemi a u návrhů `proposal` (skóre, signály, důvod, metoda) |
| POST `/v1/maintenance/propose` | admin | AM-003: vygeneruje candidate návrhy ALIAS_OF/SUPERSEDES (a s judge SUPPORTS/REFINES/CONTRADICTS); nic nepotvrzuje ani neslučuje |
| GET `/v1/jobs` | read | posledních 100 jobs, status a redigovaná chyba |
| POST `/v1/jobs/{episode_id}/retry` | admin | znovu pouze failed job |
| POST `/v1/maintenance/consolidate` | admin | přepočet četnosti a aktivity |
| DELETE `/v1/episodes/{id}` | admin | live-store delete; při Graphiti rebuild přeživších zdrojů |
| GET `/v1/export` | admin | canonical live raw messages + active graph, schema_version=1 |

## Ingest

```json
{
  "source_system": "custom-agent",
  "conversation_id": "conversation-42",
  "message_id": "msg-7",
  "role": "user",
  "content": "Chci mít svá data pod kontrolou.",
  "occurred_at": "2026-10-01T10:00:00Z",
  "extraction": {
    "items": [{
      "kind": "Goal",
      "label": "Kontrola vlastních dat",
      "summary": "Chci mít svá data pod kontrolou.",
      "quote": "Chci mít svá data pod kontrolou.",
      "themes": ["Vlastnictví dat"],
      "confidence": 0.9
    }]
  }
}
```

`extraction` je volitelná. V režimu `provided` bez ní uložíme raw zprávu, job dokončíme bez
výroby uzlů. V režimu `llm` se user zpráva extrahuje automaticky. Client-provided extraction
také zůstává candidate; nelze si v requestu poslat potvrzení.
Citace musí být přesný substring content. Neznámé properties odmítáme.

Identita epizody = server scope + source_system + conversation_id + message_id.
Stejný payload vrací stejný UUID a duplicate=true. Stejná identita s jinými daty vrací 409.
Opravená verze zprávy potřebuje nové message_id. Deleted identita se nepřijme znovu.

## Search a context

```json
{
  "query": "Vlastnictví dat",
  "limit": 12,
  "include_candidates": false,
  "as_of": "2026-10-01T00:00:00Z",
  "max_chars": 8000
}
```

`as_of` je volitelný, default je aktuální čas. Kontext budget je **znaky**, ne tokeny.
`used_chars` přesně odpovídá délce textu. Položka s příliš dlouhými zdroji se vynechá celá,
citace se neusekne. `truncated=true` oznamuje vynechané položky.
Active retrieval je zatím lexikální + 1-hop graf, Graphiti hybrid search vrací jen inferred facts
s živými zdrojovými UUID. Obě větve se neprezentují jako totožný vyhledávací engine.
Graphiti as_of je nyní post-filter nad omezenými výsledky; nezaručuje úplný historický recall.

HTTP kódy: 401 nepřihlášený, 403 právo chybí, 404 zdroj/uzel neexistuje,
409 konflikt identity/stavu jobu, 422 neplatný vstup, 503 backend/provider/delete unavailable.

## MCP

Lokální `active-memory-mcp` používá oficiální MCP Python SDK maintenance řady v1, zamčené 1.30.0.
Je to **stdio bridge**, nikoli remote HTTP MCP/OAuth server.

| Nástroj | Použití |
|---|---|
| memory_search | hledání; kandidáti jsou opt-in |
| memory_get_context | reviewed kontext včetně as_of a max_chars |
| memory_map | aktivní mapa |
| memory_get_source | původní epizoda |
| memory_add_message | jen při MEMORY_MCP_ALLOW_WRITE=true a API write právu |

Bridge nenabízí admin nástroje. Používej read token pro běžného asistenta.
Konkrétní aplikace musí umět MCP stdio nebo REST; podpora MCP není sama přístupem do všech chatbotů.

## Fronta ke schválení a události

`GET /v1/candidates?kind=node|link|all&status=candidate|confirmed|rejected|all&relation=&cursor=&limit=` (limit 1–100,
výchozí 25). Řazení je stabilní podle (pořadí první události, druh, id); `next_cursor` je neprůhledný řetězec,
`total` počet všech odpovídajících, `has_more` říká, zda existuje další stránka. Položka obsahuje přesné citace
(`evidence[]`: `quote`, `role`, `occurred_at`, `message_id`, `conversation_id`, `source_system`, `episode_id`,
`url` – vždy `null`, protože zprávy žádné externí URL nenesou), `contributions[]` (původ každého příspěvku z
událostí), poslední `decision` a `audit` (`consistent`, `last_recorded_state`). Stav je vždy z projekce;
`audit.consistent=false` znamená, že projekce a log nesouhlasí.

Hlavička `X-Correlation-Id` (volitelná) se přenese do události rozhodnutí, kontextu nebo smazání.
503 u rozhodnutí s textem „applied but … not recorded“ značí změnu bez zapsané události (viz EVENTS.md).

## Spuštění UI a dema

```bash
uv run active-memory init                 # vypíše owner token (read+write+admin)
uv run active-memory serve                # reference režim, bez LLM a Neo4j
# v druhém terminálu
export MEMORY_CLIENT_API_KEY='TOKEN'      # Windows: $env:MEMORY_CLIENT_API_KEY='TOKEN'
uv run python scripts/demo_review_queue.py
```
Otevři `http://127.0.0.1:8080/ui/review`, vlož token. Token s jen `read` smí prohlížet, tlačítka
Potvrdit/Zamítnout jsou pak zablokována. Demo používá fiktivní konverzace a extrakce dodané skriptem
(žádné volání modelu) a kandidáty nechá nerozhodnuté; opakované spuštění nic nepřidá.
Pro read-only pohled: `uv run active-memory init --client reader --permissions read`.
