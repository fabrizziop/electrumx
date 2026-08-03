"""Regression tests for _notify_inner mempool gating behaviour.

Documents the intentional fork behaviour:
- mempool_statuses are only re-checked when height_changed is True
  (new block arrived), NOT on mempool-only updates where only
  `touched` is set.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

from electrumx.server.session import ElectrumX

HASHX_A = b'\xaa' * 10
HASHX_B = b'\xbb' * 10
HASHX_M = b'\xcc' * 10


class _MockSession:
    """Minimal object with the attributes _notify_inner needs.

    Binds the real ElectrumX._notify_inner so the actual method body runs.
    """
    _notify_inner = ElectrumX._notify_inner
    _NOTIFY_SEMAPHORE_LIMIT = ElectrumX._NOTIFY_SEMAPHORE_LIMIT

    def __init__(self):
        self.hashX_subs: dict = {}
        self.mempool_statuses: dict = {}
        self.subscribe_headers = False
        self.logger = MagicMock()
        self.subscription_address_status = AsyncMock(return_value='0000')
        self.send_notification = AsyncMock()
        self.subscribe_headers_result = AsyncMock(return_value=('0' * 160, 100))


def _make_session():
    return _MockSession()


@pytest.mark.asyncio
async def test_mempool_rechecked_when_height_changed():
    """When height_changed=True and mempool_statuses is non-empty,
    mempool hashXs ARE re-checked via subscription_address_status."""
    session = _make_session()

    # Subscribe a "touched" address and a mempool address
    session.hashX_subs = {HASHX_A: 'addr_a', HASHX_M: 'addr_m'}
    session.mempool_statuses = {HASHX_M: 'old_status'}

    await session._notify_inner(touched={HASHX_A}, height_changed=True)

    # Both the touched hashX and the mempool hashX should have been looked up
    call_args = session.subscription_address_status.call_args_list
    called_hashXs = {arg[0][0] for arg in call_args}
    assert HASHX_A in called_hashXs, "touched hashX should be looked up"
    assert HASHX_M in called_hashXs, "mempool hashX should be re-checked when height_changed"


@pytest.mark.asyncio
async def test_mempool_skipped_when_only_touched():
    """When height_changed=False (mempool-only update), mempool_statuses
    re-check is SKIPPED — only the touched hashXs are looked up."""
    session = _make_session()

    session.hashX_subs = {HASHX_A: 'addr_a', HASHX_M: 'addr_m'}
    session.mempool_statuses = {HASHX_M: 'old_status'}

    await session._notify_inner(touched={HASHX_A}, height_changed=False)

    call_args = session.subscription_address_status.call_args_list
    called_hashXs = {arg[0][0] for arg in call_args}
    assert HASHX_A in called_hashXs, "touched hashX should be looked up"
    assert HASHX_M not in called_hashXs, (
        "mempool hashX should NOT be re-checked when height_changed is False"
    )


@pytest.mark.asyncio
async def test_mempool_skipped_when_empty():
    """When mempool_statuses is empty, no mempool re-check happens
    regardless of height_changed."""
    session = _make_session()

    session.hashX_subs = {HASHX_A: 'addr_a'}
    session.mempool_statuses = {}

    await session._notify_inner(touched={HASHX_A}, height_changed=True)

    call_args = session.subscription_address_status.call_args_list
    called_hashXs = {arg[0][0] for arg in call_args}
    assert HASHX_A in called_hashXs
    # No mempool hashXs to re-check
    assert len(called_hashXs) == 1


@pytest.mark.asyncio
async def test_mempool_hashX_not_in_subs_is_skipped():
    """A mempool hashX that was unsubscribed (not in hashX_subs) should
    not trigger a subscription_address_status call."""
    session = _make_session()

    # HASHX_M is in mempool_statuses but NOT in hashX_subs (user unsubscribed)
    session.hashX_subs = {HASHX_A: 'addr_a'}
    session.mempool_statuses = {HASHX_M: 'old_status'}

    await session._notify_inner(touched={HASHX_A}, height_changed=True)

    call_args = session.subscription_address_status.call_args_list
    called_hashXs = {arg[0][0] for arg in call_args}
    assert HASHX_A in called_hashXs
    assert HASHX_M not in called_hashXs


@pytest.mark.asyncio
async def test_concurrency_limit_applied():
    """Verify that the semaphore-based concurrency limit is respected:
    with 50 hashXs and a limit of 25, never more than 25 coroutines
    hold the semaphore simultaneously."""
    session = _make_session()

    many_hashXs = {bytes([i % 256]) * 10 for i in range(50)}
    session.hashX_subs = {h: f'addr_{i}' for i, h in enumerate(many_hashXs)}
    session.mempool_statuses = {}

    max_concurrent = 0
    current_concurrent = 0

    async def tracked_status(hashX):
        nonlocal max_concurrent, current_concurrent
        current_concurrent += 1
        max_concurrent = max(max_concurrent, current_concurrent)
        await asyncio.sleep(0)  # yield to let others queue
        current_concurrent -= 1
        return '0000'

    session.subscription_address_status = tracked_status

    await session._notify_inner(touched=many_hashXs, height_changed=False)

    limit = ElectrumX._NOTIFY_SEMAPHORE_LIMIT
    assert max_concurrent <= limit, (
        f"Concurrency peaked at {max_concurrent}, limit is {limit}"
    )
    assert max_concurrent > 1, "Should still run in parallel (not sequential)"
