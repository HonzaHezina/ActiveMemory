"""Seed a running reference instance with synthetic candidates left for human review.

Only fictional conversations (all text, including assistant replies, is invented for the demo). Extractions are *supplied by this script* (the API's `provided`
mode); no language model is called and nothing here pretends otherwise. Candidates stay
`candidate`; decide them on http://127.0.0.1:8080/ui/review. Safe to run repeatedly: identical
messages are recognised as duplicates and add no candidates or events.
"""

import os
import time

import httpx

BASE = os.environ.get("MEMORY_API_URL", "http://127.0.0.1:8080")


def message(chat, mid, content, items, at="2026-10-01T10:00:00Z", role="user"):
    body = {
        "source_system": "synthetic-review-demo",
        "conversation_id": chat,
        "message_id": mid,
        "role": role,
        "content": content,
        "occurred_at": at,
    }
    if items:
        body["extraction"] = {"items": items}
    return body


def item(kind, label, summary, quote, themes=(), **extra):
    return {
        "kind": kind,
        "label": label,
        "summary": summary,
        "quote": quote,
        "themes": list(themes),
        "confidence": 0.7,
        **extra,
    }


MESSAGES = [
    message(
        "architektura",
        "1",
        "Při automatizaci chci zachovat lidskou kontrolu nad výsledkem.",
        [
            item(
                "Thought",
                "Zachovat lidskou kontrolu",
                "Automatizace má nechat poslední slovo člověku.",
                "zachovat lidskou kontrolu nad výsledkem",
                ["Lidská kontrola"],
            )
        ],
    ),
    message(
        "provoz-studia",
        "2",
        "Zálohy ať dělá systém, ale poslední slovo musí mít člověk.",
        [
            item(
                "Thought",
                "Poslední slovo má člověk",
                "Rutinu řeší systém, rozhodnutí člověk.",
                "poslední slovo musí mít člověk",
                ["Lidská kontrola"],
            )
        ],
        at="2026-10-02T09:00:00Z",
    ),
    message(
        "planovani",
        "3",
        "Chci mít vlastní paměť napříč všemi asistenty.",
        [
            item(
                "Goal",
                "Vlastní paměť napříč asistenty",
                "Jedna paměť pro všechny asistenty.",
                "vlastní paměť napříč všemi asistenty",
                ["Vlastnictví dat"],
            )
        ],
        at="2026-10-03T18:00:00Z",
    ),
    message(
        "planovani",
        "4",
        "Jak poznám, kdy můžu rozhodnutí nechat na systému?",
        [
            item(
                "Question",
                "Kdy nechat rozhodnutí na systému",
                "Hranice mezi delegováním a kontrolou.",
                "Jak poznám, kdy můžu rozhodnutí nechat na systému?",
                ["Lidská kontrola"],
            )
        ],
        at="2026-10-03T18:05:00Z",
    ),
    message(
        "rozhodnuti-db",
        "5",
        "Rozhodl jsem se, že paměť bude zatím v PostgreSQL.",
        [
            item(
                "Decision",
                "Paměť v PostgreSQL",
                "Do října bude paměť v PostgreSQL.",
                "paměť bude zatím v PostgreSQL",
                ["Volba databáze"],
                valid_from="2026-06-01T00:00:00Z",
                valid_to="2026-10-01T00:00:00Z",
            )
        ],
        at="2026-06-01T14:00:00Z",
    ),
    message(
        "rozhodnuti-db",
        "6",
        "Od října přecházím na Neo4j, protože hlavní jsou vztahy.",
        [
            item(
                "Decision",
                "Paměť v Neo4j",
                "Od října bude paměť v Neo4j.",
                "přecházím na Neo4j",
                ["Volba databáze"],
                valid_from="2026-10-01T00:00:00Z",
            )
        ],
        at="2026-10-01T09:00:00Z",
    ),
    message(
        "rodina",
        "7",
        "Na víkend plánujeme výlet na Sázavu.",
        [
            item(
                "Fact",
                "Výlet na Sázavu",
                "Rodinný výlet na víkend.",
                "výlet na Sázavu",
                ["Rodinný výlet"],
            )
        ],
        at="2026-10-04T17:00:00Z",
    ),
    # An assistant turn is kept as a source, never turned into a candidate.
    message(
        "planovani",
        "8",
        "Doporučuji pro paměť použít Redis.",
        None,
        at="2026-10-03T18:10:00Z",
        role="assistant",
    ),
]


# Follow-up turns that turn the single-message demo threads into small conversations. All text is
# invented for the demo, including the assistant replies, which are kept as sources only. New
# message ids are added so the original messages (and decisions made on them) stay untouched.
def turn(chat, mid, role, content, at, *items):
    return message(chat, mid, content, list(items) or None, at=at, role=role)


MESSAGES += [
    turn(
        "architektura",
        "9",
        "assistant",
        "Dává to smysl. Můžeme rozlišit tři úrovně: kroky bez zásahu, kroky, které systém jen navrhne, "
        "a kroky, které vždy schvaluje člověk. Která úroveň ti u výsledků zní nejpřirozeněji?",
        "2026-10-01T10:01:00Z",
    ),
    turn(
        "architektura",
        "10",
        "user",
        "Nejvíc mi záleží na tom, aby se nikdy nic nesmazalo bez mého souhlasu.",
        "2026-10-01T10:03:00Z",
        item(
            "Thought",
            "Nic se nemaže bez souhlasu",
            "Mazání vždy až po souhlasu člověka.",
            "nikdy nic nesmazalo bez mého souhlasu",
            ["Lidská kontrola"],
        ),
    ),
    turn(
        "architektura",
        "11",
        "assistant",
        "Rozumím. U mazání tedy navrhuji dvoukrokový postup: systém označí, co by smazal, a smazání "
        "proběhne až po tvém potvrzení. Historie změn přitom zůstane zachovaná.",
        "2026-10-01T10:04:00Z",
    ),
    turn(
        "architektura",
        "12",
        "user",
        "A chci vidět, odkud se každá informace vzala.",
        "2026-10-01T10:06:00Z",
        item(
            "Goal",
            "Vidět původ každé informace",
            "U každého záznamu chci znát zdroj.",
            "vidět, odkud se každá informace vzala",
            ["Původ informací"],
        ),
    ),
    turn(
        "architektura",
        "13",
        "assistant",
        "Každý záznam proto ponese odkaz na zdrojovou zprávu a přesnou citaci. Kde zdroj chybí, "
        "uvidíš „původ neznámý“, ne odhad.",
        "2026-10-01T10:07:00Z",
    ),
    turn(
        "provoz-studia",
        "14",
        "assistant",
        "Jaké zálohy máš na mysli: záznamy rezervací, nebo i fotky a materiály z natáčení?",
        "2026-10-02T09:01:00Z",
    ),
    turn(
        "provoz-studia",
        "15",
        "user",
        "Hlavně rezervace a faktury, fotky jsou na jiném disku.",
        "2026-10-02T09:03:00Z",
        item(
            "Fact",
            "Zálohovat rezervace a faktury",
            "Důležité jsou rezervace a faktury; fotky jsou jinde.",
            "Hlavně rezervace a faktury",
            ["Provoz studia"],
        ),
    ),
    turn(
        "provoz-studia",
        "16",
        "assistant",
        "Rezervace a faktury tedy zálohuj denně do dvou míst. Fotky na druhém disku můžeme zatím "
        "vynechat a vrátit se k nim později.",
        "2026-10-02T09:04:00Z",
    ),
    turn(
        "planovani",
        "17",
        "user",
        "Redis nechci, chci něco, co přežije restart bez ztráty dat.",
        "2026-10-03T18:12:00Z",
        item(
            "Thought",
            "Paměť musí přežít restart",
            "Úložiště nesmí při restartu ztrácet data.",
            "něco, co přežije restart bez ztráty dat",
            ["Volba databáze"],
        ),
    ),
    turn(
        "planovani",
        "18",
        "assistant",
        "Dobrá poznámka. Redis lze nastavit i trvale, ale pro dlouhodobou paměť s vazbami je "
        "vhodnější databáze s trvalostí od začátku, například Neo4j nebo PostgreSQL.",
        "2026-10-03T18:13:00Z",
    ),
    turn("planovani", "19", "user", "Dobře, tak to zvážím večer.", "2026-10-03T18:15:00Z"),
    turn(
        "rozhodnuti-db",
        "20",
        "assistant",
        "PostgreSQL je rozumná volba pro začátek. Zapíšu, že rozhodnutí platí zatím a že se k němu "
        "máš vrátit.",
        "2026-06-01T14:01:00Z",
    ),
    turn(
        "rozhodnuti-db",
        "21",
        "assistant",
        "Rozumím, přechod na Neo4j. Dřívější rozhodnutí o PostgreSQL zůstane v historii s koncem "
        "platnosti k 1. říjnu.",
        "2026-10-01T09:01:00Z",
    ),
    turn(
        "rozhodnuti-db",
        "22",
        "user",
        "Data z PostgreSQL převedu až po záloze.",
        "2026-10-01T09:05:00Z",
        item(
            "Decision",
            "Převod dat až po záloze",
            "Data se převedou z PostgreSQL až po záloze.",
            "převedu až po záloze",
            ["Volba databáze"],
        ),
    ),
    turn(
        "rodina",
        "23",
        "assistant",
        "Skvělý nápad. Chceš připravit seznam věcí, které vzít s sebou?",
        "2026-10-04T17:01:00Z",
    ),
    turn(
        "rodina",
        "24",
        "user",
        "Ano, hlavně něco na jídlo pro děti.",
        "2026-10-04T17:03:00Z",
        item(
            "Goal",
            "Vzít jídlo pro děti",
            "Na výlet připravit jídlo pro děti.",
            "něco na jídlo pro děti",
            ["Rodinný výlet"],
        ),
    ),
    turn(
        "rodina",
        "25",
        "assistant",
        "Navrhuji svačiny, ovoce a dostatek pití. Přidej i náhradní oblečení pro případ deště.",
        "2026-10-04T17:04:00Z",
    ),
]


def main():
    key = os.environ.get("MEMORY_CLIENT_API_KEY")
    if not key:
        raise SystemExit("Set MEMORY_CLIENT_API_KEY to the OWNER token generated by init")
    with httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {key}"}, timeout=60) as api:

        def call(method, path, **kwargs):
            response = api.request(method, path, **kwargs)
            response.raise_for_status()
            return response.json()

        results = [call("POST", "/v1/episodes", json=m) for m in MESSAGES]
        ids = {r["episode_id"] for r in results}
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            jobs = [j for j in call("GET", "/v1/jobs")["jobs"] if j["episode_id"] in ids]
            if any(j["status"] == "failed" for j in jobs):
                raise SystemExit("A job failed; inspect /v1/jobs")
            if len(jobs) == len(ids) and all(j["status"] == "done" for j in jobs):
                break
            time.sleep(0.2)
        else:
            raise SystemExit("Still processing; try again")
        # One explicit, source-quoted link proposal; the same call again changes nothing.
        nodes = {n["label"]: n for n in call("GET", "/v1/map?limit=5000")["nodes"]}
        goal, theme = nodes["Vlastní paměť napříč asistenty"], nodes["Vlastnictví dat"]
        call(
            "POST",
            "/v1/links",
            json={
                "source_id": goal["id"],
                "target_id": theme["id"],
                "relation": "SUPPORTS",
                "episode_id": results[2]["episode_id"],
                "quote": "vlastní paměť napříč všemi asistenty",
            },
        )
        queue = call("GET", "/v1/candidates?status=candidate&kind=all&limit=1")
        confirmed = call("GET", "/v1/candidates?status=confirmed&kind=all&limit=1")["total"]
        events = call("GET", "/v1/events?limit=1&order=desc")
    print(f"Nové zprávy: {sum(not r['duplicate'] for r in results)} z {len(results)}")
    print(
        f"Kandidátů čeká na rozhodnutí: {queue['total']} (potvrzeno dosud: {confirmed}; "
        "nic se nepotvrzuje samo)"
    )
    print(
        f"Poslední sekvence událostí: {events['events'][0]['sequence'] if events['events'] else None}"
    )
    print(f"Otevři {BASE}/ui/review a vlož token s oprávněním admin pro rozhodování.")


if __name__ == "__main__":
    main()
