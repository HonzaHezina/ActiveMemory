# Nasazení

## Lokální Docker

Po `uv run active-memory init` existuje `config/clients.json`. `.env.example` zkopíruj do `.env`.
`docker compose up -d --build` spustí reference režim. Port 8080 je bindovaný pouze na loopback.
API běží jako UID 10001, persist volume vlastní tento UID. Klientská konfigurace je read-only mount.

S Neo4j: nastav dlouhé náhodné `MEMORY_NEO4J_PASSWORD` a použij overlay `compose.graph.yaml`.
Neo4j 7474/7687 nejsou publikované. Do `.env` není potřeba měnit URI: overlay ji nastaví interně.
Neo4j používá user `neo4j`; pokud ho měníš, změň také NEO4J_AUTH v Compose.

## Hetzner / Coolify

Po úspěšném vytvoření GitHub repa:
1. V Coolify vytvoř resource z tohoto repa a `compose.coolify.yaml`.
2. Nastav `MEMORY_API_KEY` (min. 24 náhodných znaků), `MEMORY_NEO4J_PASSWORD`.
3. Scope ponech `personal:owner` nebo jednoznačný vlastní `personal:ID`.
4. Nastav HTTPS doménu **jen službě memory, port 8080**. Neo4j doménu ani veřejný port nedostane.
5. První boot udělej s model calls=false a provided extraction. Ověř readyz, auth a demo.
6. Vytvoř backup, potom případně povol model/provider extrakci.
7. Pro připojené asistenty vytvoř read/write klíče, ne sdílený owner token. V Coolify default fallback
   používá jeden owner token; pro další klíče nastav trvalý mount clients.json a jeho cestu.

Coolify služby sdílejí svoji Compose síť; není vyžadována externí síť jménem `coolify` ani janAGI.
Pokud použiješ odlišné routování/proxy labels ve své instalaci, přidej je lokálně podle ní.
Reverzní proxy má limitovat request body, request rate a timeout; před veřejným provozem dodělat
aplikační limity a IAM z backlogu. API payload limit je 50 000 znaků content, nikoli globální body limit.

## Modely a embeddings

| Nastavení | Význam |
|---|---|
| MEMORY_EXTRACTION_MODE=provided | žádné automatické LLM návrhy |
| MEMORY_EXTRACTION_MODE=llm | user message → active-map návrhy |
| MEMORY_ALLOW_MODEL_CALLS=true | explicitně zapne možnost posílat data modelu |
| MEMORY_GRAPHITI_ENABLED=true | user source → Graphiti temporal fact graph |
| MEMORY_MODEL_BASE_URL / API_KEY / NAME | inference i reranking |
| MEMORY_EMBEDDING_BASE_URL / API_KEY / MODEL / DIM | samostatný embedding provider |

Local nebo hosted OpenAI-compatible endpoint lze nakonfigurovat. Graphiti adapter používá
OpenAIGenericClient, nikoli endpoint-specifický OpenAI Responses klient.
Active extractor vyžaduje JSON-schema structured output; pokud model neumí schema, job selže a
nevymyslí fallback fakta. Rozšíření kompatibility `json_object` se validací je úkol AM-007.
OpenRouter/Kimi/Qwen/GLM apod. nejsou v tomto balíčku kvalitou ani cenou ověřené.
Konfiguruj je až s konkrétním modelem, endpointem, strukturou a eval testem.

Při enabled Graphiti musí být nainstalované extra `graphiti`. Docker image jej obsahuje.
Graphiti telemetry je vypnutá. Concurrency SEMAPHORE_LIMIT=3 je startovní limit, ne záruka ceny/latence.
LLM i embeddings mohou odesílat části zpráv do různých služeb, podle uvedené konfigurace.

## Kapacita a versioning

Pro první instanci začni orientačně 4 vCPU, 8 GB RAM a SSD; změř RAM, ingest a retrieval na
svých objemech. Není to benchmark ani garantovaný sizing. Heap/pagecache zde mají startovní 1+1 GB.
Balíček obsahuje přesné direct verze, `uv.lock` pro dev a hashovaný `requirements.lock` pro Docker.
Base images mají konkrétní tagy, nikoli digest lock. Před provozním nasazením ověř existenci,
security updates, kompatibilitu a případně pin digest v daném registru.
Nespouštěj více API/worker procesů nad stejnou memory. Snapshot backend by přepisoval změny.
Neškáluj horizontálně před AM-006.

## Třetí strany v UI

`src/active_memory/ui/cytoscape.min.js` je přibalený Cytoscape.js 3.30.2 (licence MIT, text v `cytoscape.LICENSE`).
Nenačítá se z CDN (CSP povoluje jen `'self'`). Aktualizace: stáhnout konkrétní verzi z npm balíčku `cytoscape`,
nahradit soubor i licenci a spustit `pytest` a Node testy.
