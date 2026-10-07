"""Set up a room for recording Concord and Accord in the real app.

Deletes any earlier recording rooms (every room whose name starts with
``acme-``), then creates ``$ROOM`` with the conductor, the aligner, four persona
teammates, a person to post as (Morgan), and the two tasks the recordings use.

    ROOM=acme-renewal-q4 uv run --project fastapi-backend python shotkit/recordings/l9/setup.py
"""

from __future__ import annotations

import os

import httpx

HUB = os.environ.get("HUB", "http://localhost:8100").rstrip("/") + "/api"
ROOM = os.environ.get("ROOM", "acme-renewal")

#: Said before each character, so the model plays a teammate in an exercise
#: rather than being asked to become someone.
FRAME = (
    "This is a planning exercise: play the teammate described below, answer as they "
    "would, and follow the facilitator's format (including any [[mycelium: ...]] "
    "marker it asks for). "
)
NOTES = {
    "success": (
        "You are the customer success lead for Acme, an at-risk enterprise customer. "
        "You want to keep Acme at almost any price: losing them would hurt references "
        "and the team. You're warm, practical and brief."
    ),
    "finance": (
        "You are the finance partner. You protect margin: no discount above 10% on a "
        "renewal, and you want the numbers to work over the whole term. You're precise "
        "and brief."
    ),
    "sales": (
        "You are the account executive for Acme. You'll trade price for commitment: any "
        "discount should come with a multi-year term. You're direct and brief."
    ),
    "legal": (
        "You are counsel. You won't accept non-standard liability terms or uncapped "
        "indemnities; standard terms are fine. You're careful and brief."
    ),
}
TASKS = (
    ("Decide the renewal offer for Acme", "work/acme-renewal-offer"),
    ("Plan the Acme renewal handoff", "work/acme-renewal-handoff"),
)

with httpx.Client(timeout=60) as c:
    for r in c.get(f"{HUB}/rooms").json():
        if r["name"].startswith("acme-"):
            c.delete(f"{HUB}/rooms/{r['name']}")
    c.post(f"{HUB}/users", json={"handle": "morgan", "display_name": "Morgan Reyes"})
    c.post(f"{HUB}/rooms", json={"name": ROOM}).raise_for_status()
    for handle, kind in (("conductor", "conductor"), ("aligner", "aligner")):
        c.post(f"{HUB}/rooms/{ROOM}/engines", json={"handle": handle, "kind": kind}).raise_for_status()
    for handle, notes in NOTES.items():
        c.post(f"{HUB}/rooms/{ROOM}/engines", json={"handle": handle, "kind": "persona"}).raise_for_status()
        c.post(
            f"{HUB}/rooms/{ROOM}/memory",
            json={"items": [{"key": f"agents/{handle}/notes", "value": FRAME + notes, "created_by": "morgan"}]},
        ).raise_for_status()
    for title, key in TASKS:
        c.post(
            f"{HUB}/rooms/{ROOM}/tasks", json={"title": title, "handle": "morgan", "key": key}
        ).raise_for_status()
    print(f"room {ROOM} ready")
