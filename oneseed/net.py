"""A network that misbehaves on purpose and on the record.

Two modes, and the difference between them is the point of the project.

*Sampled.* Each message is rolled against the fault rates. Every fault that
actually fires is appended to `observed`, so a failing run hands back the list
of things that went wrong instead of a rate and a shrug.

*Scripted.* The same dice are still thrown, in the same order, and then
ignored: what happens to each message comes from a list. Throwing them anyway
is what makes a script faithful. Replay the full list from a failing run and
every latency lands where it did the first time — the trace is identical, byte
for byte — and taking one fault out changes only what that fault caused.

Connectivity is checked when a message arrives, not when it is sent, so cutting
the network also loses whatever was already in flight across the cut. That is
the harsher of the two choices and the one real networks make. The idea is
`raftlab`'s, where it found more bugs than the other way round.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from .faults import MESSAGE, Fault
from .sim import Simulator

Inbox = Callable[[int, Any], None]


class Network:
    def __init__(
        self,
        sim: Simulator,
        inbox: Inbox,
        *,
        latency: tuple[int, int] = (2, 6),
        drop_rate: float = 0.0,
        duplicate_rate: float = 0.0,
        delay_rate: float = 0.0,
        delay_ticks: tuple[int, int] = (30, 80),
        faults: Sequence[Fault] | None = None,
    ) -> None:
        self.sim = sim
        self.inbox = inbox
        self.latency = latency
        self.drop_rate = drop_rate
        self.duplicate_rate = duplicate_rate
        self.delay_rate = delay_rate
        self.delay_ticks = delay_ticks
        self.scripted = faults is not None
        self.script = {f.key: f for f in (faults or ()) if f.kind in MESSAGE}
        self.observed: list[Fault] = []
        #: The nodes on the far side of the current cut, if there is one.
        self.cut: frozenset[int] | None = None
        self.sent = 0
        self.delivered = 0
        self._counts: dict[tuple[int, int, str], int] = {}

    # ---------------------------------------------------------- connectivity

    def connected(self, a: int, b: int) -> bool:
        return self.cut is None or (a in self.cut) == (b in self.cut)

    # ----------------------------------------------------------------- send

    def send(self, source: int, target: int, message: Any) -> None:
        name = type(message).__name__
        pair = (source, target, name)
        nth = self._counts.get(pair, 0)
        self._counts[pair] = nth + 1
        self.sent += 1

        # The dice, thrown the same way in both modes.
        rng = self.sim.rng
        roll = rng.random()
        sampled: Fault | None = None
        if roll < self.drop_rate:
            sampled = Fault("drop", source, target, name, nth)
        elif roll < self.drop_rate + self.duplicate_rate:
            sampled = Fault("duplicate", source, target, name, nth)
        elif roll < self.drop_rate + self.duplicate_rate + self.delay_rate:
            sampled = Fault(
                "delay", source, target, name, nth, ticks=rng.randint(*self.delay_ticks)
            )
        latency = rng.randint(*self.latency)
        again = rng.randint(*self.latency)

        fault = self.script.get((source, target, name, nth)) if self.scripted else sampled
        label = f"{name} {source}->{target} #{nth}"
        if fault is not None:
            self.observed.append(fault)

        if fault is not None and fault.kind == "drop":
            self.sim.trace.add(self.sim.now, "drop", label)
            return
        if fault is not None and fault.kind == "delay":
            latency += fault.ticks
            self.sim.trace.add(self.sim.now, "delay", f"{label} by {fault.ticks}")
        self.sim.trace.add(self.sim.now, "send", f"{label} in {latency}")
        self._arrive_in(latency, source, target, message, label)
        if fault is not None and fault.kind == "duplicate":
            self.sim.trace.add(self.sim.now, "duplicate", f"{label} in {again}")
            self._arrive_in(again, source, target, message, label)

    def _arrive_in(self, delay: int, source: int, target: int, message: Any, label: str) -> None:
        def arrive() -> None:
            if not self.connected(source, target):
                self.sim.trace.add(self.sim.now, "cut", label)
                return
            self.delivered += 1
            self.sim.trace.add(self.sim.now, "deliver", label)
            self.inbox(target, message)

        self.sim.schedule(delay, arrive, f"deliver {label}")
