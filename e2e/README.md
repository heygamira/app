# Gamira end-to-end suite

Playwright driving the real Gamira backend and both real frontend dev servers
together — a real browser, real HTTP, no mocks. This directory is a standalone
Node package; it is not part of the backend or either frontend, and nothing in
here touches their source.

## Run it

```powershell
cd Z:\Gamira\Gamira-App\e2e
npm install
npx playwright install chromium
npm run test:e2e
```

`npm run test:e2e:ui` opens Playwright's UI mode. `npm run test:e2e:report`
opens the HTML report from the last run.

## What it starts, and on which ports

Playwright's `webServer` config brings up three processes before any test
runs, and tears them down afterwards (`reuseExistingServer` is on outside CI,
so a server already running from a previous `npm run test:e2e` is reused
rather than restarted):

| Service | Command | Port |
|---|---|---|
| Backend API | `node scripts/start-backend.mjs` (migrate, seed, then `uvicorn`) | `8020` |
| Family Dashboard | `npm run dev` in `gamira-family-dashboard` | `5174` |
| Parent App | `npm run dev` in `gamira-parent-app-original` | `5173` |

The backend runs with `AUTH_MODE=dev`, `APP_ENV=test`, `FCM_PROVIDER=fake`,
against a disposable SQLite database at `e2e/.data/gamira_e2e.db` (gitignored
— never a developer's own `.local-dev.db` or Postgres database). Each run
re-seeds that database from scratch (`python -m app.db.seed --reset`), so it
always starts from the same fixture data.

Both frontends are started with `GAMIRA_API_TARGET=http://127.0.0.1:8020` so
their `/api` proxy reaches this disposable backend rather than whatever you
might have running on 8000 or 8010.

### Port conflicts

`8020` avoids the common manual-dev backend ports (`8000` bare `uvicorn`,
`8010` `run.py`). **`5173` and `5174` do not avoid anything** — they are each
app's own hardcoded Vite dev port (see `vite.config.js` in each), the same
ports `npm run dev` or `python run.py` uses. Do not run this suite at the same
time as your own `run.py` session or a manually started `npm run dev` for
either frontend — whichever started first will win the port, and the other
will fail to bind or (worse) the suite will silently drive your own dev
session instead of its own disposable backend.

## Not part of CI

There is no CI pipeline in this repo yet. This suite is for running by hand.

## Why a dev sign-in bypass instead of real Firebase auth

Both frontends accept `?dev=<subject>` to sign the tab in as `dev:<subject>`,
but only while their Vite dev server is running in dev mode
(`import.meta.env.DEV`) — see `AuthContext.jsx` in each app. The backend only
accepts `dev:` bearer tokens when it is running with `AUTH_MODE=dev`, which is
refused outside `local`/`test` environments. So this suite:

- always starts each frontend with the real `npm run dev` (never `vite
  preview` or a built bundle) — the bypass is compiled out of production
  builds, not just hidden;
- always starts the backend with `AUTH_MODE=dev`, `APP_ENV=test`.

Any subject string works — `AUTH_MODE=dev` auto-provisions a `User` row for a
subject it has never seen (see `gamira-backend/app/api/deps.py`). Specs that
need a genuinely brand-new identity (onboarding, invite acceptance, senior
linking) generate a random one per run; specs that need pre-existing
multi-family state (the family switcher) use the seeded identities from
`gamira-backend/app/db/seed.py` — `dual-caregiver` is the only seeded identity
in more than one family.

## Layout

```
e2e/
  package.json
  playwright.config.js       webServer (backend + both frontends) and projects
  scripts/
    start-backend.mjs        migrate -> seed --reset -> exec uvicorn
  tests/
    helpers.js                signInAs, freshSubject, apiAs
    family-switch.spec.js     family switcher does not leak seniors across families
    invite-accept.spec.js     a fresh identity joins only the family it was invited to
    senior-link.spec.js       a senior-linked invite shows that senior their own record
    onboarding.spec.js        CreateFamily -> a working dashboard for a zero-family user
  .data/                      disposable SQLite database (gitignored)
```
