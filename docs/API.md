# API contract

Base path: `/api/v1`

FastAPI's generated OpenAPI specification at `/openapi.json` is the executable
source of truth. This document adds the security expectations around it, and
says which endpoints exist.

Every endpoint below is marked:

- **✅** implemented and tested
- **⬜** not implemented — planned shape only

## Conventions

- JSON request and response bodies unless uploading/downloading files
- `Authorization: Bearer <Firebase ID token>` for authenticated endpoints
- ISO 8601 timestamps with timezone
- UUID resource identifiers
- `Idempotency-Key` on retryable creation/action endpoints
- Correlation ID returned in every response and log entry
- No user role, family membership or entitlement is trusted from the client
- **A GET writes nothing.** `GET /seniors/{id}/doses` used to create the rows it
  returned; that is the worker's job now.

### Error format

```json
{
  "error": {
    "code": "medication_schedule_conflict",
    "message": "A safe user-facing explanation.",
    "details": {},
    "request_id": "uuid"
  }
}
```

Stable machine-readable codes are required. Do not make clients parse error text.

### Not found versus forbidden

A caller outside a family gets `404`, not `403`, for anything belonging to it.
An outsider must not be able to learn which senior, alert, session or device ids
exist. `403` is only for a caller who *is* in the family but whose role does not
allow the action.

## Health and session

- ✅ `GET /health` — process and dependency health
- ✅ `GET /me` — internal user, active memberships and visible seniors
- ✅ `PATCH /me` — the caller's own profile only
- ✅ `POST /devices` — register or refresh this installation, rotate its push
  token. Safe to call on every app start; the same `install_id` updates one row.
- ✅ `GET /devices` — the caller's own devices. No endpoint lists anyone else's.
- ✅ `DELETE /devices/{device_id}` — revoke and drop the token

`DeviceOut` has no `push_token` field. The token goes in and never comes out;
only its fingerprint is returned, which identifies a device without being usable
to send to it.

## Families and seniors

- ✅ `POST /families`
- ✅ `GET /families/{family_id}`
- ✅ `PATCH /families/{family_id}`
- ✅ `GET /families/{family_id}/members`
- ✅ `POST /families/{family_id}/invitations`
- ✅ `POST /invitations/{token}/accept`
- ✅ `DELETE /families/{family_id}/members/{membership_id}`
- ✅ `GET /families/{family_id}/seniors`
- ✅ `POST /families/{family_id}/seniors`
- ✅ `GET /seniors/{senior_id}`
- ✅ `PATCH /seniors/{senior_id}`
- ✅ `DELETE /seniors/{senior_id}` — archives; history survives

Invitation tokens are secret bearer values, stored only as a hash, returned once
at creation and never logged.

## Medications and doses

- ✅ `GET /seniors/{senior_id}/medications`
- ✅ `POST /seniors/{senior_id}/medications`
- ✅ `GET /medications/{medication_id}`
- ✅ `PATCH /medications/{medication_id}`
- ✅ `POST /medications/{medication_id}/archive`
- ✅ `POST /medications/{medication_id}/schedules`
- ✅ `PATCH /medication-schedules/{schedule_id}`
- ✅ `DELETE /medication-schedules/{schedule_id}`
- ✅ `GET /seniors/{senior_id}/doses?from=&to=` — **read-only**
- ✅ `POST /dose-events/{dose_event_id}/taken`
- ✅ `POST /dose-events/{dose_event_id}/skipped`

Taken/skipped are idempotent and return the current canonical event. Creating a
medication or a schedule enqueues `doses.materialize` for that person in the
same transaction, so today's doses appear as soon as the worker runs rather than
waiting for the next five-minute tick.

## Reminders, timeline and notifications

- ✅ `GET /seniors/{senior_id}/reminders`
- ✅ `POST /seniors/{senior_id}/reminders`
- ✅ `PATCH /reminders/{reminder_id}`
- ✅ `DELETE /reminders/{reminder_id}`
- ✅ `GET /seniors/{senior_id}/timeline`
- ✅ `GET /notifications` — the caller's own in-app inbox
- ✅ `POST /notifications/{notification_id}/opened`

`GET /notifications` returns `channel: "in_app"` rows only. A `push` row beside
them is a delivery job with its own per-device attempt history, not a second
inbox item.

## Health readings

- ✅ `GET /seniors/{senior_id}/health-readings`
- ✅ `POST /seniors/{senior_id}/health-readings`
- ✅ `POST /seniors/{senior_id}/device-flags` — a paired device reporting that
  one of *its own* limits was crossed. Never an SOS, never a Gamira judgement.
- ⬜ `GET /seniors/{senior_id}/health-summary`
- ⬜ `POST /seniors/{senior_id}/reports`
- ⬜ `GET /reports/{report_id}`

Reading input must specify source, unit and measured time. The backend validates
supported metric/unit combinations and physical plausibility; neither is a
clinical judgement.

## Appointments and notes

- ✅ `GET /seniors/{senior_id}/appointments`
- ✅ `POST /seniors/{senior_id}/appointments`
- ✅ `PATCH /appointments/{appointment_id}`
- ✅ `GET /families/{family_id}/notes`
- ✅ `POST /families/{family_id}/notes`

## Files

- ⬜ `POST /files/upload-intents`
- ⬜ `POST /files/{file_id}/complete`
- ⬜ `GET /files/{file_id}/download`
- ⬜ `DELETE /files/{file_id}`

None of these exist. Photo upload in both apps is still disabled because of it.

## Alerts and SOS

- ✅ `POST /seniors/{senior_id}/sos` — raise an alert
- ✅ `GET /seniors/{senior_id}/alerts?open_only=`
- ✅ `GET /alerts/{alert_id}`
- ✅ `GET /alerts/{alert_id}/events` — the append-only history
- ✅ `POST /alerts/{alert_id}/acknowledge`
- ✅ `POST /alerts/{alert_id}/resolve`
- ✅ `POST /alerts/{alert_id}/cancel` — requires a reason; only the raiser or a
  member with write access. An assistant reaches this only through the one
  narrow voice path described in `docs/AI_SAFETY.md`, which is scoped to the
  speaker's own open alert and still tells the family.
- ✅ `GET /seniors/{senior_id}/wellbeing-checks` — questions a device flag
  has left owed, and how they were answered. Any active member, including
  the cared-for person themselves
- ✅ `POST /wellbeing-checks/{check_id}/answer` — `{alright: bool}`. The
  tap equivalent of answering Gamira out loud, for anybody who cannot or
  would rather not speak
- ✅ `GET /seniors/{senior_id}/emergency-contacts`
- ✅ `POST /seniors/{senior_id}/emergency-contacts`
- ✅ `PATCH /emergency-contacts/{contact_id}`
- ✅ `DELETE /emergency-contacts/{contact_id}`

Alert creation returns immediately after durable persistence, with
`"delivery": "in_app_only"`. That field is constant and honest: Gamira raises
the alert inside the app for every other member of the family, and repeats it to
the *same people* if nobody acknowledges. It does not call anyone, send SMS,
share location or contact emergency services.

Any member may acknowledge, including a viewer — answering an emergency is not
an administrative privilege. Acknowledgement, resolution and cancellation all
require a human actor; the AI is refused at the service layer, not by
configuration.

## AI

- ✅ `POST /ai/summaries` — count a period now, queue the wording. Returns 202
  with a `summary_id` that already resolves.
- ✅ `GET /ai/summaries/{summary_id}`
- ✅ `GET /ai/seniors/{senior_id}/summaries`
- ✅ `GET /ai/jobs/{job_id}` — job state and a safe `last_error_code`
- ✅ `POST /ai/chat` — permission-scoped conversational request
- ✅ `POST /ai/live-sessions` — authenticated Live session + ephemeral token
- ✅ `POST /ai/live-sessions/{session_id}/tool-calls` — one Live message's
  function calls, as a batch
- ✅ `POST /ai/live-sessions/{session_id}/promote` — turn a speculative
  wake-word session into a real one
- ✅ `POST /ai/live-sessions/{session_id}/transcript` — a batch of turns,
  both sides, written against that session's conversation
- ✅ `POST /ai/live-sessions/{session_id}/close`
- ✅ `GET /ai/seniors/{senior_id}/memories` — what Gamira remembers about
  one person. Read by both apps; the person sees their own.
- ✅ `DELETE /ai/memories/{memory_id}` — forget one. Any active member,
  including the cared-for person themselves.
- ✅ `GET /ai/seniors/{senior_id}/family-notices` — what Gamira has told
  this person's family about them, for the person themselves to read
- ✅ `GET /ai/actions/{decision_id}`
- ✅ `POST /ai/actions/{decision_id}/confirm`
- ✅ `POST /ai/actions/{decision_id}/reject`

`POST /ai/live-token` from the earlier draft does not exist; the endpoint is
`POST /ai/live-sessions`, and it creates a session record rather than only a
token.

The client cannot submit an arbitrary backend tool name. The server declares the
catalogue into the token, stores a snapshot on the session, and refuses any call
whose name was not in that snapshot.

### Live session response

```json
{
  "session_id": "uuid",
  "conversation_id": "uuid",
  "token": "<one-use ephemeral token>",
  "model": "gemini-3.1-flash-live-preview",
  "api_version": "v1alpha",
  "expires_at": "2026-08-17T06:25:43Z",
  "connect_before": "2026-08-17T05:56:43Z",
  "senior_id": "uuid",
  "senior_name": "Vikram",
  "tools": ["get_today_doses", "..."]
}
```

`connect_before` is much sooner than `expires_at`: the token may only *open* a
session for a minute, and the session then runs for the longer window. The
permanent Gemini key and the system instruction are not in this response and are
not derivable from it.

### Tool calls

```json
POST /ai/live-sessions/{session_id}/tool-calls
{ "calls": [ { "id": "fc-1", "name": "get_today_doses", "arguments": {} } ] }
```

```json
{
  "session_id": "uuid",
  "results": [
    {
      "id": "fc-1",
      "name": "get_today_doses",
      "ok": true,
      "response": { "status": "ok", "date": "2026-08-17", "doses": [] },
      "decision_id": "uuid",
      "requires_confirmation": false,
      "confirmation_prompt": null
    }
  ]
}
```

One result per call, in order, each echoing its own `id` and `name` unchanged —
a response matched to the wrong call makes the model attribute an answer to the
wrong question. One call failing never fails the batch.

`response` is what goes to `session.sendToolResponse`. Error codes:
`permission_denied`, `confirmation_required`, `not_found`, `invalid_arguments`,
`duplicate_call`, `dependency_unavailable`, `action_failed`, `unknown_tool`,
`client_tool`. Never a stack trace, never a database message, never the rejected
argument value.

The idempotency basis for a state-changing call is
`live:{session_id}:{function_call_id}`.

## Subscription endpoints

- ⬜ `GET /entitlements`
- ⬜ `POST /billing/checkout-session`
- ⬜ `POST /billing/webhooks/provider`

None exist. Nothing in the product grants a paid entitlement.

## Realtime channels

- ⬜ WebSocket/SSE for alert lifecycle, dose acknowledgement, AI streaming
  control events and family presence.

Not implemented. Both apps poll. REST remains authoritative either way, and
every realtime connection would have to authenticate and re-check authorization
when a membership is revoked — as the Live tool-call path already does.
