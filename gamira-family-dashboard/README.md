# Gamira Family Dashboard

The family and caregiver client. It shows the people a family cares for, their
medicines and dose times, what has been confirmed or missed, health readings,
and a timeline of everything recorded.

It talks to one backend: `gamira-backend`. There is no other data source.

## Run it

```powershell
# 1. Backend, in another terminal
cd Z:\Gamira\Gamira-App\gamira-backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --port 8000

# 2. This app
cd Z:\Gamira\Gamira-App\gamira-family-dashboard
npm install
npm run dev          # http://localhost:5174
```

The dev server proxies `/api` to `http://127.0.0.1:8000`, so the browser stays
on one origin and no CORS preflight is involved.

If port 8000 is taken by something else, run the backend elsewhere and point
the proxy at it:

```powershell
uvicorn app.main:app --reload --port 8001          # backend terminal
$env:GAMIRA_API_TARGET = "http://127.0.0.1:8001"   # this terminal
npm run dev
```

## Signing in

The backend verifies a bearer token; this app never sees a password. Until a
Firebase project exists, sign in with a development identity from the seed data
(`python -m app.db.seed` in the backend):

| Identity | Person |
|---|---|
| `sharma-owner` | Anjali Sharma, family owner |
| `sharma-caregiver` | Rohan Sharma, caregiver |
| `sharma-senior` | Vikram Sharma, the cared-for person |
| `iyer-owner` | Meera Iyer, an unrelated family |

These only work while the backend runs with `AUTH_MODE=dev`, which it refuses in
staging and production. The sign-in screen also accepts a pasted Firebase ID
token — the backend already verifies real ones.

To skip the sign-in screen during UI work, set in `.env.local`:

```dotenv
VITE_BYPASS_AUTH=true
VITE_DEV_AUTH_SUBJECT=sharma-owner
```

## Checks

```powershell
npm run lint
npm run typecheck
npm run build
```

## How the code is arranged

- `src/api/gamiraClient.js` — the only module that calls `fetch`. Bearer token,
  the shared error envelope, idempotency keys. Pages must not call `fetch`.
- `src/api/dashboardData.js` — translation between API names (senior profile,
  dose event) and screen names (family member, medicine), plus the fan-out
  helpers that load several people at once.
- `src/lib/AuthContext.jsx` — the session: user, families, memberships, the
  people in your care, and which one is selected.
- `src/lib/careSummary.js` — summaries counted from records.
- `src/lib/careStatus.js` — the shared vocabulary for what a dose status means
  on screen.

## Things this app deliberately does not claim

A care app is read by someone deciding whether to drive over and check on a
parent. Where a screen has no backend behind it, it says so rather than
showing something plausible:

- **Nothing is invented.** An empty schedule looks empty. A metric with no
  reading says "Not recorded". A person with no photo shows their initial, not
  a stock photograph of a stranger.
- **Summaries are counted, not generated.** Every line comes from records the
  backend returned. AI narration is a later phase and will sit on top of the
  same figures.
- **Emergency does not alert anyone.** It dials a contact you saved. Gamira does
  not contact emergency services and does not notify anyone in the background.
- **Push notifications are not connected.** The notifications screen shows the
  delivery record the backend keeps; sending to phones arrives with FCM.
- **Plans are read-only.** There is no billing, so no button pretends to
  activate one.
- **Smart home controls nothing.** No device pairing exists, so no switch moves.
- **"All Good" is gone.** Gamira knows whether a dose was confirmed, not whether
  someone is well, so the badges say "On track" / "Dose late" / "Dose missed".

## Base44

Base44 was the builder used to generate this UI. It is not a backend this
product depends on, and every trace of it has been removed: the SDK, the Vite
plugin, the generated `base44/` directory, the hosted auth pages and the
`gamiraAI` calls. Do not reintroduce it.

The `@` import alias used to come from the Base44 Vite plugin; it is declared
explicitly in `vite.config.js` now.

## Known gaps

- Photo upload needs authenticated file storage. Both profile screens take a
  URL in the meantime.
- `WelcomeCard` asks the browser for the user's location and sends the
  coordinates to open-meteo and bigdatacloud to show local weather. It is the
  only third-party call in the app; remove the component if that is not
  wanted.
