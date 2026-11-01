"""What changed between two versions of a recipe.

Lines are matched by name rather than by position, because the interesting
question is "did the salt change?", not "did row four change?". Where a name
appears more than once, the repeats are paired up in the order they appear.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Literal

from app.models.recipe import RecipeIngredient, RecipeStage, RecipeVersion

ChangeKind = Literal["added", "removed", "changed", "moved"]


# What a changed field is called on screen. The stored name is kept too,
# because the page has to know a temperature when it sees one: it is stored
# in Celsius and shown in the user's unit like everywhere else.
FIELD_LABELS = {
    "baker_pct": "baker's %",
    "role": "role",
    "notes": "notes",
    "duration_min": "duration (min)",
    "temp_c": "temperature",
}


@dataclass(frozen=True)
class FieldChange:
    field: str
    before: Any
    after: Any

    @property
    def label(self) -> str:
        return FIELD_LABELS.get(self.field, self.field.replace("_", " "))


@dataclass(frozen=True)
class LineDiff:
    kind: ChangeKind
    name: str
    changes: list[FieldChange] = field(default_factory=list)
    before_seq: int | None = None
    after_seq: int | None = None

    @property
    def summary(self) -> str:
        if self.kind == "added":
            return f"added {self.name}"
        if self.kind == "removed":
            return f"removed {self.name}"
        if self.kind == "moved":
            return f"moved {self.name}"
        bits = ", ".join(
            f"{c.label} {_show(c.before)} → {_show(c.after)}" for c in self.changes
        )
        return f"{self.name}: {bits}"


@dataclass(frozen=True)
class VersionDiff:
    from_version: int
    to_version: int
    ingredients: list[LineDiff] = field(default_factory=list)
    stages: list[LineDiff] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.ingredients and not self.stages

    @property
    def count(self) -> int:
        return len(self.ingredients) + len(self.stages)


def _show(value: Any) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _key(name: str) -> str:
    return name.strip().lower()


def _pair_up(before: list, after: list) -> tuple[list[tuple], list, list]:
    """Match by name, repeats in order. Returns (pairs, only_before, only_after)."""
    buckets: dict[str, list] = defaultdict(list)
    for item in after:
        buckets[_key(item.name)].append(item)

    pairs: list[tuple] = []
    unmatched_before: list = []
    for item in before:
        bucket = buckets.get(_key(item.name))
        if bucket:
            pairs.append((item, bucket.pop(0)))
        else:
            unmatched_before.append(item)

    unmatched_after = [item for bucket in buckets.values() for item in bucket]
    # Keep report order stable and predictable.
    unmatched_after.sort(key=lambda i: i.seq)
    return pairs, unmatched_before, unmatched_after


def _compare(before: Any, after: Any, fields: tuple[str, ...]) -> list[FieldChange]:
    changes = []
    for name in fields:
        old, new = getattr(before, name), getattr(after, name)
        if old != new:
            changes.append(FieldChange(field=name, before=old, after=new))
    return changes


def _diff_lines(
    before: list, after: list, fields: tuple[str, ...], *, track_moves: bool
) -> list[LineDiff]:
    pairs, gone, fresh = _pair_up(before, after)
    result: list[LineDiff] = []

    for old, new in pairs:
        changes = _compare(old, new, fields)
        if changes:
            result.append(
                LineDiff(
                    kind="changed", name=new.name, changes=changes,
                    before_seq=old.seq, after_seq=new.seq,
                )
            )
        elif track_moves and old.seq != new.seq:
            # Order is meaningful for stages: a proof before the bake is not
            # the same recipe as a proof after it.
            result.append(
                LineDiff(
                    kind="moved", name=new.name,
                    before_seq=old.seq, after_seq=new.seq,
                )
            )

    result.extend(
        LineDiff(kind="removed", name=item.name, before_seq=item.seq) for item in gone
    )
    result.extend(
        LineDiff(kind="added", name=item.name, after_seq=item.seq) for item in fresh
    )
    return result


INGREDIENT_FIELDS = ("baker_pct", "role", "notes")
STAGE_FIELDS = ("duration_min", "temp_c", "notes")


def diff_versions(before: RecipeVersion, after: RecipeVersion) -> VersionDiff:
    return VersionDiff(
        from_version=before.version,
        to_version=after.version,
        ingredients=_diff_lines(
            list(before.ingredients), list(after.ingredients),
            INGREDIENT_FIELDS, track_moves=False,
        ),
        stages=_diff_lines(
            list(before.stages), list(after.stages),
            STAGE_FIELDS, track_moves=True,
        ),
    )


def describe_ingredient(line: RecipeIngredient) -> str:
    return f"{line.name} {line.baker_pct:g}%"


def describe_stage(line: RecipeStage) -> str:
    bits = [line.name]
    if line.duration_min is not None:
        bits.append(f"{line.duration_min} min")
    return " · ".join(bits)
