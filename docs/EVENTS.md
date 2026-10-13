# Kontrakt událostí v1

Veřejná, verzovaná reprezentace toho, co se v ActiveMemory skutečně stalo. Je psaná nezávisle na
jazyce: klient v Node/TypeScript ji implementuje jen z tohoto dokumentu a z `GET /v1/events`.
ActiveMemory je první producent (`producer: "active-memory"`). Kontrakt nezávisí na žádném agentním
ani orchestračním systému a nepatří janAGI.

## Co události jsou a nejsou

- Události jsou řádky existující provozní tabulky `audit` (SQLite journal) rozšířené o strukturovaný
  dokument. **Neexistuje druhý deník.** Starší řádky auditu bez události (`ingest`, `retry`, …) se přes
  tento endpoint nevracejí.
- Událost se zapisuje **až po dokončení** operace. Selhání nevytvoří událost o úspěchu.
- Události **neobsahují text zpráv ani citace**, ani popisky kandidátů. Odkazují na zdroje a kandidáty
  identifikátorem. Přesné citace se čtou z autorizovaného `GET /v1/candidates` nebo `GET /v1/episodes/{id}`.
- Událost popisuje, co systém zaznamenal. Nedokazuje, že za tokenem seděl konkrétní člověk (viz `actor`).

## Obálka

```json
{
  "schema_version": 1,
  "event_id": "ev_7d9b0c1e5f8a4f0e9a3c2b1d6e4f7a80",
  "sequence": 42,
  "producer": "active-memory",
  "type": "candidate.confirmed",
  "occurred_at": "2026-10-13T14:36:43.377591Z",
  "recorded_at": "2026-10-13T14:36:43.377592Z",
  "actor": {"kind": "human", "identifier": "owner", "assurance": "bearer_token"},
  "subject": {"kind": "node", "identifier": "2de715727b789d616de9f866dc1e5d5c"},
  "previous_state": "candidate",
  "new_state": "confirmed",
  "provenance": [{"kind": "source", "id": "74500ee6-40d6-5b9c-ad19-64a980c2b2d8", "deleted": false}],
  "correlation_id": "9f2c1c6e8d4b4a2e8a51d2f0c7b3a911",
  "data": {}
}
```

| Pole | Význam |
|---|---|
| `schema_version` | celé číslo, nyní `1` |
| `event_id` | opaque řetězec `ev_…`, unikátní |
| `sequence` | vždy rostoucí celé číslo; **jednoznačné pořadí** a kurzor. Posloupnost může mít mezery (sdílí číslování s provozním auditem), nikdy se nevrací zpět |
| `producer` | systém, který událost zapsal |
| `type` | viz níže; klient musí zacházet i s neznámým typem |
| `occurred_at` | kdy se stala skutečná událost; **může být `null`** = neznámo (snapshot). UTC, `…Z` |
| `recorded_at` | kdy byla zapsána; UTC, mikrosekundy, `…Z`. Podle něj se filtruje |
| `actor` | `kind`: `human` \| `system` \| `model`; `identifier`; `assurance`: `bearer_token` (identita ověřená bearer tokenem klienta) \| `internal` (zapsal sám systém) \| `none` |
| `subject` | `kind`: `node` \| `link` \| `source` \| `memory_scope`; `identifier` |
| `previous_state`, `new_state` | `candidate` \| `confirmed` \| `rejected` \| `live` \| `deleted`, nebo `null` pokud nejde o změnu stavu |
| `provenance` | odkazy `{kind: source\|node\|link, id}`; u `source` navíc `deleted` (viz smazání) |
| `correlation_id` | spojuje události jedné operace; při ingestu je to `episode_id` zdroje; `X-Correlation-Id` hlavička (≤ 200 znaků `[\w.:@/+=-]`) ho u rozhodnutí, kontextu a mazání přebírá, jinak se vygeneruje |
| `data` | typově specifická data, viz níže |

### `actor` poctivě

`kind: "human"` u rozhodnutí znamená „operace proběhla přes endpoint pro lidské rozhodnutí s tokenem
oprávnění `admin`“. **Admin token nedokazuje, že tlačítko stiskl člověk** (token může používat skript
nebo agent). `assurance: "bearer_token"` toto přesně říká. Jiné ověření (OIDC, druhý faktor) zatím není.
`actor.identifier` je id klienta z `clients.json`, **nikdy** hodnota z payloadu požadavku.

Dodaná extrakce (`extraction` v ingestu) není ruční návrh člověka: autor není znám a událost ho nevymýšlí
(`actor.identifier` je `client:<id>` předávajícího klienta, `data.origin.kind` je
`client_supplied_extraction`). `model` a `provider` jsou vyplněny jen u `llm_extraction`/`judge`, kde je
služba sama zaznamenala z konfigurace v okamžiku zápisu.

## Typy

Výchozí hodnoty `null` v `origin` znamenají „neznámo / neuplatňuje se“.

### `candidate.created`
Nový kandidát (uzel nebo vazba) vznikl. `subject.kind` = `node` | `link`, `previous_state` = `null`,
`new_state` = `candidate`.
```json
"data": {"candidate_kind": "Goal",
         "origin": {"kind": "client_supplied_extraction", "supplied_by_client": "writer",
                    "model": null, "provider": null, "score": null},
         "evidence_count": 1}
```
`candidate_kind`: druh uzlu (`Theme`, `Thought`, `Fact`, `Question`, `Goal`, `Decision`) nebo relace vazby
(`ABOUT`, `SUPPORTS`, `REFINES`, `CONTRADICTS`, `SUPERSEDES`, `ALIAS_OF`).
`origin.kind`: `client_supplied_extraction` | `llm_extraction` | `similarity` | `temporal` | `judge` | `manual`.

### `candidate.evidence_added`
Další zdroj přispěl k existujícímu kandidátovi. Každý příspěvek má vlastní událost a vlastní `origin` –
původ se nesčítá do jediného autora. `provenance` obsahuje zdroje kandidáta v době zápisu; nový zdroj je
poslední z nich. Stav se nemění (`previous_state` = `new_state` = `null`).
```json
"data": {"origin": {"kind": "client_supplied_extraction", "supplied_by_client": "owner",
                    "model": null, "provider": null, "score": null}, "evidence_count": 2}
```

### `candidate.confirmed` / `candidate.rejected`
Rozhodnutí. `previous_state` a `new_state` jsou zachovány (např. `rejected` → `confirmed`). `provenance` =
zdroje kandidáta v okamžiku rozhodnutí. `data` je `{}`: API nepřijímá důvod, takže se žádný nevymýšlí.
Zamítnutí vazby generované systémem ji znovu nenavrhne.

### `candidate.snapshot`
Explicitní záznam stavu, **ne** vzniku ani rozhodnutí. Používá se (a) při prvním spuštění s auditem pro
kandidáty, kteří už existovali, a (b) při obnově, když stav projekce nesouhlasí s poslední zaznamenanou
událostí. `occurred_at` je `null` (původní čas neznáme), `recorded_at` je čas pořízení snapshotu.
```json
"data": {"basis": "baseline_snapshot", "note": "State observed when audit events were first enabled; earlier history unknown."}
```
`basis`: `baseline_snapshot` | `reconciliation`. U `reconciliation` je `previous_state` poslední známý stav.

### `context.assembled`
Dokončené sestavení kontextu (`POST /v1/context`), zapsané před vydáním odpovědi.
`subject` = `{memory_scope, <scope>}`, `actor.identifier` = autentizovaný žadatel.
```json
"data": {"requester": "reader", "items_returned": 3, "max_chars_requested": 8000, "chars_used": 2303,
         "truncated": false, "include_candidates": false, "as_of": null, "target_assistant": null}
```
`target_assistant` je zatím vždy `null` (žádný ověřený zdroj této informace neexistuje; klientský údaj by
byl nedoložený). Text dotazu se neukládá. `provenance` = id vrácených uzlů.

### `source.deleted`
Živý zdroj byl smazán (`DELETE /v1/episodes/{id}`). `previous_state` `live`, `new_state` `deleted`.
Zapisuje se ve stejné SQLite transakci jako vymazání textu.
```json
"data": {"derived_stores_cleaned": ["live_journal", "active_graph"]}
```
Obsahuje i `"graphiti_projection"`, je-li Graphiti zapnuté.

## Čtení: `GET /v1/events`

Vyžaduje oprávnění `read` (stejné bearer tokeny jako zbytek API; `write` samo nestačí).

| Parametr | Význam |
|---|---|
| `type` | opakovatelný filtr (`?type=a&type=b`); neznámý typ → 422 |
| `from`, `to` | ISO-8601 **s časovou zónou**, filtr na `recorded_at`, interval `[from, to)` (od včetně, do vyloučeno); bez zóny → 422 |
| `subject_kind` + `subject_id` | události jednoho předmětu; musí být spolu |
| `cursor` | `sequence`, od kterého pokračovat (vyloučen) |
| `limit` | 1–200, výchozí 50 |
| `order` | `asc` (výchozí) nebo `desc` |
| `expand=subject` | přidá čtené `subject_view` (aktuální popisek z projekce nebo `{"available": false}`); není součástí uložené události |

Odpověď:
```json
{"schema_version": 1, "events": [ … ], "has_more": true, "next_cursor": "42", "order": "asc"}
```
- **Pořadí je podle `sequence`** (nikdy podle času), takže je jednoznačné i při shodných časech.
- `asc` + `cursor`: vrací `sequence > cursor`. `desc` + `cursor`: vrací `sequence < cursor`.
- `next_cursor` je `sequence` posledního vráceného prvku; při prázdné stránce se vrací vstupní kurzor.
  Klient může stejný kurzor později volat znovu a dostane jen nové události (průběžný odběr dotazováním;
  push zatím neexistuje).
- Stránkování je stabilní při přibývání událostí: nové mají vyšší `sequence`, stránky v `asc` se nepřekrývají
  a nic se nepřeskočí.

Čtecí fronta kandidátů (`GET /v1/candidates`, `GET /v1/candidates/{node|link}/{id}`) není událost, ale
projekce s odkazy na události: `contributions` (původ jednotlivých příspěvků), `decision`, `audit`
(`consistent`: poslední zaznamenaný stav odpovídá aktuálnímu stavu).

## Verzování, opakování, neznámé typy

- `schema_version` se zvýší při nekompatibilní změně. Přidání pole nebo typu je kompatibilní.
- Klient **musí ignorovat neznámá pole** a **neznámý `type` zobrazit jako neznámý** (jen obálku), ne ho
  zahodit ani reinterpretovat. Budoucí typy (agenti, předávání práce, lidské brány, kroky bez AI) tento
  kontrakt zatím nedefinuje ani negeneruje.
- Opakování nevytváří nové události: stejný ingest (duplicate), stejné review (`status` už platí) i znovu
  poslaný návrh vazby vrací existující stav bez zápisu. Zpracování zdroje se po chybě opakuje idempotentně
  (příspěvek, který už událost má, se nezapíše znovu).
- Review umí `expected_status`; nesouhlasí-li aktuální stav, odpověď je 409 a nic se nezmění.

## Autentizace a smazání zdroje

- Všechny koncové body jsou za bearer tokenem. `GET /ui*` je veřejný statický shell bez dat.
- Po `source.deleted` zůstávají v dřívějších událostech jen identifikátory zdroje s `deleted: true`
  (doplněno při čtení). Nezůstává žádný text. Uzly/vazby, které na smazaném zdroji stály, z fronty zmizí;
  `subject_view` je u nich `{"available": false}`. Události o nich se nemažou ani nepřepisují.
- Identifikátory zdrojů jsou UUIDv5 odvozené od `scope`, systému, konverzace a zprávy; z id samotného
  se text nedá obnovit, ale je to stále metadata. Smazání neřeší zálohy (viz `RUNBOOK.md`).

## Skutečné garance a omezení

| Tvrzení | Stav |
|---|---|
| Události jsou append-only přes službu | ano: žádný endpoint je neupravuje ani nemaže |
| Ochrana na úrovni databáze | SQLite triggery `BEFORE UPDATE/DELETE` odmítnou změnu řádků `audit`. Chrání před chybou aplikace, **ne** před správcem databáze, který může trigger smazat nebo soubor přepsat. Není to nezměnitelný archiv ani podepsaný řetězec |
| Atomicita graf ↔ událost | **není**. Graf (JSON/Neo4j) a SQLite jsou dvě úložiště bez společné transakce. Zdroj+job+události zpracování a smazání zdroje+událost jsou atomické uvnitř SQLite; změna grafu a událost rozhodnutí nikoli |
| Pořadí zápisu | graf se potvrdí první, událost až potom. Selhání grafu → žádná událost. Selhání zápisu události po potvrzení grafu → API vrací 503 „applied but not recorded“, fronta ukáže `audit.consistent=false` a rozhodování je zablokováno; při dalším startu se doplní `candidate.snapshot` (`reconciliation`). Do restartu zůstává rozdíl viditelný, ne skrytý |
| Selhání kontextu | `context.assembled` se zapisuje před vydáním výsledku; nelze-li zapsat, kontext se **nevydá** (503) |
| Co se nezapisuje | zmizení kandidáta po smazání zdroje se nevede jako samostatná událost (je to důsledek `source.deleted`); `consolidate`, `export`, `retry` zůstávají jen v provozním auditu |
| Doložení historie | kandidáti vzniklí před zavedením auditu mají jen `candidate.snapshot`; jejich původ a dřívější rozhodnutí jsou neznámé |
| Souběh | jeden proces, jeden worker; `sequence` je přidělován SQLite |
