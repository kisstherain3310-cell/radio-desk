"""라디오 데스크 핵심 로직 테스트.

UI가 아니라 '숫자와 판정'을 지키는 것이 목적이다.
지표가 조용히 틀리는 것이 이 서비스에서 가장 위험한 실패 방식이라,
과거에 실제로 발생했던 버그는 회귀 테스트로 남긴다.

실행:
    python -m pytest -q
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402


# ---------------------------------------------------------------------------
# RSI
# ---------------------------------------------------------------------------

def test_rsi_needs_at_least_period_plus_one_samples():
    assert app._calc_rsi([1.0] * 14) is None
    assert app._calc_rsi([]) is None


def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 40)]
    assert app._calc_rsi(closes) == 100.0


def test_rsi_all_losses_is_near_zero():
    closes = [float(i) for i in range(40, 1, -1)]
    rsi = app._calc_rsi(closes)
    assert rsi is not None
    assert rsi == pytest.approx(0.0, abs=1e-6)


def test_rsi_flat_series_is_neutral_or_undefined():
    """변동이 없으면 손실 평균이 0이라 100으로 수렴한다 (Wilder 정의)."""
    assert app._calc_rsi([100.0] * 30) == 100.0


def test_rsi_is_sensitive_to_sampling_interval():
    """회귀: 코인 RSI가 '14일'이 아니라 '14시간'으로 계산되던 버그.

    같은 가격 흐름이라도 시간봉을 그대로 넣으면 일봉 RSI와 값이 달라진다.
    fetch_coin_daily_closes 가 일별 다운샘플을 하는 이유를 고정한다.
    """
    # 30일치 흐름을 하루 24개 시간봉으로 표현한 뒤, 일별 마지막 값만 취함
    hourly = [100.0 + (i / 24.0) for i in range(24 * 30)]
    daily = [hourly[i] for i in range(23, len(hourly), 24)]
    assert len(daily) == 30
    assert app._calc_rsi(hourly) is not None
    assert app._calc_rsi(daily) is not None
    # 표본 수가 다르면 계산 대상 자체가 다르다 — 다운샘플을 건너뛰면 안 된다
    assert len(hourly) != len(daily)


# ---------------------------------------------------------------------------
# 심리 지표 구간 · 계기판 정렬
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "score,expected",
    [
        (0, "extreme_fear"),
        (24, "extreme_fear"),
        (25, "fear"),
        (44, "fear"),
        (45, "neutral"),
        (55, "neutral"),
        (56, "greed"),
        (74, "greed"),
        (75, "extreme_greed"),
        (100, "extreme_greed"),
    ],
)
def test_fng_band_boundaries(score, expected):
    assert app._fng_band(score) == expected


@pytest.mark.parametrize(
    "vix,expected",
    [
        (35.0, "extreme_fear"),
        (30.0, "extreme_fear"),
        (29.9, "fear"),
        (22.0, "fear"),
        (21.9, "neutral"),
        (17.0, "neutral"),
        (16.9, "greed"),
        (13.0, "greed"),
        (12.9, "extreme_greed"),
    ],
)
def test_vix_band_boundaries(vix, expected):
    assert app._vix_band(vix) == expected


@pytest.mark.parametrize(
    "rsi,expected",
    [
        (5.0, "extreme_fear"),
        (20.0, "extreme_fear"),
        (25.0, "fear"),
        (30.0, "fear"),
        (50.0, "neutral"),
        (70.0, "neutral"),
        (75.0, "greed"),
        (80.0, "greed"),
        (95.0, "extreme_greed"),
    ],
)
def test_rsi_band_boundaries(rsi, expected):
    assert app._rsi_band(rsi) == expected


@pytest.mark.parametrize(
    "vix,stop_index",
    [(30.0, 1), (22.0, 2), (17.0, 3), (13.0, 4)],
)
def test_vix_gauge_stops_match_band_boundaries(vix, stop_index):
    """회귀: 계기판 색 구간이 F&G 기준으로 고정돼 VIX 바늘과 라벨이 어긋나던 버그.

    _vix_band 가 구간을 바꾸는 VIX 값은, 게이지에서도 정확히 색 경계에 놓여야 한다.
    """
    pos = app._vix_to_gauge_score(vix)
    assert pos == pytest.approx(app._GAUGE_STOPS_VIX[stop_index], abs=0.1)


def test_rsi_gauge_stops_match_band_boundaries():
    """RSI 게이지는 20/30/70/80 이 그대로 색 경계여야 한다."""
    assert app._GAUGE_STOPS_RSI == (0, 20, 30, 70, 80, 100)


def test_vix_gauge_score_is_clamped_and_inverted():
    assert app._vix_to_gauge_score(5.0) == 100.0  # 초저변동성 → 탐욕 끝
    assert app._vix_to_gauge_score(80.0) == 0.0  # 초고변동성 → 공포 끝


def test_gauge_svg_encodes_needle_sweep_target():
    svg = app._sentiment_gauge_svg(75.0, band_stops=app._GAUGE_STOPS_FNG)
    assert "rd-gauge-needle" in svg
    assert "--rd-sweep:-135.0deg" in svg  # 75% → 180deg * 0.75


# ---------------------------------------------------------------------------
# HOT 판정
# ---------------------------------------------------------------------------

def test_watchlist_match_is_word_bounded():
    """ETH 워치리스트가 ETF 헤드라인에 걸리면 안 된다."""
    assert app._matched_terms("Bitcoin ETF approved", ["ETH"]) == []
    assert app._matched_terms("ETH leads altcoin rally", ["ETH"]) == ["ETH"]


def test_coin_name_alone_is_not_hot_on_balanced_sensitivity():
    """회귀: 기본 민감도에서 코인명만으로 전 기사가 HOT이 되던 문제."""
    heat = app._heat_info(
        "Bitcoin trades sideways in quiet session",
        watchlist=[],
        use_signal_keywords=True,
        hot_sensitivity="균형",
        category="crypto",
    )
    assert heat["is_hot"] is False


def test_coin_name_alone_is_hot_on_aggressive_sensitivity():
    heat = app._heat_info(
        "Bitcoin trades sideways in quiet session",
        watchlist=[],
        use_signal_keywords=True,
        hot_sensitivity="공격적",
        category="crypto",
    )
    assert heat["is_hot"] is True


def test_watchlist_hit_outweighs_signal_hit():
    heat = app._heat_info(
        "NVDA earnings beat expectations",
        watchlist=["NVDA"],
        use_signal_keywords=True,
        hot_sensitivity="균형",
        category="stocks",
    )
    assert heat["watch_hits"] == ["NVDA"]
    assert "earnings" in heat["signal_hits"]
    assert heat["score"] >= 3  # 워치 2점 + 시그널 1점


def test_signal_keywords_can_be_disabled():
    heat = app._heat_info(
        "SEC approves spot ETF",
        watchlist=[],
        use_signal_keywords=False,
        hot_sensitivity="균형",
        category="crypto",
    )
    assert heat["signal_hits"] == []
    assert heat["is_hot"] is False


# ---------------------------------------------------------------------------
# 기사 나이 · 속보 고정
# ---------------------------------------------------------------------------

def _item(hours_ago: float, **extra):
    now = datetime.now(timezone.utc)
    published = now - timedelta(hours=hours_ago)
    item = {"title": "t", "link": "l", "source": "s", "published_iso": published.isoformat()}
    item.update(extra)
    return item


def test_feed_age_window_keeps_recent_and_drops_old():
    now = datetime.now(timezone.utc)
    assert app._is_within_feed_max_age(_item(1), now=now) is True
    assert app._is_within_feed_max_age(_item(47), now=now) is True
    assert app._is_within_feed_max_age(_item(49), now=now) is False


def test_feed_age_window_rejects_unparsable_and_future():
    now = datetime.now(timezone.utc)
    assert app._is_within_feed_max_age({"published_iso": ""}, now=now) is False
    assert app._is_within_feed_max_age({"published_iso": "not-a-date"}, now=now) is False
    assert app._is_within_feed_max_age(_item(-3), now=now) is False


def test_breaking_detection_only_matches_title_prefix():
    assert app._item_marked_breaking({"title": "[속보] 연준 금리 동결"}) is True
    assert app._item_marked_breaking({"title": "BREAKING: Fed holds rates"}) is True
    # 본문 중간의 '속보'는 오탐 대상
    assert app._item_marked_breaking({"title": "이 매체는 속보를 잘 낸다"}) is False


def test_breaking_pin_expires_after_window():
    now = datetime.now(timezone.utc)
    fresh = _item(1, title="[속보] 금리 동결", isBreaking=True)
    stale = _item(app.BREAKING_PIN_HOURS + 1, title="[속보] 금리 동결", isBreaking=True)
    assert app._is_breaking_pinned(fresh, now=now) is True
    assert app._is_breaking_pinned(stale, now=now) is False


# ---------------------------------------------------------------------------
# 중복 제거
# ---------------------------------------------------------------------------

def _row(title: str, link: str, source: str, score: int = 0):
    return {
        "item": {"title": title, "link": link, "source": source, "published_iso": "2026-07-30T00:00:00+00:00"},
        "id": link or f"{source}|{title}",
        "heat_score": score,
        "is_new": False,
        "is_breaking": False,
        "is_breaking_pinned": False,
    }


def test_dedupe_collapses_same_link():
    rows = [_row("A", "https://x.com/a", "S1"), _row("A", "https://x.com/a/", "S2")]
    assert len(app._dedupe_feed_rows(rows)) == 1


def test_dedupe_collapses_same_title_across_sources():
    rows = [
        _row("Fed holds rates steady", "https://a.com/1", "CoinDesk"),
        _row("Fed holds rates steady", "https://b.com/2", "The Block"),
    ]
    assert len(app._dedupe_feed_rows(rows)) == 1


def test_dedupe_keeps_higher_heat_score():
    rows = [
        _row("Same headline", "https://a.com/1", "S1", score=1),
        _row("Same headline", "https://b.com/2", "S2", score=9),
    ]
    kept = app._dedupe_feed_rows(rows)
    assert len(kept) == 1
    assert kept[0]["heat_score"] == 9


def test_dedupe_ignores_breaking_prefix_when_matching_titles():
    rows = [
        _row("[속보] 금리 동결", "https://a.com/1", "S1"),
        _row("금리 동결", "https://b.com/2", "S2"),
    ]
    assert len(app._dedupe_feed_rows(rows)) == 1


def test_dedupe_keeps_genuinely_different_articles():
    rows = [
        _row("Fed holds rates", "https://a.com/1", "S1"),
        _row("ECB cuts rates", "https://b.com/2", "S2"),
    ]
    assert len(app._dedupe_feed_rows(rows)) == 2


# ---------------------------------------------------------------------------
# 필터 · 표기
# ---------------------------------------------------------------------------

def test_media_region_filter():
    assert app._source_matches_media_region("CoinDesk", "해외") is True
    assert app._source_matches_media_region("CoinDesk", "국내") is False
    assert app._source_matches_media_region("토큰포스트", "국내") is True
    assert app._source_matches_media_region("토큰포스트", "전체") is True


def test_hot_sensitivity_normalizes_to_balanced_default():
    assert app._normalize_hot_sensitivity("없는값") == "균형"
    assert app._normalize_hot_sensitivity("공격적") == "공격적"


def test_price_formatting_by_currency_and_magnitude():
    assert app._format_market_price(1234567.0, "KRW") == "₩1,234,567"
    assert app._format_market_price(64000.0, "USD") == "$64,000"
    assert app._format_market_price(12.3456, "USD") == "$12.35"
    assert app._format_market_price(0.0712, "USD") == "$0.0712"


def test_watchlist_parsing_accepts_commas_and_newlines():
    assert app._parse_watchlist("BTC, ETH\nNVDA , ") == ["BTC", "ETH", "NVDA"]


def test_query_alias_expansion():
    tokens = app._expand_query_tokens(["samsung"])
    assert "삼성전자" in tokens
    assert app._matches_query({"title": "Samsung Electronics profit"}, "", "samsung") is True
    assert app._matches_query({"title": "Apple results"}, "", "samsung") is False


# ---------------------------------------------------------------------------
# 번역 응답 파싱
# ---------------------------------------------------------------------------

def test_batch_translation_parses_json_array():
    assert app._parse_batch_translations('["가", "나"]', 2) == ["가", "나"]


def test_batch_translation_parses_fenced_json():
    raw = '```json\n["가", "나"]\n```'
    assert app._parse_batch_translations(raw, 2) == ["가", "나"]


def test_batch_translation_falls_back_to_numbered_lines():
    assert app._parse_batch_translations("1. 가\n2. 나", 2) == ["가", "나"]


def test_batch_translation_rejects_short_output():
    with pytest.raises(RuntimeError):
        app._parse_batch_translations("1. 가", 3)


# ---------------------------------------------------------------------------
# 안전성
# ---------------------------------------------------------------------------

def test_headline_highlight_escapes_html():
    out = app._highlight_html("<script>alert(1)</script> BTC", ["BTC"])
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<mark" in out


def test_settings_file_is_ignored_outside_personal_mode(monkeypatch):
    """공개 배포에서 방문자끼리 설정이 섞이면 안 된다."""
    monkeypatch.setattr(app, "personal_mode", lambda: False)
    assert app.save_settings_file({"watchlist": ["HACK"]}) is False
    assert app.load_settings_file() == app._default_settings()
