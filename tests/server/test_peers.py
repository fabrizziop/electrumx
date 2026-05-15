'''Tests for peers.py — Peer class, PeerManager logic, and peer verification.'''
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from electrumx.lib.peer import Peer
from electrumx.server.peers import (
    PEER_GOOD, PEER_STALE, PEER_NEVER, PEER_BAD,
    BadPeerError, PeerSession, PeerManager, assert_good,
)


# --- Peer class tests ---

class TestPeer:
    '''Tests for the Peer class.'''

    def test_peer_creation(self):
        features = {'hosts': {'test.example.com': {'ssl_port': 50002}}}
        peer = Peer('test.example.com', features, source='test')
        assert peer.host == 'test.example.com'
        assert peer.ssl_port == 50002
        assert peer.tcp_port is None
        assert peer.source == 'test'
        assert not peer.bad

    def test_peer_is_tor(self):
        peer = Peer('abc123def.onion', {'hosts': {'abc123def.onion': {'ssl_port': 50002}}})
        assert peer.is_tor is True

    def test_peer_is_not_tor(self):
        peer = Peer('example.com', {'hosts': {'example.com': {'ssl_port': 50002}}})
        assert peer.is_tor is False

    def test_peer_ip_address(self):
        peer = Peer('1.2.3.4', {'hosts': {'1.2.3.4': {'ssl_port': 50002}}})
        assert str(peer.ip_address) == '1.2.3.4'

    def test_peer_ip_address_none_for_hostname(self):
        peer = Peer('example.com', {'hosts': {'example.com': {'ssl_port': 50002}}})
        assert peer.ip_address is None

    def test_peer_is_public_ip(self):
        peer = Peer('1.2.3.4', {'hosts': {'1.2.3.4': {'ssl_port': 50002}}})
        assert peer.is_public is True

    def test_peer_is_not_public_private_ip(self):
        peer = Peer('192.168.1.1', {'hosts': {'192.168.1.1': {'ssl_port': 50002}}})
        assert peer.is_public is False

    def test_peer_is_public_hostname(self):
        peer = Peer('example.com', {'hosts': {'example.com': {'ssl_port': 50002}}})
        assert peer.is_public is True

    def test_peer_is_not_public_localhost(self):
        peer = Peer('localhost', {'hosts': {'localhost': {'ssl_port': 50002}}})
        assert peer.is_public is False

    def test_peer_mark_bad(self):
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        assert peer.bad is False
        peer.mark_bad()
        assert peer.bad is True

    def test_peer_matches_by_host(self):
        peer_a = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        peer_b = Peer('other.example.com', {'hosts': {'other.example.com': {'ssl_port': 50002}}})
        matches = peer_a.matches([peer_a, peer_b])
        assert peer_a in matches
        assert peer_b not in matches

    def test_peer_matches_by_ip(self):
        peer_ip = Peer('1.2.3.4', {'hosts': {'1.2.3.4': {'ssl_port': 50002}}})
        peer_host = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}}, ip_addr='1.2.3.4')
        matches = peer_ip.matches([peer_host])
        assert peer_host in matches

    def test_peer_serialize_deserialize(self):
        features = {'hosts': {'test.example.com': {'ssl_port': 50002}}}
        peer = Peer('test.example.com', features, source='test', last_good=12345, last_try=12300, try_count=3)
        data = peer.serialize()
        assert data['host'] == 'test.example.com'
        assert data['source'] == 'test'
        assert data['last_good'] == 12345
        assert data['try_count'] == 3

        peer2 = Peer.deserialize(data)
        assert peer2.host == peer.host
        assert peer2.source == peer.source

    def test_peer_from_real_name(self):
        Peer.DEFAULT_PORTS = {'s': 50002, 't': 50001}
        peer = Peer.from_real_name('erbium1.sytes.net v1.0 s t', 'test')
        assert peer.host == 'erbium1.sytes.net'
        assert peer.ssl_port == 50002
        assert peer.tcp_port == 50001
        assert peer.protocol_max == '1.0'
        assert peer.protocol_min == '1.0'

    def test_peer_from_real_name_with_pruning(self):
        Peer.DEFAULT_PORTS = {'s': 50002, 't': 50001}
        peer = Peer.from_real_name('peer.example.com v1.1 s50002 p100000', 'test')
        assert peer.host == 'peer.example.com'
        assert peer.ssl_port == 50002
        assert peer.pruning == 100000
        assert peer.protocol_max == '1.1'

    def test_peer_from_real_name_custom_ports(self):
        Peer.DEFAULT_PORTS = {'s': 50002, 't': 50001}
        peer = Peer.from_real_name('peer.example.com v1.0 s9999 t8888', 'test')
        assert peer.ssl_port == 9999
        assert peer.tcp_port == 8888

    def test_peer_real_name(self):
        Peer.DEFAULT_PORTS = {'s': 50002, 't': 50001}
        peer = Peer.from_real_name('test.example.com v1.0 s t', 'test')
        name = peer.real_name()
        assert 'test.example.com' in name
        assert 'v1.0' in name
        assert 's' in name  # default port, shown as letter only
        assert 't' in name

    def test_peer_real_name_custom_ports_shown(self):
        Peer.DEFAULT_PORTS = {'s': 50002, 't': 50001}
        peer = Peer.from_real_name('test.example.com v1.0 s9999 t8888', 'test')
        name = peer.real_name()
        assert 's9999' in name
        assert 't8888' in name

    def test_peer_to_tuple(self):
        Peer.DEFAULT_PORTS = {'s': 50002, 't': 50001}
        peer = Peer.from_real_name('test.example.com v1.0 s t', 'test')
        peer.ip_addr = '1.2.3.4'
        tup = peer.to_tuple()
        assert tup[0] == '1.2.3.4'
        assert tup[1] == 'test.example.com'

    def test_peer_check_ports(self):
        Peer.DEFAULT_PORTS = {'s': 50002, 't': 50001}
        peer = Peer.from_real_name('test.example.com v1.0 s t', 'test')
        other = Peer.from_real_name('test.example.com v1.0 s9999 t8888', 'test')
        changed = peer.check_ports(other)
        assert changed is True
        assert ('SSL', 9999) in peer.other_port_pairs
        assert ('TCP', 8888) in peer.other_port_pairs

    def test_peer_update_features(self):
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        new_features = {'hosts': {'test.example.com': {'ssl_port': 9999}}, 'server_version': 'ElectrumX 1.0'}
        peer.update_features(new_features)
        assert peer.ssl_port == 9999
        assert peer.server_version == 'ElectrumX 1.0'

    def test_peer_update_features_invalid(self):
        '''update_features silently ignores invalid features (host mismatch).'''
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        # Host mismatch triggers AssertionError in Peer constructor
        new_features = {'hosts': {'other.example.com': {'ssl_port': 9999}}}
        peer.update_features(new_features)
        # Should be unchanged
        assert peer.ssl_port == 50002

    def test_peer_connection_tuples(self):
        Peer.DEFAULT_PORTS = {'s': 50002, 't': 50001}
        peer = Peer.from_real_name('test.example.com v1.0 s t', 'test')
        peer.ip_addr = '1.2.3.4'
        tuples = peer.connection_tuples()
        kinds = [t[0] for t in tuples]
        assert 'SSL' in kinds
        assert 'TCP' in kinds

    def test_peer_connection_tuples_only_ssl(self):
        Peer.DEFAULT_PORTS = {'s': 50002}
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        peer.ip_addr = '1.2.3.4'
        tuples = peer.connection_tuples()
        assert all(t[0] == 'SSL' for t in tuples)

    def test_peer_bucket_ipv4(self):
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        peer.ip_addr = '192.0.2.100'
        bucket = peer.bucket_for_internal_purposes()
        assert bucket == '192.0.2.100'

    def test_peer_bucket_ipv6(self):
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        peer.ip_addr = '2001:db8::1'
        bucket = peer.bucket_for_internal_purposes()
        assert bucket is not None
        assert ':' in bucket  # IPv6 address with /64

    def test_peer_bucket_onion(self):
        peer = Peer('abc123.onion', {'hosts': {'abc123.onion': {'ssl_port': 50002}}})
        bucket = peer.bucket_for_internal_purposes()
        assert bucket == 'onion'

    def test_peer_bucket_no_ip(self):
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        bucket = peer.bucket_for_internal_purposes()
        assert bucket == ''

    def test_peers_from_features(self):
        features = {
            'hosts': {
                'peer1.example.com': {'ssl_port': 50002},
                'peer2.example.com': {'ssl_port': 50002},
            }
        }
        peers = Peer.peers_from_features(features, 'test')
        assert len(peers) == 2
        assert peers[0].host == 'peer1.example.com'
        assert peers[1].host == 'peer2.example.com'

    def test_peers_from_features_invalid(self):
        assert Peer.peers_from_features('not a dict', 'test') == []
        assert Peer.peers_from_features({'no_hosts': True}, 'test') == []


# --- assert_good tests ---

class TestAssertGood:
    '''Tests for the assert_good helper function.'''

    def test_assert_good_dict(self):
        assert_good('test', {'key': 'value'}, dict)  # Should not raise

    def test_assert_good_list(self):
        assert_good('test', [1, 2, 3], list)  # Should not raise

    def test_assert_good_wrong_type(self):
        with pytest.raises(BadPeerError, match='bad result type'):
            assert_good('test', 'string', dict)

    def test_assert_good_none(self):
        with pytest.raises(BadPeerError):
            assert_good('test', None, dict)


# --- PeerManager logic tests ---

class TestPeerManagerLogic:
    '''Tests for PeerManager logic methods (no network required).'''

    def _make_peer(self, host, ip_addr=None, last_good=0, try_count=0, bad=False):
        features = {'hosts': {host: {'ssl_port': 50002}}}
        peer = Peer(host, features, source='test', ip_addr=ip_addr, last_good=int(last_good), try_count=try_count)
        if bad:
            peer.mark_bad()
        return peer

    def _make_manager(self, peers=None):
        '''Create a PeerManager with mocked env and db.'''
        mock_env = MagicMock()
        mock_env.coin.PEER_DEFAULT_PORTS = {'s': 50002, 't': 50001}
        mock_env.report_services = []
        mock_env.peer_announce = True
        mock_env.force_proxy = False
        mock_env.peer_discovery = 'ON'
        mock_env.blacklist_url = None
        mock_env.services = []

        mock_db = MagicMock()
        mock_db.db_height = 100000

        pm = PeerManager(mock_env, mock_db)
        if peers:
            pm.peers = set(peers)
        return pm, mock_env

    def test_pm_init(self):
        mock_env = MagicMock()
        mock_env.coin.PEER_DEFAULT_PORTS = {'s': 50002, 't': 50001}
        mock_env.report_services = []
        mock_env.peer_announce = False
        mock_env.force_proxy = False
        mock_env.peer_discovery = 'ON'
        mock_env.blacklist_url = None
        mock_env.services = []

        pm = PeerManager(mock_env, MagicMock())
        assert pm.peers == set()
        assert pm.blacklist == set()

    def test_set_peer_statuses(self):
        now = int(time.time())
        pm, _ = self._make_manager([
            self._make_peer('good.example.com', last_good=now),
            self._make_peer('stale.example.com', last_good=now - 12000),
            self._make_peer('bad.example.com', bad=True),
            self._make_peer('never.example.com', last_good=0),
        ])
        pm._set_peer_statuses()
        for peer in pm.peers:
            if peer.host == 'good.example.com':
                assert peer.status == PEER_GOOD
            elif peer.host == 'stale.example.com':
                assert peer.status == PEER_STALE
            elif peer.host == 'bad.example.com':
                assert peer.status == PEER_BAD
            elif peer.host == 'never.example.com':
                assert peer.status == PEER_NEVER

    def test_get_recent_good_peers(self):
        now = int(time.time())
        pm, _ = self._make_manager([
            self._make_peer('recent.example.com', last_good=now),
            self._make_peer('stale.example.com', last_good=now - 12000),
            self._make_peer('bad.example.com', last_good=now, bad=True),
        ])
        recent = pm._get_recent_good_peers()
        hosts = [p.host for p in recent]
        assert 'recent.example.com' in hosts
        assert 'stale.example.com' not in hosts
        assert 'bad.example.com' not in hosts

    def test_get_recent_good_peers_blacklisted(self):
        pm, _ = self._make_manager([
            self._make_peer('blacklisted.com', last_good=time.time()),
        ])
        pm.blacklist = {'blacklisted.com'}
        recent = pm._get_recent_good_peers()
        assert len(recent) == 0

    def test_permit_new_onion_peer(self):
        pm, _ = self._make_manager()
        now = time.time()
        result1 = pm._permit_new_onion_peer(now)
        result2 = pm._permit_new_onion_peer(now)
        # First call should succeed, second should be blocked (same time)
        assert result1 is True
        assert result2 is False

    def test_features_to_register_disabled(self):
        pm, mock_env = self._make_manager()
        mock_env.peer_announce = False
        peer = self._make_peer('remote.example.com')
        result = pm._features_to_register(peer, [])
        assert result is None

    def test_features_to_register_not_public(self):
        pm, mock_env = self._make_manager()
        mock_env.report_services = []  # No public services
        peer = self._make_peer('remote.example.com')
        result = pm._features_to_register(peer, [])
        assert result is None

    def test_features_to_register_already_present(self):
        pm, mock_env = self._make_manager()
        mock_env.peer_announce = True
        mock_env.report_services = [MagicMock(host='1.2.3.4')]
        peer = self._make_peer('1.2.3.4')
        remote_peers = [Peer('1.2.3.4', {'hosts': {'1.2.3.4': {'ssl_port': 50002, 'tcp_port': 50001}}})]
        result = pm._features_to_register(peer, remote_peers)
        assert result is None  # Already registered

    def test_info(self):
        now = int(time.time())
        pm, _ = self._make_manager([
            self._make_peer('peer1.example.com', last_good=now),
            self._make_peer('peer2.example.com', last_good=now),
        ])
        info = pm.info()
        assert info['total'] == 2
        assert info['good'] == 2

    def test_info_with_bad_peer(self):
        now = int(time.time())
        pm, _ = self._make_manager([
            self._make_peer('good.example.com', last_good=now),
            self._make_peer('bad.example.com', bad=True),
        ])
        info = pm.info()
        assert info['total'] == 2
        assert info['good'] == 1
        assert info['bad'] == 1

    def test_my_clearnet_peer_no_services(self):
        pm, mock_env = self._make_manager()
        mock_env.report_services = []
        result = pm._my_clearnet_peer()
        assert result is None

    def test_my_clearnet_peer_with_services(self):
        mock_env = MagicMock()
        mock_env.coin.PEER_DEFAULT_PORTS = {'s': 50002, 't': 50001}
        mock_env.report_services = []
        mock_env.peer_announce = True
        mock_env.force_proxy = False
        mock_env.peer_discovery = 'ON'
        mock_env.blacklist_url = None
        mock_env.services = []

        mock_service = MagicMock()
        mock_service.host = '1.2.3.4'
        mock_env.report_services = [mock_service]

        # Mock the session class server_features to return a dict
        mock_sclass = MagicMock()
        mock_sclass.server_features.return_value = {'hosts': {'1.2.3.4': {'ssl_port': 50002}}}
        mock_sclass.server_version_args.return_value = []
        mock_env.coin.SESSIONCLS = mock_sclass

        pm = PeerManager(mock_env, MagicMock())
        result = pm._my_clearnet_peer()
        assert result is not None
        assert result.host == '1.2.3.4'

    def test_note_peers_adds_new(self):
        pm, _ = self._make_manager()
        new_peer = self._make_peer('new.example.com')
        with patch('asyncio.create_task'):
            result = asyncio.get_event_loop().run_until_complete(
                pm._note_peers([new_peer], limit=0)
            )
        assert result is True
        assert any(p.host == 'new.example.com' for p in pm.peers)

    def test_note_peers_skips_duplicate(self):
        pm, _ = self._make_manager([
            self._make_peer('existing.example.com'),
        ])
        new_peer = self._make_peer('existing.example.com')
        with patch('asyncio.create_task'):
            result = asyncio.get_event_loop().run_until_complete(
                pm._note_peers([new_peer], limit=0)
            )
        assert result is True
        # Should only have one copy
        count = sum(1 for p in pm.peers if p.host == 'existing.example.com')
        assert count == 1

    def test_note_peers_skips_non_public(self):
        pm, _ = self._make_manager()
        private_peer = self._make_peer('192.168.1.1', ip_addr='192.168.1.1')
        with patch('asyncio.create_task'):
            result = asyncio.get_event_loop().run_until_complete(
                pm._note_peers([private_peer], limit=0)
            )
        assert result is True
        # Private peers should be skipped
        assert not any(p.host == '192.168.1.1' for p in pm.peers)

    def test_note_peers_skips_tor_without_proxy(self):
        pm, _ = self._make_manager()
        pm.proxy = None  # No proxy
        tor_peer = self._make_peer('abc123.onion')
        with patch('asyncio.create_task'):
            result = asyncio.get_event_loop().run_until_complete(
                pm._note_peers([tor_peer], limit=0)
            )
        assert result is True
        assert not any(p.host == 'abc123.onion' for p in pm.peers)

    def test_note_peers_limit(self):
        pm, _ = self._make_manager()
        peers = [self._make_peer(f'peer{i}.example.com') for i in range(10)]
        with patch('asyncio.create_task'):
            result = asyncio.get_event_loop().run_until_complete(
                pm._note_peers(peers, limit=3)
            )
        assert result is True
        assert len(pm.peers) == 3

    def test_bucket_for_external_ipv4(self):
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        peer.ip_addr = '192.0.2.100'
        bucket = peer.bucket_for_external_interface()
        assert '/' in bucket  # /16 subnet

    def test_bucket_for_external_ipv6(self):
        peer = Peer('test.example.com', {'hosts': {'test.example.com': {'ssl_port': 50002}}})
        peer.ip_addr = '2001:db8::1'
        bucket = peer.bucket_for_external_interface()
        assert '/' in bucket  # /56 subnet

    def test_bucket_for_external_onion(self):
        peer = Peer('abc123.onion', {'hosts': {'abc123.onion': {'ssl_port': 50002}}})
        bucket = peer.bucket_for_external_interface()
        assert bucket == 'onion'

    def test_peer_server_version_and_pruning(self):
        features = {
            'hosts': {'test.example.com': {'ssl_port': 50002}},
            'server_version': 'ElectrumX 1.0.0',
            'pruning': '1000',
        }
        peer = Peer('test.example.com', features)
        assert peer.server_version == 'ElectrumX 1.0.0'
        assert peer.pruning == 1000

    def test_peer_protocol_versions(self):
        features = {
            'hosts': {'test.example.com': {'ssl_port': 50002}},
            'protocol_min': '1.0',
            'protocol_max': '1.1',
        }
        peer = Peer('test.example.com', features)
        assert peer.protocol_min == '1.0'
        assert peer.protocol_max == '1.1'

    def test_peer_genesis_hash(self):
        features = {
            'hosts': {'test.example.com': {'ssl_port': 50002}},
            'genesis_hash': '000000000019d6689c085ae165831e934ff763ae46a2a6c172b3f1b60a8ce26f',
        }
        peer = Peer('test.example.com', features)
        assert peer.genesis_hash == features['genesis_hash']

    def test_peer_genesis_hash_none(self):
        features = {'hosts': {'test.example.com': {'ssl_port': 50002}}}
        peer = Peer('test.example.com', features)
        assert peer.genesis_hash is None

    def test_peer_is_valid_hostname(self):
        peer = Peer('valid-host.example.com', {'hosts': {'valid-host.example.com': {'ssl_port': 50002}}})
        assert peer.is_valid is True

    def test_peer_is_valid_ip(self):
        peer = Peer('8.8.8.8', {'hosts': {'8.8.8.8': {'ssl_port': 50002}}})
        assert peer.is_valid is True

    def test_peer_is_not_valid_multicast(self):
        peer = Peer('224.0.0.1', {'hosts': {'224.0.0.1': {'ssl_port': 50002}}})
        assert peer.is_valid is False

    def test_peer_is_not_valid_unspecified(self):
        peer = Peer('0.0.0.0', {'hosts': {'0.0.0.0': {'ssl_port': 50002}}})
        assert peer.is_valid is False
