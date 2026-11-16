"""oneseed search lease · oneseed replay lease 4 · oneseed shrink lease 4"""

from __future__ import annotations

import argparse
import time

from .run import run, search
from .scenarios import SCENARIOS
from .shrink import shrink


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="oneseed", description="Deterministic simulation testing: one seed is one run."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="the scenarios it can run")
    for name, text in (
        ("search", "try a range of seeds and report the ones that fail"),
        ("replay", "run one seed and prove it comes out the same twice"),
        ("shrink", "cut a failing seed's faults down to the ones that matter"),
    ):
        command = sub.add_parser(name, help=text)
        command.add_argument("scenario", choices=sorted(SCENARIOS))
        if name == "search":
            command.add_argument("--seeds", type=int, default=200, help="how many seeds to try")
            command.add_argument("--start", type=int, default=0, help="the first seed")
        else:
            command.add_argument("seed", type=int)
            command.add_argument("--trace", type=int, default=14, help="trace lines to show")
    args = parser.parse_args(argv)

    if args.command == "list":
        for name, scenario in SCENARIOS.items():
            print(f"{name:<28} {scenario.summary}")
        return 0

    scenario = SCENARIOS[args.scenario]

    if args.command == "search":
        started = time.perf_counter()
        failing = search(scenario, range(args.start, args.start + args.seeds))
        took = time.perf_counter() - started
        print(f"{scenario.name}: {len(failing)} of {args.seeds} seeds fail  ({took:.1f}s)")
        by_name: dict[str, list[int]] = {}
        for outcome in failing:
            assert outcome.violation is not None
            by_name.setdefault(outcome.violation.name, []).append(outcome.seed)
        for name, seeds in by_name.items():
            shown = ", ".join(str(seed) for seed in seeds[:12]) + (" …" if len(seeds) > 12 else "")
            print(f"  {name}: {len(seeds)} — seeds {shown}")
        if failing:
            print(f"\nnext: oneseed shrink {scenario.name} {failing[0].seed}")
        return 1 if failing else 0

    first = run(scenario, args.seed)
    second = run(scenario, args.seed)
    if first.digest != second.digest:
        print(f"NOT DETERMINISTIC: seed {args.seed} gave {first.digest} and then {second.digest}")
        return 3

    if args.command == "replay":
        print(f"{scenario.name}, seed {args.seed}")
        print(f"  ran twice, same trace both times: {first.digest}  ({len(first.trace)} lines)")
        print(f"  faults that fired: {len(first.faults)}")
        if first.violation is None:
            print("  no invariant was broken")
            return 0
        print(f"  {first.violation}\n")
        print(first.trace.tail(args.trace))
        return 1

    if first.violation is None:
        print(f"{scenario.name}, seed {args.seed}: nothing to shrink, that run does not fail")
        return 0
    scripted = run(scenario, args.seed, first.faults)
    exact = "the identical trace" if scripted.digest == first.digest else "the same failure"
    shrunk = shrink(scenario, first)
    print(f"{scenario.name}, seed {args.seed}")
    print(f"  {first.violation}")
    print(f"  {len(first.faults)} faults fired; replaying them from a list gives {exact}")
    print(f"  shrunk to {len(shrunk.faults)} in {shrunk.runs} replays.")
    print("  Every one of these is needed:\n")
    # Power cuts and partitions in the order they happened, then the messages.
    for fault in sorted(shrunk.faults, key=lambda f: (f.at < 0, f.at)):
        print(f"    {fault}")
    if not shrunk.faults:
        print("    (none — it fails with a perfect network)")
    print(f"\n  with only those: {shrunk.outcome.violation}\n")
    print(shrunk.outcome.trace.tail(args.trace))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
