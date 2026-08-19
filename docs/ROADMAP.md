# Master implementation roadmap

Phases 1-3 and 8 are complete; 4, 6 and 7 are complete apart from the items
still marked `[ ]`, each of which now says why. See `TODO.md` for what is
genuinely next.

Checkboxes represent verified engineering work, not UI mockups.

## Phase 0 - repository and product baseline

- [x] Confirm the first supported roles: owner, family, caregiver, doctor and
      viewer, ranked in `app/services/authz.py`. Doctor and viewer are read-only.
- [ ] Confirm the first sign-in methods: recommended email/Google for family and phone/assisted setup for seniors.
- [x] Confirm medication terminology: medication, schedule, dose event, and the
      due/reminded/taken/skipped/late/missed/cancelled states in
      `app/models/enums.py`.
- [x] One user can belong to multiple families. A membership is per family, and
      `/me` returns every active one.
- [x] Consent is recorded on the senior profile and starts as `pending` when a
      family member creates it. Invitations expire after seven days, are stored
      as a hash, and can be accepted once.
- [ ] Define the first SOS behavior and explicitly document what it does not guarantee.
- [x] Inventory every Base44 call in both frontends.
- [x] Inventory every hard-coded mock data source in both frontends.
- [x] Investigate the invalid/misplaced dashboard Base44 configuration and
      entity files: they contained React components, not schemas. Deleted with
      the rest of Base44.
- [x] Decide which existing local changes are authoritative before cleanup.
- [x] Move or replace the obsolete local setup notes once the new backend runs.
- [x] Add a root `.gitignore` strategy for secrets, Python caches, build outputs and local databases.

### Gate

The MVP terminology, permissions and first end-to-end care loop are written and
approved. Existing files have been classified as keep, migrate or retire.

## Phase 1 - backend foundation

- [x] Create `gamira-backend` with FastAPI and a `/health` endpoint.
- [x] Add structured settings for local, test, staging and production.
- [x] Add Dockerfile and Docker Compose.
- [x] Add PostgreSQL locally.
- [x] Configure SQLAlchemy sessions and connection pooling.
- [x] Configure Alembic migrations.
- [x] Add linting, formatting, type checking and pytest.
- [x] Add structured JSON logging and correlation/request IDs.
- [x] Add a consistent API error format.
- [x] Add CORS configuration for local clients only.
- [x] Add seed data and a resettable development database.
- [x] Generate and publish OpenAPI documentation from FastAPI.

### Gate

A clean checkout can start the API and PostgreSQL with documented commands, run
migrations, load seed data, call `/health`, and execute the test suite.

## Phase 2 - identity and permissions

- [x] Create Firebase project/configuration for local use (`gamira-9415f`); a
      separate staging project is still needed before deployment.
- [x] Implement Firebase ID-token verification in FastAPI. Verified against a
      real project, 2026-08-19: Google and email/password sign-in work in
      both apps, alongside `AUTH_MODE=dev` for local multi-window testing.
- [x] Create internal `users`, `families`, `family_memberships` and `senior_profiles` tables.
- [x] Implement `GET /api/v1/me`.
- [x] Implement family creation.
- [x] Implement invite creation, expiry, acceptance and revocation.
- [x] Implement senior consent recording on the profile.
- [x] Enforce membership roles in backend service methods.
- [x] Add authorization tests for cross-family access attempts.
- [x] Remove fixed `X-User-Id` authentication from the frontend API client.
- [x] Replace Base44 auth flows in all three frontends. Each app now signs in
      with a bearer token the backend verifies; the website has no auth at all.

### Gate

Two test families cannot access one another's data. Both apps can identify the
same signed-in user through the backend.

## Phase 3 - medication care loop

- [x] Create medication, medication schedule and dose event tables.
- [x] Support create, read, update, pause and archive for medications.
- [x] Support recurring schedules in the senior's timezone.
- [x] Define taken, skipped, late and missed states.
- [x] Make dose-event creation idempotent.
- [x] Implement the medication endpoints in `API.md`.
- [x] Connect Family Dashboard medication screens to the new API.
- [x] Connect Parent App reminder and confirmation screens to the new API.
- [x] Add timeline events derived from medication state changes.
- [x] Add notification-delivery records (table and read/acknowledge endpoints;
      nothing writes reminders into it until the scheduler exists).
- [x] Add retry-safe reminder processing as a background job.
- [x] Test daylight-saving/timezone and duplicate-delivery cases.

### Gate

The first working milestone described in the root `TODO.md` passes automated and
manual testing without Base44 data storage.

## Phase 4 - devices and notifications

- [x] Register Android/web devices and FCM tokens. (`POST /devices`. No app
      registers yet — the Parent App has no service worker.)
- [x] Support token rotation and device revocation.
- [x] Send reminder notifications through FCM. (Provider, retry
      classification and invalid-token revocation implemented and tested
      against a fake. **No real credentials exist, so no push has reached a
      device.**)
- [x] Send meaningful family alerts for missed-dose policies. (Exactly once
      per dose per member.)
- [x] Track queued, sent, delivered when available, opened and failed states,
      with an explicit `in_app` / `push` channel and per-device attempts.
- [ ] Add per-user notification preferences and quiet hours.
- [x] Add notification deduplication. Rate limiting exists for Live sessions;
      per-user notification rate limits do not.
- [x] Ensure critical information remains visible inside the app if push
      delivery fails. (The in-app row is independent of the push row.)

### Gate

Notifications are traceable, retryable and cannot be duplicated by repeated job execution.

## Phase 5 - health, files and reports

- [x] Create typed health reading storage with source and unit metadata.
- [x] Define supported metrics and validation ranges without treating them as
      diagnoses.
- [x] Add manual health entry.
- [ ] Add file metadata and authenticated upload/download flow.
- [ ] Add prescription/report upload with malware and file-type checks.
- [x] Add weekly summary data aggregation without AI. (`app/ai/facts.py`;
      the figures persist whether or not a model ever runs.)
- [ ] Add PDF report generation as an asynchronous job.
- [ ] Add consent and data-retention controls.
- [ ] Add access logs for health records and files.

### Gate

Reports can be generated from deterministic stored data, shared only with
authorized users and deleted according to the retention policy.

## Phase 6 - AI orchestration

- [x] Move reusable persona/configuration code into the backend AI module.
- [x] Add an AI provider interface so model calls are replaceable and testable.
- [x] Define structured schemas for every model output.
- [x] Implement tool/action allowlists. (15 tools, strict schemas, snapshotted
      per session.)
- [x] Add deterministic policy validation before every state-changing action.
- [x] Add user confirmation for sensitive actions.
- [x] Add AI decision and tool-execution audit records.
- [ ] Add context minimization and conversation-summary retention rules.
- [x] Implement family summaries from verified database data.
- [x] Implement conversational queries with permission-scoped retrieval.
- [x] Add prompt-injection and cross-family data-leak tests.
- [x] Add per-user quotas, timeouts, retries and cost metrics. (`ai_usage`;
      Live session concurrency and per-hour limits.)
- [ ] Build an evaluation set before changing models or prompts.

### Gate

The AI cannot bypass authorization, alter medication dosage, diagnose, cancel an
emergency or expose another family's data. Model unavailability does not break
core reminders or SOS.

## Phase 7 - realtime voice

- [x] Decide proxy versus direct ephemeral-token architecture. **Direct**, with
      a backend-minted token. Nothing safety-critical depends on voice, so the
      proxy's centralisation buys nothing that justifies its latency.
- [x] Merge the development token server into authenticated backend routes.
      (The standalone server survives, explicitly labelled, as the console's
      local voice lab. No app uses it.)
- [x] Require user authentication and entitlement before issuing a Live token.
- [x] Constrain model, modalities, lifetime and token uses server-side.
- [x] Add session start/end records without storing raw audio by default.
- [x] Add session duration and concurrency limits. Cost *tracking* exists
      (`ai_usage`); a spend cap does not.
- [x] Route every data and mutation tool call through authenticated backend
      actions. Navigation runs through an allowlisted UI dispatcher.
- [ ] Add reconnection, interruption, network loss and expired-token handling.
- [ ] Translate all voice states supported by the Parent App.
- [ ] Test older/soft speakers, noisy environments and accessibility settings.

### Gate

Voice works over unreliable networks, permanent AI credentials are absent from
the app, and every action is subject to the same backend permissions as REST.

## Phase 8 - alerts and SOS

- [x] Define manual SOS as the first authoritative trigger.
- [x] Create alert and alert-event tables. Acknowledgement is a column and an
      append-only event rather than its own table.
- [x] Store emergency contacts with consent and verification status.
- [x] Implement alert creation, acknowledgement, resolution, cancellation and
      escalation.
- [ ] Add location sharing only for an explicit, documented purpose and
      duration. **Deliberately still absent** — no column exists, because no
      reviewed purpose or retention period does.
- [x] Add deterministic escalation rules. (Re-notify the same family after
      `SOS_ESCALATION_AFTER_MINUTES`, up to `SOS_MAX_ESCALATIONS`, stopped by
      the first acknowledgement.)
- [x] Add delivery retries. Fallback *contact* behaviour is deliberately
      absent: escalation is louder, not wider, because Gamira has no consented
      way to reach anybody outside the family.
- [ ] Test offline, no-location, denied-permission and unreachable-contact scenarios.
- [ ] Complete legal/product review before claiming emergency-service integration or reliability percentages.

### Gate

Every alert has a traceable lifecycle, visible failure states and clearly stated
limitations. AI assists but does not silently suppress or resolve emergencies.

## Phase 9 - Android applications

- [ ] Add Capacitor feasibility spike for both apps.
- [ ] Package the Family Dashboard first.
- [ ] Add secure token storage and deep links.
- [ ] Add notification channels and background handling.
- [ ] Determine native implementation needs for the Parent App.
- [ ] Add microphone, location and sensor permission education.
- [ ] Add offline queues for safe, idempotent actions.
- [ ] Integrate Health Connect only after supported metrics/devices are documented.
- [ ] Test battery restrictions and process termination on major Android vendors.
- [ ] Complete accessibility testing with large text and screen readers.
- [ ] Complete Play Store privacy, data safety and account deletion requirements.

## Phase 10 - Google Cloud staging and production

- [ ] Create separate staging and production Google Cloud projects.
- [ ] Select a supported region and document data residency.
- [ ] Create Artifact Registry and Cloud Run staging service.
- [ ] Create Cloud SQL staging with backups and point-in-time recovery.
- [ ] Store production secrets in Secret Manager.
- [ ] Assign least-privilege service accounts.
- [ ] Configure Cloud Storage with private access.
- [ ] Configure Cloud Tasks, Scheduler and FCM.
- [ ] Add migration and deployment pipelines.
- [ ] Add monitoring, uptime checks, error alerts and budget alerts.
- [ ] Add database backup-restore drills.
- [ ] Run security, load and failure testing.
- [ ] Deploy production only after staging acceptance criteria pass.

## Phase 11 - website integration and launch readiness

- [ ] Connect the website's Get Started actions to a real signup, waitlist or checkout flow.
- [ ] Connect the support form to an authenticated or abuse-protected backend endpoint.
- [ ] Make backend plan/entitlement configuration the source of truth for displayed pricing.
- [ ] Reconcile plan names, currencies, trials and hardware statements across the website and apps.
- [ ] Publish working Android store links only after release builds exist.
- [ ] Fix narrow mobile viewport overflow and test common device widths.
- [ ] Publish the operating legal entity, complete support details and reviewed policies.
- [ ] Remove or substantiate security, compliance, compatibility and reliability claims.
- [ ] Add privacy-safe analytics for signup and support conversion failures.
- [ ] Add uptime monitoring for the website-to-API paths.

### Gate

Every public call to action reaches a working flow, public promises match the
implemented product, and the website does not collect data through a fake or
non-submitting form.

## Deferred until core care loop is proven

- Smart-home control
- Doctor marketplace and video consultation
- Automated pharmacy refills
- Predictive medical claims
- Insurance integrations
- Automatic emergency-service dispatch
- Separate microservices
- Dedicated vector database
