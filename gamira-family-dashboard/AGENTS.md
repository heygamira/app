# Working in the Family Dashboard

## What this app is

The family and caregiver client for Gamira. One backend (`gamira-backend`), one
database. This app holds no credentials and no AI keys.

## Rules

1. **Do not reintroduce Base44.** The SDK, the Vite plugin, the generated
   `base44/` directory and the hosted auth pages were removed deliberately. It
   was the builder used to generate this UI, never a backend.
2. **All network access goes through `src/api/gamiraClient.js`.** No `fetch` in
   a page or component. Authentication, the error envelope and idempotency keys
   live in one place so they cannot drift.
3. **Never invent data to fill a layout.** No placeholder doses, no default
   vitals, no sample appointments, no stock photograph standing in for a person.
   If there is nothing to show, show that. Someone reads these screens to decide
   whether a parent took their medicine.
4. **Do not state more than the backend knows.** Gamira records what was
   entered or confirmed. It does not monitor anyone, does not judge whether a
   reading is healthy, and does not contact emergency services. An SOS reaches
   this app because it is polling; nobody is called, and acknowledging one
   marks it read for you alone.
5. **Keep an alarm and a notice apart.** An SOS is a person asking for help:
   red, interrupting, never anything else. A device flag is a watch reporting
   that a number left the range set *on the device*: amber, dismissible, and
   worded as the device's finding. Gamira adds no opinion of its own to
   either, and dressing the second up as the first would teach a family to
   ignore both.
6. **Never use a `VITE_` prefix for a secret.** Vite compiles those values into
   the client bundle.
7. **Do not commit** `.env`, `.env.local`, Firebase service-account JSON,
   database dumps or API keys.
8. **A feature is not done because its screen exists.** It needs an
   authenticated endpoint, server-side authorization, a migration, and loading,
   empty and error states.

## Layout

```
src/api/gamiraClient.js     the only fetch caller
src/api/dashboardData.js    API names <-> screen names, fan-out helpers
src/lib/AuthContext.jsx     session, families, people in care
                            (`?dev=<subject>` signs one window in locally)
src/lib/usePoll.js          screen refresh; stands in for push delivery
src/lib/useAlerts.js        unacknowledged alerts, split into sos and notices
src/lib/careSummary.js      counted summaries
src/lib/careStatus.js       dose-status vocabulary and colours
src/components/gamira/      the design system for this app
src/pages/                  one file per route, routes declared in App.jsx
```

## Before you finish

```powershell
npm run lint
npm run typecheck
npm run build
```

All three must pass.
