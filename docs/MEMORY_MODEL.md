# Model aktivní paměti

Paměť není seznam chunků. Fakt není totéž co paměť a téma není totéž co konverzace.

| Typ | Význam | Příklad |
|---|---|---|
| Source/Episode | původní zpráva a provenience | zpráva z chatu o provozu studia |
| Fact | tvrzení o světě | projekt Atlas vede Jana |
| Thought | myšlenka, princip nebo interpretace | automatizace má zachovat lidskou kontrolu |
| Theme | opakující se oblast významu | vlastnictví dat |
| Question | nevyřešená otázka | jak zabránit ztrátě souvislostí? |
| Goal | záměr | mít vlastní paměť napříč asistenty |
| Decision | explicitní volba | osobní a firemní paměť zatím odděleně |

Entity jako Person/Organization/Project/System vyplňuje Graphiti. Aktivní mapa je další
produktová vrstva nad zdroji, nikoli kopie entity extraction Graphiti.

Každý active node má `id`, `kind`, `label`, `summary`, `status`, `confidence`, `evidence[]`,
`valid_from`, `valid_to`, `strength`, `conversation_count`, `last_seen`, `activity`.
Evidence obsahuje episode UUID, přesnou citaci, roli, čas a source/conversation/message ID.
Vztah má source/target ID, typ, evidence a samostatný review status.

## Jak vzniká propojení napříč chaty

Téma se dnes sjednotí přes NFKC + casefold + whitespace normalizaci jeho labelu.
Jedna myšlenka má vlastní identitu včetně summary a validity; jiné tvrzení se stejným labelem
vznikne jako další uzel. Nepřepíše se původní význam.
LLM extractor dostává dosavadní labels témat a navrhuje jejich opětovné použití, pokud význam sedí.
Sémantické sjednocení parafrází a aliasů musí projít evaly a bude doplněno v AM-003.

`strength` = počet odlišných zdrojových epizod. `conversation_count` = počet odlišných
(source_system, conversation_id). Opakovaný import stejné epizody počet nezvýší.
`activity = log(1 + strength) * 2^(-age_days / 30)`; decay používá čas posledního výskytu.
Síla a aktivita jsou relevance, nikoli důkaz pravdy. Nízká aktivita nic nemaže.

## Stavy a čas

`candidate` → owner `confirmed` / `rejected`. Kandidáti jsou viditelní v mapě a ve vyhledávání
s explicitním `include_candidates=true`. Standardní kontext je neobsahuje.
Schválení uzlu neschvaluje okolní vazby. ABOUT může být potvrzen zvlášť.
Asistentovy odpovědi se uchovají jako zdroj, ale samy se automaticky neextrahují jako uživatelovy názory.

Platnost je `[valid_from, valid_to)`, timestampy mají timezone. Occurred_at je čas zprávy,
valid_from je čas pravdivosti tvrzení; nejsou zaměnitelné. Neznámá platnost je null.
Pokud změna projektu nastala 1. října, starý fact má valid_to přesně 1. října 00:00, nový valid_from
stejný bod. Tím existuje jediný aktuální fact a dohledatelný starší stav.
V tomto základu jsou okna explicitní data návrhu; SUPERSEDES je vztah změny, sám starý interval nezavírá.
Graphiti má vlastní automatickou temporal extraction. Ta zůstává odvozeným kandidátem.

## Vztahy

- ABOUT: patří k tématu.
- SUPPORTS: podporuje jinou myšlenku.
- REFINES: zpřesňuje ji.
- CONTRADICTS: je s ní v rozporu; nemusí znamenat změnu v čase.
- SUPERSEDES: nahrazuje předchozí formulaci/rozhodnutí; původní historii zachováme.

## Dreaming / konsolidace

Implementována je deterministická konsolidace aktivity/četnosti. Nevyrábí nové významy,
neslučuje tvrzení a neschvaluje nic. Budoucí dreaming vytvoří proposal se zdrojovými citacemi,
vysvětlením podobnosti/rozdílu a možností odmítnutí nebo vrácení. Návrhy nesmějí z vlastní
domněnky vytvořit nový důkaz. Žádné nevratné slučování ani smazání původních episode.

## Kontext a embeddings

Context Assembler vybírá relevantní reviewed uzly, časovou platnost, schválené 1-hop vazby
a kompletní zdroje. Má přesný budget v znacích, ne předstíraný budget tokenů pro všechny modely.
Kandidáti Graphiti jsou samostatná položka hledání; automatický context je zatím nepromuje.
Embedding je pomocná reprezentace podobnosti pro daný model, není univerzální přenos paměti
do libovolného LLM. Klient standardně dostává text/strukturované evidence, ne cizí modelový vektor.
