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

- [ ] **Create real FCM credentials** and set `FCM_PROVIDER=firebase`,
      `FCM_CREDENTIALS_FILE`, `FCM_PROJECT_ID` in `.env`. The delivery path,
      both apps' registration flow, and the config plumbing are all built and
      tested against a fake — but no push has reached a real device, because
      nobody has generated a service-account key or a Web Push (VAPID)
      certificate for the Firebase project yet. That has to happen in the
      Firebase console; nothing local can substitute for it.
- [ ] Nothing stops two emergency contacts both being `is_primary`. Either
      enforce one per person or drop the flag for an explicit order.
- [ ] Add authenticated file storage, then restore photo upload in both apps.
- [ ] Show the weekly care summary in the Family Dashboard. The backend
      produces it, with its figures and its provenance; no screen reads it yet.
- [ ] Wake-word recall is 0.674 and the false-positive target is not met
      (`public/wake/manifest.json`). The detector now *runs* — on launch, on
      every screen — but none of that makes it hear better.
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

## Done, 2026-08-18 — proactive, voice-first, and visible

The theme: the app stopped being something you operate.

- [x] **Voice is app-wide.** `lib/VoiceContext.jsx` is a layout route wrapping
      every signed-in screen. The session, the wake-word detector and the
      confirmation dialog used to live inside `pages/Home.jsx`, so navigating
      anywhere tore down the microphone — an app meant to be run by voice had
      voice on one screen out of six.
- [x] **It listens on launch.** The wake word arms on mount when microphone
      permission is already held (Chrome's autoplay policy exempts exactly that
      case), falling back to the first gesture on a first visit. The old "arm on
      the first tap anywhere" rule looked right and was not: the first tap it
      could see was almost always the microphone button, and that same tap
      starts a session, which *pauses* the detector for its whole duration.
- [x] **The SOS countdown is real, on both paths.** `autoConfirmSeconds`
      defaulted to 0 and nothing ever passed a value, so the voice-opened SOS
      fired on the next tick with no countdown and no cancel window — while the
      tool description told the model a cancellable countdown was running.
- [x] **"Cancel" works out loud**, before and after it has gone. Before, it is a
      client tool closing a dialog. After, `cancel_my_sos` withdraws it with a
      spoken confirmation, keeps the row, and tells the family it was cancelled.
      The one narrow exception to "the assistant cannot end an alert", written
      up in full in `docs/AI_SAFETY.md`.
- [x] **A flagged reading gets asked about.** `wellbeing_checks` (migration
      `0009`) makes the flag durable, Gamira asks, and
      `JobType.WELLBEING_CHECK_ESCALATE` tells the family if nobody answers —
      as `AlertType.WELLBEING_CHECK`, amber, never the red SOS treatment.
      The model reports the answer; a rule about elapsed time decides.
- [x] **The background TTS is gone.** Both `speechSynthesis` call sites removed.
      Gamira speaks first through the Live API instead, with the microphone shut
      until she has finished her sentence and a 20-second window after it.
- [x] **The transcript shows both sides.** The person's own words were being
      transcribed and handed to nobody. New `VoiceTranscript` panel, and a
      microphone button with five distinguishable states — grey and still when
      nothing is listening, which is a thing it could never say before.
- [x] **The "Taken" button lives on its row**, inside the card for the medicine
      it records, instead of a full-width bar underneath that read as a page
      action belonging to nothing.
- [x] **The console has a "Gamira's mind" tab.** Decisions, observations,
      memories, suggestions, notices, usage and wellbeing checks, straight from
      the rows the backend writes. Nine log lines existed in `app/ai/` and eight
      of them were failures; a *successful* tool call logged nothing at all.

## Done, 2026-08-18 — the repair pass

Found by running it rather than by testing it, which is the point of the list.

- [x] **`wellbeing_checks` could not be written to at all.** Migration `0009`
      declared `created_at`/`updated_at` NOT NULL with no `server_default`,
      while `Timestamps` supplies only a server default — so SQLAlchemy left
      them out of the INSERT and every watch flag died on NOT NULL. The whole
      feature had never run outside the tests, which build the schema from the
      models. `test_migrations.py` now compares the migrated database to the
      models **column by column**, and was checked by reintroducing the bug.
- [x] **One-off reminders.** "Remind me in five minutes" works, the backend does
      the clock arithmetic in the person's timezone, and the reminder
      **completes after it fires** — without which a five-minute timer became a
      permanent daily alarm.
- [x] **The SOS countdown reset forever and the dialog would not close.** Two
      inline arrow props gave `begin` and `confirm` a new identity on every
      parent render; the open effect re-fired and the tick timer restarted.
      Home re-renders several times a second while Gamira speaks, which is
      exactly when the dialog is up. Callbacks live in refs now, the open effect
      keys on the signal's *value*, and the countdown is 5 seconds.
- [x] **She says the countdown out loud.** The brief was `briefInto(...) ||
      talk(...)`, and `talk` is async — the `||` tested a promise, so the
      fallback never ran and with no session open she said nothing.
- [x] **The alert that would not close.** Every press and escalation writes its
      own notification; dismissing one revealed the next. Acknowledging now
      clears them all, and an acknowledged alert counts as closed.
- [x] **The transcript.** Reads `interimInputTranscription`, which nothing did —
      so the person's own words could only appear after they stopped talking,
      by which time Gamira had overwritten them. One sentence at a time in a
      fixed-height slot, hers in the accent purple, theirs held for 1.4s so they
      can be read. Nothing below it moves.
- [x] **Proactive nudges marked themselves "already said" before speaking**, so
      one failed session silently burned that dose for the day. Plus a UTC date
      key and a browser-clock comparison, both now the person's own timezone.
- [x] **Speculative voice sessions.** Each guess mints a real Google token; each
      abandoned one also queued a review of an empty conversation, and the only
      limit was a constant in the browser. Guard added, server-side hourly cap
      added, pre-connect threshold 0.40 → 0.75.
- [x] **Shutdown.** `pump()` called `stop_all()` from a daemon thread — the same
      bug fixed for the console path and left on the path taken when a dev
      server dies. And browser windows reopened from the Control tab survived
      every shutdown, because their launcher process exits immediately; they are
      closed by profile now.
- [x] **sysmon walked the whole process table once per tracked pid per sample** —
      120 full walks a minute from the tool that exists to notice things making
      the machine slow. One snapshot per sample.
- [x] **The console.** Decision rows lead with the sentence and keep the fields
      as detail; they are violet rather than a third amber. Conversation and
      Gamira's mind can be scrolled — they were bare divs in a flex column and
      no input could reach them.

## Done, 2026-08-18 — the second pass, from a screen recording

Everything here was found by using it, and several of them are the same bug
reported twice because the first fix never reached a running database.

- [x] **The watch flag still failed.** `0009` was corrected in place, which
      fixes a database built from scratch and does nothing for one that has
      already run it — Alembic does not re-run an applied revision. `0010`
      rebuilds the table with the defaults. The first version of it dropped all
      five indexes on the way through, because batch mode keeps only what
      `copy_from` was told about; `test_migrations.py` now asserts every model
      index survives every migration, and that test was checked by removing
      them again.
- [x] **"I feel unwell" now reaches the family.** New `tell_family` tool: a
      `family_update` notification and a timeline entry, never an alert, never
      urgent, and confirmed first when the idea was hers. Between an emergency
      and silence there was nothing at all, so the commonest thing anybody
      would want their family to know either became an SOS or waited for the
      after-call review — which only sends anything if the model happened to
      say it would.
- [x] **The person's own words were concatenated with themselves.** The
      interim transcript replaced, the finalised one *appended*, and both carry
      the same sentence — so their line read "I have a headacheI have a
      headache". Both replace now; the finalised one closes the utterance so
      the next thing they say starts a new line.
- [x] **The captions raced four sentences ahead of her voice.** The transcript
      is generated text and arrives as fast as the model can produce it, so a
      whole reply is on screen while she is still saying the first sentence of
      it. Arrival time says nothing about speech and is no longer used:
      sentences queue and are released at a speaking pace, and the queue
      shortens its own holds when it falls behind. `npm run caption:check`
      covers the splitting and the pacing, including the two it got wrong
      first: a full stop at the very end of the stream is not a boundary yet,
      and "Dr. Fictional" is not two sentences.
- [x] **Their line stayed too long, hers was anonymous, nothing ever cleared.**
      One second for theirs, a blue-to-violet gradient for hers — the
      microphone's own colours — and the slot empties five seconds after the
      last thing said.
- [x] **"Bye" cut her off mid-goodbye.** She calls `end_conversation` in the
      same turn as "talk to you later", and the audio for that sentence is
      already scheduled in the playback graph, which `stop()` tears down.
      `finish()` stops listening at once and closes when the sentence has
      actually been said, with a 12-second backstop.
- [x] **The "your family knows" dialog stayed open after the alert was
      withdrawn by voice.** Nothing told the screen: only confirmations came
      back to the app. Backend tool results are reported by name now, so
      `cancel_my_sos` closes it — and "Cancelled" closes itself after a few
      seconds rather than waiting to be dismissed.
- [x] **The reminder nudge was three times the size of the row it was about**,
      and it asked *whether to set a reminder* for the thing it was in the
      middle of reminding them about. It is now the same shape as a schedule
      row, with Taken or Done; the brief tells her to deliver the reminder, not
      offer one; and the card goes when the conversation it opened ends, or
      when what it is about is recorded, wherever that happened.
- [x] **A missed dose was never mentioned.** The nudge list stopped at `late`,
      and a dose becomes `missed` on a timer — so the doses most worth a word
      were the only ones she never said anything about.
- [x] **A watch that is not running no longer shows numbers.** A reading a
      *device* sent is only "now" while the device is still sending; after ten
      minutes both apps show a dash and "not reporting". A reading somebody
      typed in is never stale — a weight from last week is still their weight.
- [x] **Only the console opens at start-up.** The new **Apps** tab opens each
      window when it is wanted and closes it again, one at a time or all at
      once. `--open-all` restores the old behaviour. Four Chrome instances
      before anybody has asked for one was most of the load on the machine.
- [x] **Every line is written to `logs/run-<timestamp>.log`**, as it happens,
      and the last twenty runs are kept. The ring buffer holds a few thousand
      lines, which is the wrong amount when the interesting thing happened
      twenty minutes and one dependency re-scan ago.
- [x] **A rejected device flag was retried every tick.** `entered` is false by
      then and `stale` compares against a timestamp that was never set, so one
      failing endpoint became a request every few seconds, each one a full
      traceback in the console — hammering a server that is already failing.

### Still the biggest cost, now at least under control

Four browser windows are four *separate* Chrome instances, each with its own
profile — 20–30 processes — plus two Vite servers, a reloading uvicorn, and a
wake-word model doing up to 12.5 WASM inferences a second in the Parent App
window. `--parents 2 --watches 2` makes it six windows.

Nothing inside Gamira makes a Chrome instance cheap, so the change is to stop
opening ones nobody asked for: start-up opens the console alone, and the Apps
tab opens and closes the rest on demand. Two windows instead of four is roughly
half of it, and closing the parent app window is the only way to stop the
wake-word model entirely.

## Done, 2026-08-19 — a family can actually be more than one family, real sign-in, a verified database

### Multi-family selection, linking and onboarding

- [x] **The dashboard mixed every family's cared-for people together.**
      `AuthContext.jsx` hardcoded `activeFamily: families[0]`, and `/me`
      returns every senior across every family a user belongs to in one flat
      list — so a caregiver in two families saw both families' people in one
      grid, with no way to tell them apart or switch. `activeFamilyId` is now
      real state (same pattern as the existing senior selector), and `seniors`
      is narrowed to the active family before anything else reads it — every
      existing screen got this fix for free, since none of them read `/me`'s
      raw list directly.
- [x] A family switcher in the header, shown whenever a signed-in user
      belongs to more than one family.
- [x] **Invitations, `/family-access` and `/invite-member`.** The backend
      always supported creating and accepting invitations
      (`POST /families/{id}/invitations`, `POST /invitations/{token}/accept`);
      nothing in either frontend ever called it. Both routes now exist, plus
      an accept-invite screen at `/invite/:token` that works whether the
      person is already signed in or arrives signed out (the redirect back to
      login now preserves the link instead of dropping it).
- [x] **A senior's own sign-in could never actually be linked to their
      `SeniorProfile`.** The column (`user_id`) existed; nothing set it
      outside seed data, and invitations had no way to say "this one is for
      senior X." Invitations can now carry `senior_profile_id` (migration
      `0012`); accepting one sets the link and forces a viewer role,
      server-side, regardless of what role was requested.
- [x] **The Parent App silently showed the wrong person.** An unlinked
      caregiver fell back to `seniors[0]` — whichever cared-for person the
      family added first — with nothing indicating the record wasn't theirs.
      It now shows an explicit "link your account" screen instead.
- [x] Onboarding for a signed-in user with zero families: create a family,
      then add the first cared-for person, instead of the app having no
      defined behaviour for that state.
- [x] Dev seed data gained a second family with real members
      (`iyer-caregiver`, `iyer-senior`) and a caregiver in both families
      (`dual-caregiver`), so multi-family switching is actually exercisable
      locally instead of two families each with one lonely owner.

### Real Firebase Authentication

- [x] Google and email/password sign-in in both apps
      (`lib/firebase.js`, `lib/useFirebaseAuth.js`), alongside — not instead
      of — the `dev:` identity dropdown `run.py`'s multi-window testing
      depends on. `AUTH_MODE=dev` and `AUTH_MODE=firebase` are both real,
      separately-runnable local configurations now, not one theoretical one.
      Verified end to end: a real Firebase ID token, verified by the
      backend's `FirebaseVerifier` against Google's live signing keys, landed
      a fresh user in the new onboarding screen (dashboard) and the new
      "link your account" screen (Parent App), exactly as designed.
- [x] A Firebase ID token expires hourly; `onIdTokenChanged` keeps the stored
      bearer token current for a long-open tab, without touching
      `isLoadingAuth` — see the `refreshSession` fix below for why that
      distinction turned out to matter.
- [x] **`refreshSession` vs `checkUserAuth`.** The accept-invite screen's own
      mount effect called `checkUserAuth()` to pick up the newly joined
      family — but that screen sits behind `ProtectedRoute`, which renders
      its loading fallback (not the route) while `isLoadingAuth` is true, and
      `checkUserAuth` sets that flag. The screen unmounted itself mid-flight,
      remounted once loading cleared, and its mount effect fired again —
      calling accept a second time on an already-used token, in a loop.
      Caught by driving the actual flow in a real browser, not by lint or the
      test suite. `refreshSession` re-fetches `/me` without the flag; the
      invitation-accept call itself is additionally memoized by token so a
      second effect firing, from any cause, replays the same request instead
      of a new one.

### PostgreSQL, verified — and a real bug it found

Docker was never installed here; PostgreSQL 17 is now, natively (`winget`),
running as a Windows service — lighter than Docker Desktop on a machine with
a documented crash history under heavy multi-process load. Every migration
(`0001`–`0013`) now applies cleanly to a real server, and all six tests in
`tests/test_jobs_postgres.py` pass (five existing, one added).

- [x] **`uq_background_jobs_dedupe_live` and `uq_family_memberships_family_user_live`
      never actually fired, on either database.** Both are partial unique
      indexes written as raw SQL predicates against the enum's lowercase
      `.value` (`status IN ('queued', 'running')`, `status <> 'revoked'`).
      `Enum(..., native_enum=False)` with no `values_callable` stores a
      Python enum's *name*, not its value — confirmed directly against
      PostgreSQL: every row's `status` column held `'QUEUED'`, `'REVOKED'`,
      not the lowercase form. The predicates matched nothing, ever, so
      neither partial index ever rejected a second live row. The only thing
      standing between two concurrent requests and a duplicate live job, or a
      duplicate live membership, was the application-level check — which is
      real, but was meant to be a fast path in front of a database guarantee,
      not the only guarantee. Fixed in both the models and migration `0013`
      (uppercase predicates, matching what the column actually stores); a new
      test inserts two live memberships directly, bypassing the service
      layer, the same way the existing job-dedupe test already did.
      SQLite never caught this because no equivalent direct-insert test
      exists for it — worth writing one, since the same defect is just as
      possible there.
- [x] Confirmed manually too: API and worker started against the real
      server, a medication created through the API, dose events correctly
      materialized by the worker — every scheduled job type ran clean.

### Still owed from this pass

- [ ] Register FCM push (`FCM_PROVIDER=firebase`) is still separate — real
      auth does not imply real push credentials exist.
- [x] SQLite regression tests for both partial indexes, mirroring the
      PostgreSQL ones: `test_jobs.py`'s `test_the_partial_index_rejects_two_live_rows_directly`
      (background jobs) and `test_authorization.py`'s
      `test_the_membership_partial_index_rejects_two_live_rows_directly`
      (family memberships).
- [ ] `gamira-backend/.env`'s `DATABASE_URL` stays on SQLite by default for
      day-to-day speed; switching local dev over to Postgres permanently
      wasn't asked for and wasn't done.

## Done, 2026-08-19 — both apps register for push, and neither had a test suite

### Web push registration

- [x] Both apps request notification permission, register
      `public/firebase-messaging-sw.js`, get an FCM token, and call
      `POST /devices` — behind an explicit Settings toggle, never an
      automatic prompt on login. Off by default, silently re-registers on
      every load once permission is already granted (the backend's own
      `POST /devices` docstring: "safe to call on every app start").
      `src/lib/usePushRegistration.js` in both apps; wired into the Family
      Dashboard's existing `Settings.jsx` placeholder row and a new
      `/settings/notifications` page in the Parent App, matching each app's
      own settings pattern.
- [x] Foreground messages refresh the screen through each app's existing
      live-update path (`useAlerts`'s `reload` in the dashboard, `useVoice`'s
      `reload` in the Parent App) instead of inventing new UI; background
      messages show a real OS notification and route on click.
- [x] The Parent App's `gamiraClient.js` already had an unused `devices`
      client (`list`/`register`/`revoke`) — wired up rather than duplicated.
      The Family Dashboard had none; added to match.
- [x] `gamira-backend/.env.example` gained the `FCM_*` block
      (`FCM_PROVIDER`, `FCM_CREDENTIALS_FILE`, `FCM_PROJECT_ID`,
      `FCM_TIMEOUT_SECONDS`) — no backend code changed, since
      `get_push_provider()` already switches on `FCM_PROVIDER` alone.
- [ ] **Still not real delivery.** `FCM_PROVIDER` stays `fake` until someone
      generates an actual service-account key and VAPID certificate in the
      Firebase console and points `.env` at them — see "Next" above. Until
      then registration completes and a `RegisteredDevice` row is stored,
      but nothing is ever actually sent.

### Frontend tests, from zero

- [x] Vitest + React Testing Library in both apps (`npm run test`) — neither
      had any test framework, config, or test file before this. 37 tests
      total: `gamiraClient.js`'s auth/error handling in both apps; the
      Family Dashboard's `AuthContext` family-narrowing and `FamilySwitcher`
      visibility (direct regression coverage for the `activeFamily:
      families[0]` bug fixed above); the Parent App's `RequireLinkedSenior`
      (regression coverage for the `seniors[0]` fallback bug fixed above);
      one loading/empty/error-state test per app.
- [x] A standalone Playwright suite at [`e2e/`](e2e/README.md) — its own
      backend (port 8020, disposable SQLite, `AUTH_MODE=dev`) and both real
      Vite dev servers, signing in via `?dev=<subject>` with no Firebase UI
      involved. Four specs, run and verified green (not just written):
      family switching between the seeded Sharma/Iyer families as
      `dual-caregiver`, an invitation created and accepted across two
      browser contexts, a senior-linked invitation landing on the right
      person instead of `seniors[0]`, and zero-family onboarding. Not part
      of any CI pipeline — none exists yet — and not meant to run alongside
      a developer's own `run.py` (same frontend ports).

## Documentation

- [`docs/README.md`](docs/README.md) - decisions, repository audit and document index
- [`docs/ROADMAP.md`](docs/ROADMAP.md) - master phased checklist
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) - system boundaries and data flow
- [`docs/DATA_MODEL.md`](docs/DATA_MODEL.md) - proposed PostgreSQL model
- [`docs/API.md`](docs/API.md) - initial API contract
- [`docs/AI_SAFETY.md`](docs/AI_SAFETY.md) - AI decision and safety rules
- [`docs/LOCAL_DEVELOPMENT.md`](docs/LOCAL_DEVELOPMENT.md) - target local workflow
- [`docs/ANDROID_AND_CLOUD.md`](docs/ANDROID_AND_CLOUD.md) - Android and Google Cloud path

