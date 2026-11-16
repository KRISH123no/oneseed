"""Run a scenario once, from a seed, and say what happened.

A scenario is a small distributed system and the property it must never
break. `build` wires it onto a simulator; everything else — the clock, the
network, the faults — is supplied here, so that every scenario gets the same
three guarantees:

  the same seed gives the same run, to the last trace line;
  the faults that fired are handed back as a list;
  that list, replayed against the same seed, gives the same run again.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .faults import Fault
from .sim import InvariantViolation, Simulator
from .trace import Trace

#: Wire a system onto the simulator. Given the faults to script (or None to
#: sample them), return a function that reports the faults that fired.
Build = Callable[[Simulator, Sequence[Fault] | None], Callable[[], list[Fault]]]


@dataclass(frozen=True)
class Scenario:
    name: str
    summary: str
    build: Build
    #: How long to run, in ticks.
    until: int


@dataclass(frozen=True)
class Outcome:
    seed: int
    violation: InvariantViolation | None
    #: The faults that actually fired, in the order they did.
    faults: tuple[Fault, ...]
    trace: Trace

    @property
    def failed(self) -> bool:
        return self.violation is not None

    @property
    def digest(self) -> str:
        return self.trace.digest


def run(scenario: Scenario, seed: int, faults: Sequence[Fault] | None = None) -> Outcome:
    """One run. With `faults`, they are replayed; without, they are sampled."""
    sim = Simulator(seed)
    observed = scenario.build(sim, faults)
    violation: InvariantViolation | None = None
    try:
        sim.run(scenario.until)
    except InvariantViolation as error:
        violation = error
    return Outcome(seed, violation, tuple(observed()), sim.trace)


def search(scenario: Scenario, seeds: Sequence[int]) -> list[Outcome]:
    """Every seed in the range that breaks the scenario's invariant."""
    return [outcome for outcome in (run(scenario, seed) for seed in seeds) if outcome.failed]
