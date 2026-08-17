# Gamira backend

The authoritative API for the Parent App, the Family Dashboard and the website.
One FastAPI service, one PostgreSQL database, all authorization server-side.

## Run it locally

```powershell
cd Z:\Gamira\Gamira-App\gamira-backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
Copy-Item .env.example .env

# PostgreSQL
docker compose -f ..\docker-compose.yml up -d postgres

alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload --port 8000
```

`http://localhost:8000/docs` serves the generated OpenAPI documentation, which is
the executable source of truth for the contract.

### Without Docker

PostgreSQL is the supported database. If Docker is not available yet, a first
checkout still runs against SQLite:

```powershell
$env:DATABASE_URL = "sqlite+aiosqlite:///./.local-dev.db"
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload --port 8000
```

Settings refuse SQLite when `APP_ENV` is `staging` or `production`.

## Authentication

Every authenticated endpoint expects `Authorization: Bearer <token>`.

- `AUTH_MODE=firebase` verifies a real Firebase ID token against Google's
  rotating signing keys. This is the only mode allowed outside local and test;
  the settings object raises at startup otherwise.
- `AUTH_MODE=dev` accepts `dev:<subject>` and provisions a user for that
  subject. It is **not** authentication and exists so the API can be driven
  before Firebase is configured.

After seeding, these development identities exist:

| Token | Person |
|---|---|
| `dev:sharma-owner` | Anjali Sharma, owner of the Sharma family |
| `dev:sharma-caregiver` | Rohan Sharma, caregiver |
| `dev:sharma-senior` | Vikram Sharma, the cared-for person |
| `dev:iyer-owner` | Meera Iyer, owner of an unrelated family |

The two families are unrelated on purpose: anything one can read from the other
is an authorization bug, and `tests/test_authorization.py` asserts it cannot.

## Quality checks

```powershell
pytest
ruff check .
ruff format --check .
mypy
```

## Layout

```text
app/
  core/       settings, logging, error format, middleware, token verification
  db/         engine, session, base classes, column types, seed data
  models/     SQLAlchemy tables
  schemas/    request and response models
  services/   authorization, identity, scheduling, dose recording, audit
  api/v1/     routers
alembic/      migrations
tests/        authorization, medication loop, scheduling, care records
```

## Behaviour worth knowing

- **Timezones.** A dose schedule stores a local `HH:MM` plus the person's IANA
  timezone. Occurrences are built in that zone and converted to UTC, so an 08:00
  dose stays at 08:00 across a daylight-saving change.
- **Idempotency.** `(schedule, scheduled_at_utc)` is unique, so regenerating
  dose events is safe to retry. `POST /dose-events/{id}/taken` accepts an
  `Idempotency-Key` and returns the existing canonical event on a replay.
- **Derived status.** An unacknowledged dose becomes `late` and then `missed`
  from its own schedule's windows. A dose someone has acted on is never
  re-derived.
- **Errors.** Every failure returns
  `{"error": {"code", "message", "details", "request_id"}}`. Clients switch on
  `code`; `message` is for display only.
- **Correlation.** Every response carries `X-Request-Id`, and every log line for
  that request carries the same id.
- **Audit.** Family, membership, consent, medication and emergency-contact
  changes append to `audit_logs`. Tokens and invitation secrets never go in.

## Not implemented yet

These are roadmap items, not omissions to work around:

- Push delivery through FCM (`notification_deliveries` records exist; nothing
  sends them yet).
- File upload and report generation.
- AI endpoints and the realtime voice token service.
- Alerts and SOS lifecycle.

See [`../docs/ROADMAP.md`](../docs/ROADMAP.md).
