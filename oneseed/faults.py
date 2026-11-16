"""One thing that went wrong, written down precisely enough to do again.

A rate is not a bug report. "Five per cent of packets were dropped" cannot be
replayed, cannot be made smaller, and cannot be read. A list of faults can:
this message was held for forty ticks, that node lost power at t=1200 for six
hundred. The list and the seed are the whole run.

There are two families. Message faults say which message — the nth of its type
between a pair of nodes — and what happened to it. Timed faults say when, and
to whom.
"""

from __future__ import annotations

from dataclasses import dataclass

MESSAGE = ("drop", "delay", "duplicate")
TIMED = ("crash", "partition")


@dataclass(frozen=True)
class Fault:
    kind: str
    # --- which message, for drop, delay and duplicate
    source: int = -1
    target: int = -1
    message: str = ""
    #: Which message of this type between this pair, counting from zero.
    nth: int = -1
    # --- when, for crash and partition
    at: int = -1
    node: int = -1
    #: One side of a partition; everyone else is on the other.
    group: tuple[int, ...] = ()
    #: How long: the extra delay, or how long a crash or a partition lasts.
    ticks: int = 0

    @property
    def key(self) -> tuple[int, int, str, int]:
        return (self.source, self.target, self.message, self.nth)

    def __str__(self) -> str:
        if self.kind == "crash":
            return f"t={self.at}: node {self.node} loses power for {self.ticks} ticks"
        if self.kind == "partition":
            return f"t={self.at}: {list(self.group)} cut off from the rest for {self.ticks} ticks"
        which = f"{self.message} #{self.nth} from {self.source} to {self.target}"
        if self.kind == "delay":
            return f"{which} held for {self.ticks} extra ticks"
        return f"{which} {'dropped' if self.kind == 'drop' else 'delivered twice'}"
