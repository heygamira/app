# Gamira engineering documentation

Status: planning baseline, created 2026-08-14.

These documents define the intended architecture and implementation order. They
are not claims that the described backend features already exist.

## Product boundary

Gamira has three public-facing clients:

1. Parent App - senior-facing voice, reminders, health and SOS experience.
2. Family Dashboard - family and caregiver monitoring and coordination.
3. Website - marketing, support, account entry and plan information.

All clients must use one authoritative backend and one primary database. The AI
model is a dependency of that backend, not a separate source of truth.

## Agreed initial technology

- Backend: Python and FastAPI
- Primary database: PostgreSQL
- Migrations: Alembic
- Data access: SQLAlchemy
- Authentication: Firebase Authentication, verified by the backend
- Notifications: Firebase Cloud Messaging
- AI: Gemini, accessed with server-side credentials
- Local orchestration: Docker Compose
- Later hosting: Cloud Run and Cloud SQL on Google Cloud

## Current repository state

- `gamira-backend/` — the FastAPI service. Identity, families, medications,
  dose events, reminders, timeline, health readings and notifications, with
  authorization enforced server-side and a passing test suite.
- `gamira-family-dashboard/` — the family client, on the API.
- `gamira-parent-app-original/` — the senior client, on the API. Home,
  Reminders, Health, Family, Emergency and Profile all read live data for the
  signed-in person; dose confirmation is the write path.
- `Gamira-Website-Clean/` — the marketing site. No user data, no auth.
- `docker-compose.yml` — PostgreSQL, and the API when you want it containerised.
- Voice prototype scripts under `Backend-on-cloud-infuture`.

Base44 has been removed from all three frontends. It was the builder used to
generate them, never a backend this product depended on. Its SDK, Vite plugin,
generated `base44/` directory and hosted auth flows are gone.

Resolved from the original audit:

- The `base44/config.jsonc` and `base44/entities/*.jsonc` files contained React
  component source rather than configuration or schemas. They were deleted with
  the rest of Base44; the PostgreSQL schema was designed from product
  requirements and actual UI usage instead.
- The `gamiraApi.js` stub with its fixed `X-User-Id` header is gone, replaced by
  `src/api/gamiraClient.js`, which sends a bearer token the backend verifies.
- `gamira-family-dashboard/LOCAL_APP.md`, which described an older SQLite
  backend that never existed here, has been removed.

On 2026-08-16 the Family Dashboard was replaced by a second, more complete
export of the same UI. The old folder was deleted; the new one is at
`gamira-family-dashboard`. It arrived coupled to Base44 again, so the removal
was redone and every screen rewired to the API.

Still open:

- The root `run.py` expects voice files beside it, while the current source
  files live under `Backend-on-cloud-infuture`.
- Builder exports can contain a different component's source in a file
  (`Privacy.jsx`, `EmptyState.jsx` and `FamilyMemberCard.jsx` all did in the
  first dashboard export; the second export had fixed them). Check for this
  whenever an export is imported.

## Architecture decisions

1. Begin with a modular monolith, not microservices.
2. Both apps share users, families, permissions and data.
3. Apps never receive database credentials or permanent AI keys.
4. The backend authorizes every data access and action.
5. AI proposes structured decisions; deterministic policy code authorizes and
   executes them.
6. Safety-critical behavior must work without an LLM.
7. Use UTC for stored timestamps and retain each senior's IANA timezone.
8. Separate local, staging and production environments from the beginning.
9. Build the medication care loop before smart home, doctor marketplace or
   predictive health features.
10. A senior is a viewer in their own family — they are not there to administer
    other people's care — but they may always record their own dose. Anyone
    else needs a write role. Without this the Parent App cannot do the one
    thing it exists for.
11. A screen never invents data to fill its layout. No placeholder doses, no
    default vitals, no sample appointments, no stock photograph standing in for
    a person. Someone reads these screens to decide whether to drive over and
    check on a parent, and plausible-looking filler is indistinguishable from a
    real measurement. Where a feature has no backend behind it, the screen says
    so.

## Documents

- [`ROADMAP.md`](ROADMAP.md) - the master TODO list and completion gates
- [`ARCHITECTURE.md`](ARCHITECTURE.md) - system components and security boundaries
- [`DATA_MODEL.md`](DATA_MODEL.md) - database entities, marked implemented or not
- [`API.md`](API.md) - API conventions and every endpoint, marked implemented or not
- [`AI_SAFETY.md`](AI_SAFETY.md) - AI orchestration, permissions and guardrails
- [`LOCAL_DEVELOPMENT.md`](LOCAL_DEVELOPMENT.md) - the local workflow, as it works today
- [`ANDROID_AND_CLOUD.md`](ANDROID_AND_CLOUD.md) - packaging and deployment path

## Definition of done

A feature is not complete because its screen exists. It is complete only when:

- It has an authenticated backend endpoint.
- Authorization is enforced on the server.
- Data is persisted through a migration-managed schema.
- Important actions produce an audit event.
- Loading, empty, error and retry states are handled in the client.
- Automated tests cover the main success and failure paths.
- Sensitive values are absent from frontend bundles and source control.
- Relevant documentation and API contracts are updated.

