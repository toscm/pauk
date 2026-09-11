"""Unit tests for the client-side stale-while-revalidate cache.

These never touch the API: the client's network layer (`_call`) is
replaced with a counter that returns controllable payloads, so we can
assert exactly when a request hits the network versus the cache.
XDG_CACHE_HOME is redirected per-test by the autouse fixture in
conftest, so each test gets a fresh, isolated cache directory.
"""

from __future__ import annotations

import time

import pauk.client as client_mod
from pauk.cache import Cache, cache_root, clear_all
from pauk.client import Client


def _counting_client(token: str = "tok", cache: bool = True) -> Client:
    """A Client whose `_call` counts invocations and returns a payload
    that changes every call, so staleness/refresh is observable."""
    c = Client("http://example.invalid", token, cache=cache)
    c.calls = []

    def fake_call(method, path, **kwargs):
        c.calls.append((method, path))
        # a monotonically increasing marker per call
        return {"items": [{"n": len(c.calls)}], "n": len(c.calls)}

    c._call = fake_call
    return c


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "condition not met within timeout"


# --- the Cache primitive -------------------------------------------
def test_cache_set_get_roundtrip():
    cache = Cache("id-a")
    key = Cache.key("GET", "/quiz/dirs", None)
    assert cache.get(key) is None                 # miss
    cache.set(key, {"items": [1, 2]}, "/quiz/dirs")
    value, age = cache.get(key)
    assert value == {"items": [1, 2]}
    assert age >= 0.0


def test_key_is_param_order_independent():
    a = Cache.key("GET", "/cards", {"dir": 3, "n": 20})
    b = Cache.key("GET", "/cards", {"n": 20, "dir": 3})
    assert a == b
    assert Cache.key("GET", "/cards", {"dir": 4}) != a


def test_clear_and_clear_paths():
    cache = Cache("id-b")
    k1 = Cache.key("GET", "/quiz/dirs", None)
    k2 = Cache.key("GET", "/stats", None)
    cache.set(k1, 1, "/quiz/dirs")
    cache.set(k2, 2, "/stats")
    cache.clear_paths({"/quiz/dirs"})
    assert cache.get(k1) is None                  # dropped
    assert cache.get(k2) is not None              # kept
    cache.clear()
    assert cache.get(k2) is None


def test_disabled_cache_is_noop():
    cache = Cache("id-c", enabled=False)
    key = Cache.key("GET", "/x", None)
    cache.set(key, 1, "/x")
    assert cache.get(key) is None


# --- Client integration --------------------------------------------
def test_hit_avoids_network():
    c = _counting_client()
    assert c.quiz_dirs() == [{"n": 1}]
    assert len(c.calls) == 1                      # miss → one request
    assert c.quiz_dirs() == [{"n": 1}]            # served from cache
    assert len(c.calls) == 1                      # no further request


def test_stale_entry_refreshes_in_background(monkeypatch):
    # make the entry count as stale so the next read triggers a refresh
    monkeypatch.setitem(client_mod._TTL, "/quiz/dirs", 0.0)
    c = _counting_client()
    assert c.quiz_dirs() == [{"n": 1}]            # miss, stores n=1
    # stale hit: returns the OLD value immediately, refreshes behind it
    assert c.quiz_dirs() == [{"n": 1}]
    # the background refresh fetches again and updates the cache so the
    # fresh value is served next time (asserted on the stored entry so a
    # re-read does not itself trigger another refresh)
    key = Cache.key("GET", "/quiz/dirs", None)
    _wait_until(lambda: (c._cache.get(key) or (None,))[0] == {"items": [{"n": 2}], "n": 2})
    assert len(c.calls) == 2                       # exactly one refresh ran


def test_per_identity_keying():
    a = _counting_client(token="user-a")
    b = _counting_client(token="user-b")
    a.quiz_dirs()
    assert len(a.calls) == 1
    # b has a different identity → its own cache dir → a real request,
    # not a's cached payload
    assert b.quiz_dirs() == [{"n": 1}]
    assert len(b.calls) == 1


def test_write_invalidates_cache():
    c = _counting_client()
    c.quiz_dirs()
    c.quiz_dirs()
    assert len(c.calls) == 1                      # second was a hit
    c.create_card({"type": "text", "question_md": "q", "accepted_answers": ["a"]})
    assert len(c.calls) == 2                      # the POST
    c.quiz_dirs()
    assert len(c.calls) == 3                      # cache busted → refetch


def test_start_run_keeps_card_batch_but_busts_dirs():
    c = _counting_client()
    c.quiz_cards(None, True, 20)                  # miss → cached
    c.quiz_dirs()                                 # miss → cached
    assert len(c.calls) == 2
    c.start_run(None, 0, ranked=False)            # write: only /quiz/dirs
    assert len(c.calls) == 3
    c.quiz_cards(None, True, 20)                  # still cached
    assert len(c.calls) == 3
    c.quiz_dirs()                                 # busted → refetch
    assert len(c.calls) == 4


def test_no_cache_bypasses_everything():
    c = _counting_client(cache=False)
    c.quiz_dirs()
    c.quiz_dirs()
    assert len(c.calls) == 2                      # every read hits the network


def test_pauk_no_cache_env(monkeypatch):
    monkeypatch.setenv("PAUK_NO_CACHE", "1")
    c = _counting_client()                        # constructed with env set
    c.quiz_dirs()
    c.quiz_dirs()
    assert len(c.calls) == 2


def test_clear_all_removes_cache_root():
    cache = Cache("id-d")
    cache.set(Cache.key("GET", "/x", None), 1, "/x")
    assert cache_root().exists()
    clear_all()
    assert not cache_root().exists()
