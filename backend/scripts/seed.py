"""A canned stakeholder conversation for demos and the end-to-end check.

A demo should not depend on typing six messages into Slack correctly while
someone watches. This loads the same conversation the pipeline would have
captured, so ``/pm start`` in that channel has something to read — and so a
rehearsal is repeatable rather than improvised.

Captured messages live in the server's in-memory store, so seeding has to
happen inside the server process: set ``SEED_CHANNEL=C0123456789`` and the API
seeds that channel at startup. ``scripts.e2e`` seeds its own process the same
way. Nothing is written to disk.
"""

from __future__ import annotations

from app.models import SlackMessage
from app.store import store

#: A conversation with the properties the pipeline needs to show its work:
#: two stakeholders who disagree slightly, a real constraint, a deadline, and
#: one feature explicitly ruled out — so `out_of_scope` has something in it and
#: the extraction can be checked rather than admired.
CONVERSATION: list[tuple[str, str]] = [
    (
        "priya",
        "We need something for booking seats at campus events. Right now it's a "
        "spreadsheet and it keeps breaking.",
    ),
    (
        "omar",
        "Students should be able to see what's on and reserve a seat. Society "
        "organisers create the events.",
    ),
    (
        "priya",
        "Organisers need to see who has booked, so they can plan catering and know when to stop.",
    ),
    (
        "omar",
        "It has to work properly on phones. Almost every student will book from "
        "their phone between lectures.",
    ),
    (
        "priya",
        "Each event has a capacity and it must not be possible to over-book it. "
        "That's the bit the spreadsheet gets wrong.",
    ),
    (
        "omar",
        "Should students be able to cancel? I think yes, otherwise no-shows hold "
        "seats nobody can take.",
    ),
    ("priya", "Yes, cancellation up to 24 hours before. After that it stays booked."),
    (
        "omar",
        "We talked about charging for some events, but we're not taking payments "
        "this year, so leave that out.",
    ),
    (
        "priya",
        "Budget is zero — it has to run on free tiers. And we need it live before "
        "the spring fair in March.",
    ),
    ("omar", "Sign-in should use university accounts so we know who is actually a student."),
]


def seed_store(channel_id: str, *, reset: bool = True) -> int:
    """Load the conversation into ``channel_id``. Returns how many were added."""
    if reset:
        store.clear_channel(channel_id)

    added = 0
    for index, (name, text) in enumerate(CONVERSATION):
        added += store.add_message(
            SlackMessage(
                channel_id=channel_id,
                # Slack timestamps are "seconds.microseconds" strings and the
                # transcript is ordered by them, so they must ascend.
                ts=f"{1740000000 + index * 60}.000100",
                user_id=f"USEED{index:02d}",
                user_name=name,
                text=text,
                is_bot=False,
            )
        )
    print(f"Seeded {added} messages into {channel_id}. Run `/pm start` in that channel.")
    return added
