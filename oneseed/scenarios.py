"""The scenarios the command line knows by name."""

from __future__ import annotations

from .examples.lease import LEASE_BUGGY, LEASE_FIXED
from .examples.raft import FIGURE_8_HUNT, RAFT, RAFT_HUNT, RAFT_MUTANTS
from .run import Scenario

SCENARIOS: dict[str, Scenario] = {
    s.name: s
    for s in (LEASE_BUGGY, LEASE_FIXED, RAFT, *RAFT_MUTANTS.values(), RAFT_HUNT, FIGURE_8_HUNT)
}
