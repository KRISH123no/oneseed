from dataclasses import dataclass

from oneseed import Fault, Network, Simulator
from oneseed.chaos import Chaos


@dataclass(frozen=True)
class Ping:
    n: int


def world(seed: int = 1, **options):
    sim = Simulator(seed)
    got: list[tuple[int, int, int]] = []
    net = Network(sim, lambda target, message: got.append((sim.now, target, message.n)), **options)
    return sim, net, got


def test_a_quiet_network_delivers_everything_once():
    sim, net, got = world()
    for n in range(20):
        net.send(0, 1, Ping(n))
    sim.run(100)
    assert sorted(n for _, _, n in got) == list(range(20))
    assert net.observed == []


def test_a_dropped_message_never_arrives_and_is_written_down():
    sim, net, got = world(drop_rate=1.0)
    net.send(0, 1, Ping(0))
    net.send(0, 1, Ping(1))
    sim.run(100)
    assert got == []
    assert net.observed == [Fault("drop", 0, 1, "Ping", 0), Fault("drop", 0, 1, "Ping", 1)]


def test_a_duplicated_message_arrives_twice():
    sim, net, got = world(duplicate_rate=1.0)
    net.send(0, 1, Ping(5))
    sim.run(100)
    assert [n for _, _, n in got] == [5, 5]


def test_a_delayed_message_arrives_late_by_what_the_fault_says():
    sim, net, got = world(delay_rate=1.0, delay_ticks=(40, 40))
    net.send(0, 1, Ping(0))
    sim.run(200)
    assert net.observed[0].ticks == 40
    assert 42 <= got[0][0] <= 46


def test_messages_between_a_pair_are_numbered_per_type():
    sim, net, _ = world(drop_rate=1.0)
    net.send(0, 1, Ping(0))
    net.send(2, 1, Ping(0))
    net.send(0, 1, Ping(0))
    assert [(f.source, f.nth) for f in net.observed] == [(0, 0), (2, 0), (0, 1)]


def test_a_script_does_exactly_what_it_says_and_nothing_else():
    script = [Fault("drop", 0, 1, "Ping", 1), Fault("delay", 0, 1, "Ping", 3, ticks=50)]
    # The rates say drop everything; the script overrules them.
    sim, net, got = world(drop_rate=1.0, faults=script)
    for n in range(5):
        net.send(0, 1, Ping(n))
    sim.run(200)
    assert sorted(n for _, _, n in got) == [0, 2, 3, 4]
    assert max(got)[2] == 3  # the delayed one arrives last
    assert net.observed == script


def test_replaying_the_recorded_faults_gives_the_identical_trace():
    def play(faults=None):
        sim, net, _ = world(
            seed=42, drop_rate=0.2, duplicate_rate=0.1, delay_rate=0.1, faults=faults
        )
        for n in range(60):
            sim.schedule(n * 3, lambda n=n: net.send(n % 3, (n + 1) % 3, Ping(n)))
        sim.run(500)
        return sim.trace.digest, list(net.observed)

    digest, observed = play()
    assert observed, "the rates should have produced some faults"
    assert play(observed) == (digest, observed)
    # And an empty script is a different, fault-free run.
    assert play([])[0] != digest


def test_cutting_the_network_loses_what_was_already_in_flight():
    sim, net, got = world(latency=(10, 10))
    net.send(0, 1, Ping(0))
    net.send(0, 2, Ping(1))
    sim.schedule(5, lambda: setattr(net, "cut", frozenset({1})))
    sim.run(50)
    assert [target for _, target, _ in got] == [2]
    assert not net.connected(0, 1) and net.connected(0, 2)


def chaotic(seed: int, faults=None):
    sim = Simulator(seed)
    net = Network(sim, lambda target, message: None)
    log: list[tuple[int, str, int]] = []
    chaos = Chaos(
        sim, net, [0, 1, 2, 3, 4],
        crash=lambda n: log.append((sim.now, "crash", n)),
        restart=lambda n: log.append((sim.now, "restart", n)),
        period=100, crash_rate=0.5, partition_rate=0.3, duration=(150, 400), faults=faults,
    )  # fmt: skip
    sim.run(5000)
    return sim, chaos, log


def test_every_crash_is_followed_by_its_restart_and_a_majority_stays_up():
    _, chaos, log = chaotic(3)
    down: set[int] = set()
    for _, what, node in log:
        if what == "crash":
            assert node not in down
            down.add(node)
            assert len(down) <= 2
        else:
            down.remove(node)
    assert any(f.kind == "crash" for f in chaos.observed)
    assert any(f.kind == "partition" for f in chaos.observed)


def test_timed_faults_replay_identically_from_a_script():
    sim, chaos, log = chaotic(3)
    again, replayed, relog = chaotic(3, chaos.observed)
    assert again.trace.digest == sim.trace.digest
    assert replayed.observed == chaos.observed and relog == log
    quiet, none, _ = chaotic(3, [])
    assert none.observed == [] and quiet.trace.digest != sim.trace.digest
