'''Tests for session.py utility functions and small classes.'''
import pytest

from electrumx.server.session import (
    scripthash_to_hashX,
    non_negative_integer,
    assert_boolean,
    assert_tx_hash,
    assert_hex_str,
    assert_list_or_tuple,
    SessionGroup,
    SessionReferences,
)
from aiorpcx import RPCError


class TestUtilityFunctions:
    '''Tests for session.py utility functions.'''

    def test_scripthash_to_hashX_valid(self):
        # 64 hex chars = 32 bytes, result is first HASHX_LEN bytes
        valid_hash = 'a' * 64
        result = scripthash_to_hashX(valid_hash)
        from electrumx.lib.hash import HASHX_LEN
        assert len(result) == HASHX_LEN
        assert isinstance(result, bytes)

    def test_scripthash_to_hashX_too_short(self):
        # Less than 64 hex chars
        short_hash = 'a' * 60
        with pytest.raises(RPCError) as exc_info:
            scripthash_to_hashX(short_hash)
        assert 'not a valid script hash' in str(exc_info.value)

    def test_scripthash_to_hashX_invalid_hex(self):
        with pytest.raises(RPCError) as exc_info:
            scripthash_to_hashX('zzzz' * 16)
        assert 'not a valid script hash' in str(exc_info.value)

    def test_scripthash_to_hashX_empty(self):
        with pytest.raises(RPCError) as exc_info:
            scripthash_to_hashX('')
        assert 'not a valid script hash' in str(exc_info.value)

    def test_non_negative_integer_zero(self):
        assert non_negative_integer(0) == 0

    def test_non_negative_integer_positive(self):
        assert non_negative_integer(42) == 42

    def test_non_negative_integer_negative(self):
        with pytest.raises(RPCError) as exc_info:
            non_negative_integer(-1)
        assert 'non-negative integer' in str(exc_info.value)

    def test_non_negative_integer_string_number(self):
        assert non_negative_integer('123') == 123

    def test_non_negative_integer_string_negative(self):
        with pytest.raises(RPCError):
            non_negative_integer('-5')

    def test_non_negative_integer_invalid_string(self):
        with pytest.raises(RPCError):
            non_negative_integer('abc')

    def test_non_negative_integer_none(self):
        with pytest.raises(RPCError):
            non_negative_integer(None)

    def test_non_negative_integer_float(self):
        # int(3.14) == 3, which is >= 0, so it should pass
        assert non_negative_integer(3.14) == 3

    def test_assert_boolean_true(self):
        assert assert_boolean(True) is True

    def test_assert_boolean_false(self):
        assert assert_boolean(False) is False

    def test_assert_boolean_zero(self):
        # In Python, 0 == False, so 0 passes the check
        assert assert_boolean(0) == 0

    def test_assert_boolean_one(self):
        # In Python, 1 == True, so 1 passes the check
        assert assert_boolean(1) == 1

    def test_assert_boolean_string(self):
        with pytest.raises(RPCError):
            assert_boolean('true')

    def test_assert_boolean_none(self):
        with pytest.raises(RPCError):
            assert_boolean(None)

    def test_assert_tx_hash_valid(self):
        valid_hash = 'b' * 64
        result = assert_tx_hash(valid_hash)
        assert len(result) == 32
        assert isinstance(result, bytes)

    def test_assert_tx_hash_too_short(self):
        short_hash = 'b' * 60
        with pytest.raises(RPCError) as exc_info:
            assert_tx_hash(short_hash)
        assert 'transaction hash' in str(exc_info.value)

    def test_assert_tx_hash_invalid_hex(self):
        with pytest.raises(RPCError):
            assert_tx_hash('zzzz' * 16)

    def test_assert_tx_hash_empty(self):
        with pytest.raises(RPCError):
            assert_tx_hash('')

    def test_assert_hex_str_valid(self):
        # Valid hex string
        assert_hex_str('deadbeef')  # should not raise

    def test_assert_hex_str_invalid_prefix(self):
        # '0x' prefix is NOT valid for bytes.fromhex
        with pytest.raises(RPCError):
            assert_hex_str('0xdeadbeef')

    def test_assert_hex_str_odd_length(self):
        # Odd length hex is invalid
        with pytest.raises(RPCError):
            assert_hex_str('abc')

    def test_assert_hex_str_empty(self):
        # Empty string IS valid hex (bytes.fromhex('') = b'')
        assert_hex_str('')  # should not raise

    def test_assert_list_or_tuple_list(self):
        assert_list_or_tuple([1, 2, 3])  # should not raise

    def test_assert_list_or_tuple_tuple(self):
        assert_list_or_tuple((1, 2, 3))  # should not raise

    def test_assert_list_or_tuple_string(self):
        with pytest.raises(RPCError):
            assert_list_or_tuple('not a list')

    def test_assert_list_or_tuple_dict(self):
        with pytest.raises(RPCError):
            assert_list_or_tuple({'a': 1})

    def test_assert_list_or_tuple_none(self):
        with pytest.raises(RPCError):
            assert_list_or_tuple(None)


class TestSessionGroup:
    '''Tests for the SessionGroup attrs class.'''

    def test_session_cost(self):
        mock_session1 = type('MockSession', (), {'cost': 10})()
        mock_session2 = type('MockSession', (), {'cost': 20})()
        group = SessionGroup(
            name='test',
            weight=1,
            sessions=[mock_session1, mock_session2],
            retained_cost=5,
        )
        assert group.session_cost() == 30

    def test_cost(self):
        mock_session = type('MockSession', (), {'cost': 15})()
        group = SessionGroup(
            name='test',
            weight=1,
            sessions=[mock_session],
            retained_cost=5,
        )
        assert group.cost() == 20  # retained(5) + session(15)

    def test_session_cost_empty(self):
        group = SessionGroup(
            name='test',
            weight=1,
            sessions=[],
            retained_cost=10,
        )
        assert group.session_cost() == 0
        assert group.cost() == 10

    def test_multiple_sessions(self):
        sessions = [type('S', (), {'cost': i})() for i in range(1, 6)]
        group = SessionGroup(
            name='test',
            weight=1,
            sessions=sessions,
            retained_cost=0,
        )
        assert group.session_cost() == 15  # 1+2+3+4+5
        assert group.cost() == 15


class TestSessionReferences:
    '''Tests for the SessionReferences attrs class.'''

    def test_session_references_creation(self):
        sessions = set()
        groups = []
        specials = set()
        unknown = set()

        ref = SessionReferences(
            sessions=sessions,
            groups=groups,
            specials=specials,
            unknown=unknown,
        )

        assert ref.sessions is sessions
        assert ref.groups is groups
        assert ref.specials is specials
        assert ref.unknown is unknown

    def test_session_references_with_data(self):
        session1 = type('S', (), {})()
        session2 = type('S', (), {})()
        ref = SessionReferences(
            sessions={session1, session2},
            groups=['group1'],
            specials={'special1'},
            unknown={'unknown1'},
        )

        assert len(ref.sessions) == 2
        assert ref.groups == ['group1']
        assert 'special1' in ref.specials
        assert 'unknown1' in ref.unknown
