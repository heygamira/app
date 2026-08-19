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
aloud, answerable either way. The wording is authored by the backend from the
row it is about to change, so what is confirmed and what runs cannot differ:

> Mark Metformin scheduled for 8:00 AM as taken?

Always, however it came up:

- `mark_dose_taken`
- `mark_dose_skipped`
- `prepare_call_contact` — opens the dialer; the person still presses dial
- `prepare_sos` — opens the real SOS screen; the person still presses it

Only when Gamira proposed it herself (`confirm_when_unasked`):

- `create_reminder`
- `complete_reminder`
- `tell_family`

Asking for an everyday routine out loud *is* the consent for it, and a dialog in
front of somebody's own request is a hurdle in front of their own words — worst
for the person least able to clear it. Which case applies is decided by
`tools.needs_confirmation`, in code, from a required `proposed_by` argument the
model must state; anything but `"them"`, including its absence, confirms. The
policy engine still runs first either way, so skipping the dialog never skips
the permission check. Nothing clinical is decided this way: the four tools above
set `requires_confirmation` and never reach that rule.

**Answering.** The dialog is on screen with two large buttons, and a spoken
"yes" or "no" does the same thing through `confirm_pending_action` /
`cancel_pending_action`. Those two tools decide nothing: they carry an answer to
a decision already in the database, whose action, arguments and wording were
settled when it was raised. A decision id from any other session — including one
of this person's own, from a conversation that has ended — is `not_found`.

Tested by `test_ai_tools.py::test_a_mutation_asks_for_confirmation_naming_the_target`,
`::test_rejecting_a_confirmation_changes_nothing`,
`::test_a_reminder_they_asked_for_is_simply_added`,
`::test_a_reminder_gamira_suggested_asks_first_and_names_it`,
`::test_saying_yes_runs_the_action_that_was_read_out`,
`::test_saying_no_changes_nothing`,
`::test_saying_yes_twice_records_one_dose` and
`::test_a_decision_from_another_session_cannot_be_confirmed`.

### Must not be performed at all — implemented as absence

There is no tool for any of these. Not a tool that refuses — no tool:

- Diagnose a condition
- Prescribe, stop or change medication or dosage
- Add or edit a medication, an emergency contact, a health reading or a care
  record
- Claim a health reading is medically safe
- Acknowledge, resolve or suppress an alert
- Add a family member
- Reveal another user's or family's information
- Make a purchase
- Raise or escalate an alert of any kind — including the after-call review,
  which can ask for a `family_update` notification and nothing else, and
  including the wellbeing check below, where the escalation is a rule about
  elapsed time with no model anywhere near it

`test_ai_live.py::test_the_catalogue_exposes_no_general_purpose_tool` asserts the
catalogue contains no name matching `http`, `fetch`, `url`, `sql`, `query`,
`exec`, `file`, `endpoint` or `shell`, and none of the forbidden mutations.

Acknowledging or resolving an alert with `ActorType.AI` raises
`PermissionDenied` in `app/services/alerts.py` — not a configuration option, not
a role, no code path. **Cancelling has one narrow exception**, described in full
under *Ending an emergency* below.

## Telling the family something ordinary — implemented

Between "nothing happened" and an emergency there is almost everything anybody
would actually want their family to know: a headache since this morning, a bad
night, a sore knee, feeling low. Until `tell_family` there was no path for it.
Saying "I have a headache" could become an SOS, which it is not, or it could
wait for the after-call review — which only sends anything if the model said
out loud that it would, only once the conversation has ended, and only when the
worker reaches the job. The commonest thing a companion is for arrived late or
not at all.

`tell_family` writes a `family_update` notification and a timeline entry. What
it is not, structurally rather than by instruction:

- **Not an alert.** No `Alert` row, so no severity, no escalation, no
  acknowledge, no resolve — there is no lifecycle for it to enter. Asserted by
  `test_tell_family.py::test_it_raises_no_alert`.
- **Not urgent.** In-app only, `push=False`. The urgent path is an alert, and
  Gamira cannot raise one.
- **Not hers to decide.** `confirm_when_unasked`, so a message she proposes is
  confirmed first — and the confirmation reads out the message itself, not
  "tell your family something?", because nobody can agree to a sentence they
  have not heard.

The sentence is the model's, and that is the point: it has to be able to say
what they actually said. The persona constrains it to their words and forbids a
cause, a diagnosis or advice; the schema caps it at 300 characters. What the
model cannot do is decide whether it goes at all.

## Ending an emergency — implemented

Acknowledging an alert means somebody has promised to go and look. Resolving it
means somebody has decided it is over. Neither is a thing an assistant can be,
and both still raise `PermissionDenied` for `ActorType.AI`.

Cancelling is a different act: it is the person the alert is *about* saying
they are alright. Refusing that left somebody who pressed SOS by accident — or
whose countdown ran out while they were fetching their glasses — with no way to
take it back from their own phone, and reaching a button is the exact thing an
SOS says they may not be able to do.

So `alert_service.cancel_own_by_voice` exists, and every restriction on it is
in that one function rather than in its callers:

- **Only their own.** The alert's `senior_profile_id` must be the speaker's own
  profile, or it raises `alert_not_yours`. A voice can withdraw its own
  emergency and no other.
- **Only one still open.** A resolved alert is somebody else's conclusion and
  is not the speaker's to undo.
- **Only after a spoken confirmation.** `cancel_my_sos` sets
  `requires_confirmation`, so the backend authors the sentence and the person
  has to answer it.
- **The row survives.** Status becomes `cancelled` with the reason on it and an
  `AlertEvent` carrying `actor_type=ai` and `via: live_voice`, so the trail
  says the person decided and the assistant carried it out.
- **The family is told.** A `family_update` goes out saying it was cancelled
  and why. A red alert that silently disappears is worse for a family than the
  false alarm was — they are left wondering whether they imagined it, or
  whether it was cancelled by whatever is wrong.

Before the countdown finishes, none of this applies: nothing has been sent, so
`cancel_sos_countdown` is a **client** tool that closes a dialog and needs no
confirmation at all.

Tested by `test_sos_voice_cancel.py`, which is mostly about the walls:
`::test_a_voice_cannot_cancel_somebody_elses_alert`,
`::test_a_voice_cannot_undo_somebody_elses_conclusion`,
`::test_acknowledge_and_resolve_still_refuse_the_assistant`,
`::test_the_alert_survives_being_cancelled`,
`::test_a_refused_cancellation_leaves_the_escalation_running`.

## Wellbeing checks — implemented

A watch decides one of its own limits was crossed. Gamira asks the person how
they are. A rule decides what happens if the answer is bad or never comes. The
seam between those three is the safety property, and it is why this is safe to
build at all.

`POST /seniors/{id}/device-flags` now opens a `WellbeingCheck` row alongside the
family notice it already sent. Before, the flag was a notification and nothing
else, so the one outcome worth catching — a flagged reading followed by silence
— was invisible.

What the model can do is `answer_wellbeing_check`, which takes `alright` or
`not_alright` and no id: the check is resolved from the session's own person, so
there is nothing to invent or misdirect. It is told, in the persona, to report
what they *said* rather than what it inferred, and **not to call it at all** if
nobody answered — silence is handled by something that is not guessing.

What no model can do is escalate. `JobType.WELLBEING_CHECK_ESCALATE` runs on
elapsed time (`wellbeing_check_grace_minutes`, default 10) and a stored answer.
It raises `AlertType.WELLBEING_CHECK` at `AlertSeverity.HIGH` with
`raised_by_user_id = None` — nobody raised it, and putting somebody's name on it
would be a small lie.

It is **not** a quieter SOS, and the difference is defended in three places: a
separate `AlertType`, a separate wording entry in `ALERT_WORDING`, and an amber
treatment in the dashboard that never uses the red overlay or the looping
alarm. A watch on a bedside table leaves its band most nights; if that arrived
wearing the red alarm, a family would learn within a week to dismiss the red
alarm, and the one that matters is the one they would stop looking at.

The alert reports the **silence**, which is a fact, and never the reading, which
is not ours to interpret. "Gamira could not reach them to ask" and "Gamira asked
and got no answer" are stored and worded separately, because a phone that was
put down and a person who did not answer a direct question are different things.
The disclaimer *"Gamira has not assessed the reading"* is appended in code
rather than being part of an optional string.

Tested by `test_wellbeing_checks.py`, including
`::test_nobody_answering_raises_a_softer_alert_not_an_sos`,
`::test_the_alert_never_claims_anything_about_the_reading`,
`::test_unreachable_and_unanswered_are_told_apart` and
`::test_the_catalogue_has_no_way_to_raise_this`.

## Memory — implemented

Gamira keeps a small number of ordinary things about somebody between
conversations: who visits on Sundays, what they like being called. Written two
ways — the `remember_this` tool during a conversation, and the after-call
review — into `senior_memories`, and read back into the Live token's system
instruction and `chat_context()`.

Four limits, all structural:

- **No clinical kind exists.** The enum is person, preference, routine,
  interest, event (plus mood and concern, which only the review may write).
  There is no symptom, no reading, no diagnosis, and the tool description
  forbids them in as many words.
- **The person sees all of it**, on their own device, in Settings → *What
  Gamira remembers*, and the family sees the same list. Either can delete any
  of it. A deleted memory leaves every prompt immediately and is never written
  back, even if the same thing comes up again.
- **There is no endpoint that creates one.** A note a person wrote has an
  author and belongs in `family_notes`.
- **Memories are notes, not instructions.** They are the one part of the system
  instruction a previous conversation influenced, so they are fenced under a
  heading that says so, capped in number and length, and whitespace-collapsed
  before storage so one cannot forge a section of its own.

## Noticing — implemented

After a conversation ends, `ai.conversation_review` reads it back and may do
three things: keep memories, write an `ai_summary` of kind `conversation`, and
ask that the family be nudged to ring.

The third is the one that needed care. The shipped persona says: *"You are not
there to report on them; if something genuinely needs a family member, say so to
them first, openly."* An observer that quietly messaged the family would
contradict the instruction the model it is reading was running under. So the
review must report `told_them`, and `app/ai/review.py::notify` refuses to send
anything without it. What it sends is a `family_update` notification, never an
alert, and with push off: a nudge to ring somebody is not an emergency and the
two must not arrive looking alike.

The schema is the rest of the limit. `ConversationReviewOut` has no severity, no
risk score, no diagnosis and no free-form action — the only thing it can propose
is an everyday reminder, which the family sees as a suggestion.

## Acting — implemented

The furthest Gamira goes on her own initiative is *proposing* an everyday
routine she heard about. `app/ai/review.py::suggest_reminders` writes a
`Reminder` with `status=suggested`, which every query for live reminders
already excludes — so it prompts nobody, appears on no schedule and generates
no notification until a family member accepts it. `type` is fixed to `other` in
code and absent from the schema, so there is no path from a suggestion to a
medication. `created_by_user_id` stays null and an audit line records
`ActorType.AI`, so it can never be mistaken for something a person wrote. The
reason and the source conversation travel with it, because a suggestion whose
reasoning a family cannot inspect is one they can only guess at.

Accepting it is the ordinary status change any family member could make by
hand; dismissing it is the ordinary delete. Neither is a special AI path with
its own permissions, and a viewer can do neither.

Tested by `test_ai_suggestions.py::test_a_suggested_reminder_prompts_nobody_until_it_is_accepted`,
`::test_a_suggestion_is_recorded_as_the_assistant_s_doing` and
`::test_a_viewer_cannot_accept_a_suggestion`.

## Quiet hours — implemented

Nothing Gamira volunteers arrives in the middle of the night. Quiet hours are
read in the *cared-for person's* timezone (a family scattered across timezones
has no single night), and a notice raised inside them is held for the morning
rather than dropped — the family should still hear about it. `held_until` in
`app/ai/review.py` decides; `JobType.AI_FAMILY_NOTICE` carries it over, and
sends it through the same `deliver_notice` the immediate path uses so a notice
that waited overnight is not a slightly different notice.

This is safe precisely because nothing she volunteers is urgent. The urgent
path is an alert, and she cannot raise one.

The Parent App applies the same courtesy to itself: `lib/useProactive.js`
volunteers nothing outside 08:00–21:00 local and says each thing at most once a
day.

It now speaks through the Live API rather than the browser's
`speechSynthesis`. That was a real trade and it is worth writing down. The old
way opened no microphone at all, which was the safer shape — but it spoke in a
different voice from the one the person had been talking to, could not be
answered, and left "yes, I've taken it" with nowhere to go. A companion that
announces things is not a companion.

What replaces it keeps the important half of that property. The session opens
with `autoStream: false`, so **nothing is sent from the room until Gamira has
finished her sentence**; the microphone opens only on `turnComplete`, for a
20-second window, and the session closes itself if nobody answers. So the
common case costs one spoken sentence and no open microphone, and a session
that opened a microphone before saying why still cannot happen.

The brief she is given is built by the app from what is already on the person's
screen — a dose name and a time — and is bracketed, so the persona knows it is
the app speaking and not the person. She words it; she is not given a script,
and she is not given anything the screen was not already showing.

## Openness — implemented

Whatever Gamira tells a family about somebody, that person can read.
`GET /ai/seniors/{id}/family-notices` returns the notices word for word, one
row per notice however many people it reached, and the Parent App shows them
under Settings → *What your family was told*.

The persona's promise is "say so to them first, openly", and openly has to
survive the conversation ending: somebody should be able to check what was said
about them without asking anybody. Tested by
`test_ai_suggestions.py::test_the_person_can_read_what_was_sent_to_their_family`.

## Speculation — implemented

The wake-word detector pre-connects on a *maybe* so a real "Gamira" is answered
at once rather than after a second of silence. Most of those guesses are wrong,
by design — so what matters is what a wrong one costs.

It costs a minted ephemeral token, a `Conversation` row and a `LiveSession`
row. It used to also queue a job to *read back* that conversation, because
`close_live_session` was missing the guard `expire_stale_sessions` had; and the
only ceiling on how many could be opened was a constant in browser JavaScript,
which is not a ceiling at all. Now:

- an abandoned guess queues no review — there is nothing to read back;
- `live_provisional_per_hour` caps guesses on the server, separately from
  `live_sessions_per_hour`, so being mis-heard can never stop somebody actually
  talking to her;
- the pre-connect threshold is 0.75 rather than 0.40. It is still well short of
  the 0.94 it takes to wake, so the trick still works.

Tested by `test_ai_speculation.py`.

## Retention — implemented

`retention_policy="transcript_only"` is recorded on every conversation and is
now enforced: the `ai.conversations.retention` cron deletes messages older than
`conversation_retention_days` (30 by default) and marks the conversation
`deleted`, so the sweep stays cheap however much history accumulates. The
conversation row survives the deletion, because a conversation that was held and
then cleared is a different thing from one that never happened.

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
| An ordinary worry reaches the family without becoming an emergency | `test_tell_family.py::test_saying_they_are_unwell_reaches_the_family`, `::test_it_raises_no_alert`, `::test_gamira_suggesting_it_has_to_be_agreed_to` |
| A rejected confirmation mutates nothing | `test_ai_tools.py::test_rejecting_a_confirmation_changes_nothing` |
| A failing tool does not end the session | `test_ai_tools.py::test_one_failing_call_does_not_fail_the_batch_or_the_session` |
| No error response leaks internals | `test_ai_tools.py::test_no_error_response_carries_a_traceback_or_internals` |
| Ambiguous health question gets a limitation and an escalation | **Not automated.** The system instruction covers it and it has been tested by hand; a proper evaluation set is still owed. |
| Conversation deletion follows a retention policy | `test_ai_retention.py`. The `ai.conversations.retention` cron deletes transcripts past `conversation_retention_days` and marks the conversation `deleted`. |
| A memory is visible to the person it is about, and deletable | `test_ai_memory.py::test_deleting_a_memory_stops_it_reaching_the_model`, `::test_a_deleted_memory_does_not_come_back_on_its_own` |
| The family is never told something the person was not told first | `test_ai_conversation_review.py::test_nothing_is_sent_when_gamira_said_nothing` |
| A review never raises an alert | `test_ai_conversation_review.py::test_a_review_never_raises_an_alert` |

## Voice-specific controls — implemented

- Authentication before a token is issued.
- Model, modalities, system instruction and tool catalogue pinned server-side,
  into the token's connect constraints.
- One-use tokens: `uses=1`, a one-minute window to open a session, a
  thirty-minute session lifetime.
- Concurrent-session and per-hour limits per user.
- Every state-changing tool call goes through the Gamira backend.
- Microphone state is visible, and it stops feeding the model while a tool call
  is resolving. It keeps listening while a confirmation dialog is open, because
  a spoken "yes" is the point of it — muting there meant the person answered
  into a dead microphone and nothing happened until somebody touched the screen.
  What the mute protected against, the model proposing the same thing twice, is
  handled where it belongs: an identical request while one is still pending
  returns the confirmation already open rather than raising a second.
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
