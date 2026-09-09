"""Unit tests for the fuzzy matcher (pure logic)."""

from pauk.fuzzy import fuzzy_filter, match_span


def test_match_span_basics():
    assert match_span("", "anything") == 0
    assert match_span("abc", "abc") == 3
    assert match_span("ac", "abc") == 3
    assert match_span("abc", "a-b-c") == 5
    assert match_span("x", "abc") is None
    assert match_span("ba", "ab") is None  # order matters


def test_match_span_case_insensitive():
    assert match_span("ITA", "italian/verbs") == 3


def test_match_span_picks_tightest_window():
    # 'vb' matches from the first 'v' with span 5 ("vocab"), but
    # the tightest window is inside "verbs": v..b = span 4
    assert match_span("vb", "vocab/verbs") == 4
    assert match_span("verb", "italian/verbs") == 4


def test_fuzzy_filter_orders_by_tightness():
    items = ["italian/a1", "italian/verbs/core-verbs", "greek/lowercase"]
    result = fuzzy_filter("verb", items, key=lambda s: s)
    assert result == ["italian/verbs/core-verbs"]
    result = fuzzy_filter("ia", items, key=lambda s: s)
    # 'ia' appears tightest in 'italian' (span 4: 'ital'? i..a) —
    # both italian entries match, greek does not ('ia' not a subsequence? g-r-e-e-k...)
    assert result[0].startswith("italian")
    assert "greek/lowercase" not in result


def test_fuzzy_filter_keeps_input_order_on_ties():
    items = ["bb-a", "aa-b"]
    assert fuzzy_filter("a", items, key=lambda s: s) == ["bb-a", "aa-b"]
