# Gamira Parent App

The senior-facing client: voice, reminders, health and emergency contacts. It
reads and writes through the Gamira backend.

## Run locally

Start the API first:

```powershell
cd Z:\Gamira\gamira-backend
.\.venv\Scripts\Activate.ps1
alembic upgrade head
python -m app.db.seed
uvicorn app.main:app --reload --port 8000
```

Then:

```powershell
cd Z:\Gamira\gamira-parent-app-original
npm install
npm run dev
```

The app runs on `http://localhost:5173` and proxies `/api` to
`http://127.0.0.1:8000`.

If port 8000 is taken by something else, run the backend elsewhere and point
the proxy at it:

```powershell
uvicorn app.main:app --reload --port 8001          # backend terminal
$env:GAMIRA_API_TARGET = "http://127.0.0.1:8001"   # this terminal
npm run dev
```

For an Android emulator, the host machine is reached at `http://10.0.2.2:8000`,
not `localhost`.

## Signing in

The backend verifies a bearer token; this app never handles a password. While
the backend runs with `AUTH_MODE=dev`, the sign-in screen offers the seeded
development identities. Once a Firebase project exists, real ID tokens work
through the same screen.

To skip the sign-in screen during local work, add to `.env.local`:

```dotenv
VITE_BYPASS_AUTH=true
VITE_DEV_AUTH_SUBJECT=sharma-senior
```

There is no hard-coded bypass switch in the source: the login gate is always on,
and `VITE_BYPASS_AUTH` is the only way past it.

## Environment

```dotenv
VITE_GAMIRA_API_URL=http://127.0.0.1:8000/api/v1
```

Never put a secret behind a `VITE_` name; Vite compiles those into the bundle.
The Gemini key belongs on the server, in `.env` (gitignored), and is read by the
Python voice scripts — not by this app.

## What is connected

Every screen reads live data for the signed-in person. `self` in
`AuthContext` is the senior profile linked to that user.

- **Home** — the next dose waiting, today's real schedule (dose events plus
  routines), a health snapshot from actual readings, and one-tap confirm.
- **Reminders** — today's dose events with taken/skipped, the person's routines,
  and what has already been settled. Idempotent: a second tap on a slow
  connection cannot record a second dose.
- **Health** — every metric that has a reading, with a real trend line. Metrics
  with nothing recorded are listed as not recorded, never filled in.
- **Family** — the emergency contacts this person can call, and who in the
  family can see their care.
- **Settings → Emergency** — the real contacts, with one-tap dialling.
- **Settings → Profile** — the account name is editable; the care record is
  read-only, because the family maintains it.
- Voice uses the Gemini Live browser client and a short-lived token. Merging
  that token service into the authenticated backend is a later phase.

## What this person is allowed to do

The cared-for person is a **viewer** in their own family. They can read their
care record and they can always record their own dose. They cannot add contacts,
readings or edit their care details — their family does that in the dashboard,
and the backend enforces it. The screens say so rather than offering a form the
server would reject.

## What this app never claims

- It does not contact emergency services. SOS dials the saved primary contact
  from this phone.
- It does not alert anyone in the background. There is no push delivery yet.
- It does not share location. The old toggle for it wrote a flag nothing read.
- It does not judge whether a reading is healthy.

## Checks

```powershell
npm run lint
npm run typecheck
npm run build
```
