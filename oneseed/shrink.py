"""Make a failing run as small as it will go.

A seed that fails after two hundred faults is a bug report nobody can read.
The same failure caused by two of them is an explanation. Shrinking is delta
debugging over the fault list: take faults away, replay, and keep the removal
whenever the same invariant still breaks.

It tries big cuts first — half the list, then quarters — because most faults
in a failing run are bystanders and go in bulk. It finishes one fault at a
time, until removing any single remaining fault makes the failure go away.
That last property is what the result means: every fault left is needed.

It is not guaranteed to find the smallest possible set, only one that cannot
be made smaller by removing one thing. And every candidate is actually run:
nothing here reasons about what a fault "should" cause.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .faults import Fault
from .run import Outcome, Scenario, run


@dataclass(frozen=True)
class Shrunk:
    faults: tuple[Fault, ...]
    outcome: Outcome
    #: How many replays it took.
    runs: int


def shrink(scenario: Scenario, failing: Outcome) -> Shrunk:
    if failing.violation is None:
        raise ValueError("there is nothing to shrink: that run did not fail")
    wanted = failing.violation.name
    runs = 0

    def still_fails(faults: Sequence[Fault]) -> Outcome | None:
        nonlocal runs
        runs += 1
        outcome = run(scenario, failing.seed, faults)
        same = outcome.violation is not None and outcome.violation.name == wanted
        return outcome if same else None

    faults = list(failing.faults)
    best = still_fails(faults)
    if best is None:
        raise RuntimeError(
            "replaying the recorded faults did not reproduce the failure; "
            "the scenario is drawing randomness the simulator cannot see"
        )

    pieces = 2
    while len(faults) >= 2:
        size = max(1, len(faults) // pieces)
        removed = False
        for start in range(0, len(faults), size):
            candidate = faults[:start] + faults[start + size :]
            outcome = still_fails(candidate)
            if outcome is not None:
                faults, best = candidate, outcome
                pieces = max(2, pieces - 1)
                removed = True
                break
        if not removed:
            if size == 1:
                break
            pieces = min(len(faults), pieces * 2)

    # One last check that nothing left is a passenger.
    if len(faults) == 1:
        outcome = still_fails([])
        if outcome is not None:
            faults, best = [], outcome
    return Shrunk(tuple(faults), best, runs)
