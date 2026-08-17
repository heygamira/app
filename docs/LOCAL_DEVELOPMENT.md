# Local development workflow

These commands work today.

## One command

```powershell
cd Z:\Gamira
python run.py                 # or double-click run.cmd
```

That migrates and seeds the database, starts the API, **the background
worker**, both dev servers, the local voice lab and the watch simulator, then
opens each app in its own phone-sized window. The terminal it runs in becomes the server view: one line
per request, with a note under the ones that matter (a dose confirmed, a
reading recorded, an SOS raised). Ctrl+C stops all of it.

```powershell
python run.py --parents 2 --watches 2      # two cared-for people at once
python run.py --dashboards 2               # owner and caregiver side by side
python run.py --reset-db                   # rebuild the sample data first
python run.py --no-voice --no-browser      # servers only
python run.py --no-console                 # terminal only, no console window
python run.py --phone                      # also serve the apps to your phone
python run.py --parent-port 5273           # when a port is already taken
python run.py --raw-logs                   # unformatted API log lines
```

## The server console

One of the windows is the console, on `http://localhost:8030`. It is served by
`run.py` itself, so it sees the processes and their output directly.

- **Logs** — the same lines as the terminal, in columns:
  `time · service · method · path · status · duration`. The runner sends the
  *fields* rather than a formatted string, so the status carries colour (green,
  amber, red) and a long path cannot push anything out of line; the
  plain-language note for a request sits inside that request's own row. Search
  takes `word`, `-exclude` and `/regex/` together; kinds (writes, reads, errors,
  SOS, unusual) and services are multi-select chips carrying live counts; a time
  window trims to the last minute or fifteen; repeats collapse to one row with a
  count. Clicking a request line pins the view to that request id, and a chip in
  the filter bar is how you unpin it. **Follow** turns itself off when you scroll
  up and on again at the bottom, and **Pause** holds new lines rather than
  discarding them. Filters can be saved, and the filtered view exported. `/`
  focuses the search.
- **Requests** — every API call with method, path, status, duration and
  request id, filterable and sortable, plus per-endpoint p50/p95/max with ids
  collapsed to `:id`. Clicking a row jumps to that request's log lines.
- **Voice lab** — switch between the 3.1 Flash Live and 2.5 native-audio
  models, turn proactive audio and affective dialogue on (2.5 only — they grey
  out with the reason on 3.1), and pick the voice. This drives the standalone
  `gemini_token_server.py`, which is a **local hand-testing tool only**: the
  apps get their sessions from `POST /api/v1/ai/live-sessions` instead, which
  authenticates the user and pins the model server-side.
- **Cost** — token counts the Live API itself reported, priced from
  `tools/console/pricing.json`, split by model, session and modality.
- **Health** — this machine, not the API: CPU, memory, commit charge and free
  space on the system drive, each against a threshold, plus a three-minute CPU
  trend and a breakdown of what *this run's own processes* are using — counting
  the processes they started, because `npm run dev` is a shim and the node
  process under it is the real Vite server. It also reports when Windows firmware
  is limiting the CPU, which is the one condition that looks like a hang but is
  not caused by load. A reading it cannot take says "unavailable" rather than
  showing a figure. See "Why the Health tab exists" below.
- **Phone** — addresses and QR codes for opening the apps on a phone
  (see below).
- **Control** — stop stray Gamira processes left by an earlier run; delete
  caches and test leftovers to reclaim space on the system drive; restart the
  API, the worker, a dev server, the watch or the voice lab on its own; reopen a window that was closed; rebuild the database from seed;
  open the API documentation; raise a test SOS or a test device flag as any
  Parent App person, through the same endpoints the apps use.
- **Database** — every table with its row count, the first rows of any table,
  and a SELECT box. It opens the SQLite file **read-only**: the console is a
  window onto the data, never a second writer, so a demo cannot reach a state
  the API's own rules forbid.

A green dot beside a service means it is running **and** answering on its port.
Amber means the process is alive but nothing is listening — which is what
`uvicorn --reload` looks like when the app fails to import, and what used to
show as a confident green.

### Shut down

**Shut down** in the header is the way out. It names what it is about to close,
then closes it in order: the app, dashboard and watch windows first, then the API
and worker, then the dev servers and voice lab, then a sweep for anything a
killed parent left behind, and the console window last — so the account of what
stopped is readable until the end. `run.py` exits, and the terminal window closes
with it if `run.cmd` opened it. Nothing in the database is deleted.

Ctrl+C in the terminal does the same thing and leaves the window open.

### From a phone, the console is read-only

With `--phone` the console binds every interface so a phone can watch the logs,
and it has **no authentication of any kind**. So off this machine it can only be
read: no actions, no restarts, no database browser. That last one matters most —
the API enforces which family you can see and the SQLite browser does not.

## Testing on a phone

```powershell
python run.py --phone
```

The dev servers bind every interface and serve **https** using a certificate
`run.py` generates on the spot; the Phone tab in the console then shows a QR
code per window. The phone warns once about the certificate — that is expected,
and it is what makes the microphone work: browsers only give a page the
microphone on a secure origin, so the Live API cannot run on a phone over plain
http.

The voice lab stays bound to localhost either way, and the apps no longer need
it: a phone gets its Live session from the API through the dev server's `/api`
proxy, with its own bearer token. The Gemini key stays on this machine.

Each window signs in through `?dev=<subject>` and gets its own browser profile,
which is what lets two Parent App windows be two different people at once. Who
appears in which window is the roster at the top of [`run.py`](../run.py); add a
row there (and in `app/db/seed.py`) to grow the cast.

The watch simulator sends heart rate, oxygen saturation, blood pressure,
temperature and steps as the person wearing it, and can raise an SOS. Its
scenario buttons — racing heart, low oxygen, fever, high blood pressure — exist
to make unusual values easy to test. The amber marking is the simulator's own;
Gamira never labels a reading healthy or unhealthy.


## The worker

```powershell
cd Z:\Gamira\Gamira-App\gamira-backend
python -m app.worker            # the same thing run.py starts
python -m app.worker --once     # drain everything ready, then exit
python -m app.worker --no-scheduler   # Cloud Scheduler drives the ticks
```

**Without it, `GET /doses` returns an empty day.** Dose events, late/missed
transitions, medication reminders, general reminders, appointment reminders,
push delivery and SOS escalation all happen here. The reads stopped generating
anything, which is what makes a dose become missed because time passed rather
than because somebody opened a screen.

`run.py` starts it automatically and the console can restart it on its own. It
logs one line per job with the job id, the type, the attempt and the request id
of whatever caused it — so an API failure and its background consequence sit
under one id.

## Voice, locally

With `GEMINI_API_KEY` in `gamira-parent-app-original/.env`, `run.py` passes it
to the API and sets `AI_PROVIDER=gemini`, so `POST /api/v1/ai/live-sessions`
mints real Live tokens. The key reaches the backend and nothing else; the
browser gets a one-use ephemeral token with the model, instruction and tool
catalogue already pinned into it.

Without a key, the backend uses the deterministic fake provider. Voice will not
connect, and every other path works exactly as before.

## Testing without a paid service

The whole test suite runs against fakes, installed by `tests/conftest.py`
before any app code can build a real provider:

| Real | Fake | What the fake makes testable |
|---|---|---|
| Gemini | `FakeAIProvider` | Sustained outages, schema violations, retry rules |
| Live tokens | `FakeLiveTokenMinter` | Which model, instruction and tools were pinned |
| FCM | `FakePushProvider` | Retryable failures, invalid tokens, per-device attempts |

```powershell
cd Z:\Gamira\Gamira-App\gamira-backend
python -m pytest           # 195 tests
python -m ruff check app tests
python -m mypy
```

Five tests skip unless a PostgreSQL server is configured. They exercise the
production locking path — `SELECT ... FOR UPDATE SKIP LOCKED`, which SQLite
cannot express:

```powershell
docker compose up -d postgres
$env:TEST_POSTGRES_URL = 'postgresql+asyncpg://gamira:gamira@localhost:5432/gamira_test'
python -m pytest tests/test_jobs_postgres.py
```

On a machine with no PostgreSQL,
`test_jobs.py::test_the_production_claim_really_uses_skip_locked` compiles the
same statement against the PostgreSQL dialect and asserts the clause is in it.

## The voice end-to-end demonstration

```powershell
# terminal 1
cd Z:\Gamira\Gamira-App\gamira-backend
$env:DATABASE_URL = 'sqlite+aiosqlite:///Z:/Gamira/Gamira-App/gamira-backend/.e2e.db'
$env:APP_ENV = 'local'; $env:AUTH_MODE = 'dev'; $env:AI_PROVIDER = 'fake'
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8099

# terminal 2, same environment
python -m app.worker

# terminal 3
cd Z:\Gamira
python tools\e2e_voice_demo.py
```

[`tools/e2e_voice_demo.py`](../../tools/e2e_voice_demo.py) drives the whole
voice path the way `geminiVoice.js` does — the Live-session endpoint, the
tool-call batch endpoint, confirm and reject — and checks the things a unit test
cannot: that the API and the worker work *together*. It creates its own family,
so start from an empty database.

It stands in for one thing only: the microphone, and the model choosing which
tool to call. Every request and every assertion is the real one. Actually
speaking to Gamira needs a browser, `python run.py`, and a `GEMINI_API_KEY` —
that part is hand testing, and always will be.


## Why the Health tab exists

On 17 August 2026 this machine hard-crashed at 11:51 during a long run of the
backend test suite, rebooted, and came back with Windows firmware limiting the
CPU. The mouse lagged for minutes. Nothing in the console showed any of it
coming, because everything in it watched the *API* rather than the computer the
API was running on.

Three things went wrong, and each has a guard now.

### 1. Unsupervised processes piled up

`uvicorn` and `python -m app.worker` were started repeatedly without the
previous ones being stopped. Each worker polls once a second and enqueues a
maintenance tick every thirty; several of them against one SQLite file means
every poll queues behind another's write lock. It is invisible — no error, no
log line, just a machine getting slower.

**Guard.** `run.py` now calls `reap_orphans()` before starting anything. It
matches on the *command line* (`app.worker`, `uvicorn app.main`,
`gemini_token_server`, `sim_server.py`), so it will not touch an unrelated
Python, and `stop_all()` sweeps again on the way out for grandchildren that a
killed parent left behind. `--keep-orphans` opts out. The Control tab has a
button for it mid-run.

### 2. The reload watcher was watching 170 MB to serve 1.5 MB

`uvicorn --reload` with no `--reload-dir` watches the entire working directory
recursively — here that meant `.venv`, `.mypy_cache`, `.ruff_cache` and
`.pytest_cache`: thousands of files re-checked constantly, for a source tree of
1.5 MB.

**Guard.** `--reload-dir app`. Same behaviour when you edit the backend, without
the background cost.

### 3. Nothing was watching the machine

The system drive was at 7% free. A full test suite leaves one SQLite database
per test behind and pytest keeps several runs, and an unrelated project had left
a 3.2 GB fixture in the same temp tree. Windows keeps the page file and every
temp file there, so a full system drive is felt as the whole machine being slow.

**Guard.** The Health tab, sampling every three seconds
([`tools/sysmon.py`](../../tools/sysmon.py)), and a **Delete caches and test
leftovers** button that removed 3.1 GB the first time it ran. `run.py` also
refuses to start below 5 GB free or above 92% memory — `--force` overrides, and
between those limits it warns and carries on.

### Using the monitor on its own

```powershell
cd Z:\Gamira\Gamira-App
python tools\sysmon.py
```

Prints a line every two seconds with any warnings, without starting the stack.
Dependency-free on purpose: it reads `kernel32` through `ctypes`, so there is
nothing to install before it can warn you. Every reading degrades to `None`
rather than raising — a broken monitor must never be the thing that stops the
stack.

### One thing it cannot tell you

There is no CPU temperature. Windows exposes thermal sensors only through
vendor drivers or WMI namespaces that need administrator rights, and a monitor
that has to run elevated is a monitor that will not be running. The firmware
throttle event is the honest proxy: when Windows says the CPU is being limited,
heat or a power limit is almost always why.

## Local services

| Service | Default address |
|---|---|
| Parent App | `http://localhost:5173` |
| Family Dashboard | `http://localhost:5174` |
| Gamira API | `http://localhost:8010` |
| API documentation | `http://localhost:8010/docs` |
| Watch simulator | `http://localhost:8020` |
| Server console | `http://localhost:8030` |
| Gemini token server | `http://localhost:8787/token` |
| PostgreSQL | `localhost:5432` |

Port 8000 is avoided because it is in use on the current development machine;
`run.py --api-port` moves the API if 8010 is taken too.

The `8787` token-server prototype should be merged into the API or run only as
a temporary compatibility service.

For an Android emulator, the host machine is normally reached through
`http://10.0.2.2:8010`, not `localhost` inside the emulator.

Both dev servers proxy `/api` to `http://127.0.0.1:8000` by default, so the
browser stays on one origin and no CORS preflight is involved during local
work. The target is `127.0.0.1` rather than `localhost`: on a machine where
`localhost` resolves to `::1` first, the proxy cannot reach a uvicorn bound to
`127.0.0.1`. `run.py` sets `GAMIRA_API_TARGET` for both servers; set it
yourself when starting them by hand on another port.

## Workspace

```text
Gamira/
  gamira-backend/
  gamira-parent-app-original/
  gamira-family-dashboard/
  Gamira-Website-Clean/
  docs/
  docker-compose.yml
  run.py                    one command that starts all of the above
  tools/watch-sim/          the simulated wearable
  tools/console/            the server console window served by run.py
  TODO.md
```

## Commands, one service at a time

`run.py` does all of this; these are the same steps by hand.

```powershell
# Start PostgreSQL
docker compose up -d postgres

# Backend
cd Z:\Gamira\Gamira-App\gamira-backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload --port 8010

# Family Dashboard
cd Z:\Gamira\Gamira-App\gamira-family-dashboard
$env:GAMIRA_API_TARGET = 'http://127.0.0.1:8010'
npm install
npm run dev

# Parent App
cd Z:\Gamira\Gamira-App\gamira-parent-app-original
$env:GAMIRA_API_TARGET = 'http://127.0.0.1:8010'
npm install
npm run dev

# Watch simulator
cd Z:\Gamira\tools\watch-sim
python sim_server.py --api http://127.0.0.1:8010 --pair sharma-senior="Dad's watch"
```

Without Docker, set `DATABASE_URL=sqlite+aiosqlite:///./.local-dev.db` before
`alembic upgrade head`. Settings refuse SQLite when `APP_ENV` is `staging` or
`production`.

## Environment files

Commit `.env.example`; never commit `.env`, `.env.local`, Firebase service-account
JSON, database dumps or API keys.

Backend example names:

```dotenv
APP_ENV=local
API_PORT=8000
DATABASE_URL=postgresql+asyncpg://gamira:gamira@localhost:5432/gamira
CORS_ORIGINS=http://localhost:5173,http://localhost:5174
FIREBASE_PROJECT_ID=gamira-local
GEMINI_API_KEY=
GEMINI_LIVE_MODEL=
FILE_STORAGE_BACKEND=local
```

Frontend example names:

```dotenv
VITE_GAMIRA_API_URL=http://localhost:8000/api
```

Do not use a `VITE_` prefix for secrets. Vite compiles those values into the
client bundle.

## Development authentication

The backend runs with `AUTH_MODE=dev` locally, which accepts `dev:<subject>`
bearer tokens and provisions a user for that subject. It is not authentication;
it exists so the API can be driven before Firebase is configured, and settings
refuse it when `APP_ENV` is `staging` or `production`.

After `python -m app.db.seed`, these identities exist:

| Token | Person |
|---|---|
| `dev:sharma-owner` | Anjali Sharma, family owner |
| `dev:sharma-caregiver` | Rohan Sharma, caregiver |
| `dev:sharma-senior` | Vikram Sharma, a cared-for person |
| `dev:sharma-senior-2` | Sunita Sharma, the second cared-for person |
| `dev:iyer-owner` | Meera Iyer, an unrelated family |

Both apps offer these on their sign-in screen, and both accept
`?dev=<subject>` in the URL during development, which is how `run.py` gives
each window its own identity. Once a Firebase project exists,
set `AUTH_MODE=firebase` and `FIREBASE_PROJECT_ID`; the backend already verifies
real ID tokens against Google's rotating signing keys.

## Frontend data access

Each app has one shared wrapper. Do not place `fetch` calls in pages.

- `src/api/gamiraClient.js` — bearer token, the shared error shape, idempotency
  keys. Present in both the dashboard and the Parent App.
- `gamira-family-dashboard/src/api/dashboardData.js` — translates between API
  names (senior profile, dose event) and screen names (family member, medicine).

The website has no client: it stores no user data and has no signed-in state.

## Database workflow

- Every schema change receives an Alembic migration.
- Migrations are reviewed before application code relying on them is merged.
- Seed data uses fictional identities and measurements.
- Tests use an isolated database.
- Development reset scripts must refuse to target staging or production.
- Never edit production schema manually through a database console.

## Quality checks

Backend target checks:

```powershell
pytest
ruff check .
mypy app
alembic check
```

Frontend existing checks:

```powershell
npm run lint
npm run typecheck
npm run build
```

Base44 is gone from all three frontends. The remaining gap is automated
coverage of the frontend API clients themselves; the backend suite covers the
endpoints they call.

## Local files and audio

Use a local storage directory outside committed source for development uploads.
Raw voice audio is transient by default and should not be written to disk unless
a specific, consented test requires it. Test recordings must not contain real
patient information.

