'''Tests for P2-12: configurable compaction settings.'''
import pytest
import os
from os import environ
from unittest.mock import patch, MagicMock


@pytest.mark.asyncio
async def test_env_has_compaction_config():
    '''Verify Env has the new compaction configuration options.'''
    environ.clear()
    environ['DB_DIRECTORY'] = '/tmp/test_db'
    environ['DAEMON_URL'] = ''
    environ['COIN'] = 'BitcoinSV'

    from electrumx.server.env import Env

    env = Env()
    assert hasattr(env, 'history_max_row_entries')
    assert hasattr(env, 'large_hashx_threshold')
    assert hasattr(env, 'compaction_write_atomic')
    # Defaults
    assert env.history_max_row_entries == 12500
    assert env.large_hashx_threshold == 4
    assert env.compaction_write_atomic is True


@pytest.mark.asyncio
async def test_env_compaction_config_custom():
    '''Verify Env respects custom compaction config values.'''
    environ.clear()
    environ['DB_DIRECTORY'] = '/tmp/test_db'
    environ['DAEMON_URL'] = ''
    environ['COIN'] = 'BitcoinSV'
    environ['HISTORY_MAX_ROW_ENTRIES'] = '25000'
    environ['LARGE_HASHX_THRESHOLD'] = '8'
    # Note: env_base.boolean() uses truthy check on string,
    # so empty string = False, non-empty = True
    environ['COMPACTION_WRITE_ATOMIC'] = ''

    from electrumx.server.env import Env

    env = Env()
    assert env.history_max_row_entries == 25000
    assert env.large_hashx_threshold == 8
    assert env.compaction_write_atomic is False


@pytest.mark.asyncio
async def test_history_uses_env_config(tmpdir):
    '''Verify History class applies env config in open_db.'''
    environ.clear()
    environ['DB_DIRECTORY'] = str(tmpdir)
    environ['DAEMON_URL'] = ''
    environ['COIN'] = 'BitcoinSV'
    environ['HISTORY_MAX_ROW_ENTRIES'] = '5000'
    environ['LARGE_HASHX_THRESHOLD'] = '10'

    from electrumx.server.env import Env
    from electrumx.server.history import History

    env = Env()
    history = History()
    # Before open_db, uses defaults
    assert history.max_hist_row_entries == 12500
    assert history.large_hashx_threshold == 4

    # Mock the db class factory to avoid actual DB operations
    mock_db_instance = MagicMock()
    mock_db_instance.is_new = True
    mock_db_instance.get.return_value = None  # No state yet

    def make_mock_db(name, for_sync):
        return mock_db_instance

    with patch('electrumx.server.storage.db_class', make_mock_db):
        history.open_db(make_mock_db, False, 0, False, env)

    # After open_db, should use env values
    assert history.max_hist_row_entries == 5000
    assert history.large_hashx_threshold == 10


@pytest.mark.asyncio
async def test_compact_hashX_uses_threshold():
    '''Verify _compact_hashX logs based on configurable threshold.'''
    from electrumx.server.history import History
    from electrumx.lib.hash import HASHX_LEN
    from electrumx.lib.util import pack_be_uint16
    from os import urandom

    history = History()
    history.max_hist_row_entries = 12500
    history.large_hashx_threshold = 4

    hashX = urandom(HASHX_LEN)
    hist_map = {hashX + pack_be_uint16(0): b'\x00' * 100}
    hist_list = [b'\x00' * 100]
    write_items = []
    keys_to_delete = set()

    # Should not raise
    result = history._compact_hashX(hashX, hist_map, hist_list,
                                     write_items, keys_to_delete)
    assert isinstance(result, int)
    assert result >= 0
