"""A lease-based lock, with a bug that only a slow network reveals.

This is the smallest honest version of a mistake that has taken down real
systems. A server hands out a lease on a lock: yours until time T, and after T
I may give it to somebody else. The client has to know when to stop, and there
are two ways to work that out.

The careful-looking way is to count from the moment the grant arrives. A lease
is fifty ticks, so: fifty ticks from now, less ten for the network. That holds
right up until the grant itself is slow, because the server started counting
when it sent the reply and the client starts counting when it reads it. The gap
between those two moments is time the client believes it owns the lock and the
server has already given it away.

The fix is one line: believe the deadline the server put in the message.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..faults import Fault
from ..net import Network
from ..run import Scenario
from ..sim import Simulator

LEASE = 50  # how long the server honours a lease
MARGIN = 10  # the client's allowance for the network
POLL = 10  # how often a client without the lock asks for it
SERVER = 0
CLIENTS = (1, 2)


@dataclass(frozen=True)
class Request:
    sender: int


@dataclass(frozen=True)
class Granted:
    expires_at: int


@dataclass(frozen=True)
class Denied:
    pass


class Server:
    def __init__(self, sim: Simulator, net: Network) -> None:
        self.sim = sim
        self.net = net
        self.holder: int | None = None
        self.expires_at = 0

    def receive(self, message: Any) -> None:
        if not isinstance(message, Request):
            return
        now = self.sim.now
        if self.holder is None or now >= self.expires_at:
            self.holder = message.sender
            self.expires_at = now + LEASE
            self.sim.trace.add(now, "grant", f"client {self.holder} until {self.expires_at}")
            self.net.send(SERVER, message.sender, Granted(self.expires_at))
        else:
            self.net.send(SERVER, message.sender, Denied())


class Client:
    def __init__(self, sim: Simulator, net: Network, ident: int, *, fixed: bool) -> None:
        self.sim = sim
        self.net = net
        self.ident = ident
        self.fixed = fixed
        self.holds_until = 0
        self.waiting = False

    @property
    def holding(self) -> bool:
        return self.sim.now < self.holds_until

    def poll(self) -> None:
        if self.holding or self.waiting:
            return
        self.waiting = True
        self.net.send(self.ident, SERVER, Request(self.ident))

    def receive(self, message: Any) -> None:
        self.waiting = False
        if not isinstance(message, Granted):
            return
        if self.fixed:
            self.holds_until = message.expires_at
        else:
            # The bug. Both halves of "fifty ticks from now, less ten for the
            # network" are wrong when the reply itself took thirty.
            self.holds_until = self.sim.now + LEASE - MARGIN
        self.sim.trace.add(self.sim.now, "acquire", f"client {self.ident} until {self.holds_until}")


def _build(fixed: bool):
    def build(sim: Simulator, faults: Sequence[Fault] | None):
        nodes: dict[int, Any] = {}
        net = Network(
            sim,
            lambda target, message: nodes[target].receive(message),
            delay_rate=0.02,
            faults=faults,
        )
        nodes[SERVER] = Server(sim, net)
        clients = [Client(sim, net, ident, fixed=fixed) for ident in CLIENTS]
        for client in clients:
            nodes[client.ident] = client
            sim.every(POLL, client.poll, f"poll {client.ident}")

        def one_holder() -> str | None:
            holding = [client.ident for client in clients if client.holding]
            if len(holding) > 1:
                return f"clients {holding} both believe they hold the lock"
            return None

        sim.invariant("at most one lock holder", one_holder)
        return lambda: list(net.observed)

    return build


LEASE_BUGGY = Scenario(
    "lease",
    "a lock lease whose client counts from when the grant arrived",
    _build(fixed=False),
    until=600,
)
LEASE_FIXED = Scenario(
    "lease-fixed",
    "the same lock, with the client believing the server's deadline",
    _build(fixed=True),
    until=600,
)
