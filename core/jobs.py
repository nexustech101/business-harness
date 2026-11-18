"""jobs.py

The upload job gate: at most `running` documents are parsed and indexed at
once (Docling and the uploaded file in memory) and `queued` more may wait.
Beyond that a job is refused at once with `Busy` instead of piling up.
In-process, like the rate limits. Used by the library upload route
(`api.deps.job_slot`).

*Usage:*
>>> gate = JobGate(running=2, queued=8)
>>> async with gate.slot():
...     draft = await read_file(parser, data, "handbook.pdf", chunk_chars=1500)
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class Busy(RuntimeError):
    """Every upload slot and the queue are taken."""


class JobGate:
    def __init__(self, running: int, queued: int):
        self.slots = asyncio.Semaphore(max(1, running))
        self.capacity = max(1, running) + max(0, queued)
        self.held = 0  # running + waiting

    @asynccontextmanager
    async def slot(self) -> AsyncIterator[None]:
        if self.held >= self.capacity:
            raise Busy("The server is busy with other documents. Retry shortly.")
        self.held += 1
        try:
            async with self.slots:
                yield
        finally:
            self.held -= 1
