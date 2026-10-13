# Začni zde

Projekt žije v repozitáři [HonzaHezina/ActiveMemory](https://github.com/HonzaHezina/ActiveMemory).
Python package a CLI se jmenují `active-memory`; název GitHub repa tuto integraci nemění.

## 1. Naklonuj repo

```bash
git clone https://github.com/HonzaHezina/ActiveMemory.git
cd ActiveMemory
```

Otevři adresář ve VS Code, Cursoru nebo jiném editoru a pokračuj lokálním spuštěním níže.
Pokud už máš aktuální checkout, použij běžný `git pull` a zachovej své lokální změny.

Původní ZIP balíček obsahuje také offline Git bundle. Ten je pouze alternativa ke klonování
GitHubu, do zdrojového repa ho není potřeba přidávat.
Repo obsahuje kód a fiktivní ukázky. Osobní data, `.env`, klientské tokeny a backupy patří
mimo veřejný Git; odpovídající cesty jsou v `.gitignore`.

## 2. Spusť reference režim

### Windows PowerShell

```powershell
uv sync --frozen --extra dev
Copy-Item .env.example .env
uv run active-memory init
uv run active-memory serve
```

Fronta kandidátů: otevři `http://127.0.0.1:8080/ui/review` a vlož token (jen v paměti stránky).
Demo kandidátů ke schválení: `uv run python scripts/demo_review_queue.py` (token v `MEMORY_CLIENT_API_KEY`).

V novém terminálu ve stejném adresáři:

```powershell
$env:MEMORY_CLIENT_API_KEY = 'SEM_TOKEN_Z_INIT'
uv run python scripts/demo.py
uv run pytest -q
```

### Linux/macOS

```bash
uv sync --frozen --extra dev
cp .env.example .env
uv run active-memory init
uv run active-memory serve
```

V druhém terminálu:

```bash
export MEMORY_CLIENT_API_KEY='SEM_TOKEN_Z_INIT'
uv run python scripts/demo.py
uv run pytest -q
```

Bez `uv`: `python -m venv .venv`, aktivace venv, `pip install -e '.[dev]'`.
`uv.lock` je preferovaný zamčený vývojový postup. Docker používá samostatný hashovaný
`requirements.lock`, včetně Graphiti.

V `/docs` klikni Authorize a vlož token. Výsledná mapa je JSON z `/v1/map`.
Samostatné webové UI je připravený navazující úkol, nepovažuj tento balíček za hotové UI.

## 3. Předej repo programovacímu agentovi

Vlož agentovi **celý obsah [docs/AGENT_START_PROMPT.md](docs/AGENT_START_PROMPT.md)**.
Repo obsahuje `AGENTS.md`, `CLAUDE.md` i `.github/copilot-instructions.md`.
První úkol není velké přepsání: má ověřit existující základ a projít živý Neo4j/Graphiti scénář.
Pak pokračuje vyhodnocením kvality a aktivní sémantickou mapou.

## 4. Připoj ostatní asistenty

Vytvoř samostatný read token:

```bash
uv run active-memory init --client agent-reader --permissions read
```

Po změně `clients.json` restartuj API. Agentům nedávej owner/admin token.
Spusť MCP bridge s `MEMORY_API_URL` a `MEMORY_CLIENT_API_KEY`, viz
`config/vscode.mcp.example.json` a `config/mcp.generic.example.json`.
Na Windows změň command na úplnou cestu `.venv\Scripts\active-memory-mcp.exe`.
Systémy bez MCP použijí stejné REST API. janAGI potřebuje jen URL a klientský token.

## 5. Až pak nasazení na Hetzner/Coolify

Použij [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md). Nasazení a skutečné placené modelové volání
v tomto prostředí neproběhlo. Repo má konfiguraci i agentovi zadává živé integrační ověření.
