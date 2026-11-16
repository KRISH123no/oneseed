# oneseed

[![CI](https://github.com/KRISH123no/oneseed/actions/workflows/ci.yml/badge.svg)](https://github.com/KRISH123no/oneseed/actions/workflows/ci.yml)

**A distributed system's worst day, replayed from one integer — and then cut down to the two
things that actually went wrong.**

```
$ oneseed search lease
lease: 37 of 200 seeds fail  (0.3s)
  at most one lock holder: 37 — seeds 4, 9, 13, 15, 18, 20, 25, 37, 39, 42, 44, 46 …

$ oneseed shrink lease 13
lease, seed 13
  at most one lock holder violated at t=590 (seed=13): clients [1, 2] both believe they hold the lock
  2 faults fired; replaying them from a list gives the identical trace
  shrunk to 2 in 3 replays.
  Every one of these is needed:

    Request #7 from 1 to 0 held for 49 extra ticks
    Granted #7 from 0 to 1 held for 58 extra ticks

   585  grant        client 2 until 635
   585  send         Granted 0->2 #3 in 5
   588  deliver      Granted 0->1 #7
   588  acquire      client 1 until 628
   590  deliver      Granted 0->2 #3
   590  acquire      client 2 until 630
   590  VIOLATION    at most one lock holder: clients [1, 2] both believe they hold the lock
```

The bugs that matter in distributed code are the ones you cannot reproduce. They need a message
to be late by a particular amount at a particular moment, they show up once in a CI run, and
then they are gone. This is the technique FoundationDB and TigerBeetle use against that: run the
whole system inside a simulator that owns the clock, the network and every source of randomness,
so that a run is a pure function of one number. A failure stops being "it broke once" and becomes
`seed=13`.

No dependencies. The simulator is about 550 lines.

## Three things it promises, and how each is checked

**The same seed gives the same run.** Not the same outcome — the same trace, line for line. Every
run keeps a log of each send, delivery, fault and state change, and `replay` runs the seed twice
and compares the hash of the two logs. If they differ it says `NOT DETERMINISTIC` and exits 3,
because then nothing else it reports is worth anything.

**The faults that fired are handed back as a list, and the list replays the run.** A rate is not
a bug report. "Two per cent of messages were delayed" cannot be re-run, made smaller or read.
"`Granted #7 from 0 to 1 held for 58 extra ticks`" can. When that list is fed back in with the
seed, the trace hash is identical to the original — tested on the lease and on Raft with crashes
and partitions.

**After shrinking, every fault left is needed.** Take any one of them away and the failure
stops. That is checked by doing it.

## The decision that made replay exact

My first version sampled faults from the random generator in one mode and read them from a list
in the other. Replaying the list reproduced the *failure* but not the *run*: with no dice being
thrown for faults, every later latency came out different.

So in scripted mode the dice are still thrown, in the same order, and then ignored. What happens
to each message comes from the list; the generator's position does not. Replay the full list and
every latency lands where it did the first time. Take one fault out and the only thing that
changes is what that fault caused.

Two smaller ones in the same spirit. **A crash and its restart are one fault**, as are a
partition and its healing — shrinking that removed "the crash" and kept "the restart" would be
replaying a run that never happened to anything. And **scripted power cuts are applied from
inside the same periodic event that sampled them**, not scheduled on their own, because
scheduling them separately moves them by a hair among the other events of that tick, and a hair
is enough.

## The lease bug

[`examples/lease.py`](oneseed/examples/lease.py) is the smallest honest version of a mistake
that has taken down real systems. A server hands out a lock with a lease: yours for fifty ticks,
then I may give it to someone else. The client works out when to stop by counting from the moment
the grant *arrives* — fifty ticks from now, less ten for the network.

That is right until the grant itself is slow. The server started counting when it sent the reply;
the client starts when it reads it. The gap is time the client believes it holds the lock and the
server has already handed it on.

It fails on 37 of 200 seeds and never with a quiet network. The fix is one line — believe the
deadline the server put in the message — and with it 0 of 200 fail.

## Raft, and three bugs put back on purpose

[`raftlab`](https://github.com/KRISH123no/raftlab) is my Raft implementation. Its nodes are pure
state machines — told the time, handed messages — so it runs under this simulator with nothing
mocked: five nodes, lossy links, power cuts, partitions, a write every 120 ticks, and four safety
properties from the paper checked after every single event.

**As written, it passes: 0 of 2,000 seeds, and 0 of another 2,000 with the faults aimed at the
leader.**

A simulator that has only ever said "fine" has not shown it can say anything else. So three
guards from the Raft paper are removed, one at a time, by editing the node's source before it is
loaded. Each is a bug the paper warns about by name.

| Guard removed | Paper | Found | Shrinks to |
|---|---|---|---|
| A node may vote twice in one term | §5.2 | 131 of 200 seeds | nothing at all |
| A node votes for a candidate with a staler log | §5.4.1 | 192 of 200 seeds | one partition |
| A leader commits an old term's entry by counting replicas | §5.4.2, figure 8 | 0 of 6,000 seeds; then 59 of 48,000 | six faults, on the best seed |

**Voting twice** does not need a fault. Seed 2 had one fault fire; shrinking removed it and the
run still failed, at t=190, in the first election: `two leaders in term 1: 4 and 1`. Two
candidates timed out close together and both collected a majority. The tool says so in as many
words — `(none — it fails with a perfect network)`.

**Voting for a stale log** fired 24 faults on seed 0 and needs exactly one of them:

```
t=2000: [2, 3] cut off from the rest for 545 ticks
```

Two nodes are cut off and fall behind. The network heals, one of them stands for election with
its out-of-date log, the guard that should refuse it is gone, it wins, and it overwrites entries
the cluster had already committed. That is the whole of §5.4.1 in one line of output.

**Committing an old term's entry** is the bug the paper needs a figure to explain, and random
faults did not find it. Six thousand seeds of dropped packets, power cuts and partitions: nothing.
Aiming most of the power cuts at whoever was leader, without partitions: another 1,500, nothing.
Both together — partitions, plus power cuts every 130 ticks with four in five aimed at the leader —
found it on 59 seeds of 48,000. About one in 800.

Seed 13374 is the cleanest. Nineteen faults fired and six are needed:

```
$ oneseed shrink raft-commits-old-terms-leader-hunt 13374

    t=130: [0] cut off from the rest for 245 ticks
    t=390: node 2 loses power for 260 ticks
    t=780: node 1 loses power for 371 ticks
    t=910: node 3 loses power for 305 ticks
    t=1430: [1, 4] cut off from the rest for 249 ticks
    t=1690: [2] cut off from the rest for 486 ticks

  commit agreement violated at t=2126: node 1 committed [(1:'cmd1'), (6:'cmd3')]
  where the cluster had already committed [(1:'cmd1'), (1:'cmd2')]
```

`cmd2` was written in term 1. A later leader committed it by counting copies, which is the thing
§5.4.2 forbids, and a leader in term 6 then replaced it with `cmd3`. An entry the cluster had
called committed is gone. With the guard back in, the same scenario survives 2,000 seeds.

**Shrinking does much worse here, and that is the honest part.** The first figure 8 seed I tried
fired 77 faults and came down to 44, after 650 replays. When a failure needs a long run of things
to line up, taking any early fault away shifts everything after it, and the failure vanishes for
reasons that have nothing to do with that fault. "Cannot be made smaller by removing one thing"
is then a long way from "small". Seeds that fail early shrink well. Seeds that fail late do not.

## What it does not do

- **It has found no bug in anyone else's code.** The lease bug is real as a class and I wrote the
  system that has it. The Raft bugs are planted. The aim was a seed that breaks an open-source
  Raft implementation and an issue its maintainers acknowledge. That has not happened.
- **It can only run code written as state machines.** A node has to take the time and its
  messages as arguments. Real implementations use sockets, threads and `asyncio`, and running one
  of those needs a simulated event loop that this does not have. That is the piece between here
  and the previous point.
- **No disk faults.** Nothing models a write that was acknowledged and then lost, or a torn page.
  For a consensus algorithm that is half of what can go wrong.
- **One clock.** Every node sees the same time. Clock skew between machines — the other classic
  way a lease goes wrong — cannot be expressed.
- **Random search is weak against bugs that need several things in a row.** Figure 8 took a fault
  mix chosen by someone who already knew where the bug was. There is no coverage guidance and no
  systematic exploration of orderings, so a bug nobody suspects gets only the random faults.
- **Shrinking finds a set you cannot shrink by one, not the smallest set.** And a fault is named
  by which message it hit — the nth of its type between two nodes — so removing an early fault
  can change which message a later one refers to. Every candidate is run, so the result is always
  a real failing schedule; it may not be the one a person would have picked.
- **It is Python.** About thirty Raft runs of 8,000 ticks a second on a laptop core. The
  simulators this is modelled on do millions of events a second.

## Run it

```bash
pip install -e ".[dev,raft]"

oneseed list
oneseed search lease --seeds 200
oneseed replay lease 13
oneseed shrink lease 13
oneseed search raft --seeds 300
oneseed shrink raft-votes-for-stale-log 0

pytest
ruff check .
```

## Putting your own system under it

A scenario wires nodes onto the simulator, registers the property that must never break, and
returns a function that reports which faults fired:

```python
from oneseed import Network, Scenario, Simulator, search, shrink


def build(sim: Simulator, faults):
    nodes = {}
    net = Network(
        sim,
        lambda target, message: nodes[target].receive(message),
        drop_rate=0.05,
        delay_rate=0.02,
        faults=faults,
    )
    nodes[0] = MyNode(sim, net)  # use sim.now, sim.rng, net.send — nothing else
    sim.every(10, nodes[0].tick)
    sim.invariant("never two primaries", lambda: "two primaries" if broken(nodes) else None)
    return lambda: list(net.observed)


mine = Scenario("mine", "my system", build, until=5000)
for failing in search(mine, range(500)):
    print(shrink(mine, failing).faults)
```

The rule is in the comment. A node that reads the wall clock, opens a socket or calls
`random.random()` has a source of events the simulator cannot see, and the run stops being a
function of the seed. `replay` will tell you.

## Layout

| Path | What is in it |
|---|---|
| `oneseed/sim.py` | the clock, the event queue, the one random generator, invariants |
| `oneseed/net.py` | message faults, sampled or scripted, always recorded |
| `oneseed/chaos.py` | power cuts and partitions, on the same terms |
| `oneseed/faults.py` | one fault, written down precisely enough to do again |
| `oneseed/run.py` | one run from a seed; a search over many |
| `oneseed/shrink.py` | delta debugging over the fault list |
| `oneseed/examples/lease.py` | the lock with the slow-grant bug, and its fix |
| `oneseed/examples/raft.py` | `raftlab` under simulation, and the three edits |

## Licence

MIT.
