# Backlog pro pokračování s AI agentem

Každý úkol je samostatný commit/PR s behavior testem. Nejdřív osobní paměť, potom až jiný produktový scope.

| ID | Priorita | Úkol | Hotovo, když |
|---|---|---|---|
| AM-001 | P0 | živý Neo4j/Graphiti test a Docker build | clean boot, role/user ingest, UUID provenance, search, restart, deletion/rebuild, isolation skutečně projdou |
| AM-002 | P0 (hotovo: [EVALUATION.md](EVALUATION.md); chybí měření LLM extraktoru) | pevný CZ eval dataset | 30+ ručně označených scénářů, parapráze, temporal, irrelevant, cross-chat themes, source role; měří precision/recall/provenance/latency/model cost |
| AM-003 | P0 (implementováno; čeká na měření s reálnými embeddingy a kalibraci prahu) | aktivní sémantická mapa | embedding podobnost + grafová souvislost navrhují Theme/Thought aliases a vazby napříč různými chaty; žádné auto-confirm ani false merge bez možnosti vrácení |
| AM-004 | P1 | UI pro mapu a review | rozbalit téma, vidět zdroje a vývoj, potvrdit/odmítnout uzel/vazbu; candidate jasně viditelný |
| AM-005 | P1 | dreaming proposals | dávková konsolidace s budgetem, explicitní proposal/evidence/reason, review a revert; original nodes/history zůstávají |
| AM-006 | P1 | incremental persistence a projection ledger | žádný O(N) snapshot při každé zprávě, DB queries/pagination, crash-safe checkpoints, rozdělení workerů a konzistence reviews |
| AM-007 | P1 | provider test matrix a budgets | model + embedding samostatně; schema/json_object validated; allowed endpoints, max call/token/cost budget, timeouts/rate limits/backoff |
| AM-008 | P1 | robustní deletion a restore | deletion ledger, live projection purge/rebuild verified, backup restore neznovuobnoví smazané zdroje, dokumentovaný retention |
| AM-009 | P1 | export/replay/migrace | reference→Neo4j i schema migration; zachová IDs, reviews, vazby a konflikty; dry-run a verze |
| AM-010 | P2 | export adaptéry ChatGPT/Claude/Gemini | skutečné fixtures exportů, pořadí/role/dates/branches/attachments, stable IDs; žádné neautorizované session scraping |
| AM-011 | P2 | Context Assembler v2 | kombinuje semantic active map + Graphiti facts se source trust; vysvětluje výběr, uncertainty a relevantní konflikty; token budget per client model |
| AM-012 | P2 | IAM boundary implementace | read/write/admin principal adaptér, OIDC validation, audience/issuer/revocation testy; nevybírá předčasně Keycloak/Entra/MidPoint |
| AM-013 | P2 | remote MCP | authenticated Streamable HTTP s podporovaným SDK/auth kontraktem a testy; stdio bridge zůstává pro lokální klienty |

## Měřitelné scénáře

- Stejná myšlenka řešená v chatu o IT a v chatu o práci propojí téma; lokální téma chatů se neztratí.
- Parafráze se mohou propojit, významově podobné ale opačné rozhodnutí se nesmí sloučit.
- User preference se neodvodí z asistentova návrhu ani z citovaného cizího textu.
- Otázka nezmizí jen proto, že model vygeneroval hypotetickou odpověď.
- Změna rozhodnutí zachová obě formulace, datum a citace; aktuální a historické dotazy se liší správně.
- Nesouvisející dotaz nevrací náhodně silné téma.
- Opakovaný import nemění counts/cost opakovanou extrakcí bez důvodu.
- Owner může odmítnout automatickou interpretaci; další konsolidace ji automaticky neoživí.
- Smazání jediného důkazu odstraní příslušnou interpretaci z kontextu.

V `examples/evaluation-cases.json` jsou startovní syntetické případy, nikoli již změřený benchmark.
Žádná cílová čísla kvality se nepovažují za splněná bez měření na datasetu.

## Mimo nynější scope

Firemní paměť, personal/company knowledge transfer, shared ownership, enterprise multi-tenancy,
digitální osobnost člověka, billing, SaaS marketplace a automatické připojování všech účtů.
