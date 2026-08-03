'''Tests for lrucache.py — Cache and LRUCache implementations.'''
import pytest

from electrumx.lib.lrucache import Cache, LRUCache


# --- Cache tests ---

class TestCache:
    '''Tests for the base Cache class.'''

    def test_cache_init(self):
        cache = Cache(10)
        assert cache.maxsize == 10
        assert cache.currsize == 0
        assert len(cache) == 0
        assert cache.num_lookups == 0
        assert cache.num_hits == 0

    def test_cache_setitem_getitem(self):
        cache = Cache(10)
        cache['a'] = 1
        cache['b'] = 2
        assert cache['a'] == 1
        assert cache['b'] == 2
        assert len(cache) == 2
        assert cache.currsize == 2

    def test_cache_contains(self):
        cache = Cache(10)
        cache['a'] = 1
        assert 'a' in cache
        assert 'b' not in cache

    def test_cache_get_existing(self):
        cache = Cache(10)
        cache['a'] = 1
        assert cache.get('a') == 1
        assert cache.get('a', 99) == 1

    def test_cache_get_missing(self):
        cache = Cache(10)
        assert cache.get('a') is None
        assert cache.get('a', 99) == 99

    def test_cache_getitem_missing_raises(self):
        cache = Cache(10)
        with pytest.raises(KeyError):
            _ = cache['a']

    def test_cache_delitem(self):
        cache = Cache(10)
        cache['a'] = 1
        del cache['a']
        assert len(cache) == 0
        assert 'a' not in cache

    def test_cache_delitem_missing(self):
        cache = Cache(10)
        with pytest.raises(KeyError):
            del cache['a']

    def test_cache_pop_existing(self):
        cache = Cache(10)
        cache['a'] = 1
        value = cache.pop('a')
        assert value == 1
        assert len(cache) == 0

    def test_cache_pop_missing_no_default(self):
        cache = Cache(10)
        with pytest.raises(KeyError):
            cache.pop('a')

    def test_cache_pop_missing_with_default(self):
        cache = Cache(10)
        value = cache.pop('a', 99)
        assert value == 99

    def test_cache_popitem_empty(self):
        cache = Cache(10)
        with pytest.raises(KeyError):
            cache.popitem()

    def test_cache_setdefault_existing(self):
        cache = Cache(10)
        cache['a'] = 1
        result = cache.setdefault('a', 99)
        assert result == 1
        assert cache['a'] == 1

    def test_cache_setdefault_missing(self):
        cache = Cache(10)
        result = cache.setdefault('a', 99)
        assert result == 99
        assert cache['a'] == 99

    def test_cache_setdefault_missing_none(self):
        cache = Cache(10)
        result = cache.setdefault('a')
        assert result is None
        assert cache['a'] is None

    def test_cache_iteration(self):
        cache = Cache(10)
        cache['a'] = 1
        cache['b'] = 2
        keys = list(cache)
        assert set(keys) == {'a', 'b'}

    def test_cache_repr(self):
        cache = Cache(10)
        cache['a'] = 1
        r = repr(cache)
        assert 'Cache' in r
        assert "maxsize=10" in r
        assert "'a'" in r

    def test_cache_value_too_large(self):
        cache = Cache(10)

        class BigValue:
            pass

        # Each item counts as size 1 by default, so this should work
        cache['a'] = BigValue()
        assert 'a' in cache

    def test_cache_value_too_large_custom_size(self):
        def size_of(v):
            return len(v) if isinstance(v, str) else 1

        cache = Cache(5, getsizeof=size_of)
        cache['a'] = 'hi'  # size 2
        assert cache.currsize == 2

        # 'hello' has size 5, fits exactly
        cache['b'] = 'hello'  # size 5, should evict 'a'
        assert 'a' not in cache
        assert cache['b'] == 'hello'
        assert cache.currsize == 5

    def test_cache_custom_getsizeof(self):
        def size_of(v):
            return len(v)

        cache = Cache(100, getsizeof=size_of)
        cache['a'] = 'hello'  # size 5
        assert cache.currsize == 5

    def test_cache_eviction(self):
        cache = Cache(3)
        cache['a'] = 1
        cache['b'] = 2
        cache['c'] = 3
        assert len(cache) == 3
        assert cache.currsize == 3

        # Adding 'd' should evict 'a'
        cache['d'] = 4
        assert 'a' not in cache
        assert 'b' in cache
        assert 'c' in cache
        assert 'd' in cache
        assert len(cache) == 3

    def test_cache_update_size_on_replace(self):
        def size_of(v):
            return len(v) if isinstance(v, str) else 1

        cache = Cache(20, getsizeof=size_of)
        cache['a'] = 'hi'  # size 2
        assert cache.currsize == 2

        # Replace with larger value
        cache['a'] = 'hello world'  # size 11
        assert cache['a'] == 'hello world'
        assert cache.currsize == 11

    def test_cache_eviction(self):
        cache = Cache(3)
        cache['a'] = 1
        cache['b'] = 2
        cache['c'] = 3
        assert len(cache) == 3
        assert cache.currsize == 3

        # Adding 'd' should evict 'a'
        cache['d'] = 4
        assert 'a' not in cache
        assert 'b' in cache
        assert 'c' in cache
        assert 'd' in cache
        assert len(cache) == 3


# --- LRUCache tests ---

class TestLRUCache:
    '''Tests for the LRUCache class.'''

    def test_lru_init(self):
        cache = LRUCache(10)
        assert cache.maxsize == 10
        assert cache.currsize == 0

    def test_lru_basic_get_set(self):
        cache = LRUCache(10)
        cache['a'] = 1
        cache['b'] = 2
        assert cache['a'] == 1
        assert cache['b'] == 2

    def test_lru_eviction_order(self):
        cache = LRUCache(3)
        cache['a'] = 1
        cache['b'] = 2
        cache['c'] = 3

        # Access 'a' to make it recently used
        _ = cache['a']

        # Add 'd' — should evict 'b' (least recently used)
        cache['d'] = 4
        assert 'a' in cache
        assert 'b' not in cache  # evicted
        assert 'c' in cache
        assert 'd' in cache

    def test_lru_popitem(self):
        cache = LRUCache(3)
        cache['a'] = 1
        cache['b'] = 2
        cache['c'] = 3

        # 'a' is least recently used
        key, value = cache.popitem()
        assert key == 'a'
        assert value == 1
        assert len(cache) == 2

    def test_lru_popitem_access_changes_order(self):
        cache = LRUCache(3)
        cache['a'] = 1
        cache['b'] = 2
        cache['c'] = 3

        # Access 'a' to make it recently used
        _ = cache['a']

        # Now 'b' is least recently used
        key, value = cache.popitem()
        assert key == 'b'
        assert value == 2

    def test_lru_popitem_empty(self):
        cache = LRUCache(10)
        with pytest.raises(KeyError, match='is empty'):
            cache.popitem()

    def test_lru_eviction_with_access(self):
        cache = LRUCache(2)
        cache['a'] = 1
        cache['b'] = 2

        # Access 'a' — it becomes recently used
        _ = cache['a']

        # Add 'c' — should evict 'b'
        cache['c'] = 3
        assert 'a' in cache
        assert 'b' not in cache
        assert 'c' in cache

    def test_lru_contains(self):
        cache = LRUCache(10)
        cache['a'] = 1
        assert 'a' in cache
        assert 'b' not in cache

    def test_lru_get(self):
        cache = LRUCache(10)
        cache['a'] = 1
        assert cache.get('a') == 1
        assert cache.get('b') is None
        assert cache.get('b', 99) == 99

    def test_lru_delitem(self):
        cache = LRUCache(10)
        cache['a'] = 1
        cache['b'] = 2
        del cache['a']
        assert 'a' not in cache
        assert 'b' in cache

    def test_lru_delitem_missing(self):
        cache = LRUCache(10)
        with pytest.raises(KeyError):
            del cache['a']

    def test_lru_pop(self):
        cache = LRUCache(10)
        cache['a'] = 1
        cache['b'] = 2
        value = cache.pop('a')
        assert value == 1
        assert 'a' not in cache
        assert 'b' in cache

    def test_lru_pop_missing(self):
        cache = LRUCache(10)
        with pytest.raises(KeyError):
            cache.pop('a')

    def test_lru_pop_with_default(self):
        cache = LRUCache(10)
        value = cache.pop('a', 99)
        assert value == 99

    def test_lru_setdefault(self):
        cache = LRUCache(10)
        cache['a'] = 1
        result = cache.setdefault('a', 99)
        assert result == 1

        result = cache.setdefault('b', 2)
        assert result == 2
        assert cache['b'] == 2

    def test_lru_iteration(self):
        cache = LRUCache(10)
        cache['a'] = 1
        cache['b'] = 2
        keys = list(cache)
        assert set(keys) == {'a', 'b'}

    def test_lru_repr(self):
        cache = LRUCache(10)
        cache['a'] = 1
        r = repr(cache)
        assert 'LRUCache' in r
        assert 'maxsize=10' in r

    def test_lru_large_value_replaces_small(self):
        def size_of(v):
            return len(v) if isinstance(v, str) else 1

        cache = LRUCache(10, getsizeof=size_of)
        cache['a'] = 'x'  # size 1
        cache['b'] = 'y'  # size 1
        # 'a' is LRU, 'b' is MRU

        # Replace 'a' with larger value — should work
        cache['a'] = 'hello'  # size 5, currsize was 2, now 6
        assert cache['a'] == 'hello'
        assert cache.currsize == 6

    def test_lru_getitem_triggers_update(self):
        '''Reading a key should move it to recently used.'''
        cache = LRUCache(3)
        cache['a'] = 1
        cache['b'] = 2
        cache['c'] = 3

        # Access 'a' to make it MRU
        _ = cache['a']

        # Add 'd' — should evict 'b' (now LRU)
        cache['d'] = 4
        assert 'b' not in cache
        assert 'a' in cache

    def test_lru_missing_does_not_update(self):
        '''__missing__ should not update the LRU order.'''
        cache = LRUCache(3)
        cache['a'] = 1
        cache['b'] = 2
        cache['c'] = 3

        # Access non-existent key — should raise, not affect order
        with pytest.raises(KeyError):
            _ = cache['d']

        # 'a' should still be LRU (same as if we hadn't accessed 'd')
        cache['e'] = 5  # size 1, currsize was 3, evicts 'a'
        assert 'a' not in cache  # 'a' was evicted, not 'c'
        assert 'b' in cache
        assert 'c' in cache
        assert 'e' in cache
