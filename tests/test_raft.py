import inspect

import pytest

pytest.importorskip("raftlab", reason="the Raft scenarios need raftlab")

from oneseed import run, search, shrink  # noqa: E402
from oneseed.examples.raft import FIGURE_8_HUNT, MUTATIONS, RAFT, RAFT_MUTANTS  # noqa: E402

SEEDS = range(40)


def test_every_edit_still_applies_to_raftlab_exactly_once():
    import raftlab.node

    source = inspect.getsource(raftlab.node)
    for mutation in MUTATIONS.values():
        assert source.count(mutation.remove) == 1, mutation.name


def test_raft_as_written_breaks_nothing():
    assert search(RAFT, SEEDS) == []


def test_a_run_is_a_seed_even_with_crashes_and_partitions():
    first, second = run(RAFT, 11), run(RAFT, 11)
    assert first.digest == second.digest
    assert any(f.kind == "crash" for f in first.faults)
    assert any(f.kind == "partition" for f in first.faults)
    assert run(RAFT, 11, first.faults).digest == first.digest


@pytest.mark.parametrize(
    ("mutant", "invariant"),
    [("votes-twice", "election safety"), ("votes-for-stale-log", "commit agreement")],
)
def test_a_removed_guard_is_caught_by_the_property_it_protected(mutant, invariant):
    failing = search(RAFT_MUTANTS[mutant], SEEDS)
    assert failing, f"{mutant} was not caught in {len(SEEDS)} seeds"
    assert invariant in {o.violation.name for o in failing}


def test_a_raft_failure_shrinks_and_every_fault_left_is_needed():
    scenario = RAFT_MUTANTS["votes-twice"]
    failing = search(scenario, SEEDS)[0]
    assert run(scenario, failing.seed, failing.faults).digest == failing.digest
    shrunk = shrink(scenario, failing)
    assert len(shrunk.faults) < len(failing.faults)
    for fault in shrunk.faults:
        without = [f for f in shrunk.faults if f is not fault]
        again = run(scenario, failing.seed, without)
        assert again.violation is None or again.violation.name != failing.violation.name


def test_figure_8_is_reproduced_by_its_seed_and_shrinks_to_a_handful():
    # The bug the Raft paper needs a figure for. Plain random faults did not
    # find it in 6,000 seeds; this seed, from a fault mix aimed at the leader,
    # does, and the entry it loses is one a later leader committed by counting.
    failing = run(FIGURE_8_HUNT, 13374)
    assert failing.violation is not None
    assert failing.violation.name == "commit agreement"
    assert "(1:'cmd2')" in failing.violation.detail
    assert run(FIGURE_8_HUNT, 13374, failing.faults).digest == failing.digest
    shrunk = shrink(FIGURE_8_HUNT, failing)
    assert len(shrunk.faults) <= 8
    assert {fault.kind for fault in shrunk.faults} == {"crash", "partition"}
