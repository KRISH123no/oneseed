"""Raft under simulation: `raftlab`'s nodes, this simulator's faults.

`raftlab` is a Raft implementation whose nodes are pure state machines — they
are told the time and handed messages, and they answer with messages. That
makes it the easy case, and the right first one: nothing has to be mocked.

As written, it passes. So this file also breaks it. Three guards from the Raft
paper are taken out, one at a time, by editing the node's source before it is
loaded, and each edit is a bug the paper warns about by name. A simulator that
cannot find a known bug has no business being trusted to find an unknown one.

The edits are done on the source text and each must match exactly once. If
`raftlab` changes so that one no longer applies, loading the scenario fails
loudly instead of silently testing the unbroken code.
"""

from __future__ import annotations

import inspect
import random
import sys
import types
from collections.abc import Sequence
from dataclasses import dataclass

from ..chaos import Chaos
from ..faults import Fault
from ..net import Network
from ..run import Scenario
from ..sim import Simulator

SIZE = 5
TICK = 10
PROPOSE_EVERY = 120
UNTIL = 8000


@dataclass(frozen=True)
class Mutation:
    name: str
    #: What the paper calls it, and where.
    paper: str
    summary: str
    remove: str
    insert: str


MUTATIONS = {
    m.name: m
    for m in (
        Mutation(
            "commits-old-terms",
            "§5.4.2, figure 8",
            "a leader commits an entry from an earlier term by counting replicas",
            "            if self.term_at(index) != self.current_term:\n                continue\n",
            "",
        ),
        Mutation(
            "votes-twice",
            "§5.2, election safety",
            "a node votes for a second candidate in a term it has already voted in",
            " and self.state.voted_for in (None, message.sender)",
            "",
        ),
        Mutation(
            "votes-for-stale-log",
            "§5.4.1, the election restriction",
            "a node votes for a candidate whose log is behind its own",
            "            if up_to_date:\n",
            "            if up_to_date or True:\n",
        ),
    )
}


def _node_class(mutation: str | None):
    try:
        import raftlab.node as original
    except ImportError as error:
        raise SystemExit(
            'The Raft scenarios need raftlab: pip install "oneseed[raft]", '
            "or put a checkout of it on PYTHONPATH."
        ) from error
    if mutation is None:
        return original.RaftNode
    edit = MUTATIONS[mutation]
    source = inspect.getsource(original)
    if source.count(edit.remove) != 1:
        raise RuntimeError(
            f"the {mutation} edit no longer applies to raftlab/node.py; "
            "the guard it removes has moved or changed"
        )
    name = f"raftlab._oneseed_{mutation.replace('-', '_')}"
    module = types.ModuleType(name)
    module.__package__ = "raftlab"
    sys.modules[name] = module
    exec(
        compile(source.replace(edit.remove, edit.insert), f"<raftlab.node, {mutation}>", "exec"),
        module.__dict__,
    )  # noqa: S102
    return module.RaftNode


def _build(mutation: str | None, *, hunt_leader: bool = False):
    def build(sim: Simulator, faults: Sequence[Fault] | None):
        from raftlab.checker import InvariantViolation as RaftViolation
        from raftlab.checker import SafetyChecker
        from raftlab.types import Role

        node_class = _node_class(mutation)
        ids = list(range(SIZE))
        nodes = {
            ident: node_class(ident, ids, rng=random.Random(sim.rng.getrandbits(64)))
            for ident in ids
        }

        def deliver(target: int, message) -> None:
            for reply in nodes[target].receive(message, sim.now):
                net.send(reply.sender, reply.recipient, reply)

        net = Network(
            sim,
            deliver,
            latency=(5, 20),
            drop_rate=0.03,
            duplicate_rate=0.02,
            delay_rate=0.01,
            delay_ticks=(40, 160),
            faults=faults,
        )

        def leader() -> int | None:
            for node in nodes.values():
                if not node.crashed and node.role is Role.LEADER:
                    return node.id
            return None

        if hunt_leader:
            # Random faults rarely take out a leader in the few ticks between
            # accepting a write and replicating it, and that window is where
            # the subtle Raft bugs live. So: crash often, briefly, and mostly
            # whoever is in charge.
            chaos = Chaos(
                sim, net, ids,
                crash=lambda ident: nodes[ident].crash(),
                restart=lambda ident: nodes[ident].restart(sim.now),
                period=130, crash_rate=0.35, partition_rate=0.35, duration=(150, 500),
                aim=leader, aim_rate=0.8, faults=faults,
            )  # fmt: skip
        else:
            chaos = Chaos(
                sim, net, ids,
                crash=lambda ident: nodes[ident].crash(),
                restart=lambda ident: nodes[ident].restart(sim.now),
                crash_rate=0.3, partition_rate=0.3, faults=faults,
            )  # fmt: skip
        for node in nodes.values():
            node.start(sim.now)

        def tick() -> None:
            for node in nodes.values():
                for message in node.tick(sim.now):
                    net.send(message.sender, message.recipient, message)

        proposed = 0

        def propose() -> None:
            nonlocal proposed
            # Every node that believes it is leader gets a write. A deposed
            # leader that has not heard the news is exactly who should be tested.
            for node in nodes.values():
                if not node.crashed and node.role is Role.LEADER:
                    proposed += 1
                    node.propose(f"cmd{proposed}")

        sim.every(TICK, tick, "tick")
        sim.every(PROPOSE_EVERY, propose, "propose")

        checker = SafetyChecker()

        def guard(check):
            def run() -> str | None:
                try:
                    check(nodes, sim.now)
                except RaftViolation as violation:
                    return str(violation)
                return None

            return run

        sim.invariant("election safety", guard(checker.check_election_safety))
        sim.invariant("log matching", guard(checker.check_log_matching))
        sim.invariant("commit agreement", guard(checker.check_commit_agreement))
        sim.invariant("state machine safety", guard(checker.check_state_machine_safety))
        return lambda: sorted(net.observed + chaos.observed, key=_order)

    return build


def _order(fault: Fault) -> tuple:
    return (fault.kind, fault.at, fault.source, fault.target, fault.message, fault.nth)


RAFT_HUNT = Scenario(
    "raft-leader-hunt",
    "raftlab as written, with crashes aimed at whoever is leader",
    _build(None, hunt_leader=True),
    UNTIL,
)
FIGURE_8_HUNT = Scenario(
    "raft-commits-old-terms-leader-hunt",
    "the figure 8 bug again, with crashes aimed at whoever is leader",
    _build("commits-old-terms", hunt_leader=True),
    UNTIL,
)
RAFT = Scenario(
    "raft", "raftlab as written: five nodes, crashes, partitions, lossy links", _build(None), UNTIL
)
RAFT_MUTANTS = {
    name: Scenario(
        f"raft-{name}",
        f"raftlab with one guard removed: {m.summary} ({m.paper})",
        _build(name),
        UNTIL,
    )
    for name, m in MUTATIONS.items()
}
