import pytest

from oneseed import Fault, Scenario, run, search, shrink
from oneseed.examples.lease import LEASE_BUGGY, LEASE_FIXED
from oneseed.net import Network

SEEDS = range(120)


def test_the_bug_shows_on_some_seeds_and_not_on_others():
    failing = search(LEASE_BUGGY, SEEDS)
    assert 0 < len(failing) < len(SEEDS)
    assert {o.violation.name for o in failing} == {"at most one lock holder"}


def test_the_fix_survives_every_seed_the_bug_failed_on():
    assert search(LEASE_FIXED, SEEDS) == []


def test_a_seed_is_a_run():
    for seed in (0, 4, 9, 77):
        first, second = run(LEASE_BUGGY, seed), run(LEASE_BUGGY, seed)
        assert first.digest == second.digest
        assert first.faults == second.faults
    assert run(LEASE_BUGGY, 4).digest != run(LEASE_BUGGY, 5).digest


def test_the_recorded_faults_replay_to_the_identical_trace():
    for outcome in search(LEASE_BUGGY, SEEDS)[:10]:
        replayed = run(LEASE_BUGGY, outcome.seed, outcome.faults)
        assert replayed.digest == outcome.digest
        assert str(replayed.violation) == str(outcome.violation)


def test_shrinking_leaves_only_faults_that_are_needed():
    for outcome in search(LEASE_BUGGY, SEEDS)[:10]:
        shrunk = shrink(LEASE_BUGGY, outcome)
        assert shrunk.outcome.failed
        assert 1 <= len(shrunk.faults) <= len(outcome.faults)
        for fault in shrunk.faults:
            without = [f for f in shrunk.faults if f is not fault]
            assert not run(LEASE_BUGGY, outcome.seed, without).failed
        # This bug is a slow grant. Sometimes a second delay is needed to line
        # the other client up, but there is always a late grant among them.
        assert all(f.kind == "delay" for f in shrunk.faults)
        assert any(f.message == "Granted" for f in shrunk.faults)


def test_the_bug_needs_the_network_to_misbehave():
    for seed in SEEDS:
        assert not run(LEASE_BUGGY, seed, faults=[]).failed


def _needs_two(sim, faults):
    """Fails only when message 3 and message 7 are both dropped."""
    got: set[int] = set()
    net = Network(sim, lambda target, message: got.add(message), drop_rate=0.4, faults=faults)
    for n in range(12):
        sim.schedule(n, lambda n=n: net.send(0, 1, n))
    sim.invariant(
        "3 or 7 arrives", lambda: "neither did" if sim.now >= 40 and not got & {3, 7} else None
    )
    sim.every(40, lambda: None)
    return lambda: list(net.observed)


def test_shrinking_finds_the_two_faults_that_matter_among_many():
    scenario = Scenario("two", "needs two drops", _needs_two, until=60)
    failing = next(o for o in search(scenario, range(200)) if len(o.faults) >= 5)
    shrunk = shrink(scenario, failing)
    assert shrunk.faults == (Fault("drop", 0, 1, "int", 3), Fault("drop", 0, 1, "int", 7))
    assert shrunk.runs < 40


def test_shrinking_a_run_that_passed_is_an_error():
    passing = next(o for o in (run(LEASE_BUGGY, s) for s in SEEDS) if not o.failed)
    with pytest.raises(ValueError, match="did not fail"):
        shrink(LEASE_BUGGY, passing)
