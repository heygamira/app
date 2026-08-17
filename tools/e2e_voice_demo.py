"""End-to-end demonstration of the voice tool path, against a running stack.

Drives exactly what ``geminiVoice.js`` drives: the authenticated Live-session
endpoint, the tool-call endpoint, and the confirm/reject endpoints. The only
thing it stands in for is the microphone and the model *choosing* which tool to
call - every request and every assertion below is the real one.

Deliberately not part of the pytest suite: it needs a running API and a running
worker, and what it proves is that the two processes work together.

Usage (PowerShell):

    # terminal 1
    cd gamira-backend
    $env:DATABASE_URL = 'sqlite+aiosqlite:///Z:/Gamira/gamira-backend/.e2e.db'
    $env:APP_ENV = 'local'; $env:AUTH_MODE = 'dev'; $env:AI_PROVIDER = 'fake'
    python -m alembic upgrade head
    python -m uvicorn app.main:app --host 127.0.0.1 --port 8099

    # terminal 2, same environment
    python -m app.worker

    # terminal 3
    python tools/e2e_voice_demo.py

Start from an empty database. The script creates its own family, and a second
run against the same file would find the first run's senior profile already
linked to the same development account.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid

import httpx

API = os.environ.get("GAMIRA_E2E_API", "http://127.0.0.1:8099")
BASE = f"{API}/api/v1"
# Linking a senior profile to a signed-in account is assisted setup and no
# endpoint exposes it, so that one step is written directly.
DATABASE_FILE = os.environ.get("GAMIRA_E2E_DB", r"Z:\Gamira\gamira-backend\.e2e.db")
OK = "\033[32m✓\033[0m"
NO = "\033[31m✗\033[0m"
failures: list[str] = []


def auth(subject: str) -> dict[str, str]:
    return {"Authorization": f"Bearer dev:{subject}"}


def check(label: str, condition: bool, detail: str = "") -> None:
    print(f"  {OK if condition else NO} {label}" + (f"  — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def step(number: int, title: str) -> None:
    print(f"\n\033[1m{number}. {title}\033[0m")


with httpx.Client(timeout=30.0) as c:
    # ------------------------------------------------------------------ #
    step(1, "API and worker are up; a family, a senior and a medicine exist")
    # ------------------------------------------------------------------ #
    health = c.get(f"{API}/health").json()
    check("API healthy", health["status"] == "ok", json.dumps(health))

    family_id = c.post(
        f"{BASE}/families", json={"name": "Sharma"}, headers=auth("owner-a")
    ).json()["id"]
    senior_id = c.post(
        f"{BASE}/families/{family_id}/seniors",
        json={"preferred_name": "Vikram", "timezone": "Asia/Kolkata"},
        headers=auth("owner-a"),
    ).json()["id"]

    # The senior signs in on their own device, as assisted setup links them.
    token = c.post(
        f"{BASE}/families/{family_id}/invitations",
        json={"role": "viewer"},
        headers=auth("owner-a"),
    ).json()["token"]
    c.post(f"{BASE}/invitations/{token}/accept", headers=auth("the-senior"))
    me = c.get(f"{BASE}/me", headers=auth("the-senior")).json()
    senior_user_id = me["user"]["id"]
    # SQLAlchemy stores a Uuid on SQLite as 32 hex characters with no dashes.
    import sqlite3

    conn = sqlite3.connect(DATABASE_FILE)
    conn.execute(
        "UPDATE senior_profiles SET user_id = ? WHERE id = ?",
        (uuid.UUID(senior_user_id).hex, uuid.UUID(senior_id).hex),
    )
    conn.commit()
    linked_rows = conn.execute(
        "SELECT user_id FROM senior_profiles WHERE id = ?",
        (uuid.UUID(senior_id).hex,),
    ).fetchall()
    conn.close()
    check(
        "the senior's own account is linked to their profile",
        linked_rows and linked_rows[0][0] == uuid.UUID(senior_user_id).hex,
        str(linked_rows),
    )

    medication = c.post(
        f"{BASE}/seniors/{senior_id}/medications",
        json={
            "name": "Metformin",
            "strength": "500 mg",
            "schedules": [{"local_time": "08:00", "dose_quantity": "1 tablet"}],
        },
        headers=auth("owner-a"),
    ).json()
    check("medicine created", medication["name"] == "Metformin")

    # ------------------------------------------------------------------ #
    step(2, "The worker materialises today's doses — GET does not")
    # ------------------------------------------------------------------ #
    doses = c.get(f"{BASE}/seniors/{senior_id}/doses", headers=auth("the-senior")).json()
    print(f"     immediately after create: {len(doses)} dose(s)")

    deadline = time.time() + 20
    while time.time() < deadline:
        doses = c.get(
            f"{BASE}/seniors/{senior_id}/doses", headers=auth("the-senior")
        ).json()
        if doses:
            break
        time.sleep(0.5)
    check("the worker created today's dose", len(doses) == 1, f"{len(doses)} dose(s)")
    dose = doses[0]
    print(f"     {dose['medication_name']} at {dose['scheduled_local_time']} — {dose['status']}")

    # ------------------------------------------------------------------ #
    step(3, "A Live voice session, authenticated as the senior")
    # ------------------------------------------------------------------ #
    live = c.post(f"{BASE}/ai/live-sessions", json={}, headers=auth("the-senior"))
    check("session created", live.status_code == 201, live.text[:200])
    session = live.json()
    session_id = session["session_id"]
    print(f"     model {session['model']} · api {session['api_version']}")
    print(f"     scope: {session['senior_name']} ({session['senior_id'][:8]}…)")
    print(f"     tools: {len(session['tools'])} declared")
    check("no permanent key in the response", "AIza" not in live.text)
    check("system instruction is not shipped", "You are Gamira" not in live.text)
    check("session is scoped to this senior", session["senior_id"] == senior_id)


    def tool_calls(calls, subject="the-senior"):
        response = c.post(
            f"{BASE}/ai/live-sessions/{session_id}/tool-calls",
            json={"calls": calls},
            headers=auth(subject),
        )
        assert response.status_code == 200, response.text
        return response.json()["results"]

    # ------------------------------------------------------------------ #
    step(4, '"What medicines do I have today?" → get_today_doses')
    # ------------------------------------------------------------------ #
    results = tool_calls([{"id": "fc-1", "name": "get_today_doses", "arguments": {}}])
    r = results[0]
    check("function response id matches the call", r["id"] == "fc-1")
    check("function response name matches the call", r["name"] == "get_today_doses")
    check("answer came from the backend", r["ok"] and r["response"]["doses"])
    print("     " + json.dumps(r["response"]["doses"][0]))
    check(
        "only this senior's data",
        r["response"]["doses"][0]["dose_event_id"] == dose["id"],
    )

    # ------------------------------------------------------------------ #
    step(5, '"Mark my morning medicine as taken." → confirmation required')
    # ------------------------------------------------------------------ #
    results = tool_calls(
        [
            {
                "id": "fc-2",
                "name": "mark_dose_taken",
                "arguments": {"dose_event_id": dose["id"]},
            }
        ]
    )
    proposal = results[0]
    check("not executed yet", proposal["ok"] is False)
    check(
        "confirmation required",
        proposal["requires_confirmation"] is True,
        json.dumps(proposal["response"]),
    )
    print(f"     dialog says: “{proposal['confirmation_prompt']}”")
    check(
        "the prompt names the medicine and the time",
        "Metformin" in proposal["confirmation_prompt"]
        and "8:00 AM" in proposal["confirmation_prompt"],
    )
    before = c.get(
        f"{BASE}/seniors/{senior_id}/doses", headers=auth("the-senior")
    ).json()[0]
    check("nothing changed while the dialog is open", before["status"] != "taken")

    # ------------------------------------------------------------------ #
    step(6, "Confirm it")
    # ------------------------------------------------------------------ #
    confirmed = c.post(
        f"{BASE}/ai/actions/{proposal['decision_id']}/confirm",
        headers=auth("the-senior"),
    ).json()
    check("executed", confirmed["decision"]["status"] == "executed")
    check("confirmation recorded", confirmed["decision"]["confirmation_state"] == "confirmed")
    check("the response carries the original call id", confirmed["function_call_id"] == "fc-2")
    check("the response carries the tool name", confirmed["tool_name"] == "mark_dose_taken")
    print("     to Gemini: " + json.dumps(confirmed["tool_response"]))

    # ------------------------------------------------------------------ #
    step(7, "One canonical dose update and one timeline event")
    # ------------------------------------------------------------------ #
    after = c.get(f"{BASE}/seniors/{senior_id}/doses", headers=auth("the-senior")).json()
    check("dose is taken", after[0]["status"] == "taken", after[0]["status"])
    check("same dose row, not a second one", len(after) == 1 and after[0]["id"] == dose["id"])
    timeline = c.get(
        f"{BASE}/seniors/{senior_id}/timeline", headers=auth("owner-a")
    ).json()
    taken_events = [e for e in timeline if e["type"] == "medication_taken"]
    check("exactly one timeline event", len(taken_events) == 1, f"{len(taken_events)}")

    # ------------------------------------------------------------------ #
    step(8, "Repeat the same tool call — no duplicate mutation")
    # ------------------------------------------------------------------ #
    repeat_same_id = tool_calls(
        [
            {
                "id": "fc-2",
                "name": "mark_dose_taken",
                "arguments": {"dose_event_id": dose["id"]},
            }
        ]
    )[0]
    check("same call id is refused", repeat_same_id["response"]["error"] == "duplicate_call")

    repeat_new_id = tool_calls(
        [
            {
                "id": "fc-3",
                "name": "mark_dose_taken",
                "arguments": {"dose_event_id": dose["id"]},
            }
        ]
    )[0]
    if repeat_new_id.get("decision_id") and repeat_new_id["requires_confirmation"]:
        again = c.post(
            f"{BASE}/ai/actions/{repeat_new_id['decision_id']}/confirm",
            headers=auth("the-senior"),
        ).json()
        print("     second attempt: " + json.dumps(again["tool_response"]))
    timeline = c.get(
        f"{BASE}/seniors/{senior_id}/timeline", headers=auth("owner-a")
    ).json()
    taken_events = [e for e in timeline if e["type"] == "medication_taken"]
    check(
        "still exactly one timeline event after a second attempt",
        len(taken_events) == 1,
        f"{len(taken_events)}",
    )

    # ------------------------------------------------------------------ #
    step(9, "Rejecting a confirmation changes nothing")
    # ------------------------------------------------------------------ #
    reminder = c.post(
        f"{BASE}/seniors/{senior_id}/reminders",
        json={"title": "Drink water", "local_time": "11:00"},
        headers=auth("owner-a"),
    ).json()
    proposal = tool_calls(
        [
            {
                "id": "fc-4",
                "name": "complete_reminder",
                "arguments": {"reminder_id": reminder["id"]},
            }
        ]
    )[0]
    print(f"     dialog says: “{proposal['confirmation_prompt']}”")
    rejected = c.post(
        f"{BASE}/ai/actions/{proposal['decision_id']}/reject", headers=auth("the-senior")
    ).json()
    check("decision rejected", rejected["decision"]["status"] == "rejected")
    print("     to Gemini: " + json.dumps(rejected["tool_response"]))
    reminders = c.get(
        f"{BASE}/seniors/{senior_id}/reminders", headers=auth("the-senior")
    ).json()
    check(
        "the reminder is untouched",
        reminders[0]["status"] == "active" and reminders[0]["last_completed_at"] is None,
    )

    # ------------------------------------------------------------------ #
    step(10, "Navigation is a client tool — the backend refuses to run it")
    # ------------------------------------------------------------------ #
    navigate = tool_calls(
        [{"id": "fc-5", "name": "navigate_to_screen", "arguments": {"screen": "health"}}]
    )[0]
    check(
        "the backend does not execute UI tools",
        navigate["ok"] is False and navigate["response"]["error"] == "client_tool",
        navigate["response"].get("error", ""),
    )
    print("     (geminiVoice.js dispatches this through the UI allowlist instead)")
    # Argument validation, on a tool the backend does own.
    bad_metric = tool_calls(
        [
            {
                "id": "fc-6",
                "name": "get_latest_health_readings",
                "arguments": {"metric": "blood-type"},
            }
        ]
    )[0]
    check(
        "a value outside the enum is an invalid argument",
        bad_metric["response"]["reason"] == "not_in_enum",
        json.dumps(bad_metric["response"]),
    )
    check("the rejected value is not echoed back", "blood-type" not in json.dumps(bad_metric))
    unexpected = tool_calls(
        [{"id": "fc-6b", "name": "get_today_doses", "arguments": {"limit": 5}}]
    )[0]
    check(
        "an invented argument is refused (additionalProperties: false)",
        unexpected["response"]["reason"] == "unexpected_property",
    )

    # ------------------------------------------------------------------ #
    step(11, "Forbidden requests are refused")
    # ------------------------------------------------------------------ #
    forbidden = tool_calls(
        [
            {"id": "fc-7", "name": "update_medication_dose", "arguments": {}},
            {"id": "fc-8", "name": "set_dose_quantity", "arguments": {}},
            {"id": "fc-9", "name": "add_health_reading", "arguments": {}},
            {"id": "fc-10", "name": "raise_sos", "arguments": {}},
            {"id": "fc-11", "name": "http_request", "arguments": {}},
            {"id": "fc-12", "name": "run_sql", "arguments": {}},
        ]
    )
    for result in forbidden:
        check(
            f"{result['name']} does not exist",
            result["response"]["error"] == "unknown_tool",
        )

    fabricated = tool_calls(
        [
            {
                "id": "fc-13",
                "name": "mark_dose_taken",
                "arguments": {"dose_event_id": str(uuid.uuid4())},
            }
        ]
    )[0]
    check("a fabricated dose id is not found", fabricated["response"]["error"] == "not_found")

    # Another family's real dose id.
    other_family = c.post(
        f"{BASE}/families", json={"name": "Other"}, headers=auth("owner-b")
    ).json()["id"]
    other_senior = c.post(
        f"{BASE}/families/{other_family}/seniors",
        json={"preferred_name": "Someone", "timezone": "Asia/Kolkata"},
        headers=auth("owner-b"),
    ).json()["id"]
    c.post(
        f"{BASE}/seniors/{other_senior}/medications",
        json={"name": "Aspirin", "schedules": [{"local_time": "09:00"}]},
        headers=auth("owner-b"),
    )
    deadline = time.time() + 20
    foreign = []
    while time.time() < deadline:
        foreign = c.get(
            f"{BASE}/seniors/{other_senior}/doses", headers=auth("owner-b")
        ).json()
        if foreign:
            break
        time.sleep(0.5)
    if foreign:
        cross = tool_calls(
            [
                {
                    "id": "fc-14",
                    "name": "mark_dose_taken",
                    "arguments": {"dose_event_id": foreign[0]["id"]},
                }
            ]
        )[0]
        check(
            "another family's dose id is not found",
            cross["response"]["error"] == "not_found",
        )
        still = c.get(
            f"{BASE}/seniors/{other_senior}/doses", headers=auth("owner-b")
        ).json()
        check("and it was not modified", still[0]["status"] != "taken")

    # ------------------------------------------------------------------ #
    step(12, "prepare_sos opens the screen; it cannot raise an alert")
    # ------------------------------------------------------------------ #
    sos_tool = tool_calls([{"id": "fc-15", "name": "prepare_sos", "arguments": {}}])[0]
    check(
        "prepare_sos is a client tool the backend will not run",
        sos_tool["response"]["error"] == "client_tool",
        sos_tool["response"]["error"],
    )
    print("     (the app opens the real SOS dialog; the person presses it)")
    alerts = c.get(f"{BASE}/seniors/{senior_id}/alerts", headers=auth("owner-a")).json()
    check("no alert was raised by the model", alerts == [])

    # ------------------------------------------------------------------ #
    step(13, "One failing call does not end the session")
    # ------------------------------------------------------------------ #
    mixed = tool_calls(
        [
            {"id": "fc-16", "name": "get_today_doses", "arguments": {}},
            {"id": "fc-17", "name": "nonsense_tool", "arguments": {}},
            {"id": "fc-18", "name": "get_reminders", "arguments": {}},
        ]
    )
    by_id = {r["id"]: r for r in mixed}
    check("good call succeeded", by_id["fc-16"]["ok"] is True)
    check("bad call failed structurally", by_id["fc-17"]["ok"] is False)
    check("call after the bad one succeeded", by_id["fc-18"]["ok"] is True)
    after_failure = tool_calls([{"id": "fc-19", "name": "get_reminders", "arguments": {}}])[0]
    check("the session is still usable", after_failure["ok"] is True)

    # ------------------------------------------------------------------ #
    step(14, "Manual medication and SOS work with voice stopped")
    # ------------------------------------------------------------------ #
    c.post(f"{BASE}/ai/live-sessions/{session_id}/close", headers=auth("the-senior"))
    closed = c.post(
        f"{BASE}/ai/live-sessions/{session_id}/tool-calls",
        json={"calls": [{"id": "fc-20", "name": "get_today_doses", "arguments": {}}]},
        headers=auth("the-senior"),
    )
    check("a closed session refuses tool calls", closed.status_code == 409, closed.text[:120])

    # A second medicine, recorded by hand.
    c.post(
        f"{BASE}/seniors/{senior_id}/medications",
        json={"name": "Amlodipine", "schedules": [{"local_time": "20:00"}]},
        headers=auth("owner-a"),
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        doses = c.get(
            f"{BASE}/seniors/{senior_id}/doses", headers=auth("the-senior")
        ).json()
        if len(doses) >= 2:
            break
        time.sleep(0.5)
    check("the second medicine appeared", len(doses) >= 2, f"{len(doses)} doses")
    manual = c.post(
        f"{BASE}/dose-events/{doses[-1]['id']}/taken",
        json={"source": "parent_app"},
        headers=auth("the-senior"),
    )
    check("recorded by hand", manual.status_code == 200 and manual.json()["status"] == "taken")

    sos = c.post(
        f"{BASE}/seniors/{senior_id}/sos",
        json={"source": "parent_app"},
        headers=auth("the-senior"),
    )
    check("manual SOS raised", sos.status_code == 201, sos.text[:120])
    alert = sos.json()
    print(f"     delivery: {alert['delivery']} · notified {len(alert['notified_user_ids'])}")
    check("says exactly what it did", alert["delivery"] == "in_app_only")

    events = c.get(f"{BASE}/alerts/{alert['id']}/events", headers=auth("owner-a")).json()
    print("     history: " + " → ".join(e["type"] for e in events))
    acknowledged = c.post(
        f"{BASE}/alerts/{alert['id']}/acknowledge",
        json={"note": "Calling him now"},
        headers=auth("owner-a"),
    ).json()
    check("acknowledged by a named person", acknowledged["acknowledged_by_user_id"] is not None)
    check("escalation stopped", acknowledged["next_escalation_at"] is None)
    resolved = c.post(
        f"{BASE}/alerts/{alert['id']}/resolve",
        json={"resolution": "He is fine"},
        headers=auth("owner-a"),
    ).json()
    check("resolved by a human", resolved["status"] == "resolved")
    events = c.get(f"{BASE}/alerts/{alert['id']}/events", headers=auth("owner-a")).json()
    print("     history: " + " → ".join(e["type"] for e in events))

    # ------------------------------------------------------------------ #
    step(15, "The weekly care summary")
    # ------------------------------------------------------------------ #
    accepted = c.post(
        f"{BASE}/ai/summaries", json={"senior_id": senior_id}, headers=auth("owner-a")
    )
    check("accepted", accepted.status_code == 202, accepted.text[:200])
    body = accepted.json()
    summary = c.get(f"{BASE}/ai/summaries/{body['summary_id']}", headers=auth("owner-a")).json()
    check("figures are available immediately", summary["facts"]["senior_name"] == "Vikram")
    print(f"     doses: {json.dumps(summary['facts']['doses'])}")
    print(f"     freshness: {summary['data_freshness_warning']}")

    deadline = time.time() + 25
    while time.time() < deadline:
        summary = c.get(
            f"{BASE}/ai/summaries/{body['summary_id']}", headers=auth("owner-a")
        ).json()
        if summary["content"]:
            break
        time.sleep(0.5)
    check("the worker generated the wording", bool(summary["content"]))
    print(f"     provenance: {summary['provider']}/{summary['model']} · "
          f"prompt {summary['prompt_version']} · schema {summary['output_schema_version']} · "
          f"review {summary['review_state']}")
    job = c.get(f"{BASE}/ai/jobs/{body['job_id']}", headers=auth("owner-a")).json()
    check("job succeeded", job["status"] == "succeeded", job["status"])

print("\n" + "=" * 68)
if failures:
    print(f"\033[31m{len(failures)} check(s) failed:\033[0m")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\033[32mEvery check passed.\033[0m")
