# Stav dodaného základu · 2026-10-13

## Implementace

| Oblast | Stav |
|---|---|
| Nezávislý Python projekt, public REST, Python SDK | implementováno |
| MCP stdio read tools + write opt-in | implementováno, discovery test; wire smoke viz VALIDATION |
| Raw zdroje a idempotence, queue/retry, audit, export | implementováno |
| Reference persistent graf | implementováno, behavior testy |
| Neo4j native active-map adapter | implementováno; živý server zde nebyl spuštěn |
| Graphiti adapter 0.30.2, oddělený model/embedder | implementováno; constructor/contract test, bez reálné inference |
| User LLM structured extraction, přesné citace | implementováno; lokální mocked failure/success testy; kvalita modelu neměřena |
| Theme recurrence, exact identity, activity/decay | implementováno |
| Parafráze/latentní témata a automatické link proposals | backlog AM-003 |
| Review kandidátů a explicitní temporal intervals | implementováno, current/historical test |
| SUPPORTS/REFINES/CONTRADICTS/SUPERSEDES | explicitní link API; automatické odvozování a interval closure v backlogu |
| Kontext s reviewed sources a budgetem znaků | implementováno; zatím lexical + 1-hop active graph |
| Full hybrid context assembly | Graphiti facts separátně v search; společný context v backlogu AM-011 |
| Deterministická konsolidace counts/activity | implementováno |
| Autonomní dreaming/semantic clustering | backlog AM-005; není hotové |
| Webové UI pro myšlenkovou mapu | backlog AM-004; map API dnes vrací JSON |
| JSONL import normalizovaných zpráv | implementováno |
| Originální chatbot export connectors | backlog AM-010 |
| Docker/Compose/Coolify/CI | konfigurace dodána; image build/live deployment zde neověřeno |
| Enterprise IAM/multi-tenant/security hardening | mimo základ; IAM interface/backlog zachováno |

## Praktické limity

Jeden proces a jeden osobní scope. Read client má přístup k celému tomuto scope.
Snapshot active graph načítá celý graf a při každé změně přepisuje projekci; před velkým datasetem
nutné AM-006. Queue 30min lease je jednoduchá recovery, ne distribuovaný scheduler.
Audit není immutable. SQLite/Neo4j transakce nejsou společné. Secret filter je minimální pattern
detekce, není kompletní DLP ani anonymizace. Model calls dnes nemají měřený finanční budget.

Aktivita se přepočítá při ingestu nebo explicitní maintenance/consolidate; automatický noční
scheduler není přidaný. Node review nic automaticky nepovažuje za schválené propojení.
Explicitní as_of v active graph funguje, inferred Graphiti history potřebuje lepší search filters/eval.
Model-compatible URL neznamená univerzální podporu každého modelu nebo UI chatbota.
Neo4j nemá DB-level scope marker; používá serverový scope a journal guard. V první fázi instaluj
jednu osobní memory do jednoho data setu a vlastního Neo4j resource.

## Ověření

Přesné provedené kontroly a jejich výsledky jsou v [VALIDATION.md](VALIDATION.md).
Při dalších změnách tento soubor aktualizuj a neoznačuj návrhy za hotové funkce.
