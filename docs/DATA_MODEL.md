# PostgreSQL data model

Most of this is now built. Each section is marked:

- **Implemented** — the table exists, with a migration and tests
- **Not implemented** — logical model only

Where an implemented table's columns differ from the logical sketch below, the
difference is stated. `alembic/versions/` is authoritative:

| Migration | Adds |
|---|---|
| `0001` | identity, medications, doses, care, notifications, audit |
| `0002` | `background_jobs` |
| `0003` | `registered_devices`, `notification_delivery_attempts`, notification `channel`, timeline `dedupe_key` |
| `0004` | `alerts`, `alert_events` |
| `0005` | `conversations`, `conversation_messages`, `ai_summaries`, `live_sessions`, `ai_decisions`, `ai_usage` |
| `0006` | `live_sessions.provisional` |
| `0007` | `senior_memories` |
| `0008` | `reminders.suggestion_reason`, `reminders.suggested_from_conversation_id` |

## Common conventions

- Primary keys: UUID
- Stored timestamps: timezone-aware UTC
- User timezone: IANA name such as `Asia/Kolkata`
- Mutable records: `created_at`, `updated_at`
- User-deletable domain records: archive status or `deleted_at` when history is required
- Sensitive events: append-only audit record
- External requests/jobs: idempotency key and provider reference where applicable

Never use a display name, phone number or email address as a foreign key.

## Identity and families - implemented

One difference from the sketch: `users.external_auth_id` rather than
`firebase_uid`, because the provider is configuration rather than identity.

### users

- `id`
- `firebase_uid` - unique
- `email`, `phone` - nullable and normalized
- `display_name`
- `locale`
- `timezone`
- `status`
- timestamps

### families

- `id`
- `name`
- `created_by_user_id`
- `status`
- timestamps

### family_memberships

- `id`
- `family_id`
- `user_id`
- `role` - owner, family, caregiver, doctor, viewer
- `status` - invited, active, suspended, revoked
- `invited_by_user_id`
- `accepted_at`, `revoked_at`
- timestamps

Unique active membership per `family_id` and `user_id`.

### senior_profiles

- `id`
- `family_id`
- optional linked `user_id`
- `preferred_name`
- `date_of_birth` - only if required
- `timezone`
- `language`
- `consent_status`
- `consent_recorded_at`
- timestamps

A senior profile is not automatically visible to every user. Visibility comes
from an active family membership and server-side permission rules.

### family_invitations

- `id`
- `family_id`
- `invited_by_user_id`
- intended role
- hashed invitation token
- destination email/phone if needed
- `expires_at`, `accepted_at`, `revoked_at`
- timestamps

Store only a hash of bearer-style invitation tokens.

## Devices and notifications - implemented

### registered_devices

One row per *installation*, not per token. Keyed on `(user_id, install_id)`, so a
token rotation updates the row instead of creating a two-hundredth one for a
phone somebody has used for a year.

- `id`
- `user_id` - a device belongs to a person, which is what makes revocation mean
  something
- `install_id` - the client's own stable id for this installation
- `platform` - android, ios, web, watch
- `app_version`, `device_label`, `locale`, `timezone`
- `push_token` - held for the worker, returned by no endpoint
- `push_token_fingerprint` - a short non-reversible label, safe to log
- `push_token_updated_at`, `push_token_invalid_at`
- `status` - active, revoked
- `last_seen_at`, `revoked_at`
- timestamps

`push_tokens` as a separate table was not built: one live token per installation
is the whole requirement, and a second table would only add a join. Revoking a
device drops the token rather than only flagging it, so a bug that ignores
`status` still cannot send.

### notification_deliveries

One row per person per event **per channel**, and the channel is the field that
keeps this honest.

- `id`
- `user_id`, `family_id`, `senior_profile_id`
- `type` - medication_reminder, missed_dose, reminder, appointment, sos,
  sos_escalation, family_update, system
- **`channel`** - `in_app` or `push`
- `title`, `body`
- `related_entity_type`, `related_entity_id`
- `dedupe_key` - unique. A retried job cannot notify the same person twice about
  the same event.
- `status` - queued, sent, opened, failed, cancelled
- `provider_reference`, `attempt_count`, `max_attempts`, `next_attempt_at`,
  `last_error_code`
- `sent_at`, `delivered_at`, `opened_at`
- timestamps

An `in_app` row is the inbox item: it is `sent` the moment the event happens, and
`delivered_at` stays null, because a phone in a pocket with the app closed has
received nothing. A `push` row has real provider attempts behind it and only
gets `delivered_at` when one succeeded. `GET /notifications` returns `in_app`
rows only.

### notification_delivery_attempts

Append-only. One row per attempt per device.

- `id`
- `notification_delivery_id`, `device_id`
- `channel`, `provider`
- `status` - succeeded, retryable, permanent, token_invalid, skipped
- `provider_message_id`, `error_code`
- `device_token_fingerprint` - never the token
- `attempt_number`, `latency_ms`, `attempted_at`

## Medication care loop - implemented

### medications

- `id`
- `family_id`
- `senior_profile_id`
- name, form, strength and instructions
- prescribing clinician text if needed
- start/end dates
- status: active, paused, archived
- created/updated by user
- timestamps

Gamira stores the prescribed information; it does not independently change a
drug or dosage.

### medication_schedules

- `id`
- `medication_id`
- recurrence rule or normalized schedule fields
- local time and IANA timezone
- dose instructions
- grace/late/missed windows
- effective start/end
- status
- timestamps

### dose_events

- `id`
- `medication_schedule_id`
- `senior_profile_id`
- scheduled UTC time
- local scheduled time/timezone snapshot
- status: due, reminded, taken, skipped, late, missed, cancelled
- actor user/device
- source: parent app, family app, backend rule, import
- recorded time
- idempotency key
- optional note

Use a uniqueness rule that prevents duplicate logical dose events for the same
schedule occurrence.

## General reminders and timeline - implemented

### reminders

- `id`
- `family_id`, `senior_profile_id`
- type, title and instructions
- recurrence/timezone
- effective dates
- status
- created/updated by user
- timestamps

### timeline_events

- `id`
- `family_id`, `senior_profile_id`
- event type
- related entity type/id
- actor
- safe display payload
- occurred time
- `dedupe_key` - nullable and unique. Set only by events that must exist exactly
  once however many times their job runs: "this dose was missed" is written by a
  retryable worker, while "this dose was taken" can legitimately be written twice
  if somebody corrects themselves. Both PostgreSQL and SQLite allow repeated
  NULLs in a unique index, so the ordinary events leave it unset.
- timestamps

Timeline events are derived presentation records, not the only record of a
medication, alert or health action.

## Health and files

### health_readings - implemented

- `id`
- `family_id`, `senior_profile_id`
- metric type
- numeric/text value and normalized unit
- source device/provider
- measured time and received time
- quality/verification status
- optional source payload reference
- timestamps

Do not silently compare values that use incompatible units or collection methods.

### files - not implemented

- `id`
- `family_id`, `senior_profile_id`
- owner user
- purpose/type
- private object-storage key
- original filename, MIME type and size
- checksum and malware-scan status
- retention/deletion timestamps
- timestamps

## Alerts and SOS - implemented

### emergency_contacts

- `id`
- `senior_profile_id`
- name, relationship and contact method
- priority order
- verification and consent status
- timestamps

### alerts

An SOS is now a thing with a life, not a timeline row. Before this there was no
record that *somebody* had responded, and nothing to escalate.

- `id`
- `family_id`, `senior_profile_id`
- `type` (sos), `severity` (critical, high, info)
- `status` - raised, acknowledged, escalated, resolved, cancelled
- `source` - parent_app, watch, family_app, approved_device
- `source_device_id`
- `raised_by_user_id`, `raised_at`, `note`
- `acknowledged_by_user_id`, `acknowledged_at`
- `escalation_count`, `last_escalated_at`, `next_escalation_at`
- `resolved_by_user_id`, `resolved_at`, `resolution`
- `cancelled_by_user_id`, `cancelled_at`, `cancel_reason`
- `notified_user_count`, `timeline_event_id`
- timestamps

`next_escalation_at` is cleared on acknowledgement, which is how a responded-to
alert stops nagging the family. Escalation is *louder, not wider*: it re-notifies
the same family members, because Gamira has no consented way to reach anybody
else. **Location is not stored.** No column exists for it, because no reviewed
purpose or retention period for it exists.

Acknowledgement, resolution and cancellation all require a human actor. The
service refuses `ActorType.AI` outright - not a configuration option, not a
role, no code path.

### alert_events

Append-only. Written once, never updated or deleted.

- `id`
- `alert_id`
- `type` - raised, delivery_attempted, delivered, acknowledged, escalated,
  resolved, cancelled, note
- `actor_type` - user, system, device, ai
- `actor_user_id`
- `detail` - safe structured metadata: a recipient count, an escalation number,
  a delivery channel. Never a token, a phone number or a health value.
- `occurred_at`

`actor_type` includes `ai` so an AI-originated event is always distinguishable in
the trail. It is never accepted on the three transitions that end an alert.

## Background jobs - implemented

### background_jobs

- `id`, `job_type`, `schema_version`
- `status` - queued, running, succeeded, failed, cancelled
- `family_id`, `actor_user_id`
- `payload` - **references, not health data.** A job names which dose event to
  look at, never what the medicine is, so a job that sat in the queue for an hour
  cannot act on a stale copy of somebody's care record.
- `dedupe_key` - unique *while queued or running* (a partial index). Two
  schedulers racing produce one job; the same key is reusable next hour.
- `priority`, `run_after`
- `attempt_count`, `max_attempts`
- `locked_by`, `lock_expires_at`
- `result_reference` - a reference, never the generated content
- `last_error_code` - a short stable code. Never a traceback: detail goes to the
  logs, keyed by job id.
- `started_at`, `completed_at`
- `request_id` - so a user-visible failure can be followed into the worker

## AI and auditability - implemented

### conversations

- `id`
- `family_id`, `user_id`, `senior_profile_id`
- `channel` - text or voice
- `status` - active, ended, expired
- `started_at`, `ended_at`
- `retention_policy` - `transcript_only`. **Raw audio is never stored.** Only
  what the provider transcribed is even eligible.
- `consent_snapshot` - what the rules were when this started, so changing the
  policy later does not retroactively change what somebody agreed to

### conversation_messages

- `id`, `conversation_id`
- `role` - user, assistant, system, tool
- `content` - text only
- `tool_name` - set instead of content when the turn was a tool call
- `model`, `provider`, `prompt_version`
- `created_at`

### ai_summaries

Built rather than `conversation_summaries`, because the first real AI feature is
a *weekly care summary* that belongs to a person and a period rather than to a
conversation. `kind` distinguishes them and `conversation_id` is nullable.

- `id`, `kind` (weekly_care, conversation)
- `family_id`, `senior_profile_id`, `conversation_id`, `requested_by_user_id`
- `dedupe_key` - unique; the period is the key
- `period_start`, `period_end`
- **`facts`** - the figures the backend counted. The model never adds to this.
- `source_reference` - which tables the figures came from, and when
- `source_data_version` - bumped when the *meaning* of a counted figure changes
- `data_freshness_warning` - shown wherever the summary is shown, and the model
  cannot word it away
- `content` - the wording. The model's only contribution.
- `model`, `provider`, `prompt_version`, `output_schema_version`, `generated_at`
- `review_state` - unreviewed, reviewed, rejected. Everything starts
  `unreviewed`, and nothing treats an unreviewed summary as a clinical record.
- `reviewed_by_user_id`, `reviewed_at`
- timestamps

The provenance columns are the point. A summary without its date range, its
source figures, its prompt version and its freshness warning is a paragraph of
unattributable text about somebody's health.

### senior_memories

The small set of ordinary things Gamira remembers about somebody between
conversations - who visits on Sundays, that they would rather not be rung before
nine. Its own table rather than a column on `senior_profiles`, because `notes`
and `family_notes` are written by people and merging model output into them
would destroy the "who said this" property the rest of the schema keeps.

- `id`, `family_id`, `senior_profile_id`
- `kind` - person, preference, routine, interest, event, mood, concern. There is
  deliberately no clinical kind: a memory is never a symptom, a reading or a
  diagnosis, and the tool Gamira calls mid-conversation cannot even name the
  last two.
- `content` - one short sentence, whitespace-collapsed, capped at 400 characters
- `source_conversation_id` - which exchange it came out of
- `confidence` - recorded and shown; never used to decide anything on its own
- `dedupe_key` - unique. The same thing said twice is one memory.
- `model`, `provider`, `prompt_version`, `output_schema_version`
- `review_state`, `superseded_by_id`
- `deleted_at`, `deleted_by_user_id` - soft, so "why did Gamira say that?" stays
  answerable, and filtered out of every prompt immediately

Written two ways: the `remember_this` tool during a conversation, and the
after-call review. Read into the Live token's system instruction and into
`chat_context()`. Shown to the person on their own device and to their family in
the dashboard, and either can delete any of it - which is the condition on which
keeping it is reasonable at all.

### live_sessions

- `id`, `user_id`, `family_id`, `senior_profile_id`, `conversation_id`
- `membership_role` - the role at session creation, for the audit trail
- `status` - active, closed, expired, revoked
- `model`, `api_version`, `provider`, `prompt_version`
- **`tool_snapshot`** - the exact catalogue this session was opened with. A tool
  added to the server tomorrow is not callable by a session opened today, and one
  removed for safety stops working immediately.
- `token_fingerprint` - **not the token.** It is returned once and never stored,
  so a database read cannot open a voice session.
- `expires_at`, `last_seen_at`, `closed_at`, `tool_call_count`, `request_id`

The scope columns are set from verified authentication and never re-read from
anything the model says.

### ai_decisions

One row per tool call, created *before* anything is executed - which is what
makes the confirm/reject endpoints possible: the arguments a person is shown are
the arguments that will run, because they are read back from this row rather than
resent by the client.

- `id`, `conversation_id`, `live_session_id`
- `user_id`, `family_id`, `senior_profile_id`
- `tool_name`, `function_call_id`, `arguments`, `decision_schema_version`
- `policy_result` - allowed, confirmation_required, denied
- `policy_reason_code`
- `confirmation_state` - not_required, pending, confirmed, rejected, expired
- `confirmation_prompt` - the exact sentence a person is shown and hears, built
  by the backend from the row it is about to change, so what is confirmed and
  what runs cannot differ
- `confirmed_by_user_id`, `confirmation_decided_at`, `expires_at`
- `status` - proposed, executed, rejected, failed, expired
- `result_entity_type`, `result_entity_id`, `error_code`, `executed_at`
- `model`, `provider`, `prompt_version`
- `idempotency_key` - unique. `live:{session_id}:{function_call_id}`.
- `request_id`

There is no `confidence` column. Model confidence never contributed to a
decision here, so storing it would suggest it did.

### ai_usage

- `id`, `provider`, `model`, `operation`
- `family_id`, `user_id`, `conversation_id`, `job_id`, `live_session_id`
- `prompt_version`, `prompt_tokens`, `response_tokens`, `total_tokens`
- `latency_ms`, `outcome`, `error_code`
- `created_at`

Every provider call writes one row, successful or not. Errors are codes: a
provider's exception text can contain the prompt it choked on, and a metrics
table is not a place to put somebody's medication list.

### audit_logs - implemented

- `id`
- actor user/service/device
- action
- target type/id
- family id
- request/correlation id
- result
- safe metadata
- occurred time

Audit logs must not contain permanent secrets, raw authentication tokens or
unredacted model prompts containing unnecessary health data.

## Later extensions

- Files and object storage
- Push tokens for more than one live credential per installation
- Location on an alert, once a purpose and retention period are reviewed
- Care plans
- Smart-home devices and commands
- Subscriptions and entitlements
- Pharmacy/refill orders
- Clinician organizations
- Wearable provider connections
- `pgvector` embeddings for consented, permission-scoped memory

