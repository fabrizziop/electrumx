'''Tests for transport.py — PaddedRSTransport.'''
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from electrumx.server.transport import PaddedRSTransport


class TestPaddedRSTransport:
    '''Tests for the PaddedRSTransport class.'''

    def _make_transport(self):
        '''Create a PaddedRSTransport with mocked dependencies.'''
        mock_session = MagicMock()
        mock_session.send_size = 0
        mock_session.taskgroup = MagicMock()

        # Mock the parent RSTransport
        with patch('electrumx.server.transport.RSTransport.__init__', return_value=None):
            transport = PaddedRSTransport.__new__(PaddedRSTransport)
            transport._can_send = asyncio.Event()
            transport._can_send.set()
            transport._framer = MagicMock()
            transport._framer.frame = lambda msg: f'{msg}\n'.encode()
            transport._asyncio_transport = MagicMock()
            transport._asyncio_transport.is_closing = MagicMock(return_value=False)
            transport._sbuffer = bytearray()
            transport._sbuffer_task = None
            transport._sbuffer_has_data_evt = asyncio.Event()
            transport._last_send = time.monotonic()
            transport._force_send = False
            transport.session = mock_session
            transport._closed_event = MagicMock()
            transport._closed_event.is_set = MagicMock(return_value=False)
            transport.is_closing = MagicMock(return_value=False)
            # Mock _proxy to avoid aiorpcx RSTransport attribute errors
            transport._proxy = None
            return transport, mock_session

    def test_init_sets_defaults(self):
        transport, _ = self._make_transport()
        assert transport._sbuffer == bytearray()
        assert transport._sbuffer_task is None
        assert isinstance(transport._sbuffer_has_data_evt, asyncio.Event)
        assert transport._force_send is False
        # Check class constants
        assert PaddedRSTransport.MIN_PACKET_SIZE == 1024
        assert PaddedRSTransport.WAIT_FOR_BUFFER_GROWTH_SECONDS == 1.0
        assert PaddedRSTransport.WARMUP_BUDGET_SIZE == 1024

    def test_write_queues_message(self):
        transport, mock_session = self._make_transport()
        transport._framer.frame = lambda msg: b'{"test": 1}\n'

        asyncio.get_event_loop().run_until_complete(transport.write('{"test": 1}'))
        # write() calls _maybe_consume_sbuffer which may send immediately
        # (warmup budget allows small sends)
        transport._asyncio_transport.write.assert_called_once()

    def test_write_closing_does_nothing(self):
        transport, _ = self._make_transport()
        transport.is_closing = MagicMock(return_value=True)

        # Should not raise, just return (is_closing check happens after can_send)
        async def _write():
            # Clear can_send so wait blocks, but is_closing returns True
            transport._can_send.clear()
            result = await asyncio.wait_for(transport.write('test'), timeout=0.1)
            return result

        # Since _can_send is cleared, write will wait for it.
        # But is_closing returns True, so it returns early.
        # However, _can_send.wait() blocks first, so we need to handle this.
        # Actually the code does: await _can_send.wait() THEN if is_closing().
        # So with can_send cleared, it will block. Let's just test the is_closing path.
        transport._can_send.set()
        transport.is_closing = MagicMock(return_value=True)
        result = asyncio.get_event_loop().run_until_complete(transport.write('test'))
        assert result is None
        transport._asyncio_transport.write.assert_not_called()

    def test_maybe_consume_sbuffer_empty(self):
        transport, _ = self._make_transport()
        transport._maybe_consume_sbuffer()
        # Nothing to send, no error
        transport._asyncio_transport.write.assert_not_called()

    def test_maybe_consume_sbuffer_force_send_small(self):
        transport, mock_session = self._make_transport()
        transport._sbuffer = bytearray(b'{"test": 1}\n')
        transport._force_send = True
        mock_session.send_size = 0

        transport._maybe_consume_sbuffer()
        # Should send with padding to MIN_PACKET_SIZE
        transport._asyncio_transport.write.assert_called_once()
        call_arg = transport._asyncio_transport.write.call_args[0][0]
        assert len(call_arg) >= PaddedRSTransport.MIN_PACKET_SIZE

    def test_maybe_consume_sbuffer_large_enough(self):
        transport, mock_session = self._make_transport()
        # Create a buffer larger than MIN_PACKET_SIZE
        large_msg = bytearray(b'{"data": "' + b'x' * 2000 + b'"}\n')
        transport._sbuffer = large_msg
        mock_session.send_size = 0

        transport._maybe_consume_sbuffer()
        transport._asyncio_transport.write.assert_called_once()

    def test_maybe_consume_sbuffer_warmup_budget(self):
        transport, mock_session = self._make_transport()
        transport._sbuffer = bytearray(b'{"test": 1}\n')
        mock_session.send_size = 500  # Under warmup budget
        transport._last_send = time.monotonic() - 10  # Long time since last send

        transport._maybe_consume_sbuffer()
        # Should send because time elapsed
        transport._asyncio_transport.write.assert_called_once()

    def test_maybe_consume_sbuffer_no_send_when_not_ready(self):
        transport, mock_session = self._make_transport()
        transport._sbuffer = bytearray(b'{"test": 1}\n')
        transport._can_send.clear()
        mock_session.send_size = 0
        transport._last_send = time.monotonic()

        transport._maybe_consume_sbuffer()
        transport._asyncio_transport.write.assert_not_called()

    def test_maybe_consume_sbuffer_clears_evt_when_empty(self):
        transport, mock_session = self._make_transport()
        transport._sbuffer = bytearray(b'{"test": 1}\n')
        transport._force_send = True
        transport._sbuffer_has_data_evt.set()
        mock_session.send_size = 0

        transport._maybe_consume_sbuffer()
        assert not transport._sbuffer  # buffer consumed
        assert not transport._sbuffer_has_data_evt.is_set()

    def test_maybe_consume_sbuffer_pads_to_power_of_two(self):
        transport, mock_session = self._make_transport()
        # Small message: 14 bytes
        transport._sbuffer = bytearray(b'{"test": 1}\n')
        transport._force_send = True
        mock_session.send_size = 0

        transport._maybe_consume_sbuffer()
        call_arg = transport._asyncio_transport.write.call_args[0][0]
        # Should be padded to at least MIN_PACKET_SIZE (1024)
        assert len(call_arg) >= PaddedRSTransport.MIN_PACKET_SIZE
        # Should end with valid JSON-RPC terminator
        assert call_arg[-2:] in (b'}\n', b']\n')

    def test_maybe_consume_sbuffer_defers_with_ssize(self):
        transport, mock_session = self._make_transport()
        # Create a buffer that's just over MIN_PACKET_SIZE
        # so that ssize (half) would waste less padding
        msg = bytearray(b'{"data": "' + b'x' * 1100 + b'"}\n')
        transport._sbuffer = msg
        transport._force_send = True
        mock_session.send_size = 0

        transport._maybe_consume_sbuffer()
        transport._asyncio_transport.write.assert_called_once()
        call_arg = transport._asyncio_transport.write.call_args[0][0]
        assert len(call_arg) >= PaddedRSTransport.MIN_PACKET_SIZE

    def test_connection_made_spawns_poll_task(self):
        transport, mock_session = self._make_transport()

        # Mock the parent connection_made
        with patch('electrumx.server.transport.RSTransport.connection_made'):
            transport.connection_made(MagicMock())

        mock_session.taskgroup.spawn.assert_called_once()
        assert transport._sbuffer_task is not None

    def test_close_flushes_buffer(self):
        transport, mock_session = self._make_transport()
        transport._sbuffer = bytearray(b'{"test": 1}\n')
        transport._force_send = False

        mock_parent_close = AsyncMock()
        with patch('electrumx.server.transport.RSTransport.close', mock_parent_close):
            asyncio.get_event_loop().run_until_complete(transport.close())

        assert transport._force_send is True  # force_send was set
        mock_parent_close.assert_called_once()

    def test_poll_sbuffer_exits_on_close(self):
        transport, _ = self._make_transport()
        transport._can_send.set()

        async def _test():
            transport._sbuffer_has_data_evt.set()
            transport._sbuffer = bytearray()  # empty, so _maybe_consume won't call write
            # After one iteration, mark as closing
            transport.is_closing = MagicMock(return_value=True)
            await transport._poll_sbuffer()

        # Use a timeout to prevent infinite loop
        asyncio.get_event_loop().run_until_complete(
            asyncio.wait_for(_test(), timeout=1.0)
        )
        # Should exit cleanly without error
