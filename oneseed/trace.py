"""Every interesting thing that happened, in order, hashable.

A trace is how a replay proves itself. Two runs of the same seed are only the
same run if they produced the same events at the same times, so the digest of
the trace is the claim the tool makes about determinism: if it differs, the
simulator is lying somewhere and nothing it reports can be trusted.
"""

from __future__ import annotations

import hashlib


class Trace:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def add(self, at: int, kind: str, detail: str = "") -> None:
        self.lines.append(f"{at:>6}  {kind:<12} {detail}".rstrip())

    @property
    def digest(self) -> str:
        body = "\n".join(self.lines).encode()
        return hashlib.sha256(body).hexdigest()[:12]

    def tail(self, count: int = 20) -> str:
        return "\n".join(self.lines[-count:])

    def __len__(self) -> int:
        return len(self.lines)

    def __str__(self) -> str:
        return "\n".join(self.lines)
