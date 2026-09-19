"""Validity intervals for relations (PoC v1 Temporal rules).

- The intervals of one relation (same source, target, kind) never overlap.
- `valid_to` is only ever set from an explicit statement in the source.
- An unknown start is treated as -infinity and a missing end as +infinity.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

_EARLIEST = datetime.min.replace(tzinfo=UTC)


def parse_instant(value: str | None) -> datetime | None:
    """ISO 8601 date or datetime -> aware UTC datetime; anything unparseable is None."""
    if not value or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@dataclass(frozen=True)
class Interval:
    valid_from: datetime | None
    valid_to: datetime | None

    def overlaps(self, other: "Interval") -> bool:
        starts_before_other_ends = (
            self.valid_from is None or other.valid_to is None or self.valid_from <= other.valid_to
        )
        other_starts_before_end = (
            other.valid_from is None or self.valid_to is None or other.valid_from <= self.valid_to
        )
        return starts_before_other_ends and other_starts_before_end

    def merge(self, other: "Interval") -> "Interval":
        """Union of two overlapping intervals.

        A source that does not mention a start or end tells us nothing, so only *known* values
        count: the merged start is the earliest known start, and an explicit end wins over an
        open end (that is how a later source closes a relation).
        """
        starts = [start for start in (self.valid_from, other.valid_from) if start is not None]
        start = min(starts) if starts else None
        ends = [end for end in (self.valid_to, other.valid_to) if end is not None]
        return Interval(start, max(ends) if ends else None)


def normalize(intervals: list[Interval]) -> list[Interval]:
    """Sort and fold overlapping intervals so the result is disjoint."""
    result: list[Interval] = []
    for interval in sorted(intervals, key=lambda item: item.valid_from or _EARLIEST):
        if result and result[-1].overlaps(interval):
            result[-1] = result[-1].merge(interval)
        else:
            result.append(interval)
    return result
