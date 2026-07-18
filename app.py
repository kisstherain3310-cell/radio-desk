# ============================================================
# Dual News Terminal — Crypto | Stocks (Tree News style MVP)
# ------------------------------------------------------------
# 필요 패키지 설치:
#   pip install streamlit streamlit-autorefresh feedparser google-generativeai python-dotenv
# 실행:
#   1) 로컬: .env 에 GEMINI_API_KEY / 클라우드: Streamlit Secrets
#   2) streamlit run app.py
#   3) 배포: https://share.streamlit.io → DEPLOY.md 참고
#
# 뉴스 출처 (공개 RSS, API 키 불필요)
# ============================================================

from __future__ import annotations

import html
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, unquote

import feedparser
import requests
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

def _load_gemini_api_key() -> str:
    """Streamlit Cloud Secrets 우선, 로컬은 .env / 환경변수."""
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return str(st.secrets["GEMINI_API_KEY"]).strip()
    except Exception:
        pass
    load_dotenv(Path(__file__).resolve().parent / ".env")
    return os.getenv("GEMINI_API_KEY", "").strip()


API_KEY = _load_gemini_api_key()

Category = Literal["crypto", "stocks"]
DisplayMode = Literal["both", "en", "ko"]

CRYPTO_FEEDS = [
    {"source": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/"},
    {"source": "Cointelegraph", "url": "https://cointelegraph.com/rss"},
    {"source": "Decrypt", "url": "https://decrypt.co/feed"},
    {"source": "The Block", "url": "https://www.theblock.co/rss.xml"},
    {"source": "Bitcoin Magazine", "url": "https://bitcoinmagazine.com/feed"},
    {"source": "Blockworks", "url": "https://blockworks.co/feed"},
]

STOCK_FEEDS = [
    {"source": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex"},
    {"source": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html"},
    {"source": "MarketWatch", "url": "https://feeds.marketwatch.com/marketwatch/topstories/"},
    {"source": "Bloomberg", "url": "https://feeds.bloomberg.com/markets/news.rss"},
    {"source": "NASDAQ", "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets"},
    {"source": "Seeking Alpha", "url": "https://seekingalpha.com/feed.xml"},
    {"source": "Fox Business", "url": "https://feeds.foxbusiness.com/foxbusiness/latest"},
    {"source": "WSJ Markets", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"},
    {"source": "Investing.com", "url": "https://www.investing.com/rss/news.rss"},
]

RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketNewsTerminal/1.0; +https://localhost)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

ALL_SOURCES = [f["source"] for f in CRYPTO_FEEDS + STOCK_FEEDS]
SETTINGS_PATH = Path(__file__).resolve().parent / "data" / "user_settings.json"
# 방문객 표시용 시각 — 항상 한국 표준시 (서머타임 없음)
KST = timezone(timedelta(hours=9))

# 워치리스트 외 시장 시그널 키워드 (Hot 점수 보강)
SIGNAL_KEYWORDS = [
    "ETF",
    "SEC",
    "Fed",
    "FOMC",
    "listing",
    "delist",
    "hack",
    "exploit",
    "bankrupt",
    "lawsuit",
    "approval",
    "reject",
    "rate cut",
    "rate hike",
    "earnings",
    "guidance",
    "upgrade",
    "downgrade",
    "merger",
    "acquisition",
    "IPO",
    "ATH",
    "crash",
    "rally",
    "상장",
    "해킹",
    "실적",
    "금리",
]

TRANSLATE_PROMPTS = {
    "crypto": (
        "너는 한국의 베테랑 코인 트레이더야. 다음 영어 속보를 직관적이고 간결한 한국어로 번역해. "
        "'Burn'은 '소각', 'Bullish'는 '강세/호재', 'Rug pull'은 '먹튀/러그풀', "
        "'ATH'는 '역대 최고점' 등 코인판 은어와 전문 용어를 자연스럽게 사용해. "
        "부연설명 없이 번역된 한 줄만 출력해."
    ),
    "stocks": (
        "너는 한국의 베테랑 주식 트레이더야. 다음 영어 속보를 직관적이고 간결한 한국어로 번역해. "
        "'Bullish'는 '강세/호재', 'Bearish'는 '약세/악재', 'Earnings'는 '실적', "
        "'Guidance'는 '가이던스', 'Rally'는 '급등', 'Sell-off'는 '매도세/급락' 등 "
        "주식·매크로 용어를 자연스럽게 사용해. 부연설명 없이 번역된 한 줄만 출력해."
    ),
}

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Noto+Sans+KR:wght@400;500;600;700;800&display=swap');

:root {
  --bg: #0d0f13;
  --bg-elevated: #12151b;
  --bg-hover: #161a22;
  --line: rgba(255, 255, 255, 0.055);
  --line-soft: rgba(255, 255, 255, 0.04);
  --text: #e6e8ee;
  --text-soft: #c4c8d0;
  --muted: #7a8290;
  --faint: #5a6270;
  --accent: #6e9fff;
  --accent-dim: rgba(110, 159, 255, 0.14);
  --accent-border: rgba(110, 159, 255, 0.28);
  --crypto: #7ec8a8;
  --stocks: #9aa8d8;
  --hot: #e8b84a;
  --new: #6e9fff;
}

html, body, [class*="css"] {
  font-family: 'Noto Sans KR', sans-serif;
}

.stApp {
  background:
    radial-gradient(1000px 480px at 8% -8%, rgba(110, 159, 255, 0.05), transparent 55%),
    radial-gradient(900px 420px at 92% 0%, rgba(126, 200, 168, 0.035), transparent 50%),
    var(--bg);
  color: var(--text);
}

#MainMenu, footer { visibility: hidden; }

/* 헤더는 완전히 숨기지 않음 — 사이드바 재열기 버튼이 여기 있음 */
header[data-testid="stHeader"] {
  background: transparent !important;
  color: transparent !important;
}
header[data-testid="stHeader"] * {
  color: var(--text) !important;
}
div[data-testid="stToolbar"] { display: none !important; }

/* Streamlit 기본 << / >> 사이드바 토글 숨김 (햄버거만 사용) */
[data-testid="stSidebarCollapseButton"],
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
section[data-testid="stSidebar"] button[kind="header"],
section[data-testid="stSidebar"] button[kind="headerNoPadding"],
section.stSidebar [data-testid="stBaseButton-header"],
section.stSidebar [data-testid="stBaseButton-headerNoPadding"] {
  display: none !important;
  visibility: hidden !important;
  pointer-events: none !important;
  width: 0 !important;
  height: 0 !important;
  overflow: hidden !important;
}
/* 사이드바 헤더의 Material double-arrow 버튼까지 제거 */
section.stSidebar button:has([data-testid="stIconMaterial"]) {
  display: none !important;
}

.block-container {
  padding: 0.7rem 1.1rem 1.4rem 1.1rem !important;
  max-width: 1480px;
}

.sidebar-open-hint {
  font-size: 0.78rem;
  color: var(--text-soft);
  margin: 0.15rem 0 0.85rem 0;
  padding: 0.55rem 0.7rem;
  border: 1px solid var(--accent-border);
  background: rgba(110, 159, 255, 0.08);
  border-radius: 8px;
}


section[data-testid="stSidebar"] {
  background: #0f1218;
  border-right: 1px solid var(--line);
}

section[data-testid="stSidebar"] .block-container {
  padding-top: 1.25rem !important;
  padding-bottom: 2rem !important;
}

section[data-testid="stSidebar"] .sidebar-label {
  font-size: 0.68rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--faint);
  margin: 0 0 0.55rem 0;
}

section[data-testid="stSidebar"] .sidebar-hint {
  font-size: 0.72rem;
  color: var(--faint);
  line-height: 1.45;
  margin-top: 0.4rem;
}

section[data-testid="stSidebar"] .stRadio > label { display: none; }

section[data-testid="stSidebar"] .stRadio [role="radiogroup"] { gap: 0.35rem; }

section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label {
  background: var(--bg-elevated);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 0.45rem 0.65rem !important;
  margin: 0 !important;
}

section[data-testid="stSidebar"] .stRadio [role="radiogroup"] label p {
  font-size: 0.84rem !important;
  color: var(--text-soft) !important;
}

section[data-testid="stSidebar"] .stTextInput input,
section[data-testid="stSidebar"] .stTextArea textarea {
  background: var(--bg-elevated) !important;
  color: var(--text) !important;
  border: 1px solid var(--line) !important;
  border-radius: 6px !important;
  font-size: 0.86rem !important;
  font-family: 'Noto Sans KR', sans-serif !important;
}

section[data-testid="stSidebar"] div[data-testid="stCheckbox"] label p {
  font-size: 0.82rem !important;
  color: var(--text-soft) !important;
}

.app-title-row {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  margin: 0 0 0.2rem 0;
}

.app-brand {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
  margin: 0;
}

.app-title {
  font-size: 1.55rem;
  font-weight: 800;
  color: #f3f5f9;
  margin: 0;
  letter-spacing: -0.04em;
  line-height: 1.15;
}

.app-subtitle {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-soft);
  margin: 0;
  letter-spacing: 0.02em;
  line-height: 1.25;
}

.app-sub {
  font-size: 0.8rem;
  font-weight: 400;
  color: var(--muted);
  margin: 0.15rem 0 0.65rem 0;
  padding-left: 0;
  letter-spacing: -0.01em;
}

/* 번역 토글 — 헤더 우측 끝 정렬 */
[data-testid="stColumn"]:has(.rd-translate-anchor) {
  display: flex !important;
  justify-content: flex-end !important;
  align-items: center !important;
}
[data-testid="stColumn"]:has(.rd-translate-anchor) > div,
[data-testid="stColumn"]:has(.rd-translate-anchor) [data-testid="stVerticalBlock"] {
  width: 100% !important;
  align-items: flex-end !important;
}
[data-testid="stColumn"]:has(.rd-translate-anchor) [data-testid="stCheckbox"],
[data-testid="stColumn"]:has(.rd-translate-anchor) [data-testid="stToggle"],
[data-testid="stColumn"]:has(.rd-translate-anchor) .stCheckbox,
[data-testid="stColumn"]:has(.rd-translate-anchor) .stToggle {
  display: flex !important;
  justify-content: flex-end !important;
  width: 100% !important;
}
[data-testid="stColumn"]:has(.rd-translate-anchor) label {
  justify-content: flex-end !important;
  margin-left: auto !important;
}
.rd-translate-anchor {
  display: none;
}

.panel-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.5rem;
  border-bottom: 1px solid var(--line);
  padding-bottom: 0.5rem;
  margin-bottom: 0.25rem;
}

.panel-title {
  font-size: 1.05rem;
  font-weight: 800;
  letter-spacing: 0.06em;
}

.panel-title.crypto { color: var(--crypto); }
.panel-title.stocks { color: var(--stocks); }

.panel-meta {
  font-size: 0.68rem;
  font-weight: 500;
  color: var(--faint);
}

.feed-meta {
  font-size: 0.62rem;
  color: #4a5160;
  margin: 0 0 0.55rem 0;
}

.news-item {
  background: rgba(255, 255, 255, 0.015);
  border: 1px solid var(--line-soft);
  border-radius: 8px;
  padding: 0.62rem 0.75rem 0.68rem 0.75rem;
  margin-bottom: 0.4rem;
  transition: background 0.15s ease, border-color 0.15s ease, box-shadow 0.2s ease;
}

.news-item:hover {
  background: var(--bg-hover);
  border-color: var(--line);
}

.news-item.is-new {
  border-color: rgba(110, 159, 255, 0.35);
  box-shadow: inset 3px 0 0 var(--new);
  background: rgba(110, 159, 255, 0.05);
  animation: new-fade 2.4s ease-out 1;
}

.news-item.is-hot {
  border-color: rgba(232, 184, 74, 0.28);
}

.news-item.is-new.is-hot {
  box-shadow: inset 3px 0 0 var(--hot);
}

@keyframes new-fade {
  0% { background: rgba(110, 159, 255, 0.12); }
  100% { background: rgba(110, 159, 255, 0.05); }
}

.news-flags {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin-bottom: 0.28rem;
  flex-wrap: wrap;
}

.news-time {
  font-family: 'IBM Plex Mono', monospace;
  font-size: 11px;
  font-weight: 400;
  color: var(--faint);
  white-space: nowrap;
}

.pill {
  display: inline-block;
  font-size: 0.58rem;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 0.06rem 0.32rem;
  border-radius: 3px;
  line-height: 1.3;
}

.pill-new {
  background: rgba(110, 159, 255, 0.16);
  color: #9cbcff;
  border: 1px solid rgba(110, 159, 255, 0.3);
}

/* HOT / HOT+ / SIGNAL — 동일 accent */
.pill-hot,
.pill-hot-plus,
.pill-signal {
  background: rgba(232, 184, 74, 0.14);
  color: var(--hot);
  border: 1px solid rgba(232, 184, 74, 0.32);
}

.meta-line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.28rem;
  margin-top: 0.38rem;
  font-size: 11px;
  font-weight: 400;
  color: var(--faint);
  line-height: 1.35;
}

.meta-line .meta-source {
  font-weight: 500;
  color: var(--muted);
}

.meta-line a {
  color: var(--faint) !important;
  text-decoration: none;
}

.meta-line a:hover {
  color: var(--accent) !important;
  text-decoration: underline;
}

.meta-line .meta-dot {
  color: #3d4450;
  user-select: none;
}

.headline-stack {
  display: flex;
  flex-direction: column;
  gap: 0.2rem;
}

.headline-en,
.headline-en:link,
.headline-en:visited {
  font-size: 0.98rem;
  font-weight: 600;
  color: var(--text);
  line-height: 1.38;
  text-decoration: none;
}

.headline-en:hover {
  color: #f3f5f9;
  text-decoration: underline;
  text-underline-offset: 0.18em;
}

.headline-ko,
.headline-ko a,
.headline-ko a:link,
.headline-ko a:visited {
  font-size: 0.84rem;
  font-weight: 400;
  color: var(--muted);
  line-height: 1.4;
  text-decoration: none;
}
.headline-ko a:hover {
  color: var(--text-soft);
  text-decoration: underline;
}

.headline-en-only {
  font-size: 0.98rem;
  font-weight: 600;
  color: var(--text);
  line-height: 1.38;
}

mark.hl {
  background: transparent;
  color: #c9d4ef;
  font-weight: inherit;
  padding: 0;
  border-radius: 0;
}

.status-banner {
  font-size: 0.74rem;
  font-weight: 400;
  color: var(--muted);
  margin: 0 0 0.35rem 0;
  padding: 0.45rem 0.65rem;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
  line-height: 1.4;
}

.status-banner.is-warn {
  color: #d4b896;
  border-color: rgba(232, 184, 74, 0.28);
  background: rgba(232, 184, 74, 0.06);
}

.status-banner .status-rss {
  color: var(--faint);
  font-size: 0.68rem;
  margin-top: 0.15rem;
}

/* 피드 2열만 구분선 (헤더 햄버거 행 제외) */
div[data-testid="stHorizontalBlock"]:has(.panel-head) > div:nth-child(1) {
  border-right: 1px solid var(--line);
  padding-right: 0.75rem !important;
}
div[data-testid="stHorizontalBlock"]:has(.panel-head) > div:nth-child(2) {
  padding-left: 0.75rem !important;
}

/* ---- Reader page (prototype) ---- */
.ad-slot {
  min-height: 280px;
  border: 1px dashed rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.02);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.35rem;
  padding: 1rem 0.5rem;
  color: var(--faint);
  font-size: 0.72rem;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  text-align: center;
}
.ad-slot .ad-label {
  font-weight: 700;
  color: #6a7384;
  font-size: 0.62rem;
}
.ad-slot .ad-note {
  text-transform: none;
  letter-spacing: 0;
  font-size: 0.68rem;
  color: #4a5160;
  line-height: 1.4;
  max-width: 9rem;
}
.reader-kicker {
  font-size: 0.72rem;
  color: var(--faint);
  margin: 0 0 0.75rem 0;
}
.reader-title {
  font-size: 1.35rem;
  font-weight: 700;
  color: #f3f5f9;
  line-height: 1.35;
  letter-spacing: -0.03em;
  margin: 0 0 0.55rem 0;
}
.reader-ko {
  font-size: 1.02rem;
  font-weight: 400;
  color: var(--text-soft);
  line-height: 1.45;
  margin: 0 0 1rem 0;
}
.reader-meta {
  font-size: 0.78rem;
  color: var(--muted);
  margin: 0 0 1.1rem 0;
}
.reader-notice {
  font-size: 0.72rem;
  color: var(--faint);
  line-height: 1.45;
  margin: 1rem 0 0 0;
  padding: 0.65rem 0.75rem;
  border: 1px solid var(--line-soft);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.02);
}
.reader-pill-row {
  display: flex;
  gap: 0.35rem;
  flex-wrap: wrap;
  margin-bottom: 0.75rem;
}
@media (max-width: 900px) {
  .ad-slot { min-height: 100px; margin-bottom: 0.75rem; }
}
</style>
"""


# ---------------------------------------------------------------------------
# Settings helpers
# ---------------------------------------------------------------------------

def _default_settings() -> dict[str, Any]:
    return {
        "sources_enabled": {s: True for s in ALL_SOURCES},
        "sources_alert": {s: False for s in ALL_SOURCES},
        "watchlist": ["BTC", "ETH", "ETF", "NVDA"],
        "alerts_enabled": False,
        "alert_on_watchlist": True,
        "alert_on_source": True,
        "result_limit": 40,
        "sort_hot_first": True,
        "use_signal_keywords": True,
        # 번역은 기본 OFF. ON이어도 HOT/NEW만 배치 1회로 호출해 할당량 절약
        "enable_translation": False,
        "translate_limit": 6,
        "translate_only_hot_new": True,
    }


def load_settings_file() -> dict[str, Any]:
    defaults = _default_settings()
    if not SETTINGS_PATH.exists():
        return defaults
    try:
        raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        merged = defaults | raw
        merged["sources_enabled"] = {
            **defaults["sources_enabled"],
            **raw.get("sources_enabled", {}),
        }
        merged["sources_alert"] = {
            **defaults["sources_alert"],
            **raw.get("sources_alert", {}),
        }
        return merged
    except (OSError, json.JSONDecodeError):
        return defaults


def save_settings_file(settings: dict[str, Any]) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(
        json.dumps(settings, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _ensure_source_keys(settings: dict[str, Any]) -> dict[str, Any]:
    """신규 RSS 소스가 추가돼도 기존 설정에 키가 생기도록 보정."""
    enabled = settings.setdefault("sources_enabled", {})
    alert = settings.setdefault("sources_alert", {})
    for src in ALL_SOURCES:
        enabled.setdefault(src, True)
        alert.setdefault(src, False)
    return settings


# 세션당 무료 번역 맛보기 한도 (로그인 전)
FREE_TRANSLATE_SESSION_LIMIT = 10


def init_session_settings() -> None:
    if "settings" not in st.session_state:
        st.session_state.settings = load_settings_file()
    st.session_state.settings = _ensure_source_keys(st.session_state.settings)
    if "seen_ids" not in st.session_state:
        st.session_state.seen_ids = set()
    if "seeded_seen" not in st.session_state:
        st.session_state.seeded_seen = False
    if "alerted_ids" not in st.session_state:
        st.session_state.alerted_ids = set()
    if "translate_fail_count" not in st.session_state:
        st.session_state.translate_fail_count = 0
    if "translate_circuit_open" not in st.session_state:
        st.session_state.translate_circuit_open = False
    if "translation_memory" not in st.session_state:
        st.session_state.translation_memory = {}
    if "translate_api_calls" not in st.session_state:
        st.session_state.translate_api_calls = 0
    if "article_index" not in st.session_state:
        st.session_state.article_index = {}
    if "translate_quota_limit" not in st.session_state:
        st.session_state.translate_quota_limit = FREE_TRANSLATE_SESSION_LIMIT
    if "translate_quota_used" not in st.session_state:
        st.session_state.translate_quota_used = 0


def _translate_quota_limit() -> int:
    return int(
        st.session_state.get("translate_quota_limit", FREE_TRANSLATE_SESSION_LIMIT)
    )


def _translate_quota_used() -> int:
    return int(st.session_state.get("translate_quota_used", 0))


def _translate_quota_remaining() -> int:
    return max(0, _translate_quota_limit() - _translate_quota_used())


def _translate_quota_consume(n: int) -> None:
    n = max(0, int(n))
    if n <= 0:
        return
    st.session_state["translate_quota_used"] = min(
        _translate_quota_limit(),
        _translate_quota_used() + n,
    )


def _translate_quota_reset() -> None:
    st.session_state["translate_quota_used"] = 0


def _register_article(row: dict[str, Any], category: Category = "crypto") -> str:
    """Cache article payload for reader page; return stable id."""
    item = row["item"]
    aid = str(row.get("id") or _item_id(item))
    st.session_state.article_index[aid] = {
        "id": aid,
        "title": item.get("title", ""),
        "translated": row.get("translated") or item.get("title", ""),
        "source": item.get("source", ""),
        "link": item.get("link", "") or "",
        "published_iso": item.get("published_iso", ""),
        "category": category,
        "is_new": bool(row.get("is_new")),
        "is_hot": bool(row.get("is_hot")),
        "heat_tier": row.get("heat_tier"),
        "heat_score": row.get("heat_score", 0),
    }
    return aid


def _read_href(article_id: str) -> str:
    return f"?view=read&id={quote(article_id, safe='')}"


def _resolve_article(article_id: str) -> dict[str, Any] | None:
    """Session cache first; rebuild from RSS if cold open / refresh."""
    if not article_id:
        return None
    cached = st.session_state.article_index.get(article_id)
    if cached:
        return cached

    try:
        crypto_news, stock_news, _health = fetch_all_news()
    except Exception:
        crypto_news = list(st.session_state.get("last_crypto_news") or [])
        stock_news = list(st.session_state.get("last_stock_news") or [])
    for cat, news in (("crypto", crypto_news), ("stocks", stock_news)):
        for item in news:
            iid = str(item.get("id") or _item_id(item))
            if iid != article_id:
                continue
            title = item.get("title", "")
            row = {
                "item": item,
                "translated": title,
                "id": iid,
                "is_new": False,
                "is_hot": False,
                "heat_tier": None,
                "heat_score": 0,
            }
            _register_article(row, cat)
            return st.session_state.article_index[iid]
    return None


def _ad_slot_html(side: str) -> str:
    return (
        f'<div class="ad-slot" aria-label="광고 영역">'
        f'<div class="ad-label">Ad · {html.escape(side)}</div>'
        f'<div class="ad-note">프로토타입 슬롯<br/>배포 시 광고 코드 연결</div>'
        f"</div>"
    )


def render_reader_page(article: dict[str, Any]) -> None:
    """Center article + left/right ad placeholders + CTA to original."""
    title = article.get("title", "")
    translated = article.get("translated") or title
    source = article.get("source", "")
    link = article.get("link", "")
    domain = _source_domain(link)
    rel = _relative_time(article.get("published_iso", ""))
    same = translated.strip() == title.strip()

    pills = ""
    if article.get("is_new"):
        pills += '<span class="pill pill-new">NEW</span>'
    tier = article.get("heat_tier")
    if tier == "hot+":
        pills += f'<span class="pill pill-hot-plus">HOT+{article.get("heat_score", 0)}</span>'
    elif tier == "hot":
        pills += f'<span class="pill pill-hot">HOT·{article.get("heat_score", 0)}</span>'

    left, center, right = st.columns([1, 2.4, 1], gap="medium")
    with left:
        st.markdown(_ad_slot_html("Left"), unsafe_allow_html=True)
    with center:
        st.markdown(
            '<div class="reader-kicker">라디오 데스크 · 읽기</div>',
            unsafe_allow_html=True,
        )
        if pills:
            st.markdown(
                f'<div class="reader-pill-row">{pills}</div>',
                unsafe_allow_html=True,
            )
        st.markdown(
            f'<div class="reader-meta">'
            f"{html.escape(source)}"
            f' · {html.escape(rel)}'
            f' · {html.escape(domain or "rss")}'
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<h1 class="reader-title">{html.escape(title)}</h1>',
            unsafe_allow_html=True,
        )
        if not same:
            st.markdown(
                f'<div class="reader-ko">{html.escape(translated)}</div>',
                unsafe_allow_html=True,
            )

        cta1, cta2 = st.columns(2)
        with cta1:
            if link:
                st.link_button(
                    "원문 보기",
                    link,
                    use_container_width=True,
                    type="primary",
                )
            else:
                st.button("원문 없음", disabled=True, use_container_width=True)
        with cta2:
            if st.button("목록으로", use_container_width=True, key="reader_back"):
                st.query_params.clear()
                st.rerun()

        st.markdown(
            '<div class="reader-notice">'
            "이 페이지는 헤드라인·번역 안내입니다. "
            "기사 전문·이미지는 원문 사이트에서 확인하세요. "
            "좌·우 ‘Ad’ 영역은 배포 후 광고가 들어갈 자리입니다."
            "</div>",
            unsafe_allow_html=True,
        )
    with right:
        st.markdown(_ad_slot_html("Right"), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Data / translate
# ---------------------------------------------------------------------------

def _parse_published(entry: dict[str, Any]) -> datetime:
    for key in ("published", "updated", "created"):
        raw = entry.get(key)
        if not raw:
            continue
        try:
            dt = parsedate_to_datetime(raw)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (TypeError, ValueError, IndexError):
            pass

    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass

    return datetime.now(timezone.utc)


def _item_id(item: dict[str, Any]) -> str:
    return item.get("link") or f"{item.get('source')}|{item.get('published_iso')}|{item.get('title')}"


RSS_TIMEOUT_SEC = 6
RSS_MAX_WORKERS = 8
RSS_ENTRIES_PER_FEED = 20


def _parse_feed_url(url: str) -> tuple[Any, bool]:
    """Fetch RSS with hard timeout. Returns (parsed, http_ok)."""
    try:
        resp = requests.get(
            url,
            headers=RSS_HEADERS,
            timeout=(3, RSS_TIMEOUT_SEC),  # connect, read
        )
        resp.raise_for_status()
        return feedparser.parse(resp.content), True
    except Exception:
        return feedparser.parse(""), False


def _entries_from_feed(feed: dict[str, str]) -> tuple[list[dict[str, Any]], bool]:
    """Returns (entries, success). success=False on HTTP/network failure."""
    parsed, http_ok = _parse_feed_url(feed["url"])
    if not http_ok:
        return [], False

    out: list[dict[str, Any]] = []
    for entry in parsed.entries[:RSS_ENTRIES_PER_FEED]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title:
            continue
        published_dt = _parse_published(entry)
        out.append(
            {
                "title": title,
                "link": link,
                "source": feed["source"],
                "published": published_dt,
                "published_iso": published_dt.isoformat(),
            }
        )
    # HTTP는 성공했는데 파싱이 완전히 깨진 경우
    if not out and getattr(parsed, "bozo", False) and not parsed.entries:
        return [], False
    return out, True


def _normalize_feed_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = sorted(items, key=lambda x: x["published"], reverse=True)
    return [
        {
            "title": i["title"],
            "link": i["link"],
            "source": i["source"],
            "published_iso": i["published_iso"],
            "id": _item_id(
                {
                    "title": i["title"],
                    "link": i["link"],
                    "source": i["source"],
                    "published_iso": i["published_iso"],
                }
            ),
        }
        for i in items
    ]


def _fetch_from_feeds(
    feeds: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """Fetch feeds in parallel. Returns (items, {ok, fail} source names)."""
    items: list[dict[str, Any]] = []
    ok_sources: list[str] = []
    fail_sources: list[str] = []
    if not feeds:
        return [], {"ok": [], "fail": []}

    workers = min(RSS_MAX_WORKERS, len(feeds))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_entries_from_feed, feed): feed for feed in feeds}
        for fut in as_completed(futures):
            feed = futures[fut]
            src = feed["source"]
            try:
                entries, ok = fut.result()
                if ok:
                    ok_sources.append(src)
                    items.extend(entries)
                else:
                    fail_sources.append(src)
            except Exception:
                fail_sources.append(src)

    return _normalize_feed_items(items), {"ok": ok_sources, "fail": fail_sources}


@st.cache_data(ttl=60, show_spinner=False)
def fetch_real_crypto_news() -> list[dict[str, Any]]:
    items, _health = _fetch_from_feeds(CRYPTO_FEEDS)
    return items


@st.cache_data(ttl=60, show_spinner=False)
def fetch_real_stock_news() -> list[dict[str, Any]]:
    items, _health = _fetch_from_feeds(STOCK_FEEDS)
    return items


@st.cache_data(ttl=60, show_spinner=False)
def fetch_all_news() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
]:
    """Fetch crypto + stocks together. Returns (crypto, stocks, health)."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_c = pool.submit(_fetch_from_feeds, CRYPTO_FEEDS)
        fut_s = pool.submit(_fetch_from_feeds, STOCK_FEEDS)
        crypto_items, crypto_h = fut_c.result()
        stock_items, stock_h = fut_s.result()

    health = {
        "crypto_ok": crypto_h["ok"],
        "crypto_fail": crypto_h["fail"],
        "stocks_ok": stock_h["ok"],
        "stocks_fail": stock_h["fail"],
        "crypto_count": len(crypto_items),
        "stocks_count": len(stock_items),
    }
    return crypto_items, stock_items, health


def _load_news_stable() -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, Any],
    bool,
]:
    """
    Fetch with session fallback to reduce blank flicker on refresh failure.
    Returns (crypto, stocks, health, is_stale).
    """
    try:
        crypto, stocks, health = fetch_all_news()
    except Exception as exc:
        crypto = list(st.session_state.get("last_crypto_news") or [])
        stocks = list(st.session_state.get("last_stock_news") or [])
        health = {
            "crypto_ok": [],
            "crypto_fail": [f["source"] for f in CRYPTO_FEEDS],
            "stocks_ok": [],
            "stocks_fail": [f["source"] for f in STOCK_FEEDS],
            "crypto_count": len(crypto),
            "stocks_count": len(stocks),
            "error": str(exc),
        }
        return crypto, stocks, health, bool(crypto or stocks)

    if crypto or stocks:
        st.session_state["last_crypto_news"] = crypto
        st.session_state["last_stock_news"] = stocks
        st.session_state["last_rss_health"] = health
        return crypto, stocks, health, False

    # 이번 수집이 완전히 비었으면 직전 성공분 유지
    prev_c = list(st.session_state.get("last_crypto_news") or [])
    prev_s = list(st.session_state.get("last_stock_news") or [])
    if prev_c or prev_s:
        health = {
            **health,
            "crypto_count": len(prev_c),
            "stocks_count": len(prev_s),
            "used_fallback": True,
        }
        return prev_c, prev_s, health, True

    return crypto, stocks, health, False


# 무료 티어에서 gemini-2.0-flash 할당량이 0인 경우가 있어 flash-latest 사용
GEMINI_MODEL = "gemini-flash-latest"


def _translation_stub(text: str) -> str:
    return f"(번역 대기 중) {text}"


def _memory_key(category: Category, text: str) -> str:
    return f"{category}::{text.strip()}"


def _memory_get(category: Category, text: str) -> str | None:
    mem = st.session_state.setdefault("translation_memory", {})
    return mem.get(_memory_key(category, text))


def _memory_set(category: Category, text: str, translated: str) -> None:
    mem = st.session_state.setdefault("translation_memory", {})
    mem[_memory_key(category, text)] = translated


def _parse_batch_translations(raw: str, expected: int) -> list[str]:
    """Parse model output into a list of Korean lines."""
    text = (raw or "").strip()
    if not text:
        raise RuntimeError("empty batch translation")

    # JSON array 우선
    try:
        # ```json ... ``` 제거
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
        data = json.loads(cleaned)
        if isinstance(data, list) and len(data) == expected:
            return [re.sub(r"\s+", " ", str(x)).strip() for x in data]
    except json.JSONDecodeError:
        pass

    # 번호 목록 / 줄바꿈 목록 폴백
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cleaned_lines: list[str] = []
    for ln in lines:
        ln2 = re.sub(r"^\s*\d+[\.\)\]:]\s*", "", ln).strip()
        ln2 = re.sub(r"^\s*[-*]\s*", "", ln2).strip()
        if ln2:
            cleaned_lines.append(re.sub(r"\s+", " ", ln2))
    if len(cleaned_lines) >= expected:
        return cleaned_lines[:expected]
    raise RuntimeError(f"batch parse mismatch: got {len(cleaned_lines)}, expected {expected}")


@st.cache_data(show_spinner=False)
def _llm_translate_batch_cached(
    titles: tuple[str, ...],
    category: Category,
    _model: str,
) -> tuple[str, ...]:
    """여러 헤드라인을 1회 API 호출로 번역. 성공 결과만 캐시."""
    import google.generativeai as genai

    if not titles:
        return tuple()

    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    prompt = (
        f"{TRANSLATE_PROMPTS[category]}\n\n"
        f"아래 영어 헤드라인 {len(titles)}개를 같은 순서·같은 개수로 번역해. "
        f"반드시 JSON 문자열 배열만 출력해. 예: [\"번역1\", \"번역2\"]\n\n"
        f"{numbered}"
    )

    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel(_model)
    response = model.generate_content(
        prompt,
        request_options={"timeout": 20},
    )
    raw = (getattr(response, "text", None) or "").strip()
    parsed = _parse_batch_translations(raw, len(titles))
    if any(not p for p in parsed):
        raise RuntimeError("empty item in batch translation")
    return tuple(parsed)


def translate_titles_batch(
    titles: list[str],
    category: Category,
    *,
    enabled: bool,
) -> dict[str, str]:
    """
    HOT/NEW 후보를 메모리 캐시 + 배치 1회로 번역.
    세션 맛보기 잔여만큼만 신규 API 호출. 캐시 히트는 차감 없음.
    반환: {원문: 번역문}
    """
    result: dict[str, str] = {}
    if not enabled or not API_KEY or not titles:
        return result

    if st.session_state.get("translate_circuit_open"):
        # 회로 차단 시에도 캐시는 제공
        for t in titles:
            t = (t or "").strip()
            if not t:
                continue
            cached = _memory_get(category, t)
            if cached:
                result[t] = cached
        return result

    remaining = _translate_quota_remaining()
    unique: list[str] = []
    for t in titles:
        t = (t or "").strip()
        if not t or t in result:
            continue
        cached = _memory_get(category, t)
        if cached:
            result[t] = cached
        elif t not in unique:
            if len(unique) < remaining:
                unique.append(t)
            # 잔여 없으면 신규 API 후보에 넣지 않음 (원문 유지)

    if not unique:
        return result

    try:
        translated = _llm_translate_batch_cached(
            tuple(unique), category, GEMINI_MODEL
        )
        st.session_state["translate_fail_count"] = 0
        for src, dst in zip(unique, translated):
            result[src] = dst
            _memory_set(category, src, dst)
        _translate_quota_consume(len(unique))
        st.session_state["translate_api_calls"] = (
            int(st.session_state.get("translate_api_calls", 0)) + 1
        )
        st.session_state["translate_last_batch_size"] = len(unique)
    except Exception as exc:
        st.session_state["translate_last_error"] = str(exc).split("\n")[0][:180]
        fails = int(st.session_state.get("translate_fail_count", 0)) + 1
        st.session_state["translate_fail_count"] = fails
        if fails >= 2:
            st.session_state["translate_circuit_open"] = True

    return result


# ---------------------------------------------------------------------------
# Matching / highlight
# ---------------------------------------------------------------------------

def _parse_watchlist(raw: str) -> list[str]:
    parts = re.split(r"[,，\n]+", raw)
    return [p.strip() for p in parts if p.strip()]


def _term_boundary_pattern(term: str) -> re.Pattern[str]:
    """Word-ish boundary so ETH does not match inside ETF."""
    escaped = re.escape(term.strip())
    return re.compile(
        rf"(?<![A-Za-z0-9_]){escaped}(?![A-Za-z0-9_])",
        re.IGNORECASE,
    )


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    hits: list[str] = []
    for term in terms:
        t = term.strip()
        if not t:
            continue
        if _term_boundary_pattern(t).search(text) and t not in hits:
            hits.append(t)
    return hits


def _heat_info(
    text: str,
    watchlist: list[str],
    use_signal_keywords: bool,
) -> dict[str, Any]:
    """Watchlist + market signal keywords → heat score / labels."""
    watch_hits = _matched_terms(text, watchlist)
    signal_hits = (
        _matched_terms(text, SIGNAL_KEYWORDS) if use_signal_keywords else []
    )
    # 워치리스트 가중치 더 높게
    score = len(watch_hits) * 2 + len(signal_hits)
    if score >= 4 or len(watch_hits) >= 2:
        tier = "hot+"
    elif score >= 1:
        tier = "hot"
    else:
        tier = None
    # 하이라이트는 워치리스트 우선, 시그널은 보조
    highlight_terms = list(dict.fromkeys(watch_hits + signal_hits))
    return {
        "score": score,
        "tier": tier,
        "watch_hits": watch_hits,
        "signal_hits": signal_hits,
        "highlight_terms": highlight_terms,
        "is_hot": tier is not None,
    }


def _now_kst() -> datetime:
    return datetime.now(KST)


def _relative_time(iso: str) -> str:
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = now - dt.astimezone(timezone.utc)
        secs = int(delta.total_seconds())
        if secs < 0:
            return "just now"
        if secs < 60:
            return f"{secs}s ago"
        mins = secs // 60
        if mins < 60:
            return f"{mins}m ago"
        hours = mins // 60
        if hours < 48:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except ValueError:
        return "—"


def _source_domain(link: str) -> str:
    if not link:
        return ""
    try:
        from urllib.parse import urlparse

        host = urlparse(link).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _highlight_html(text: str, terms: list[str]) -> str:
    escaped = html.escape(text)
    if not terms:
        return escaped
    ordered = sorted({t for t in terms if t}, key=len, reverse=True)
    for term in ordered:
        pat = _term_boundary_pattern(html.escape(term))
        escaped = pat.sub(lambda m: f'<mark class="hl">{m.group(0)}</mark>', escaped)
    return escaped


def _query_tokens(query: str) -> list[str]:
    return [t for t in re.split(r"[\s,]+", query.strip()) if t]


def _matches_query(item: dict[str, Any], translated: str, query: str) -> bool:
    if not query or not query.strip():
        return True
    blob = f"{item.get('title', '')} {translated}".lower()
    tokens = _query_tokens(query)
    if not tokens:
        return True
    # OR: any token matches (substring on the combined blob)
    return any(tok.lower() in blob for tok in tokens)


def inject_css() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def play_alert_beep(count: int = 1) -> None:
    """Play a short Web Audio beep in the browser (no asset file needed)."""
    n = max(1, min(int(count), 3))
    components.html(
        f"""
        <script>
        (function() {{
          try {{
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            let t = ctx.currentTime;
            for (let i = 0; i < {n}; i++) {{
              const o = ctx.createOscillator();
              const g = ctx.createGain();
              o.type = 'sine';
              o.frequency.value = 880;
              g.gain.setValueAtTime(0.0001, t);
              g.gain.exponentialRampToValueAtTime(0.08, t + 0.01);
              g.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
              o.connect(g); g.connect(ctx.destination);
              o.start(t); o.stop(t + 0.2);
              t += 0.22;
            }}
          }} catch (e) {{}}
        }})();
        </script>
        """,
        height=0,
        width=0,
    )


def prepare_rows(
    news: list[dict[str, Any]],
    category: Category,
    query: str,
    enabled_sources: dict[str, bool],
    watchlist: list[str],
    limit: int,
    use_signal_keywords: bool = True,
    sort_hot_first: bool = True,
    fetched_at: str | None = None,
    enable_translation: bool = False,
    translate_limit: int = 6,
    translate_only_hot_new: bool = True,
) -> list[dict[str, Any]]:
    """소스 필터 → 후보 구성 → (번역) → 검색 → 정렬 → limit."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = st.session_state.seen_ids
    fetched_at = fetched_at or _now_kst().strftime("%H:%M:%S")
    # 검색이 번역 이후에 걸리므로, 쿼리 있을 때 후보 풀을 더 넓게
    pool_cap = max(limit * 5, 100) if query.strip() else max(limit * 3, limit)

    for item in news:
        if not enabled_sources.get(item["source"], True):
            continue

        title = item.get("title", "")
        heat = _heat_info(title, watchlist, use_signal_keywords)
        item_id = item.get("id") or _item_id(item)
        is_new = item_id not in seen if st.session_state.seeded_seen else False

        rows.append(
            {
                "item": item,
                "translated": title,
                "is_new": is_new,
                "is_hot": heat["is_hot"],
                "heat_tier": heat["tier"],
                "heat_score": heat["score"],
                "hits": heat["highlight_terms"],
                "watch_hits": heat["watch_hits"],
                "signal_hits": heat["signal_hits"],
                "id": item_id,
                "fetched_at": fetched_at,
            }
        )
        if len(rows) >= pool_cap:
            break

    def _sort_key(r: dict[str, Any]) -> tuple[Any, ...]:
        return (
            r["heat_score"],
            1 if r["is_new"] else 0,
            r["item"].get("published_iso", ""),
        )

    if sort_hot_first:
        rows.sort(key=_sort_key, reverse=True)

    # --- HOT/NEW 배치 번역 + 세션 맛보기 쿼터 ---
    translate_pool = rows[: max(limit * 2, limit)]
    if enable_translation and API_KEY:
        # 컬럼당 상한 (캐시 조회 포함 후보 수). 실제 API는 세션 잔여로 제한됨.
        col_cap = max(0, int(translate_limit))
        candidates: list[str] = []
        for row in translate_pool:
            if len(candidates) >= col_cap:
                break
            title = row["item"].get("title", "")
            if not title:
                continue
            if translate_only_hot_new and not (row["is_hot"] or row["is_new"]):
                continue
            if title not in candidates:
                candidates.append(title)

        mapping = translate_titles_batch(candidates, category, enabled=True)
        for row in rows:
            title = row["item"].get("title", "")
            if title in mapping:
                row["translated"] = mapping[title]
            else:
                cached = _memory_get(category, title)
                row["translated"] = cached if cached else title

            blob = f"{title} {row['translated']}"
            heat = _heat_info(blob, watchlist, use_signal_keywords)
            row["is_hot"] = heat["is_hot"] or row["is_hot"]
            row["heat_tier"] = heat["tier"] or row["heat_tier"]
            row["heat_score"] = max(row["heat_score"], heat["score"])
            row["hits"] = heat["highlight_terms"] or row["hits"]
            row["watch_hits"] = heat["watch_hits"] or row["watch_hits"]
            row["signal_hits"] = heat["signal_hits"] or row["signal_hits"]
    else:
        for row in rows:
            title = row["item"].get("title", "")
            row["translated"] = title

    # 검색: 원문 + 번역문 (토큰 OR)
    if query.strip():
        rows = [
            r
            for r in rows
            if _matches_query(r["item"], r.get("translated", ""), query)
        ]

    if sort_hot_first:
        rows.sort(key=_sort_key, reverse=True)

    return rows[:limit]


def _linked_or_span(text_html: str, href: str, has_link: bool, css_class: str) -> str:
    """Headline links to our reader page (same tab)."""
    if has_link:
        return (
            f'<a class="{css_class}" href="{href}">{text_html}</a>'
        )
    return f'<span class="headline-en-only">{text_html}</span>'


def _news_card_html(row: dict[str, Any], mode: DisplayMode, _watchlist: list[str]) -> str:
    item = row["item"]
    translated = row["translated"]
    time_str = _format_time(item["published_iso"])
    rel_time = _relative_time(item["published_iso"])
    link_raw = item.get("link", "") or ""
    link = html.escape(link_raw, quote=True)
    has_link = bool(link_raw)
    domain = _source_domain(link_raw)
    article_id = str(row.get("id") or _item_id(item))
    read_href = html.escape(_read_href(article_id), quote=True)

    if row["hits"]:
        en_html = _highlight_html(item.get("title", ""), row["hits"])
        ko_html = _highlight_html(translated, row["hits"])
    else:
        en_html = html.escape(item.get("title", ""))
        ko_html = html.escape(translated)

    pills = ""
    if row["is_new"]:
        pills += '<span class="pill pill-new">NEW</span>'
    tier = row.get("heat_tier")
    if tier == "hot+":
        pills += (
            f'<span class="pill pill-hot-plus">HOT+{row.get("heat_score", 0)}</span>'
        )
    elif tier == "hot":
        pills += f'<span class="pill pill-hot">HOT·{row.get("heat_score", 0)}</span>'
    if row.get("signal_hits") and not row.get("watch_hits"):
        pills += '<span class="pill pill-signal">SIGNAL</span>'
    flags = f'<div class="news-flags">{pills}</div>' if pills else ""

    stack: list[str] = ['<div class="headline-stack">']
    raw_title = item.get("title", "")
    same_as_origin = translated.strip() == raw_title.strip()
    # 헤드라인 → 우리 읽기 페이지 (원문은 읽기 페이지의 CTA)
    if mode == "both":
        stack.append(
            f"<div>{_linked_or_span(en_html, read_href, True, 'headline-en')}</div>"
        )
        if not same_as_origin:
            stack.append(
                f'<div class="headline-ko">'
                f'<a class="headline-ko" href="{read_href}">{ko_html}</a>'
                f"</div>"
            )
    elif mode == "en":
        stack.append(
            f"<div>{_linked_or_span(en_html, read_href, True, 'headline-en')}</div>"
        )
    else:
        stack.append(_linked_or_span(ko_html, read_href, True, "headline-en"))
    stack.append("</div>")

    domain_html = html.escape(domain) if domain else "rss"
    source_html = html.escape(item["source"])
    # 도메인만 원문 직접 링크 (고급 사용자용)
    host_html = (
        f'<a href="{link}" target="_blank" rel="noopener" title="원문 바로가기">'
        f"{domain_html}</a>"
        if has_link
        else domain_html
    )
    meta = (
        f'<div class="meta-line">'
        f'<span class="news-time">{html.escape(time_str)}</span>'
        f'<span class="meta-dot">·</span>'
        f"<span>{html.escape(rel_time)}</span>"
        f'<span class="meta-dot">·</span>'
        f'<span class="meta-source">{source_html}</span>'
        f'<span class="meta-dot">·</span>'
        f"{host_html}"
        f"</div>"
    )

    classes = ["news-item"]
    if row["is_new"]:
        classes.append("is-new")
    if row["is_hot"]:
        classes.append("is-hot")

    return (
        f'<div class="{" ".join(classes)}">'
        f"{flags}"
        f"{''.join(stack)}"
        f"{meta}"
        f"</div>"
    )


def _format_time(iso: str) -> str:
    """카드에 표시하는 시각 — 항상 KST(UTC+9)."""
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(KST).strftime("%H:%M")
    except ValueError:
        return "--:--"


def render_feed_panel(
    title: str,
    css_class: str,
    sources_caption: str,
    rows: list[dict[str, Any]],
    mode: DisplayMode,
    watchlist: list[str],
    sort_hot_first: bool = True,
    category: Category = "crypto",
) -> None:
    st.markdown(
        f'<div class="panel-head {css_class}">'
        f'<div class="panel-title {css_class}">{title}</div>'
        f'<div class="panel-meta">{sources_caption}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )
    new_count = sum(1 for r in rows if r["is_new"])
    hot_count = sum(1 for r in rows if r["is_hot"])
    sort_label = "HOT순" if sort_hot_first else "시간순"
    st.markdown(
        f'<div class="feed-meta">{len(rows)} results'
        f' · {new_count} new · {hot_count} hot'
        f' · {sort_label}'
        f' · sync {_now_kst().strftime("%H:%M:%S")} KST</div>',
        unsafe_allow_html=True,
    )

    if not rows:
        st.info(
            "표시할 속보가 없습니다. "
            "① 소스 체크 ② 검색어 ③ RSS 실패(상단 배너)를 확인해 주세요."
        )
        return

    for r in rows:
        _register_article(r, category)
    cards = "".join(_news_card_html(r, mode, watchlist) for r in rows)
    st.markdown(cards, unsafe_allow_html=True)


def _update_seen_and_alerts(
    all_rows: list[dict[str, Any]],
    settings: dict[str, Any],
) -> None:
    """Seed seen set on first load; afterwards mark NEW and fire beeps."""
    current_ids = {r["id"] for r in all_rows}

    if not st.session_state.seeded_seen:
        st.session_state.seen_ids = set(current_ids)
        st.session_state.seeded_seen = True
        return

    # Alerts for newly appeared items
    if settings.get("alerts_enabled"):
        beep_targets = []
        for row in all_rows:
            if not row["is_new"]:
                continue
            if row["id"] in st.session_state.alerted_ids:
                continue
            source = row["item"]["source"]
            source_alert = (
                settings.get("alert_on_source")
                and settings.get("sources_alert", {}).get(source, False)
            )
            watch_alert = settings.get("alert_on_watchlist") and row["is_hot"]
            if source_alert or watch_alert:
                beep_targets.append(row["id"])

        if beep_targets:
            play_alert_beep(len(beep_targets))
            st.session_state.alerted_ids.update(beep_targets)

    # Mark everything currently shown as seen for next cycle
    st.session_state.seen_ids.update(current_ids)


# ---------------------------------------------------------------------------
# Sidebar UI
# ---------------------------------------------------------------------------

def _translation_status_lines(
    enable_translation: bool,
    translate_limit: int,
    translate_only_hot_new: bool,
) -> tuple[str, bool]:
    """Return (main status text, is_warn)."""
    if not API_KEY:
        return (
            "번역 불가 · API 키가 없습니다 (로컬 .env / 배포 Streamlit Secrets)",
            True,
        )
    if st.session_state.get("translate_circuit_open"):
        err = str(st.session_state.get("translate_last_error") or "").strip()
        brief = ""
        if err:
            # 한 줄로 짧게
            brief = err.replace("\n", " ")
            if len(brief) > 80:
                brief = brief[:77] + "…"
            brief = f" · {brief}"
        return (
            f"번역 일시중지 · API 할당량/오류{brief} (사이드바에서 재시도)",
            True,
        )

    limit = _translate_quota_limit()
    remaining = _translate_quota_remaining()
    taste = f"맛보기 잔여 {remaining}/{limit}"

    if enable_translation and remaining <= 0:
        return (
            f"번역 맛보기 소진 · 원문만 표시 · 추후 구독 시 무제한 ({taste})",
            True,
        )

    err = st.session_state.get("translate_last_error")
    if enable_translation and err and not st.session_state.get("translate_circuit_open"):
        return f"번역 ON · 최근 오류 있음 · {taste}", True
    if not enable_translation:
        return f"번역 OFF · 원문만 표시 · {taste}", False
    scope = "HOT/NEW" if translate_only_hot_new else "표시 항목"
    return (
        f"번역 ON · {scope} 최대 {translate_limit}건/컬럼 · {taste}",
        False,
    )


def _rss_status_line(health: dict[str, Any], is_stale: bool) -> str:
    c_ok = len(health.get("crypto_ok") or [])
    c_fail = len(health.get("crypto_fail") or [])
    s_ok = len(health.get("stocks_ok") or [])
    s_fail = len(health.get("stocks_fail") or [])
    c_n = int(health.get("crypto_count") or 0)
    s_n = int(health.get("stocks_count") or 0)
    line = (
        f"RSS · Crypto {c_n}건 ({c_ok}소스 성공"
        + (f"/{c_fail}실패" if c_fail else "")
        + f") · Stocks {s_n}건 ({s_ok}소스 성공"
        + (f"/{s_fail}실패" if s_fail else "")
        + ")"
    )
    if is_stale or health.get("used_fallback"):
        line += " · 이전 수집분 표시 중"
    if health.get("error"):
        line += " · 수집 오류"
    fails = (health.get("crypto_fail") or []) + (health.get("stocks_fail") or [])
    if fails:
        shown = ", ".join(fails[:4])
        more = f" 외 {len(fails) - 4}" if len(fails) > 4 else ""
        line += f" · 실패: {shown}{more}"
    return line


def render_sidebar() -> tuple[str, DisplayMode, dict[str, Any]]:
    settings = st.session_state.settings

    # 1) 검색
    st.markdown('<div class="sidebar-label">검색</div>', unsafe_allow_html=True)
    query = st.text_input(
        "키워드 필터",
        placeholder="btc, nvidia, 실적…",
        label_visibility="collapsed",
        key="search_query",
    )
    st.markdown(
        '<div class="sidebar-hint">원문·번역문 검색 · 콤마/공백은 OR</div>',
        unsafe_allow_html=True,
    )

    # 2) 표시 모드
    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">표시</div>', unsafe_allow_html=True)
    mode_label = st.radio(
        "표시 모드",
        options=["원문 + 번역", "원문만", "번역만"],
        index=0,
        label_visibility="collapsed",
    )
    mode_map: dict[str, DisplayMode] = {
        "원문 + 번역": "both",
        "원문만": "en",
        "번역만": "ko",
    }
    mode = mode_map[mode_label]
    _limit_opts = [20, 40, 80]
    _cur_limit = settings.get("result_limit", 40)
    settings["result_limit"] = st.selectbox(
        "결과 수 (컬럼당)",
        options=_limit_opts,
        index=_limit_opts.index(_cur_limit) if _cur_limit in _limit_opts else 1,
    )
    st.markdown(
        '<div class="sidebar-hint">'
        "표시 모드 = 카드에 무엇을 보여줄지 · "
        "번역 스위치(메인 상단) = 실제로 Gemini 호출할지 · "
        f"세션당 신규 번역 {FREE_TRANSLATE_SESSION_LIMIT}건 무료 "
        "(캐시 히트는 차감 없음)"
        "</div>",
        unsafe_allow_html=True,
    )
    q_rem = _translate_quota_remaining()
    q_lim = _translate_quota_limit()
    st.caption(f"맛보기 잔여: {q_rem}/{q_lim}건")
    if q_rem <= 0:
        st.info("맛보기 소진 · 추후 구독 시 무제한 번역")
    if settings.get("enable_translation"):
        settings["translate_only_hot_new"] = st.checkbox(
            "HOT / NEW 만 번역 (권장)",
            value=bool(settings.get("translate_only_hot_new", True)),
            key="translate_only_hot_new_cb",
        )
        settings["translate_limit"] = st.slider(
            "배치 번역 최대 개수(컬럼당)",
            min_value=3,
            max_value=12,
            value=int(settings.get("translate_limit", 6)),
            key="translate_limit_slider",
            help="실제 API는 세션 맛보기 잔여와 min으로 제한됩니다.",
        )
        calls = int(st.session_state.get("translate_api_calls", 0))
        batch_n = int(st.session_state.get("translate_last_batch_size", 0))
        st.caption(f"이번 세션 API 호출: {calls}회 · 마지막 배치: {batch_n}건")
    else:
        st.caption("현재 번역 OFF · 메인 상단 스위치로 켤 수 있습니다.")
    if st.button("맛보기 쿼터 초기화 (테스트)", use_container_width=True):
        _translate_quota_reset()
        st.rerun()

    # 3) 워치리스트
    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">워치리스트</div>', unsafe_allow_html=True)
    watch_raw = st.text_area(
        "워치리스트",
        value=", ".join(settings.get("watchlist", [])),
        height=78,
        label_visibility="collapsed",
        placeholder="BTC, ETH, ETF, NVDA",
        key="watchlist_raw",
    )
    settings["watchlist"] = _parse_watchlist(watch_raw)
    st.markdown(
        '<div class="sidebar-hint">'
        "HOT 점수 = 워치×2 + 시그널 · 단어 단위 매칭 (ETH≠ETF)"
        "</div>",
        unsafe_allow_html=True,
    )
    settings["use_signal_keywords"] = st.checkbox(
        "시장 시그널 키워드 포함 (ETF, SEC, 실적…)",
        value=settings.get("use_signal_keywords", True),
        key="use_signal_keywords",
    )
    settings["sort_hot_first"] = st.checkbox(
        "HOT 점수 높은 순으로 정렬",
        value=settings.get("sort_hot_first", True),
        key="sort_hot_first",
    )

    # 4) 소스
    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">소스</div>', unsafe_allow_html=True)
    st.caption("체크 = 표시 · 🔔 = 소리 알림 대상")

    st.markdown("**Crypto**")
    for src in [f["source"] for f in CRYPTO_FEEDS]:
        c1, c2 = st.columns([2.2, 1])
        with c1:
            settings["sources_enabled"][src] = st.checkbox(
                src,
                value=settings["sources_enabled"].get(src, True),
                key=f"feed_{src}",
            )
        with c2:
            settings["sources_alert"][src] = st.checkbox(
                "🔔",
                value=settings["sources_alert"].get(src, False),
                key=f"alert_{src}",
                help=f"{src} 알림",
            )

    st.markdown("**Stocks**")
    for src in [f["source"] for f in STOCK_FEEDS]:
        c1, c2 = st.columns([2.2, 1])
        with c1:
            settings["sources_enabled"][src] = st.checkbox(
                src,
                value=settings["sources_enabled"].get(src, True),
                key=f"feed_{src}",
            )
        with c2:
            settings["sources_alert"][src] = st.checkbox(
                "🔔",
                value=settings["sources_alert"].get(src, False),
                key=f"alert_{src}",
                help=f"{src} 알림",
            )

    # 5) 알림
    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">알림</div>', unsafe_allow_html=True)
    settings["alerts_enabled"] = st.toggle(
        "소리 알림 사용",
        value=settings.get("alerts_enabled", False),
        help="새 속보가 알림 조건에 맞으면 비프음",
    )
    settings["alert_on_watchlist"] = st.checkbox(
        "워치리스트 매칭 시 알림",
        value=settings.get("alert_on_watchlist", True),
        disabled=not settings["alerts_enabled"],
    )
    settings["alert_on_source"] = st.checkbox(
        "🔔 체크된 소스 알림",
        value=settings.get("alert_on_source", True),
        disabled=not settings["alerts_enabled"],
    )
    if settings["alerts_enabled"]:
        st.markdown(
            '<div class="sidebar-hint">첫 로드는 알림 없음 · 이후 새 속보만</div>',
            unsafe_allow_html=True,
        )

    # 6) 저장
    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">설정 저장</div>', unsafe_allow_html=True)

    export_payload = json.dumps(settings, ensure_ascii=False, indent=2)
    st.download_button(
        "설정 Export (JSON)",
        data=export_payload,
        file_name="market_news_settings.json",
        mime="application/json",
        use_container_width=True,
        key="export_settings_btn",
    )

    uploaded = st.file_uploader(
        "설정 Import (JSON)",
        type=["json"],
        accept_multiple_files=False,
        key="import_settings_file",
    )
    if uploaded is not None:
        file_id = f"{uploaded.name}:{uploaded.size}:{uploaded.getvalue()[:32]!r}"
        if st.session_state.get("last_import_id") != file_id:
            try:
                imported = json.loads(uploaded.getvalue().decode("utf-8"))
                if not isinstance(imported, dict):
                    raise ValueError("JSON 객체가 아닙니다.")
                merged = _default_settings()
                merged.update({k: v for k, v in imported.items() if k in merged})
                if "sources_enabled" in imported and isinstance(
                    imported["sources_enabled"], dict
                ):
                    merged["sources_enabled"] = {
                        **_default_settings()["sources_enabled"],
                        **imported["sources_enabled"],
                    }
                if "sources_alert" in imported and isinstance(
                    imported["sources_alert"], dict
                ):
                    merged["sources_alert"] = {
                        **_default_settings()["sources_alert"],
                        **imported["sources_alert"],
                    }
                st.session_state.settings = merged
                st.session_state.last_import_id = file_id
                save_settings_file(merged)
                st.success("설정을 Import 하고 저장했습니다.")
                st.rerun()
            except Exception as exc:
                st.error(f"Import 실패: {exc}")

    if st.button("설정 저장 (로컬 파일)", use_container_width=True):
        save_settings_file(settings)
        st.success("저장됨 → data/user_settings.json")

    st.markdown(
        '<div class="sidebar-hint">자동 새로고침 60초 · RSS 공개 피드</div>',
        unsafe_allow_html=True,
    )
    if not API_KEY:
        st.warning("`GEMINI_API_KEY`가 비어 있습니다. 로컬은 `.env`, 배포는 Streamlit Secrets에 넣으세요.")
    else:
        st.markdown(
            f'<div class="sidebar-hint">번역 모델 · {GEMINI_MODEL}</div>',
            unsafe_allow_html=True,
        )
    err = st.session_state.get("translate_last_error")
    if err:
        st.caption(f"번역 오류: {err}")
    if st.session_state.get("translate_circuit_open"):
        st.warning("번역 회로 차단됨 · API 호출 일시 중지")
    if err or st.session_state.get("translate_circuit_open"):
        if st.button("번역 재시도 / 캐시 초기화", use_container_width=True):
            _llm_translate_batch_cached.clear()
            st.session_state.pop("translate_last_error", None)
            st.session_state["translate_fail_count"] = 0
            st.session_state["translate_circuit_open"] = False
            st.rerun()

    st.session_state.settings = settings
    return query, mode, settings


def _render_brand_header() -> None:
    """Hamburger + brand as one cluster (avoids Streamlit column min-width gap)."""
    components.html(
        """
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link href="https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;700;800&display=swap" rel="stylesheet">
        <style>
          html, body {
            margin: 0;
            padding: 0;
            background: transparent;
            overflow: hidden;
            font-family: 'Noto Sans KR', sans-serif;
          }
          .brand-cluster {
            display: flex;
            align-items: flex-start;
            gap: 10px;
            box-sizing: border-box;
            padding: 0;
            margin: 0;
          }
          .hamburger-btn {
            flex: 0 0 36px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            box-sizing: border-box;
            width: 36px;
            height: 36px;
            margin: 2px 0 0 0;
            padding: 0;
            background: transparent;
            border: none;
            border-radius: 6px;
            cursor: pointer;
          }
          .hamburger-btn:hover {
            background: rgba(255, 255, 255, 0.04);
          }
          .hamburger-btn:hover .bar {
            background: #c8ced8;
          }
          .hamburger-btn .bars {
            display: flex;
            flex-direction: column;
            justify-content: center;
            gap: 5px;
            width: 18px;
            height: 14px;
          }
          .hamburger-btn .bar {
            display: block;
            height: 2px;
            width: 100%;
            background: #9aa3b2;
            border-radius: 1px;
          }
          .brand-text {
            display: flex;
            flex-direction: column;
            gap: 2px;
            min-width: 0;
          }
          .app-title {
            font-size: 1.55rem;
            font-weight: 800;
            color: #f3f5f9;
            margin: 0;
            letter-spacing: -0.04em;
            line-height: 1.15;
          }
          .app-subtitle {
            font-size: 0.78rem;
            font-weight: 500;
            color: #c4c8d0;
            margin: 0;
            letter-spacing: 0.02em;
            line-height: 1.25;
          }
          .app-sub {
            font-size: 0.8rem;
            font-weight: 400;
            color: #7a8290;
            margin: 0.2rem 0 0 0;
            letter-spacing: -0.01em;
            line-height: 1.3;
          }
        </style>
        <div class="brand-cluster">
          <button class="hamburger-btn" id="hamburger-btn" title="메뉴" aria-label="사이드바 열기">
            <span class="bars" aria-hidden="true">
              <span class="bar"></span>
              <span class="bar"></span>
              <span class="bar"></span>
            </span>
          </button>
          <div class="brand-text">
            <div class="app-title">라디오 데스크</div>
            <div class="app-subtitle">Market News Terminal</div>
            <div class="app-sub">영어 원문과 한국어 번역을 한 화면에서</div>
          </div>
        </div>
        <script>
        (function () {
          try {
            const frame = window.frameElement;
            if (frame) frame.setAttribute('title', 'radio-desk-brand');
          } catch (e) {}
          function openSidebar() {
            const doc = window.parent.document;
            const selectors = [
              '[data-testid="stSidebarCollapsedControl"] button',
              '[data-testid="collapsedControl"] button',
              '[data-testid="stSidebarCollapseButton"] button',
              '[data-testid="stBaseButton-headerNoPadding"]',
              'button[kind="headerNoPadding"]',
              'button[kind="header"]'
            ];
            for (const sel of selectors) {
              const nodes = doc.querySelectorAll(sel);
              for (const el of nodes) {
                const label = (
                  (el.getAttribute('aria-label') || '') + ' ' +
                  (el.getAttribute('title') || '') + ' ' +
                  (el.innerText || '')
                ).toLowerCase();
                const rect = el.getBoundingClientRect();
                if (rect.left < 80 || label.includes('keyboard') || label.includes('sidebar') || label.includes('arrow')) {
                  el.click();
                  return;
                }
              }
            }
            const leftBtn = Array.from(doc.querySelectorAll('header button, [data-testid="stHeader"] button'))
              .find((el) => el.getBoundingClientRect().left < 60);
            if (leftBtn) leftBtn.click();
          }
          const btn = document.getElementById('hamburger-btn');
          if (btn) btn.addEventListener('click', openSidebar);
        })();
        </script>
        """,
        height=78,
        scrolling=False,
    )


def render_title_with_hamburger(settings: dict[str, Any]) -> dict[str, Any]:
    """Brand cluster (hamburger + title) | translation toggle."""
    left, right = st.columns([6.2, 1.3], vertical_alignment="center", gap="small")
    with left:
        _render_brand_header()
    with right:
        st.markdown('<div class="rd-translate-anchor" aria-hidden="true"></div>', unsafe_allow_html=True)
        settings["enable_translation"] = st.toggle(
            "번역",
            value=bool(settings.get("enable_translation", False)),
            key="main_enable_translation_toggle",
            help="HOT/NEW만 배치 번역합니다.",
        )
    st.session_state.settings = settings
    return settings


def main() -> None:
    st.set_page_config(
        page_title="라디오 데스크 · Market News Terminal",
        page_icon="◈",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    init_session_settings()
    inject_css()

    # ---- 읽기 페이지 프로토타입 (?view=read&id=...) ----
    view = str(st.query_params.get("view", "") or "")
    if view == "read":
        raw_id = st.query_params.get("id", "")
        article_id = unquote(str(raw_id or ""))
        # 읽기 화면에서는 60s 전체 리프레시 부담을 줄임
        settings = st.session_state.settings
        settings = render_title_with_hamburger(settings)
        with st.spinner("기사 불러오는 중…"):
            article = _resolve_article(article_id)
        if not article:
            st.warning("기사를 찾지 못했습니다. 목록으로 돌아가 다시 선택해 주세요.")
            if st.button("목록으로", key="reader_missing_back"):
                st.query_params.clear()
                st.rerun()
            return
        render_reader_page(article)
        return

    st_autorefresh(interval=60_000, key="news_autorefresh")

    with st.sidebar:
        query, mode, settings = render_sidebar()

    settings = render_title_with_hamburger(settings)

    has_feed_cache = bool(
        st.session_state.get("last_crypto_news")
        or st.session_state.get("last_stock_news")
    )
    if has_feed_cache:
        # 이전 피드가 있으면 스피너 없이 갱신 → 깜빡임 완화
        crypto_news, stock_news, rss_health, is_stale = _load_news_stable()
    else:
        with st.spinner("속보 수집 중… (RSS 병렬 로딩)"):
            crypto_news, stock_news, rss_health, is_stale = _load_news_stable()
    fetched_at = _now_kst().strftime("%H:%M:%S")

    watchlist = settings.get("watchlist", [])
    limit = int(settings.get("result_limit", 40))
    enabled = settings.get("sources_enabled", {})
    enable_translation = bool(settings.get("enable_translation", False))
    translate_limit = int(settings.get("translate_limit", 6))
    translate_only_hot_new = bool(settings.get("translate_only_hot_new", True))

    if not crypto_news and not stock_news:
        st.error(
            "RSS를 가져오지 못했습니다. 네트워크·소스 상태를 확인한 뒤 잠시 후 새로고침해 주세요."
        )

    crypto_rows = prepare_rows(
        crypto_news,
        "crypto",
        query,
        enabled,
        watchlist,
        limit,
        use_signal_keywords=settings.get("use_signal_keywords", True),
        sort_hot_first=settings.get("sort_hot_first", True),
        fetched_at=fetched_at,
        enable_translation=enable_translation,
        translate_limit=translate_limit,
        translate_only_hot_new=translate_only_hot_new,
    )
    stock_rows = prepare_rows(
        stock_news,
        "stocks",
        query,
        enabled,
        watchlist,
        limit,
        use_signal_keywords=settings.get("use_signal_keywords", True),
        sort_hot_first=settings.get("sort_hot_first", True),
        fetched_at=fetched_at,
        enable_translation=enable_translation,
        translate_limit=translate_limit,
        translate_only_hot_new=translate_only_hot_new,
    )

    # 번역 차감 반영 후 배너 (맛보기 잔여가 이번 새로고침 결과를 포함)
    status_text, status_warn = _translation_status_lines(
        enable_translation,
        translate_limit,
        translate_only_hot_new,
    )
    rss_line = _rss_status_line(rss_health, is_stale)
    fail_n = len(rss_health.get("crypto_fail") or []) + len(
        rss_health.get("stocks_fail") or []
    )
    banner_warn = status_warn or is_stale or fail_n > 0 or bool(rss_health.get("error"))
    warn_cls = " is-warn" if banner_warn else ""
    st.markdown(
        f'<div class="status-banner{warn_cls}">'
        f"<div>{html.escape(status_text)}</div>"
        f'<div class="status-rss">{html.escape(rss_line)}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )

    _update_seen_and_alerts(crypto_rows + stock_rows, settings)

    col_crypto, col_stocks = st.columns(2, gap="medium")

    with col_crypto:
        active_crypto = [
            s for s in (f["source"] for f in CRYPTO_FEEDS) if enabled.get(s, True)
        ]
        render_feed_panel(
            title="CRYPTO",
            css_class="crypto",
            sources_caption=" · ".join(active_crypto) or "No sources",
            rows=crypto_rows,
            mode=mode,
            watchlist=watchlist,
            sort_hot_first=bool(settings.get("sort_hot_first", True)),
            category="crypto",
        )

    with col_stocks:
        active_stocks = [
            s for s in (f["source"] for f in STOCK_FEEDS) if enabled.get(s, True)
        ]
        render_feed_panel(
            title="STOCKS",
            css_class="stocks",
            sources_caption=" · ".join(active_stocks) or "No sources",
            rows=stock_rows,
            mode=mode,
            watchlist=watchlist,
            sort_hot_first=bool(settings.get("sort_hot_first", True)),
            category="stocks",
        )


if __name__ == "__main__":
    main()
