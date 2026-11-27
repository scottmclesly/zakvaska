"""The jars picked out to be set against each other.

Comparing is something you decide to do, about jars you choose: "add to
comparison" on a jar's own page puts it on the list, and the comparison page
draws the list head to head. The dashboard used to do this unasked, for
whichever jars happened to share a flour, and it sat there looking like it
belonged to something else.

The list is one row in the settings table, a comma-separated run of jar
ids in the order they were added. Nothing else is stored: the page works
the chart out from the jars' own feeds each time it is drawn.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.jar import Jar
from app.services import settings_store

KEY = "compare_jars"
#: More lines than this on one axis is a tangle, not a comparison.
MOST = 6


def chosen_ids(session: Session) -> list[int]:
    raw = settings_store.get_setting(session, KEY) or ""
    ids: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and int(part) not in ids:
            ids.append(int(part))
    return ids


def _save(session: Session, ids: list[int]) -> None:
    settings_store.set_setting(session, KEY, ",".join(str(i) for i in ids))


def chosen_jars(session: Session) -> list[Jar]:
    """The jars on the list that are still there to compare, in the order
    they were added. One that has since been archived drops out of the
    picture without being struck off: unarchive it and it is back."""
    jars = []
    for jar_id in chosen_ids(session):
        jar = session.get(Jar, jar_id)
        if jar is not None and not jar.archived:
            jars.append(jar)
    return jars


def is_chosen(session: Session, jar: Jar) -> bool:
    return jar.id in chosen_ids(session)


def is_full(session: Session) -> bool:
    return len(chosen_ids(session)) >= MOST


def add(session: Session, jar: Jar) -> bool:
    """Put a jar on the list. False, changing nothing, when it is full."""
    ids = chosen_ids(session)
    if jar.id in ids:
        return True
    if len(ids) >= MOST:
        return False
    _save(session, ids + [jar.id])
    return True


def remove(session: Session, jar_id: int) -> None:
    _save(session, [i for i in chosen_ids(session) if i != jar_id])


def clear(session: Session) -> None:
    _save(session, [])
