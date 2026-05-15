'''Tests for block_processor.py — Prefetcher, BlockProcessor logic.'''
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from electrumx.server.block_processor import (
    ChainError, Prefetcher, BlockProcessor,
)
from electrumx.server.db import FlushData


# --- ChainError tests ---

class TestChainError:
    '''Tests for the ChainError exception.'''

    def test_chain_error_is_exception(self):
        assert issubclass(ChainError, Exception)

    def test_chain_error_message(self):
        err = ChainError('test error')
        assert str(err) == 'test error'


# --- Prefetcher tests ---

class TestPrefetcher:
    '''Tests for the Prefetcher class.'''

    def _make_prefetcher(self):
        mock_daemon = MagicMock()
        mock_coin = MagicMock()
        blocks_event = asyncio.Event()
        pf = Prefetcher(mock_daemon, mock_coin, blocks_event, polling_delay_secs=1.0)
        return pf, mock_daemon, mock_coin

    def test_prefetcher_init(self):
        pf, _, _ = self._make_prefetcher()
        assert pf.blocks == []
        assert pf.caught_up is False
        assert pf.fetched_height is None
        assert pf.cache_size == 0
        assert pf.min_cache_size == 10 * 1024 * 1024
        assert pf.ave_size == pf.min_cache_size // 10
        assert pf.polling_delay == 1.0

    def test_get_prefetched_blocks_empty(self):
        pf, _, _ = self._make_prefetcher()
        pf.refill_event.set()
        blocks = pf.get_prefetched_blocks()
        assert blocks == []
        assert pf.cache_size == 0
        # refill_event should be set after get
        assert pf.refill_event.is_set()

    def test_get_prefetched_blocks_with_blocks(self):
        pf, _, _ = self._make_prefetcher()
        pf.blocks = [b'block1', b'block2']
        pf.cache_size = 100
        pf.refill_event.set()
        blocks = pf.get_prefetched_blocks()
        assert blocks == [b'block1', b'block2']
        assert pf.blocks == []
        assert pf.cache_size == 0

    def test_reset_height_clears_state(self):
        pf, mock_daemon, _ = self._make_prefetcher()
        mock_daemon.height = AsyncMock(return_value=100)

        async def _test():
            pf.fetched_height = 50
            pf.blocks = [b'block1']
            pf.cache_size = 100
            await pf.reset_height(40)

        asyncio.get_event_loop().run_until_complete(_test())
        assert pf.blocks == []
        assert pf.cache_size == 0
        assert pf.fetched_height == 40


# --- BlockProcessor tests ---

class TestBlockProcessor:
    '''Tests for the BlockProcessor class.'''

    def _make_env(self):
        mock_env = MagicMock()
        mock_env.coin.PEER_DEFAULT_PORTS = {'s': 50002, 't': 50001}
        mock_env.daemon_poll_interval_blocks_msec = 1000
        mock_env.cache_MB = 512
        mock_env.coin = MagicMock()
        mock_env.coin.TX_COUNT_HEIGHT = 0
        mock_env.coin.TX_PER_BLOCK = 50
        mock_env.coin.GENESIS_ACTIVATION = 0
        return mock_env

    def _make_db(self):
        mock_db = MagicMock()
        mock_db.fs_tx_count = 0
        mock_db.fs_height = -1
        mock_db.tx_counts = []
        mock_db.history = MagicMock()
        mock_db.history.unflushed_memsize.return_value = 0
        mock_db.min_undo_height.return_value = 0
        mock_db.first_sync = True
        return mock_db

    def _make_daemon(self):
        mock_daemon = MagicMock()
        mock_daemon.cached_height.return_value = 100
        return mock_daemon

    def _make_processor(self):
        env = self._make_env()
        db = self._make_db()
        daemon = self._make_daemon()
        notifications = MagicMock()
        bp = BlockProcessor(env, db, daemon, notifications)
        return bp, env, db, daemon

    def test_bp_init(self):
        bp, _, _, _ = self._make_processor()
        assert bp.height == -1
        assert bp.tip is None
        assert bp.tx_count == 0
        assert bp.touched == set()
        assert bp.reorg_count == 0
        assert bp.headers == []
        assert bp.tx_hashes == []
        assert bp.undo_infos == []
        assert bp.utxo_cache == {}
        assert bp.db_deletes == []
        assert bp.next_cache_check == 0
        assert bp.prefetcher is not None

    def test_flush_data(self):
        bp, _, _, _ = self._make_processor()
        bp.height = 100
        bp.tx_count = 500
        bp.headers = [b'header1', b'header2']
        bp.tx_hashes = [b'txhash1']
        bp.undo_infos = [([b'undo'], 100)]
        bp.utxo_cache = {b'key': b'value'}
        bp.db_deletes = [b'delete1']
        bp.tip = b'tip_hash'

        # Need to acquire the lock for flush_data
        async def _test():
            async with bp.state_lock:
                fd = bp.flush_data()
            return fd

        fd = asyncio.get_event_loop().run_until_complete(_test())
        assert isinstance(fd, FlushData)
        assert fd.height == 100
        assert fd.tx_count == 500
        assert fd.headers == [b'header1', b'header2']
        assert fd.block_tx_hashes == [b'txhash1']
        assert fd.undo_infos == [([b'undo'], 100)]
        assert fd.adds == {b'key': b'value'}
        assert fd.deletes == [b'delete1']
        assert fd.tip == b'tip_hash'

    def test_check_cache_size_under_threshold(self):
        bp, _, db, _ = self._make_processor()
        bp.height = 100
        bp.tx_count = 500
        db.fs_tx_count = 0
        db.fs_height = 0
        db.history.unflushed_memsize.return_value = 0

        result = bp.check_cache_size()
        # With empty caches, should return None (no flush needed)
        assert result is None

    def test_check_cache_size_utxo_threshold(self):
        bp, env, db, _ = self._make_processor()
        bp.height = 100
        bp.tx_count = 500
        db.fs_tx_count = 0
        db.fs_height = 0
        db.history.unflushed_memsize.return_value = 0

        # Populate UTXO cache to trigger flush
        # 1_MB = 1000*1000, each UTXO = 205 bytes
        # utxo_MB = len * 205 / 1000000
        # Need utxo_MB >= cache_MB * 4 // 5 = 512 * 4 // 5 = 409
        # So need len >= 409 * 1000000 / 205 ≈ 1,995,122
        large_count = 2_000_000
        bp.utxo_cache = {i.to_bytes(4, 'little'): b'x' * 100 for i in range(large_count)}
        bp.db_deletes = [b'delete'] * large_count

        result = bp.check_cache_size()
        # Should return True (flush UTXOs)
        assert result is True

    def test_estimate_txs_remaining(self):
        bp, _, _, daemon = self._make_processor()
        bp.height = 1000
        bp.tx_count = 50000
        daemon.cached_height.return_value = 2000
        bp.env.coin.TX_COUNT = 1000000
        bp.env.coin.TX_COUNT_HEIGHT = 500

        est = bp.estimate_txs_remaining()
        # Should be a positive number
        assert est > 0

    def test_estimate_txs_remaining_at_tx_count_height(self):
        bp, _, _, daemon = self._make_processor()
        bp.height = 1000
        bp.tx_count = 50000
        daemon.cached_height.return_value = 2000
        bp.env.coin.TX_COUNT = 1000000
        bp.env.coin.TX_COUNT_HEIGHT = 500  # height < TX_COUNT_HEIGHT

        est = bp.estimate_txs_remaining()
        assert est > 0

    def test_run_in_thread_with_lock(self):
        bp, _, _, _ = self._make_processor()

        def sync_func(x, y):
            return x + y

        async def _test():
            result = await bp.run_in_thread_with_lock(sync_func, 3, 4)
            return result

        result = asyncio.get_event_loop().run_until_complete(_test())
        assert result == 7

    def test_blocks_event_is_event(self):
        bp, _, _, _ = self._make_processor()
        assert isinstance(bp.blocks_event, asyncio.Event)
        assert not bp.blocks_event.is_set()

    def test_tip_advanced_event_is_event(self):
        bp, _, _, _ = self._make_processor()
        assert isinstance(bp.tip_advanced_event, asyncio.Event)
        assert not bp.tip_advanced_event.is_set()

    def test_backed_up_event_is_event(self):
        bp, _, _, _ = self._make_processor()
        assert isinstance(bp.backed_up_event, asyncio.Event)
        assert not bp.backed_up_event.is_set()

    def test_state_lock_is_lock(self):
        bp, _, _, _ = self._make_processor()
        assert isinstance(bp.state_lock, asyncio.Lock)
        assert not bp.state_lock.locked()
