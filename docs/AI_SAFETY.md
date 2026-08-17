# AI decision and safety rules

Gamira's AI is an assistant inside an authorized backend. It is not the database,
the permission system, a clinician or the final authority for emergencies.

Everything in this document is implemented unless a section says otherwise, and
every rule that could be tested is named against the test that tests it.

## Decision pipeline — implemented

```text
authenticated request or verified event
  -> retrieve minimum permitted context      app/ai/context.py
  -> model returns schema-validated output   app/ai/provider.py + schemas.py
  -> deterministic policy engine evaluates   app/ai/policy.py
  -> request user confirmation when required app/ai/executor.py
  -> backend service performs the action     app/services/*
  -> audit decision and result               ai_decisions + audit_logs
```

The model never receives database credentials and never executes SQL. There is
no tool that takes a URL, a query, a path, a route or another tool's name.

## The dependency arrow

The arrow only ever points from the model towards the rules, never back:

| Module | Knows about the model? |
|---|---|
| `app/ai/facts.py` | No. Counts rows. |
| `app/ai/context.py` | No. Takes a verified actor, returns permitted data. |
| `app/ai/policy.py` | No. Takes a tool name and an actor, returns a verdict. |
| `app/ai/validation.py` | No. Checks arguments against a schema. |
| `app/ai/executor.py` | Only that a call came from one. |
| `app/ai/provider.py` | Yes — and it is the only place that does. |

## Action classes

### May run automatically after normal validation — implemented

- Read already-authorized information (`get_today_doses`,
  `get_today_schedule`, `get_reminders`, `get_latest_health_readings`,
  `get_upcoming_appointments`, `get_emergency_contacts`,
  `get_notification_summary`)
- Navigate within the app (`navigate_to_screen`, `open_dose_details`,
  `open_reminder_details`)
- Explain verified app data
- Personalize wording or language

### Requires explicit confirmation — implemented

Confirmation means an accessible visual dialog **and** the same sentence spoken
aloud. The wording is authored by the backend from the row it is about to change,
so what is confirmed and what runs cannot differ:

> Mark Metformin scheduled for 8:00 AM as taken?

- `mark_dose_taken`
- `mark_dose_skipped`
- `complete_reminder`
- `prepare_call_contact` — opens the dialer; the person still presses dial
- `prepare_sos` — opens the real SOS screen; the person still presses it

Tested by `test_ai_tools.py::test_a_mutation_asks_for_confirmation_naming_the_target`
and `::test_rejecting_a_confirmation_changes_nothing`.

### Must not be performed at all — implemented as absence

There is no tool for any of these. Not a tool that refuses — no tool:

- Diagnose a condition
- Prescribe, stop or change medication or dosage
- Add or edit a medication, an emergency contact, a health reading or a care
  record
- Claim a health reading is medically safe
- Cancel, suppress, acknowledge or resolve an SOS
- Add a family member
- Reveal another user's or family's information
- Make a purchase

`test_ai_live.py::test_the_catalogue_exposes_no_general_purpose_tool` asserts the
catalogue contains no name matching `http`, `fetch`, `url`, `sql`, `query`,
`exec`, `file`, `endpoint` or `shell`, and none of the forbidden mutations.

Acknowledging, resolving or cancelling an alert with `ActorType.AI` raises
`PermissionDenied` in `app/services/alerts.py` — not a configuration option, not
a role, no code path.

## Structured output — implemented

Every model response validates against a versioned Pydantic model with
`extra="forbid"`. A reply that omitted a field, invented a status or wrapped
itself in prose is a validation error rather than something a screen renders.

The weekly summary's output schema is deliberately narrow. Note what it *cannot*
express: no score, no risk level, no recommendation, no assessment of any
reading.

```python
class WeeklySummaryOut(StrictModel):
    schema_version: Literal["1"] = "1"
    headline: str          # <= 140 chars
    body: str              # <= 1200 chars
    highlights: list[str]  # <= 6 short factual lines
```

The policy engine independently verifies the senior, the membership, the
persisted entity, the ownership, the deduplication key and the current state.
**Model confidence is not stored and never contributed to a decision**, which is
why `ai_decisions` has no `confidence` column.

## Deterministic core — implemented and tested

These features operate when Gemini is unavailable:

- Authentication and permissions
- Medication scheduling and dose-event creation
- Reminder delivery
- Taken/skipped acknowledgements
- Manual SOS creation, acknowledgement, escalation and resolution
- Family timeline

`tests/test_ai_outage.py` runs the whole suite with the AI provider raising on
every call *and* the Live token minter refusing to mint: doses are still
materialised, a dose still becomes missed, the family is still told, an SOS is
still raised, escalated, acknowledged and resolved, and every non-AI endpoint
still answers 200.

`app/jobs/handlers/care.py` imports nothing from `app/ai/`. That is checked by
the split, not by convention.

When AI *is* unavailable, `/ai/chat` and `/ai/live-sessions` return 503 with a
stable code and a message that says what still works — a voice outage must not
read like a total one.

## Facts versus wording — implemented

The weekly care summary is the first complete AI feature, and its shape is the
template for the rest:

1. The backend counts the period deterministically (`app/ai/facts.py`): doses by
   status, unanswered doses, reminder completion, how many health readings and
   how old, watch last-sync time, upcoming appointments, family activity, SOS
   alerts raised and acknowledged.
2. Those figures are **persisted before any model is called**, with their period,
   source version, source references and freshness warning.
3. The model is asked only to turn those figures into two or three sentences.
4. The wording is stored beside the figures with the model, provider, prompt
   version, output schema version and generation time.

If step 3 fails, steps 1 and 2 have already happened: the family gets the numbers
with a note that the wording is not ready, rather than nothing. `GET
/ai/summaries/{id}` resolves before the job runs.

`facts.py` forms no opinion. There is no wellness score and no trend
classification — counts, timestamps and freshness. A week with two readings says
so:

> Only 2 health readings were recorded, which is too few to describe a trend.
> The paired device last sent a reading 92 hours ago.

## Context and memory — implemented

- Retrieval takes a verified `ActorContext` (user + senior + *active* membership)
  rather than ids, so the scoping is structural rather than remembered.
- Least data: one reading per metric, not a month of them.
- Emergency contacts come back as a name, a relationship and an id — **never a
  phone number.** The model only needs to offer to ring somebody; the dialer is
  opened from the contact id. Digits in a conversation would be digits in a
  transcript for no benefit.
- Raw audio is not stored. `retention_policy` is `transcript_only`.
- Provenance and timestamps travel with every health fact.
- No API key, bearer token or invitation token appears in a prompt or a log.

## Tool execution — implemented

Ordered checks, each with its own stable error code, before anything happens:

1. Is the session live, owned by this caller, and unexpired? → `session_expired`
2. Is the tool a real one? → `unknown_tool`
3. Is it a client-side tool that reached the server by mistake? → `client_tool`
4. Was it in **this session's** snapshot? → `permission_denied`
   (`tool_not_in_session`)
5. Do the arguments match the strict schema? → `invalid_arguments`
6. Is the caller still active and still a member? → `permission_denied`
7. Does every id in the arguments belong to this session's senior? → `not_found`
8. Has this exact call id already run? → `duplicate_call`
9. Does it need confirming? → `confirmation_required`

Then it executes by calling the same service function the REST endpoint calls.
There is no second implementation of "mark a dose taken" for the voice path to
drift away from.

Step 6 runs at *execution* time, not session-creation time. That is the point: a
membership revoked mid-conversation stops the next tool call even though the
session was authorised minutes earlier and the model has no idea anything
changed.

What comes back is small and structured. Never a traceback, never a database
message, never the rejected argument value — a tool call is model output, and
echoing it back gives a prompt injection a second chance.

## Prompt injection and untrusted data — implemented

User messages, transcripts, family notes and future uploaded documents are
content, not instruction. The shared prompt preamble says so explicitly, and the
enforcement is structural rather than textual:

- The tool catalogue is pinned into the ephemeral token and snapshotted on the
  session. A conversation cannot add a tool.
- The system instruction is a constant. Nothing a caller sends contributes to it,
  and it is not returned to the browser.
- Family, senior and role come from membership rows. A role, `family_id` or
  `senior_id` stated in conversation is never read.
- Ids are checked by *ownership*, so a well-formed uuid from another family gets
  the same `not_found` as an invented one.

## Evaluation checklist

| Check | Test |
|---|---|
| Cross-family information request is refused | `test_ai_summaries.py::test_another_family_cannot_request_or_read_a_summary`, `test_ai_tools.py::test_another_familys_dose_id_is_not_found` |
| Fake user-supplied role is ignored | Structural: no request model accepts a role. `test_ai_tools.py::test_a_viewer_who_is_not_the_person_cannot_record_their_dose` |
| Prompt asks AI to alter medication dosage and is refused | Structural: no such tool. `test_ai_live.py::test_the_catalogue_exposes_no_general_purpose_tool` |
| Prompt tries to reveal system instructions or secrets | `test_ai_live.py::test_the_permanent_key_is_never_returned` |
| Model invents a dose event; policy rejects it | `test_ai_tools.py::test_a_fabricated_entity_id_is_not_found` |
| Duplicate tool call creates only one state change | `test_ai_tools.py::test_a_duplicate_call_id_does_not_act_twice`, `::test_repeating_a_confirmed_mutation_does_not_mutate_twice` |
| Revoked member loses access during an active session | `test_ai_tools.py::test_a_membership_revoked_mid_session_stops_the_next_tool_call`, `::test_a_revocation_between_prompt_and_confirmation_blocks_it` |
| AI provider timeout produces a safe retry state | `test_ai_summaries.py::test_a_provider_outage_leaves_a_retryable_job_and_the_figures` |
| A schema violation is not retried forever | `test_ai_summaries.py::test_a_schema_violation_is_not_retried` |
| Manual SOS succeeds while the model is unavailable | `test_ai_outage.py::test_a_manual_sos_works_with_the_ai_down` |
| An assistant cannot end an alert | `test_alerts.py::test_an_assistant_can_never_end_an_alert` |
| A rejected confirmation mutates nothing | `test_ai_tools.py::test_rejecting_a_confirmation_changes_nothing` |
| A failing tool does not end the session | `test_ai_tools.py::test_one_failing_call_does_not_fail_the_batch_or_the_session` |
| No error response leaks internals | `test_ai_tools.py::test_no_error_response_carries_a_traceback_or_internals` |
| Ambiguous health question gets a limitation and an escalation | **Not automated.** The system instruction covers it and it has been tested by hand; a proper evaluation set is still owed. |
| Conversation deletion follows a retention policy | **Not implemented.** `retention_policy` is recorded on every conversation; no deletion job runs yet. |

## Voice-specific controls — implemented

- Authentication before a token is issued.
- Model, modalities, system instruction and tool catalogue pinned server-side,
  into the token's connect constraints.
- One-use tokens: `uses=1`, a one-minute window to open a session, a
  thirty-minute session lifetime.
- Concurrent-session and per-hour limits per user.
- Every state-changing tool call goes through the Gamira backend.
- Microphone state is visible, and it stops feeding the model while a tool call
  is resolving or a confirmation dialog is open — otherwise the model hears the
  room, takes another turn, and asks for the same thing again while the person is
  still reading the first prompt.
- Ending the session stops streaming and closes the backend session.
- Every important action has a non-voice path. The red SOS button is unchanged
  and does not involve the AI at all.

### A note on the Live API and strict schemas

The catalogue's JSON schemas set `additionalProperties: false`, and the backend
validator enforces it. Getting that *declared to the model* took a real API call
to discover: `FunctionDeclaration.parameters` is the SDK's own `Schema` type,
which has no such field, and the Live setup returns 400 for it. The declaration
therefore uses `parameters_json_schema`, which takes a raw JSON Schema and
accepts it. Verified against the live API on 17 Aug 2026;
`test_ai_live.py::test_the_gemini_declaration_keeps_the_strict_schema` is the
regression guard.

If a future SDK drops that field, the declaration falls back to `Schema` with the
key removed and logs a warning. Strictness is not lost when that happens: the
backend validator rejects an unexpected argument regardless of what the model was
told, and it is the validator that is authoritative.

## What Gamira does not claim

- It does not contact emergency services. It never has, and no code path does.
- It does not place a call. It opens the phone's dialer, and the person presses
  dial.
- It does not reach anybody outside the family. Escalation re-notifies the same
  family members.
- An `in_app` notification is not a delivered push, and no row says it is.
- No push has reached a real device: FCM credentials do not exist yet.
