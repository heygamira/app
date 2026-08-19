# AGENTS.md

## Project context

The Gamira Parent App: the senior-facing client. React and Vite, talking to one
backend, `gamira-backend`, over `/api/v1`.

This app was originally generated with the Base44 builder. Base44 has been
removed; do not reintroduce the SDK, the Vite plugin or a `base44/` directory.

Start with `README.md` for local setup and environment variables.

## Key files

- `src/api/gamiraClient.js` — the only module that calls `fetch`.
- `src/api/parentData.js` — health-metric cards, dose status vocabulary and the
  small time helpers the screens share. No data is invented here.
- `src/lib/AuthContext.jsx` — signed-in session. `self` is the senior profile
  linked to the signed-in user.
- `src/lib/useSeniorCare.js` — loads this person's doses, reminders, readings
  and emergency contacts. Every screen with live data goes through it.
- `src/pages/Reminders.jsx` — today's dose events and the taken/skipped action.
- `src/lib/geminiVoice.js`, `src/lib/useGeminiVoice.js` — voice session. The
  session comes from `POST /api/v1/ai/live-sessions` through `gamiraClient`,
  with the normal bearer token. The backend picks the model, the system
  instruction and the tool catalogue and pins them into a one-use ephemeral
  token; the browser only obeys what it is handed. **No API key, and no direct
  call to the token server.**
- `src/lib/voiceTools.js` — the client half of the tool catalogue: which tools
  run in this browser (navigation, opening a detail, opening the real SOS or
  dialer confirmation) and the allowlisted dispatcher that runs them. Everything
  else is forwarded to the backend.
- `src/components/gamira/VoiceConfirmDialog.jsx` — the confirmation every
  state-changing voice action passes through. The wording comes from the
  backend, built from the row it is about to change.
- `vite.config.js` — dev server on 5173, proxies `/api` to `127.0.0.1:8000`
  (override with `GAMIRA_API_TARGET`; the repo-root `run.py` sets it to 8010).

## What this person can and cannot do

The cared-for person holds a **viewer** role in their own family. The backend
enforces it, and the UI must agree:

- They **can** read their own doses, reminders, readings, contacts and family.
- They **can always** record their own dose — taken or skipped. This is the one
  thing the app exists for.
- They **can always** raise an SOS for themselves, and a watch paired to their
  account may record their own health readings.
- They **cannot** add or edit emergency contacts, another person's readings or
  their own care record. Their family curates that in the dashboard. The
  Health screen here stays read-only: the watch writes, the screen does not.

So those screens are read-only here, and say who to ask. Do not add a form that
the server will reject.

## Working notes

- This screen is used by an older person, often in a hurry. Keep targets large,
  text at the existing sizes, and never rely on colour alone to convey state.
- Add API calls to `gamiraClient.js`; do not put `fetch` in a page.
- Dose actions must stay idempotent. The client sends an `Idempotency-Key` and
  the backend returns the existing event on a replay — do not work around it.
- Safety-critical behaviour must work without the AI. Reminders and emergency
  contacts cannot depend on a model being reachable. `/ai/*` returning 503 must
  leave every other screen working.
- **Voice can read and act, but only through the catalogue.** Never add a tool
  that changes a medication, a dose quantity, an emergency contact, a health
  reading or a care record. Never add one that raises, cancels or resolves an
  SOS — `prepare_sos` opens the real dialog and the person presses it.
- A tool that changes anything must go through `VoiceConfirmDialog`, and the
  prompt must be the backend's wording, not the model's. Only say something
  succeeded after the backend returns a persisted result.
- Client tools are an allowlist in `voiceTools.js`. Never build a route, a URL
  or a handler name from what the model said.
- **Never invent a value to fill a card.** No default vitals, no sample
  schedule. This app is read by the person whose medicine it is.
- **Never claim the app contacts emergency services.** It does not. SOS raises
  an in-app alert that the rest of the family sees *if their app is open*, and
  then offers to dial a saved contact from this phone. That is all it can do:
  no SMS, no push, no call placed for the person, no escalation when nobody
  answers. Say exactly that on screen.
- The Parent App can register for push: `usePushRegistration`
  (`src/lib/usePushRegistration.js`) asks permission, gets an FCM token via
  `public/firebase-messaging-sw.js`, and calls `POST /devices`. It only runs
  when the person turns it on from Settings → Notifications — nothing here
  asks on its own. Even then, an actual push additionally needs the backend's
  `FCM_PROVIDER=firebase` credentials configured, which is a separate,
  not-yet-done step; until that happens, or for anyone who leaves the toggle
  off, a notification still only reaches somebody whose app is open.
- There is no login-bypass switch in the source any more. Use
  `VITE_BYPASS_AUTH` in `.env.local`, or `?dev=<subject>` in the URL to make
  one window a particular seeded person, for local UI work. Both only work
  against a backend running with `AUTH_MODE=dev`.
- Run `npm run lint`, `npm run typecheck` and `npm run build` before finishing.
