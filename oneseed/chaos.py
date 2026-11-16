"""Power cuts and network splits, on the same terms as message faults.

Every `period` ticks the dice decide whether a node loses power or the network
is cut in two, and for how long. A crash and its restart are one fault, as are
a partition and its healing: removing "the crash" while keeping "the restart"
would be a run that never happened to anything.

As in net.py, the dice are thrown identically whether the faults are being
sampled or replayed from a script.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from .faults import TIMED, Fault
from .net import Network
from .sim import Simulator


class Chaos:
    def __init__(
        self,
        sim: Simulator,
        net: Network,
        nodes: Sequence[int],
        *,
        crash: Callable[[int], None],
        restart: Callable[[int], None],
        period: int = 400,
        crash_rate: float = 0.0,
        partition_rate: float = 0.0,
        duration: tuple[int, int] = (300, 900),
        aim: Callable[[], int | None] | None = None,
        aim_rate: float = 0.0,
        faults: Sequence[Fault] | None = None,
    ) -> None:
        self.sim = sim
        self.net = net
        self.nodes = list(nodes)
        self._crash = crash
        self._restart = restart
        self.crash_rate = crash_rate
        self.partition_rate = partition_rate
        self.duration = duration
        #: Picks a node worth crashing — the leader, say — and how often to
        #: crash that one instead of a random one.
        self.aim = aim
        self.aim_rate = aim_rate
        self.scripted = faults is not None
        self.observed: list[Fault] = []
        self.down: set[int] = set()
        # Scripted faults are applied from inside the same periodic event that
        # sampled them, so they fall in the same place among the other events
        # of that tick. Scheduling them separately would move them by a hair,
        # and a hair is enough to change a run.
        self.script: dict[int, list[Fault]] = {}
        for fault in faults or ():
            if fault.kind in TIMED:
                self.script.setdefault(fault.at, []).append(fault)
        if crash_rate > 0 or partition_rate > 0:
            sim.every(period, self._roll, "chaos")

    def _roll(self) -> None:
        rng = self.sim.rng
        roll = rng.random()
        node = rng.choice(self.nodes)
        size = rng.randint(1, max(1, len(self.nodes) // 2))
        group = tuple(sorted(rng.sample(self.nodes, size)))
        ticks = rng.randint(*self.duration)
        aimed = rng.random() < self.aim_rate
        if self.scripted:
            for fault in self.script.get(self.sim.now, ()):
                self._apply(fault)
            return
        if roll < self.crash_rate:
            target = self.aim() if aimed and self.aim is not None else None
            node = node if target is None else target
            self._apply(Fault("crash", at=self.sim.now, node=node, ticks=ticks))
        elif roll < self.crash_rate + self.partition_rate:
            self._apply(Fault("partition", at=self.sim.now, group=group, ticks=ticks))

    def _apply(self, fault: Fault) -> None:
        if fault.kind == "crash":
            # One power cut at a time per node, and never the whole cluster's
            # worth at once: a majority that is switched off proves nothing.
            if fault.node in self.down or len(self.down) + 1 > (len(self.nodes) - 1) // 2:
                return
            self.observed.append(fault)
            self.down.add(fault.node)
            self.sim.trace.add(self.sim.now, "crash", f"node {fault.node} for {fault.ticks}")
            self._crash(fault.node)

            def back() -> None:
                self.down.discard(fault.node)
                self.sim.trace.add(self.sim.now, "restart", f"node {fault.node}")
                self._restart(fault.node)

            self.sim.schedule(fault.ticks, back, f"restart {fault.node}")
        else:
            if self.net.cut is not None:
                return
            self.observed.append(fault)
            self.net.cut = frozenset(fault.group)
            self.sim.trace.add(self.sim.now, "partition", f"{list(fault.group)} for {fault.ticks}")

            def heal() -> None:
                self.net.cut = None
                self.sim.trace.add(self.sim.now, "heal")

            self.sim.schedule(fault.ticks, heal, "heal")
