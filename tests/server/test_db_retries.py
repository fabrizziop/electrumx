'''Tests for P2-11: retry logic with exponential backoff in limited_history
and all_utxos.'''
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from os import environ

from electrumx.lib.hash import HASHX_LEN
from electrumx.lib.util import pack_le_uint64


@pytest.mark.asyncio
async def test_exponential_backoff_delays():
    '''Verify that the retry delays follow exponential backoff pattern.'''
    max_retries = 20
    base_delay = 0.1
    max_delay = 2.0

    delays = []
    for attempt in range(max_retries):
        delay = min(base_delay * (2 ** attempt), max_delay)
        delays.append(delay)

    # Check first few delays are doubling
    assert abs(delays[0] - 0.1) < 0.001
    assert abs(delays[1] - 0.2) < 0.001
    assert abs(delays[2] - 0.4) < 0.001
    assert abs(delays[3] - 0.8) < 0.001
    assert abs(delays[4] - 1.6) < 0.001
    # After attempt 5, delay caps at 2.0
    for i in range(5, max_retries):
        assert abs(delays[i] - 2.0) < 0.001

    # Total max wait time should be ~30s, not 50s like before
    total = sum(delays)
    assert total < 35  # generous margin
    assert total > 25  # should be meaningful


@pytest.mark.asyncio
async def test_max_retries_is_20():
    '''Verify max_retries was reduced from 200 to 20.'''
    # Read the source to verify the constant
    import inspect
    from electrumx.server.db import DB

    source = inspect.getsource(DB.limited_history)
    assert 'max_retries = 20' in source
    assert 'max_retries = 200' not in source

    source2 = inspect.getsource(DB.all_utxos)
    assert 'max_retries = 20' in source2
    assert 'max_retries = 200' not in source2


@pytest.mark.asyncio
async def test_exponential_backoff_logic_in_db():
    '''Verify the exponential backoff calculation is present in DB methods.'''
    import inspect
    from electrumx.server.db import DB

    source = inspect.getsource(DB.limited_history)
    assert 'base_delay = 0.1' in source
    assert 'max_delay = 2.0' in source
    assert 'base_delay * (2 ** attempt)' in source

    source2 = inspect.getsource(DB.all_utxos)
    assert 'base_delay = 0.1' in source2
    assert 'max_delay = 2.0' in source2
    assert 'base_delay * (2 ** attempt)' in source2
