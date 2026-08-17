# Gamira build plan

This is the short entry point for the Gamira implementation work. The detailed,
ordered checklist is in [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Current objective

Build one local backend that connects the Parent App and Family Dashboard to one
shared PostgreSQL database. The backend will later be deployed to Google Cloud.

## First working milestone

A family member can create a medication schedule, the parent receives the
reminder, the parent records the dose as taken or skipped, and the Family
Dashboard shows the updated event.

## Done

- [x] Scaffold `gamira-backend` as a Python/FastAPI project.
- [x] Add Docker Compose with PostgreSQL (`docker-compose.yml` at the repo root).
- [x] Add database migrations and seed data.
- [x] Implement authenticated users, families, seniors and memberships.
- [x] Implement medications, schedules and dose events.
- [x] Add tests for the complete medication care loop.
- [x] Remove Base44 from all three frontends and replace it with one API client.
- [x] Connect the Family Dashboard to the API.
- [x] Connect the Parent App's reminder and confirmation screen to the API.
- [x] Connect the Parent App's Home, Health, Family, Emergency and Profile
      screens to the API, and remove its login-bypass switch.

The first working milestone now runs end to end: a family member creates a
medication schedule in the dashboard, the dose appears on the Parent App's
Reminders screen, the parent records it as taken or skipped, and the dashboard
timeline shows the result. Confirming twice records one dose.

## Running it

```powershell
python run.py                          # API, worker, both apps, a watch, in windows
python run.py --parents 2 --watches 2  # two cared-for people at once
```

`run.py` now starts the **background worker** alongside the API. Without it
`GET /doses` returns an empty day: the reads stopped generating dose events, and
the worker creates them. It can be restarted on its own from the console.

[`run.py`](run.py) starts everything and narrates the API in the terminal it
runs in. The roster at the top of that file decides who appears in which
window. See [`docs/LOCAL_DEVELOPMENT.md`](docs/LOCAL_DEVELOPMENT.md).

## Next

- [ ] **Configure Firebase** and switch `AUTH_MODE` from `dev` to `firebase`.
      Still the largest single gap: nothing is really authenticated yet.
- [ ] **Create FCM credentials** and set `FCM_PROVIDER=firebase`. The whole
      delivery path — retries, invalid-token revocation, per-device attempts —
      is built and tested against a fake, but no push has reached a real device.
- [ ] **Register for push in the apps.** Needs a service worker in the Parent
      App; `POST /devices` is waiting for it. Until then every notification
      still only reaches somebody whose app is open.
- [ ] **Verify against PostgreSQL.** Docker is not installed on this machine, so
      the production locking path has never run against a server. The tests
      exist and skip; see "Known issues" below.
- [ ] Nothing stops two emergency contacts both being `is_primary`. Either
      enforce one per person or drop the flag for an explicit order.
- [ ] Add authenticated file storage, then restore photo upload in both apps.
- [ ] Show the weekly care summary in the Family Dashboard. The backend
      produces it, with its figures and its provenance; no screen reads it yet.
- [ ] Conversation retention: `retention_policy` is recorded on every
      conversation, but no deletion job runs.
- [ ] An AI evaluation set, before changing models or prompts. The safety rules
      are tested; the *quality* of the wording is not.
- [ ] Connect the website's Get Started and support flows.

## Done, 2026-08-16 — one-command start, a watch, and an SOS that arrives

- [x] `run.py` at the repo root: migrates, seeds, starts the API on **8010**,
      both dev servers, the voice token server and the watch simulator, then
      opens each app in its own phone-sized window. Window counts and the
      identity roster are configurable at the top of the file and per run.
- [x] `POST /seniors/{id}/sos`: records the press as a timeline event and
      raises an in-app alert for every other active family member. The Family
      Dashboard shows it over whatever screen is open; the Parent App alerts
      the family first and still offers the phone call. It contacts nobody
      else — no SMS, no push, no emergency services.
- [x] `tools/watch-sim/`: a simulated wearable that signs in as the person
      wearing it and sends heart rate, oxygen saturation, blood pressure,
      temperature and steps, with scenarios for unusual values and an SOS
      button.
- [x] A person may record their own health reading (the open question below).
      Resolved as: your own device may record you, `source=device` from a
      paired watch included; recording somebody else still needs a write role.
      The Parent App's Health screen stays read-only — the watch writes, the
      screen does not.
- [x] Device readings stay out of the timeline. A stream every few seconds
      would bury the doses and alerts the timeline exists to show; the trend
      still has every value.
- [x] A second cared-for person (Sunita Sharma, `dev:sharma-senior-2`) in the
      Sharma family, so two Parent Apps and one dashboard is a real test.
- [x] The console log formatter now prints the fields a caller passed in
      `extra`, so an access line shows its method, path, status and duration
      instead of the bare word `request_completed`.
- [x] `tools/console/`: a server console window served by `run.py` — the same
      logs with filters and search, restart buttons per service, window
      reopening, a seed/rebuild control, a test SOS, and a **read-only**
      browser over the SQLite database. It cannot write to the database; the
      API stays the only writer.
- [x] The SOS dialog was trapped inside the transformed bar that holds the
      button, so it was cut off at the bottom of the screen and tapping
      outside did nothing. It renders through a portal now, closes on Escape
      or a tap outside, and scrolls on a short window.
- [x] Scrollbars are hidden in every window. Scrolling still works; the track
      was eating a column of a phone-width layout.

## Done, 2026-08-17 — the console as a development surface

- [x] A watch flag reaches the family: `POST /seniors/{id}/device-flags` raises
      a `family_update` notice for every other member, attributed to the device
      by name. The dashboard shows it as an amber, dismissible banner and an
      amber chip on the reading — never the red SOS treatment. The watch fires
      one when a metric leaves its band, and at most once per metric per ten
      minutes while it stays out.
- [x] Console: log filtering with `-exclude` and `/regex/`, multi-select kinds
      and services with counts, a time window, repeat collapsing, presets,
      export, and pinning to one request id.
- [x] Console: a request inspector — every call with its timing and request id,
      p50/p95/max per endpoint with ids collapsed to `:id`.
- [x] Console: a voice lab. Switch between `gemini-3.1-flash-live-preview` and
      `gemini-2.5-flash-native-audio-preview-12-2025`, turn on proactive audio
      and affective dialogue (2.5 only), pick a voice (Erinome by default on
      2.5). The model registry in `gamira_persona.py` drops anything the chosen
      model does not support rather than letting the session fail.
- [x] Console: what the Live API has cost — real `usage_metadata` from the
      session, priced from `tools/console/pricing.json` (paid-tier rates, dated
      and sourced), by model, session and modality.
- [x] `--phone`: dev servers on the network over https with a generated
      certificate, and QR codes in the console. The token server stays on
      localhost; the apps reach it through a `/gemini-token` proxy, so the
      phone's own microphone drives the Live API without the key leaving this
      machine.
- [x] The Gamira mark is now the icon on all four window types, tinted per
      window. The Parent App's `favicon.svg` and `manifest.json` were
      referenced by its HTML but had never existed.
- [x] `success` and `warning` were used by the dashboard's screens but missing
      from its Tailwind config, so every `text-success` / `bg-warning` class
      silently produced nothing.

### Worth knowing

Proactive audio and affective dialogue are documented as needing `v1beta`.
Through an ephemeral token they do not work there: `v1beta` rejects
`proactivity` both when minting and at session setup, while `v1alpha` accepts
it in the token constraints and connects. The registry pins 2.5 to `v1alpha`
for that reason; if it moves, minting fails loudly and the console shows why.

## Fixed along the way

- The senior could not confirm their own dose: they hold a viewer role, and the
  dose endpoints required a write role. A person may now always record their
  own dose event; everyone else still needs write access. Covered by two tests
  in `tests/test_authorization.py`.
- The access log reset its correlation id before writing the line, so requests
  were logged without one.

## Known issues found during the migration

- **PostgreSQL is unverified.** Docker is not installed on this machine, so
  every migration and every test has only run against SQLite. The five tests in
  `tests/test_jobs_postgres.py` exercise the production locking path and skip
  without a server. To close this:

  ```powershell
  docker compose up -d postgres
  cd Z:\Gamira\Gamira-App\gamira-backend
  $env:DATABASE_URL = 'postgresql+asyncpg://gamira:gamira@localhost:5432/gamira'
  python -m alembic upgrade head
  $env:TEST_POSTGRES_URL = 'postgresql+asyncpg://gamira:gamira@localhost:5432/gamira_test'
  python -m pytest tests/test_jobs_postgres.py -v
  ```

  Two things specifically need a real server: the partial unique index on
  `background_jobs.dedupe_key`, and `SELECT ... FOR UPDATE SKIP LOCKED` under
  concurrent workers. In the meantime,
  `test_jobs.py::test_the_production_claim_really_uses_skip_locked` compiles the
  statement against the PostgreSQL dialect and asserts the clause survives.
- The duplicate-content files in the first dashboard export (`Privacy.jsx`,
  `EmptyState.jsx`, `FamilyMemberCard.jsx` each held another component's
  source) were fixed in the second export. Other exports may carry the same
  defect; it is worth a check whenever one is imported.

## Dashboard rebuild, 2026-08-16

`gamira-family-dashboard-new` — a second, more complete export of the same UI —
replaced the first dashboard. The old folder was deleted and the new one now
sits at `gamira-family-dashboard`.

The export arrived fully coupled to Base44 again, so the same removal was
redone: SDK, Vite plugin, generated `base44/` directory, hosted auth pages
(Register, ForgotPassword, ResetPassword, OAuthConsent) and every `gamiraAI`
call. Every screen was then rewired to the API.

The export also shipped invented content wired into the layout. All of it was
replaced with real data or an honest empty state:

- placeholder doses ("Blood Pressure Tablet — Done") in the schedule list
- default vitals and fake sparklines for every health metric
- two fixed "AI insights" about a Mom and Dad who do not exist
- a hardcoded wellness score of 86, "up 4% this week"
- two sample doctor appointments and three sample activities
- a permanent "All Clear — family is safe and monitored" banner
- an SOS button that only wrote a database row
- smart-home switches, including a door lock, that controlled nothing
- a plan chooser that granted entitlements without payment
- a stock photograph of a stranger as the default family-member picture


## Done, 2026-08-17 — a backend that works with no screen open

The theme: everything that had been happening because somebody looked at a
screen now happens because time passed, and everything the AI can do now goes
through checks the AI cannot influence.

### A durable job queue

- `background_jobs` and `python -m app.worker`: a typed `JobQueue` interface, a
  database-backed implementation, atomic claiming with leases, bounded
  exponential backoff with jitter, dead-job handling, graceful shutdown, lease
  recovery, and structured logs carrying the job id and the request id of
  whatever caused the job.
- Claiming has two implementations of one guarantee. PostgreSQL uses
  `SELECT ... FOR UPDATE SKIP LOCKED`; SQLite uses a compare-and-swap update per
  row so the test suite runs without Docker. A test compiles the PostgreSQL
  statement and asserts the clause is really in it.
- `dedupe_key` is unique **while a job is queued or running**, not forever. Two
  schedulers racing produce one job; the same logical key works again next hour.
- Recurring ticks are enqueued on a time bucket, so Cloud Scheduler can replace
  the worker's own ticking (`WORKER_RUN_SCHEDULER=false`) without a handler
  knowing. Cloud Tasks would replace `DatabaseJobQueue` behind the same
  protocol.
- FastAPI's `BackgroundTasks` is used nowhere.

### Deterministic care, moved off the read path

- **`GET /seniors/{id}/doses` writes nothing now.** It used to create the rows it
  was about to return and derive their late/missed status on the way past, which
  meant a dose was only missed once somebody opened a screen.
- `doses.materialize` fills a rolling window ahead of now; creating a medication
  enqueues it in the same transaction, so today's doses do not wait for a tick.
- `doses.advance_status` moves an unanswered dose to late, then missed — and
  writes the missed timeline event and notifies each family member **exactly
  once**, keyed on the dose event id.
- `medications.queue_reminders`, `reminders.process_occurrences`,
  `appointments.queue_reminders`, `notifications.retry_sweep`,
  `alerts.escalation_check`.
- None of these import anything from `app/ai/`.

### Devices and honest delivery

- `registered_devices`: owned by a user, keyed on the client's own `install_id`
  so a token rotation updates one row. Platform, app version, last seen,
  revocation. The push token goes in and never comes out — only a fingerprint
  is returned, and only a fingerprint is ever logged.
- A push provider interface with a fake and a real FCM HTTP v1 implementation,
  retry classification, invalid-token revocation, per-device delivery attempts
  and deduplication.
- **An in-app record is not a delivered push, and no row says it is.** Every
  notification carries an explicit `channel`; an `in_app` row is `sent` when the
  event happens and `delivered_at` stays null.

### A real SOS lifecycle

- `alerts` and `alert_events`: raised, delivery attempted, acknowledged by a
  named person at a named time, escalated when nobody came, resolved by a human,
  or cancelled through an explicitly awkward flow that requires a reason.
- The first acknowledgement wins and stops the escalation. Any member may
  acknowledge, including a viewer — answering an emergency is not an
  administrative privilege.
- Escalation is **louder, not wider**: it re-notifies the same family, because
  Gamira has no consented way to reach anybody else. It still contacts no
  emergency service, and `delivery: "in_app_only"` says so on every response.
- Acknowledgement, resolution and cancellation refuse an AI actor at the service
  layer. Not a config option, not a role, no code path.

### An AI layer whose rules the model cannot reach

- `app/ai/`: provider protocol with a Gemini implementation and a deterministic
  fake, a versioned prompt registry, strict Pydantic output schemas, a
  permission-scoped context builder, a policy engine that never sees the model,
  usage and latency tracking, timeouts, and retry rules that distinguish
  retryable from permanent.
- The first complete feature is the **weekly care summary**, and its shape is the
  point: the backend counts the week (doses by status, unanswered doses,
  reminder completion, reading counts and freshness, watch last-sync, upcoming
  appointments, family activity), persists those figures *before* any model is
  called, and asks the model only to word them. If Gemini fails, the job is
  retryable and the family still has the numbers.
- Stored with every summary: date range, source references, source-data version,
  freshness warning, model, provider, prompt version, output schema version,
  generated time and review state. Nothing starts out reviewed.
- A thin week says so out loud rather than reading as reassurance:
  "Only 2 health readings were recorded, which is too few to describe a trend."

### Authenticated voice, and function calling that works

- `POST /api/v1/ai/live-sessions` replaces the standalone token server. It
  requires a signed-in user, derives the family and cared-for person from
  membership rows, refuses a suspended user or revoked member, enforces
  concurrency and per-hour limits, mints a one-use ephemeral token with the
  model, modalities, system instruction and tool catalogue pinned into it, and
  stores the tool snapshot and the token's *fingerprint*. The permanent key
  never leaves the backend.
- The standalone server survives as an explicitly labelled local voice lab for
  the console's model comparison. No app uses it.
- 15 tools, strict schemas with `additionalProperties: false`: seven read, five
  client-side UI, three state-changing. No generic HTTP, URL, SQL, file or
  endpoint tool, and nothing that can change a medication, a dose quantity, an
  emergency contact, a health reading or a care record.
- Several function calls in one Live message are handled as a batch, each
  keeping its own id and name. One failing call never fails the batch or the
  session.
- Every state-changing call needs a confirmation whose wording the *backend*
  authors from the row it is about to change — "Mark Metformin scheduled for
  8:00 AM as taken?" — shown on screen and spoken aloud. The microphone stops
  feeding the model while a dialog is open, so it cannot ask again over the
  person reading it.
- `live:{session_id}:{function_call_id}` is the idempotency basis. A repeated
  call id gets `duplicate_call`; a second attempt on the same dose changes
  nothing.
- Permission is re-checked at **execution** time, so a membership revoked
  mid-conversation stops the next tool call — and one revoked between the dialog
  appearing and the person tapping yes stops the execution.

### Worth knowing

Declaring strict schemas to the Live API took a real API call to work out.
`FunctionDeclaration.parameters` is the SDK's own `Schema` type, which has no
`additionalProperties` field, and the Live setup returns 400 for it. The
declaration uses `parameters_json_schema` instead, which takes a raw JSON Schema
and accepts it. The fake minter could never have found this; a single real
`auth_tokens.create` call did, and there is now a regression test.


## Incident, 2026-08-17 — the machine crashed under test load

Recorded because the cause was partly this project's own tooling, and because
the fix is a set of guards somebody will otherwise remove as clutter.

**What happened.** At 11:51 the machine shut down uncleanly (`Kernel-Power 41`,
`EventLog 6008`) during a long run of the backend test suite. It rebooted at
12:03 and came back with Windows firmware limiting two cores
(`Kernel-Processor-Power 37`) — the mouse lagged for minutes, and no amount of
closing programs would have helped, because the CPU was clamped rather than
busy.

**What contributed.**

- Several `python -m app.worker` and `uvicorn` processes left running from
  earlier starts, each polling the same SQLite file once a second. One stray
  worker was still alive hours later; the new reaper found it immediately.
- `uvicorn --reload` watching the whole backend directory — the 170 MB `.venv`
  and three caches — instead of the 1.5 MB `app/`.
- The system drive at 7% free (3.4 GB of it pytest leftovers from this project,
  3.2 GB an unrelated project's fixture in the same temp tree).
- 22 VS Code processes, 27 Chrome, and Ollama resident, before any of the above.

**What is not explained by this project.** The same machine also shut down
uncleanly on 6 and 7 August, both at 02:41, when nothing of ours was running.
There is a `TPM` event 30 about hibernate/resume counts not matching. Something
independent is wrong — worth chasing separately, and worth knowing that heavy
test runs land on an already-fragile machine.

**Guards added.**

- [x] Console **Health** tab: CPU, memory, commit charge, system-drive space,
      firmware throttling, a CPU trend, and this run's own usage separately from
      the machine total. [`tools/sysmon.py`](tools/sysmon.py), no dependencies.
- [x] `run.py` stops stray Gamira processes before starting, and sweeps again on
      exit. `--keep-orphans` opts out.
- [x] `run.py` refuses to start below 5 GB free or above 92% memory, and warns
      between there and comfortable. `--force` overrides.
- [x] `--reload-dir app`, so the reload watcher stops scanning `.venv`.
- [x] Console buttons: **Stop stray Gamira processes** and **Delete caches and
      test leftovers** (3.1 GB back the first time).

**Still owed.**

- [ ] Find out why this machine shuts down uncleanly with nothing running. The
      two 02:41 crashes are the thread to pull.
- [ ] Get the system drive comfortably clear. 37 GB of 476 GB is still only 8%,
      and none of the remaining bulk is this project's.
- [ ] The test suite is the heaviest thing here. If it stays a problem, run it
      with fewer workers rather than turning the guards off.

## Console audit, 2026-08-17 — the log screen, the shutdown, and two security holes

Prompted by "redesign the log screen and add a shutdown button". An audit of
`run.py`, `tools/console/console.html` and `tools/sysmon.py` alongside it turned
up two things more serious than the request, so those went first.

**Security.**

- [x] **Stored XSS in the console.** The API accepts an inbound `X-Request-Id`
      header — correct, it is only ever used for correlation — and that value
      travelled into an HTML attribute in the console with no escaping, in a page
      that can restart services, rebuild the database and read every row of it.
      Any page open in the same browser could send the header; CORS blocks reading
      a reply, not making the request. Now sanitised where it is captured
      (`safe_request_id`), the console's escaper covers quotes, and the log
      renderer builds rows as elements rather than strings.
- [x] **`--phone` published the control plane with no authentication.** The
      console bound `0.0.0.0` so a phone could watch the logs, which also gave
      anyone on the Wi-Fi `reset-db`, `stop-all` and unrestricted SELECTs over the
      care records. Off this machine it is now read-only, and says so.

**Shutdown.**

- [x] "Stop everything" ran `stop_all()` on a **daemon** thread while the main
      loop exited on the flag `stop_all()` sets first — so interpreter shutdown
      killed the sweep part-way through and children survived. The console now
      only *asks*; the main thread does the work and always finishes.
- [x] The console window was killed before the first service was asked to stop,
      so nobody ever saw a shutdown. Windows are named and the console goes last.
- [x] `kill()` was the one taskkill on the shutdown path with no timeout: a wedged
      taskkill hung the shutdown, and Ctrl+C with it.
- [x] A **Shut down** button in the header, with a sheet that names what closes.
      `run.py` exits 7 and `run.cmd` skips its `pause`, so the terminal closes too
      — and only ever the terminal `run.cmd` opened.

**The log screen.** The cause was architectural: `render_api()` formatted for a
terminal and the console got the flat string, so it could not align columns or
colour a 500 differently from a 200, and every row showed its clock twice.

- [x] Renderers now return terminal lines *and* structured records separately.
      Columns are a grid; status has colour; the note folds into its request's row.
- [x] Appending rather than rebuilding 1500 rows a second — text selection
      survives, and the console stops being a CPU cost in the tool that warns
      about CPU.
- [x] **Pause was destroying lines.** It advanced the cursor before dropping them,
      so "N waiting" counted lines already lost and resuming could not recover
      them. They are held now.
- [x] Follow yields when you scroll up. The pinned-request state has a chip to
      dismiss it. Four control bars are two.
- [x] Bursts over 900 lines/second used to vanish silently; the gap is now a row.
- [x] `worker` lines had no chip, no count and no colour in either surface.

**The Health tab was measuring the wrong processes.** It tracked direct children,
but the real Vite servers are node grandchildren of npm and the real API is a
child of uvicorn's reload supervisor — so it reported `Gamira: 0.0 GB` and 0% CPU
for everything while the machine sat at 60%.

- [x] Descendants rolled up per service (`CreateToolhelp32Snapshot`, still no
      dependencies), with a process count per row.
- [x] A missing reading said `null GB free of null GB` in critical red, because
      `null <= 10` is true in JavaScript. It says "unavailable".
- [x] The disk alarm and the meter beside it could disagree: the percentage
      thresholds were not exported, so the page improvised "1% free". Exported.
- [x] `snapshot()` sampled synchronously **on the console's HTTP thread** whenever
      no reading existed yet — which is exactly when the page first asks. That
      mutated the CPU tick counters outside the lock, racing the sampler into a
      garbage first reading, threw the sample away so the next request repeated
      it, and ran a `Get-WinEvent` probe whose timeout is 15s inside a request the
      browser was waiting on. It now records through the sampler's own path, under
      the lock, and never probes unless asked. Measured honestly: the probe costs
      about 0.36s on a healthy machine, not 15 — but 15 is the ceiling, and it
      would only be reached on a machine already struggling, which is the one time
      the Health tab matters.
- [x] `monitor.stop()` was never called, and `stop()` left the monitor
      unrestartable.

**Also fixed.** `restart()` was unsynchronised and mutated the list `stop_all()`
walks; a failed `reset-db` left the API stopped; a malformed `Content-Length`
closed a socket with no reply and a traceback into the log; any `/api/state`
error was reported as "runner not reachable"; the orphan reaper could not see a
stranded Vite server holding 5173; two services given the same port passed the
preflight; uptime was wall-clock and could render `up -1m -5s`; `browsers` grew
without bound; error messages printed as `['...']`; `tools/e2e_voice_demo.py` and
~14 documented paths still pointed at the pre-move folder.

**Still owed.**

- [ ] The console has no authentication even on loopback. Read-only from the
      network is a mitigation, not authentication; a token in the URL would be
      the real answer if this ever needs to be driven from a phone.
- [ ] The shutdown sheet's checklist is paced to match what the runner does, not
      driven by it. Real progress would need the runner to report each step.

## Documentation

- [`docs/README.md`](docs/README.md) - decisions, repository audit and document index
- [`docs/ROADMAP.md`](docs/ROADMAP.md) - master phased checklist
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - system boundaries and data flow
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) - proposed PostgreSQL model
- [`docs/API.md`](docs/API.md) - initial API contract
- [`docs/AI_SAFETY.md`](docs/AI_SAFETY.md) - AI decision and safety rules
- [`docs/LOCAL_DEVELOPMENT.md`](docs/LOCAL_DEVELOPMENT.md) - target local workflow
- [`docs/ANDROID_AND_CLOUD.md`](docs/ANDROID_AND_CLOUD.md) - Android and Google Cloud path

