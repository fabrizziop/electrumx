'''Tests for P2-14: peer verification RPC timeouts.'''
import pytest
import inspect


@pytest.mark.asyncio
async def test_peer_rpc_timeout_constant():
    '''Verify PEER_RPC_TIMEOUT constant exists.'''
    from electrumx.server.peers import PEER_RPC_TIMEOUT
    assert PEER_RPC_TIMEOUT == 30


@pytest.mark.asyncio
async def test_timeout_after_imported():
    '''Verify timeout_after is imported in peers module.'''
    from electrumx.server import peers
    assert hasattr(peers, 'timeout_after')
    assert hasattr(peers, 'TaskTimeout')


@pytest.mark.asyncio
async def test_verify_peer_has_timeout():
    '''Verify _verify_peer wraps RPC calls with timeout_after.'''
    from electrumx.server.peers import PeerManager

    source = inspect.getsource(PeerManager._verify_peer)
    assert 'timeout_after' in source
    assert 'PEER_RPC_TIMEOUT' in source
    assert 'TaskTimeout' in source


@pytest.mark.asyncio
async def test_send_headers_subscribe_has_timeout():
    '''Verify _send_headers_subscribe wraps RPC calls with timeout_after.'''
    from electrumx.server.peers import PeerManager

    source = inspect.getsource(PeerManager._send_headers_subscribe)
    assert 'timeout_after' in source
    assert 'PEER_RPC_TIMEOUT' in source
    assert 'TaskTimeout' in source


@pytest.mark.asyncio
async def test_send_server_features_has_timeout():
    '''Verify _send_server_features wraps RPC calls with timeout_after.'''
    from electrumx.server.peers import PeerManager

    source = inspect.getsource(PeerManager._send_server_features)
    assert 'timeout_after' in source
    assert 'PEER_RPC_TIMEOUT' in source
    assert 'TaskTimeout' in source


@pytest.mark.asyncio
async def test_send_peers_subscribe_has_timeout():
    '''Verify _send_peers_subscribe wraps RPC calls with timeout_after.'''
    from electrumx.server.peers import PeerManager

    source = inspect.getsource(PeerManager._send_peers_subscribe)
    assert 'timeout_after' in source
    assert 'PEER_RPC_TIMEOUT' in source
    assert 'TaskTimeout' in source
