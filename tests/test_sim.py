import pytest

from oneseed import InvariantViolation, Simulator


def test_events_run_in_time_order_and_ties_run_in_the_order_they_were_scheduled():
    sim = Simulator(1)
    seen: list[str] = []
    sim.schedule(5, lambda: seen.append("b"))
    sim.schedule(2, lambda: seen.append("a"))
    sim.schedule(5, lambda: seen.append("c"))
    sim.run(10)
    assert seen == ["a", "b", "c"]
    assert sim.now == 10


def test_nothing_past_the_horizon_runs():
    sim = Simulator(1)
    seen: list[int] = []
    sim.schedule(5, lambda: seen.append(5))
    sim.schedule(11, lambda: seen.append(11))
    sim.run(10)
    assert seen == [5]


def test_a_repeating_timer_keeps_firing():
    sim = Simulator(1)
    ticks: list[int] = []
    sim.every(10, lambda: ticks.append(sim.now))
    sim.run(45)
    assert ticks == [10, 20, 30, 40]


def test_an_event_can_schedule_another_at_the_same_instant():
    sim = Simulator(1)
    seen: list[str] = []
    sim.schedule(3, lambda: (seen.append("first"), sim.schedule(0, lambda: seen.append("second"))))
    sim.run(3)
    assert seen == ["first", "second"]


def test_the_past_cannot_be_scheduled():
    with pytest.raises(ValueError, match="past"):
        Simulator(1).schedule(-1, lambda: None)


def test_an_invariant_is_checked_after_every_event_and_stops_the_run():
    sim = Simulator(7)
    count = {"n": 0}
    sim.every(1, lambda: count.__setitem__("n", count["n"] + 1))
    sim.invariant("small", lambda: "too big" if count["n"] >= 3 else None)
    with pytest.raises(InvariantViolation) as caught:
        sim.run(100)
    assert (caught.value.name, caught.value.at, caught.value.seed) == ("small", 3, 7)
    assert count["n"] == 3
    assert sim.trace.lines[-1].endswith("small: too big")


def test_the_same_seed_draws_the_same_numbers():
    assert [Simulator(9).rng.random() for _ in range(3)] == [
        Simulator(9).rng.random() for _ in range(3)
    ]
    assert Simulator(9).rng.random() != Simulator(10).rng.random()
