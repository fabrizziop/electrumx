'''Tests for db.py — UTXO, FlushData, DBError, and DB utility methods.'''
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from electrumx.server.db import UTXO, FlushData, DB, COMP_TXID_LEN
from electrumx.lib.hash import HASHX_LEN


class TestUTXO:
    '''Tests for the UTXO dataclass.'''

    def test_utxo_creation(self):
        utxo = UTXO(
            tx_num=100,
            tx_pos=0,
            tx_hash=b'\x01' * 32,
            height=500000,
            value=100000000,
        )
        assert utxo.tx_num == 100
        assert utxo.tx_pos == 0
        assert utxo.tx_hash == b'\x01' * 32
        assert utxo.height == 500000
        assert utxo.value == 100000000

    def test_utxo_ordering(self):
        utxo1 = UTXO(tx_num=100, tx_pos=0, tx_hash=b'\x00' * 32, height=0, value=0)
        utxo2 = UTXO(tx_num=101, tx_pos=0, tx_hash=b'\x00' * 32, height=0, value=0)
        assert utxo1 < utxo2

    def test_utxo_equality(self):
        utxo1 = UTXO(tx_num=100, tx_pos=0, tx_hash=b'\x01' * 32, height=0, value=0)
        utxo2 = UTXO(tx_num=100, tx_pos=0, tx_hash=b'\x01' * 32, height=0, value=0)
        assert utxo1 == utxo2


class TestFlushData:
    '''Tests for the FlushData attrs class.'''

    def test_flushdata_creation(self):
        flush = FlushData(
            height=100,
            tx_count=500,
            headers=[b'header1', b'header2'],
            block_tx_hashes=[b'hash1', b'hash2'],
            undo_infos=[],
            adds={},
            deletes=[],
            tip=b'tip123',
        )
        assert flush.height == 100
        assert flush.tx_count == 500
        assert len(flush.headers) == 2
        assert len(flush.block_tx_hashes) == 2
        assert flush.undo_infos == []
        assert flush.adds == {}
        assert flush.deletes == []
        assert flush.tip == b'tip123'

    def test_flushdata_with_undo_infos(self):
        undo = [(b'hash1', 1), (b'hash2', 2)]
        adds = {b'key1': b'value1'}
        deletes = [b'delete1', b'delete2']

        flush = FlushData(
            height=200,
            tx_count=1000,
            headers=[],
            block_tx_hashes=[],
            undo_infos=undo,
            adds=adds,
            deletes=deletes,
            tip=b'tip456',
        )
        assert flush.undo_infos == undo
        assert flush.adds == adds
        assert flush.deletes == deletes


class TestDBError:
    '''Tests for DB.DBError exception.'''

    def test_db_error_is_exception(self):
        assert issubclass(DB.DBError, Exception)

    def test_db_error_message(self):
        err = DB.DBError('corruption detected')
        assert str(err) == 'corruption detected'


class TestDBConstants:
    '''Tests for DB constants.'''

    def test_comp_txid_len(self):
        assert COMP_TXID_LEN == 4

    def test_db_versions(self):
        assert DB.DB_VERSIONS == (6, 7, 8)


class TestDBInit:
    '''Tests for DB initialization with mocked dependencies.'''

    def test_db_init_static_headers(self):
        '''Test DB init when coin uses static headers.'''
        mock_env = MagicMock()
        mock_env.db_dir = '/tmp/test_db'
        mock_env.db_engine = 'lmdb'
        mock_env.coin = MagicMock()
        mock_env.coin.STATIC_BLOCK_HEADERS = True
        mock_env.coin.NAME = 'BTC'
        mock_env.coin.NET = 'mainnet'
        mock_env.coin.static_header_offset = lambda h: h * 80
        mock_env.coin.static_header_len = 80

        with patch('electrumx.server.db.os.chdir'), \
             patch('electrumx.server.db.db_class') as mock_db_class, \
             patch('electrumx.server.db.util.class_logger') as mock_logger, \
             patch('electrumx.server.db.Merkle'), \
             patch('electrumx.server.db.MerkleCache'), \
             patch('electrumx.server.db.util.LogicalFile'), \
             patch('electrumx.server.db.History'):
            mock_db_class.return_value = MagicMock()
            db = DB(mock_env)

            assert db.header_offset == mock_env.coin.static_header_offset
            assert db.header_len == mock_env.coin.static_header_len
            assert db.utxo_db is None
            assert db.fs_height == -1
            assert db.fs_tx_count == 0
            assert db.db_height == -1
            assert db.db_tx_count == 0
            assert db.db_tip is None
            assert db.tx_counts is None
            assert db.db_version == -1
            assert db.first_sync is True

    def test_db_init_dynamic_headers(self):
        '''Test DB init when coin uses dynamic headers.'''
        mock_env = MagicMock()
        mock_env.db_dir = '/tmp/test_db'
        mock_env.db_engine = 'lmdb'
        mock_env.coin = MagicMock()
        mock_env.coin.STATIC_BLOCK_HEADERS = False
        mock_env.coin.NAME = 'BTC'
        mock_env.coin.NET = 'testnet'

        with patch('electrumx.server.db.os.chdir'), \
             patch('electrumx.server.db.db_class') as mock_db_class, \
             patch('electrumx.server.db.util.class_logger') as mock_logger, \
             patch('electrumx.server.db.Merkle'), \
             patch('electrumx.server.db.MerkleCache'), \
             patch('electrumx.server.db.util.LogicalFile'), \
             patch('electrumx.server.db.History'):
            mock_db_class.return_value = MagicMock()
            db = DB(mock_env)

            assert db.header_offset == db.dynamic_header_offset
            assert db.header_len == db.dynamic_header_len
            # headers_offsets_file should be created for dynamic headers
            assert hasattr(db, 'headers_offsets_file')


class TestDBHeaderMerkle:
    '''Tests for DB header merkle cache methods (require mocking).'''

    def test_header_branch_and_root_delegates(self):
        '''header_branch_and_root delegates to header_mc.branch_and_root.'''
        mock_env = MagicMock()
        mock_env.db_dir = '/tmp/test_db'
        mock_env.db_engine = 'lmdb'
        mock_env.coin = MagicMock()
        mock_env.coin.STATIC_BLOCK_HEADERS = True
        mock_env.coin.static_header_offset = lambda h: h * 80
        mock_env.coin.static_header_len = 80

        with patch('electrumx.server.db.os.chdir'), \
             patch('electrumx.server.db.db_class') as mock_db_cls, \
             patch('electrumx.server.db.util.class_logger'), \
             patch('electrumx.server.db.Merkle'), \
             patch('electrumx.server.db.MerkleCache') as mock_merkle_cache, \
             patch('electrumx.server.db.util.LogicalFile'), \
             patch('electrumx.server.db.History'):
            mock_db_cls.return_value = MagicMock()
            db = DB(mock_env)

            # Mock the header_mc.branch_and_root to return a coroutine result
            mock_merkle_cache_instance = mock_merkle_cache.return_value
            async def mock_branch(length, height):
                return ([b'branch'], b'root')
            mock_merkle_cache_instance.branch_and_root = mock_branch

            # Test that the method exists and is async
            import asyncio
            result = asyncio.get_event_loop().run_until_complete(
                db.header_branch_and_root(100, 50)
            )
            assert result == ([b'branch'], b'root')


class TestDBReadHeaders:
    '''Tests for DB read_headers method (require mocking).'''

    def test_read_headers_negative_start(self):
        '''read_headers raises DBError for negative start_height.'''
        mock_env = MagicMock()
        mock_env.db_dir = '/tmp/test_db'
        mock_env.db_engine = 'lmdb'
        mock_env.coin = MagicMock()
        mock_env.coin.STATIC_BLOCK_HEADERS = True
        mock_env.coin.static_header_offset = lambda h: h * 80
        mock_env.coin.static_header_len = 80

        with patch('electrumx.server.db.os.chdir'), \
             patch('electrumx.server.db.db_class') as mock_db_cls, \
             patch('electrumx.server.db.util.class_logger'), \
             patch('electrumx.server.db.Merkle'), \
             patch('electrumx.server.db.MerkleCache'), \
             patch('electrumx.server.db.util.LogicalFile'), \
             patch('electrumx.server.db.History'):
            mock_db_cls.return_value = MagicMock()
            db = DB(mock_env)
            db.db_height = 100

            import asyncio
            with pytest.raises(DB.DBError) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    db.read_headers(-1, 1)
                )
            assert 'not on disk' in str(exc_info.value)

    def test_read_headers_negative_count(self):
        '''read_headers raises DBError for negative count.'''
        mock_env = MagicMock()
        mock_env.db_dir = '/tmp/test_db'
        mock_env.db_engine = 'lmdb'
        mock_env.coin = MagicMock()
        mock_env.coin.STATIC_BLOCK_HEADERS = True
        mock_env.coin.static_header_offset = lambda h: h * 80
        mock_env.coin.static_header_len = 80

        with patch('electrumx.server.db.os.chdir'), \
             patch('electrumx.server.db.db_class') as mock_db_cls, \
             patch('electrumx.server.db.util.class_logger'), \
             patch('electrumx.server.db.Merkle'), \
             patch('electrumx.server.db.MerkleCache'), \
             patch('electrumx.server.db.util.LogicalFile'), \
             patch('electrumx.server.db.History'):
            mock_db_cls.return_value = MagicMock()
            db = DB(mock_env)
            db.db_height = 100

            import asyncio
            with pytest.raises(DB.DBError) as exc_info:
                asyncio.get_event_loop().run_until_complete(
                    db.read_headers(0, -1)
                )
            assert 'not on disk' in str(exc_info.value)
