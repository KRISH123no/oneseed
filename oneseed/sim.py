"""One clock, one event queue, one seed.

Nothing in a simulated system is allowed its own source of time or randomness.
Timers become events on this queue and every coin flip comes from this
generator, which is the whole trick: the schedule of a run is a function of
the seed, so a failure has a name you can type back in.

Invariants are checked after every single event rather than at the end. A
distributed bug is usually a window a few ticks wide that closes again before
the run finishes, and a check at the end never sees it.
"""

from __future__ import annotations

import heapq
import random
from collections.abc import Callable
from dataclasses import dataclass, field

from .trace import Trace


class InvariantViolation(Exception):
    """An invariant failed. Carries enough to reproduce and to report."""

    def __init__(self, name: str, detail: str, at: int, seed: int) -> None:
        super().__init__(f"{name} violated at t={at} (seed={seed}): {detail}")
        self.name = name
        self.detail = detail
        self.at = at
        self.seed = seed


@dataclass(order=True)
class _Event:
    at: int
    sequence: int
    run: Callable[[], None] = field(compare=False)
    label: str = field(compare=False, default="")


class Simulator:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.rng = random.Random(seed)
        self.trace = Trace()
        self.now = 0
        self._queue: list[_Event] = []
        self._sequence = 0
        self._invariants: list[tuple[str, Callable[[], str | None]]] = []

    # ---------------------------------------------------------------- timers

    def schedule(self, delay: int, run: Callable[[], None], label: str = "") -> None:
        if delay < 0:
            raise ValueError("cannot schedule into the past")
        self._sequence += 1
        heapq.heappush(self._queue, _Event(self.now + delay, self._sequence, run, label))

    def every(self, period: int, run: Callable[[], None], label: str = "") -> None:
        """A repeating timer. Reschedules itself, so it stays on the one queue."""

        def fire() -> None:
            run()
            self.schedule(period, fire, label)

        self.schedule(period, fire, label)

    # ------------------------------------------------------------ invariants

    def invariant(self, name: str, check: Callable[[], str | None]) -> None:
        """`check` returns None when the property holds, or why it does not."""
        self._invariants.append((name, check))

    # ------------------------------------------------------------------- run

    def run(self, until: int) -> Simulator:
        while self._queue and self._queue[0].at <= until:
            event = heapq.heappop(self._queue)
            self.now = event.at
            event.run()
            self._check()
        self.now = until
        return self

    def _check(self) -> None:
        for name, check in self._invariants:
            detail = check()
            if detail is not None:
                self.trace.add(self.now, "VIOLATION", f"{name}: {detail}")
                raise InvariantViolation(name, detail, self.now, self.seed)
