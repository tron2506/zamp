"""In-process pub/sub so the live-run view receives stage events the moment they happen."""
import asyncio
from collections import defaultdict

_subs: dict[str, list[asyncio.Queue]] = defaultdict(list)


def subscribe(run_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subs[run_id].append(q)
    return q


def unsubscribe(run_id: str, q: asyncio.Queue) -> None:
    if q in _subs.get(run_id, []):
        _subs[run_id].remove(q)


def publish(run_id: str, event: dict) -> None:
    for q in list(_subs.get(run_id, [])):
        q.put_nowait(event)
