# Provozní postupy

## Kontrola

`/healthz` je liveness. `/readyz` kontroluje lokální úložiště, nikoli funkčnost/cenu modelu.
`/v1/jobs`: pending → running → done; na chybu dvě automatická opakování, pak failed.
202 znamená přijetí zdroje, teprve done znamená dokončenou extrakci/map update.
Restart workeru převezme stale lease po 30 minutách. Jeden worker je záměrný limit první verze.
API access log je vypnutý, audit je actor/action/target/time bez textu. Nejde o neměnný audit.

## Rotace klíče

Přidej nový client `active-memory init --client reader-v2 --permissions read`, restart API,
přepoj klienta, vymaž starý hash z clients.json, znovu restartuj. Neuchovávej skutečné klíče v Gitu.
Při Coolify owner fallback změň env token a redeploy. Klienti pak potřebují nový token.

## Záloha

Vývojová reference: API **zastav**, zkopíruj celý `data/` a `.env`/clients odděleně bezpečně ulož.
SQLite WAL/SHM patří při file backup do stejného konzistentního kopírování; nekopíruj jen otevřený
sqlite3 soubor za běhu. `scripts/backup_local.py` vytváří SQLite online backup + JSON graf,
ale pro vzájemnou konzistenci musí být service zastavená.

Docker: zastav memory worker/API; zálohuj celý memory_data volume. Neo4j zastav a použij
offline `neo4j-admin database dump neo4j --to-path=/backups` podle verze image, nebo offline
kopii neo4j_data volume. Neo4j běžící datové soubory nekopíruj jako konzistentní backup.
Samostatně ulož potřebné configy a secrets. Obě vrstvy označ stejným backup ID a časem.
Repo je v GitHubu, raw data a secrets nikdy nejsou jeho backup.

JSON `/v1/export` je přenositelný export raw episodes + active graph. Neobsahuje Neo4j interní
indexy, Graphiti vektory, audit ani queue. Je určen pro replay/review migraci, ne kompletní disaster recovery.
Import obnovující reviews zatím není implementován; nedělej obnovu pouhým opakovaným ingestem,
pokud potřebuješ zachovat přesná potvrzení a změnové vazby.

## Obnova

Obnov do nové izolované instance se stejným scope. Před startem zastav API.
Obnov konzistentní data a nastavení. Ověř zdroje, počty mapy, reviews, časové dotazy a pending jobs.
Nezkoušej obnovu rovnou na jediné existující kopii dat. Test restore je navazující milestone.

## Smazání zdroje

DELETE vyžaduje admin. Odstraní živý raw text, jeho jobs a příspěvky evidence do active mapy.
Uzly opřené také o jiné zdroje zůstávají; četnosti se přepočtou. Idempotency tombstone zůstává,
aby pozdější stejný import smazaný text nevzkřísil. Audit ponechá identifikátor akce bez obsahu.

Při zapnutém Graphiti se rebuildne jeho odvozený scoped graf z ostatních živých user zdrojů,
aby v souhrnech nezůstaly informace ze smazaného zdroje. To je nákladné a potřebuje funkční model.
Při chybě vrací 503 a raw text není označen jako úspěšně smazaný; po opravě provideru DELETE opakuj.
Rebuild nemusí rekonstruovat identické inferred edges. Živé Graphiti smazání zatím vyžaduje integrační ověření.

Operace není kryptografické ani forenzní odstranění. WAL, disky a staré backupy mohou obsahovat původní bytes.
Po smazání spravuj backup retention/tombstone replay, SQLite checkpoint/VACUUM offline a případně
šifrování disků. Veřejný produkt vyžaduje implementovanou deletion ledger + restore suppression AM-008.

## Porucha modelu nebo graphu

Zdroj v journalu zůstává. Oprav konfiguraci, zjisti error class v jobs a retry failed ID.
Při graph save failure není committed nová in-memory mapa; retry používá stejné source UUID.
SQLite a Neo4j nejsou společná transakce; job může opakovat Graphiti projekci po pádu mezi zápisy.
Exactly-once odvozený graf není slíben. Další milestone přidá checkpoints/projection ledger a reconciliation.
Modelové call failures nesmí vracet fake fakta nebo tichý přechod k jinému providerovi.
