"""Part E — Multi-window, multi-burn-rate alerting (Google SRE Workbook, ch. 5).

Input: per-minute ``total`` and ``bad`` request counts for a 30-day window.

burn_rate(window) = error_ratio(window) / (1 - SLO)

A rule fires at minute i when BOTH its long and its short window (ending at i,
inclusive) burn at least ``burn_rate``. The long window says "this is
significant"; the short window says "it is still happening" (so the alert
resets quickly after recovery).

Tests: tests/test_alerting.py, then `make slo`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlertRule:
    name: str
    severity: str  # "page" or "ticket"
    long_min: int
    short_min: int
    burn_rate: float


# SRE Workbook defaults for a 30-day SLO window
DEFAULT_RULES: tuple[AlertRule, ...] = (
    AlertRule("fast_burn_2pct_1h", "page", 60, 5, 14.4),
    AlertRule("slow_burn_5pct_6h", "page", 360, 30, 6.0),
    AlertRule("budget_leak_10pct_3d", "ticket", 4320, 360, 1.0),
)


@dataclass(frozen=True)
class AlertEvent:
    rule: str
    severity: str
    start_min: int  # first minute the rule fired
    end_min: int  # first minute it stopped firing (exclusive)


class WindowSums:
    """O(1) sum of any window, via prefix sums. Build once, query many times.

    43,200 minutes x 6 windows: recomputing every window with sum() is far too slow.
    """

    def __init__(self, values: list[int]) -> None:
        """TODO(student): build the prefix-sum list (prefix[0] = 0)."""

        self.prefix = [0]
        for x in values: self.prefix.append(self.prefix[-1] + x)

    def sum(self, end_inclusive: int, length: int) -> int:
        """TODO(student): sum of values[end_inclusive - length + 1 .. end_inclusive],
        clipped at index 0 when the window starts before the data."""

        end = min(len(self.prefix)-1, end_inclusive + 1)
        return self.prefix[end] - self.prefix[max(0,end-length)]


class BurnRateAlerter:
    def __init__(self, slo: float = 0.995, rules: tuple[AlertRule, ...] = DEFAULT_RULES) -> None:
        if not 0 < slo < 1:
            raise ValueError("slo must be in (0, 1)")
        self.slo = slo
        self.rules = rules

    def burn_rate(self, total: WindowSums, bad: WindowSums, end: int, length: int) -> float:
        """TODO(student): (bad / total over the window) / (1 - slo); 0.0 if total is 0."""

        n = total.sum(end, length)
        return bad.sum(end,length) / n / (1-self.slo) if n else 0.0

    def evaluate(self, total: list[int], bad: list[int]) -> list[AlertEvent]:
        """TODO(student): one AlertEvent per contiguous firing episode of each rule.

        For each rule, scan the minutes; the rule fires at minute i when
        burn(long) >= rule.burn_rate AND burn(short) >= rule.burn_rate.
        An episode starts at the first firing minute and ends (exclusive) at the
        first minute it stops firing (or len(total)). Sort by start_min.
        """

        tot, failures = WindowSums(total), WindowSums(bad)
        events = []
        for rule in self.rules:
            active = None
            for i in range(len(total)):
                firing = (self.burn_rate(tot,failures,i,rule.long_min) >= rule.burn_rate and
                          self.burn_rate(tot,failures,i,rule.short_min) >= rule.burn_rate)
                if firing and active is None: active = i
                elif not firing and active is not None:
                    events.append(AlertEvent(rule.name,rule.severity,active,i))
                    active = None
            if active is not None: events.append(AlertEvent(rule.name,rule.severity,active,len(total)))
        return sorted(events,key=lambda x:x.start_min)


def error_budget_report(total: list[int], bad: list[int], slo: float = 0.995) -> dict[str, float | bool]:
    """TODO(student): how much of the 30-day error budget is spent?

    Return a dict with:
      requests          sum(total)
      allowed_bad       (1 - slo) * requests            (round to 1 decimal)
      bad               sum(bad)
      availability      1 - bad / requests              (round to 6 decimals)
      budget_consumed   bad / allowed_bad               (round to 4 decimals)
      budget_remaining  1 - budget_consumed             (round to 4 decimals)
      freeze_releases   True when nothing is left (budget_remaining <= 0)
    """
    requests = sum(total)
    allowed = round((1-slo)*requests,1)
    b = sum(bad)
    consumed = round(b/allowed,4) if allowed else (float('inf') if b else 0.0)
    remaining = round(1-consumed,4)
    return {
        "requests": requests,
        "allowed_bad": allowed,
        "bad": b,
        "availability": round(1 - b / requests, 6) if requests else 1.0,
        "budget_consumed": consumed,
        "budget_remaining": remaining,
        "freeze_releases": remaining <= 0,
    }
