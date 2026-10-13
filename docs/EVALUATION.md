# Evaluace (AM-002)

Pevný syntetický český dataset `evals/cs_v1.json`: 30 zpráv v 10 chatech (včetně asistentových zpráv,
citovaného cizího názoru a pokusu o prompt injection), 23 dotazů a 25 párových soudů
(stejné téma/myšlenka, odlišné, CONTRADICTS, SUPERSEDES, REFINES, SUPPORTS) = **48 scénářů**.
Zlaté štítky jsou ručně psané, ne výstup modelu. Dataset neobsahuje osobní data.
Test `tests/test_eval.py` kontroluje, že každá gold citace je přesná podstring zprávy.

Spuštění (offline, bez modelu, nulový náklad):

```bash
uv run python scripts/run_eval.py --output /tmp/report.json
```

`--llm` změří nakonfigurovaný extraktor na týchž gold štítcích (posílá syntetické věty providerovi,
vypíše počet volání a tokenů; cenu zatím nepočítá – `price_usd: null`). **Tento režim nebyl dosud spuštěn.**

## Co se měří

| Metrika | Význam |
|---|---|
| precision / recall podle kategorie | položka je správná, pokud cituje zdroj očekávaný gold štítky; recall = pokryté očekávané zprávy |
| violations | vrácená položka stojí na zakázaném zdroji/konceptu/citaci (např. protikladné rozhodnutí v jiném čase, asistent, injection) |
| future_evidence_items | vrácená položka cituje zprávu napsanou až po `as_of` |
| false_positives | dotaz bez očekávané odpovědi něco vrátil |
| same_merge_recall / false_merge_rate | spojení stejných témat/myšlenek napříč chaty × chybné spojení odlišných |
| relation_recall | nalezené SUPPORTS/REFINES/CONTRADICTS/SUPERSEDES vazby (jakýkoli stav) |
| invariants | přesné citace, nic neschváleno strojově, default skrývá kandidáty, rozpočet kontextu, kontext označen jako nedůvěryhodný |
| latency, model_cost | střední/p95 ms ingestu a dotazu; volání/tokeny modelu |

## Baseline (reference backend, gold extrakce, lexikální hledání) – 2026-10-13

Uloženo v `evals/baseline_cs_v1.json`; test selže, pokud se kterákoli z těchto čísel zhorší.

- precision 0.51, recall 0.82 přes všech 23 dotazů; paraphrase recall 0.48, cross_chat_theme recall 0.63.
- same_merge_recall **0.083** (1 z 12 párů; jediný spojený pár má totožný label), false_merge_rate 0.0,
  relation_recall **0.0** (žádné automatické vazby; očekávané, AM-003).
- 4 violations, 14 položek s důkazem pozdějším než `as_of`, 1 false positive
  (dotaz „Jaké je hlavní město Francie?“ se zachytí na slově „je/hlavní“ – lexikální hledání bez stopwords).
- invarianty drží; latence ingestu ≈27 ms, dotazu <1 ms; modelové volání 0.

### Zjištění, která baseline odhalil

1. Parafráze se lexikálně nenajdou a nespojí – to je cílový přínos AM-003.
2. `as_of` filtruje jen platnost tvrzení. Téma bez intervalu se vrací včetně důkazů, které uživatel
   napsal až po daném datu („co jsem věděl tehdy“ nemá filtr).
3. Lexikální shoda bez stopwords vrací nesouvisející silné uzly.

Žádné z čísel není cílová hodnota kvality; slouží jako spodní mez proti regresi.

## AM-003: návrhy vazeb

`scripts/run_eval.py --proposals` po ingestu spustí generátor návrhů a vyhodnotí je proti 25 gold párům
(`evals/baseline_cs_v1_proposals.json`). Metriky: `proposals.precision_on_judged`, `recall` (kolik z 17 gold
vazeb se našlo ve správném typu a směru), `false_proposals_on_distinct` (návrh pro pár, který je v gold
označen jako odlišný), `all_candidate`, `all_sourced`. Sekce `retrieval_after_oracle_review` ukazuje hledání
poté, co „vlastník“ potvrdí gold-správné a odmítne chybné návrhy (jen v evalu; ukazuje horní mez přínosu).

Offline baseline (lexikální + grafové signály): 2 návrhy (ALIAS_OF pro dvojici „Vidět původ informace“ /
„Původní věta a datum“, SUPERSEDES pro PostgreSQL→Neo4j z navazujících intervalů), oba správné, 0 návrhů
pro odlišné páry, recall 2/17 = 0,12. Parafráze bez sdílených slov (např. „Lidská kontrola“ ↔
„Poslední slovo člověka“) se bez embeddingů nenajdou – to je očekávané a změřené.

Se skutečným modelem: `scripts/run_eval.py --proposals --embeddings --judge` (MEMORY_EMBEDDING_*,
MEMORY_MODEL_*; posílá syntetické věty providerovi). CI job `graphiti-live` to spouští ručně/týdně a ukládá
`eval-report.json`. **Toto měření dosud neproběhlo**, prahy proto nejsou kalibrované.
