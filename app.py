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

import auth_quota
import billing

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

# region: overseas = 해외 매체, domestic = 국내 매체
CRYPTO_FEEDS = [
    {"source": "CoinDesk", "url": "https://www.coindesk.com/arc/outboundfeeds/rss/", "region": "overseas"},
    {"source": "Cointelegraph", "url": "https://cointelegraph.com/rss", "region": "overseas"},
    {"source": "Decrypt", "url": "https://decrypt.co/feed", "region": "overseas"},
    {"source": "The Block", "url": "https://www.theblock.co/rss.xml", "region": "overseas"},
    {"source": "Bitcoin Magazine", "url": "https://bitcoinmagazine.com/feed", "region": "overseas"},
    {"source": "Blockworks", "url": "https://blockworks.co/feed", "region": "overseas"},
    {"source": "CryptoSlate", "url": "https://cryptoslate.com/feed/", "region": "overseas"},
    {"source": "NewsBTC", "url": "https://www.newsbtc.com/feed/", "region": "overseas"},
    {"source": "CryptoPotato", "url": "https://cryptopotato.com/feed/", "region": "overseas"},
    {"source": "DL News", "url": "https://www.dlnews.com/arc/outboundfeeds/rss/", "region": "overseas"},
    {"source": "코인데스크코리아", "url": "https://www.coindeskkorea.com/rss", "region": "domestic"},
    {"source": "토큰포스트", "url": "https://www.tokenpost.kr/rss", "region": "domestic"},
    {"source": "블록미디어", "url": "https://www.blockmedia.co.kr/feed", "region": "domestic"},
]

STOCK_FEEDS = [
    {"source": "Yahoo Finance", "url": "https://finance.yahoo.com/news/rssindex", "region": "overseas"},
    {"source": "CNBC", "url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "region": "overseas"},
    {"source": "CNBC Markets", "url": "https://www.cnbc.com/id/20910258/device/rss/rss.html", "region": "overseas"},
    {"source": "MarketWatch", "url": "https://feeds.marketwatch.com/marketwatch/topstories/", "region": "overseas"},
    {"source": "MarketWatch Markets", "url": "https://feeds.marketwatch.com/marketwatch/marketpulse/", "region": "overseas"},
    {"source": "Bloomberg", "url": "https://feeds.bloomberg.com/markets/news.rss", "region": "overseas"},
    {"source": "NASDAQ", "url": "https://www.nasdaq.com/feed/rssoutbound?category=Markets", "region": "overseas"},
    {"source": "Seeking Alpha", "url": "https://seekingalpha.com/feed.xml", "region": "overseas"},
    {"source": "Fox Business", "url": "https://feeds.foxbusiness.com/foxbusiness/latest", "region": "overseas"},
    {"source": "WSJ Markets", "url": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "region": "overseas"},
    {"source": "Investing.com", "url": "https://www.investing.com/rss/news.rss", "region": "overseas"},
    {"source": "FT Markets", "url": "https://www.ft.com/markets?format=rss", "region": "overseas"},
    {"source": "한경 증권", "url": "https://www.hankyung.com/feed/finance", "region": "domestic"},
    {"source": "매경 증권", "url": "https://www.mk.co.kr/rss/30100041/", "region": "domestic"},
    {"source": "매경 경제", "url": "https://www.mk.co.kr/rss/30000001/", "region": "domestic"},
    {"source": "연합뉴스 경제", "url": "https://www.yna.co.kr/rss/economy.xml", "region": "domestic"},
    {"source": "연합뉴스 산업", "url": "https://www.yna.co.kr/rss/industry.xml", "region": "domestic"},
    {"source": "뉴시스 경제", "url": "https://www.newsis.com/RSS/economy.xml", "region": "domestic"},
    {"source": "동아일보 경제", "url": "https://rss.donga.com/economy.xml", "region": "domestic"},
    {"source": "조선일보 경제", "url": "https://www.chosun.com/arc/outboundfeeds/rss/category/economy/?outputType=xml", "region": "domestic"},
    {"source": "JTBC 경제", "url": "https://fs.jtbc.co.kr/RSS/economy.xml", "region": "domestic"},
    {"source": "SBS 경제", "url": "https://news.sbs.co.kr/news/SectionRssFeed.do?sectionId=01&plink=RSSREADER", "region": "domestic"},
    {"source": "디지털투데이", "url": "https://www.digitaltoday.co.kr/rss/allArticle.xml", "region": "domestic"},
]

RSS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MarketNewsTerminal/1.0; +https://localhost)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

ALL_SOURCES = [f["source"] for f in CRYPTO_FEEDS + STOCK_FEEDS]
SOURCE_REGION: dict[str, str] = {
    f["source"]: f.get("region", "overseas") for f in CRYPTO_FEEDS + STOCK_FEEDS
}
SETTINGS_PATH = Path(__file__).resolve().parent / "data" / "user_settings.json"
# 방문객 표시용 시각 — 항상 한국 표준시 (서머타임 없음)
KST = timezone(timedelta(hours=9))

# HOT 민감도 — 시그널 키워드 범위 + HOT/HOT+ 임계값
HOT_SENSITIVITY_OPTIONS = ("보수적", "균형", "공격적")
# 매체 지역 — 전체 / 해외만 / 국내만
MEDIA_REGION_OPTIONS = ("전체", "해외", "국내")

_SIGNAL_CONSERVATIVE = [
    "ETF",
    "SEC",
    "Fed",
    "FOMC",
    "hack",
    "exploit",
    "bankrupt",
    "lawsuit",
    "approval",
    "earnings",
    "rate cut",
    "rate hike",
    "상장",
    "해킹",
    "실적",
    "금리",
]
_SIGNAL_BALANCED_EXTRA = [
    "listing",
    "delist",
    "reject",
    "guidance",
    "upgrade",
    "downgrade",
    "merger",
    "acquisition",
    "IPO",
    "ATH",
    "crash",
    "rally",
    "CFTC",
    "liquidation",
    "승인",
    "반려",
    "급등",
    "급락",
    "인수",
    "합병",
]
_SIGNAL_AGGRESSIVE_EXTRA = [
    "outflow",
    "inflow",
    "whale",
    "airdrop",
    "unlock",
    "staking",
    "mainnet",
    "stablecoin",
    "Tether",
    "USDC",
    "buyback",
    "dividend",
    "split",
    "layoff",
    "관세",
    "제재",
    "규제",
    "반도체",
    "유출",
    "파산",
    "공시",
]

SIGNAL_KEYWORDS_BY_SENSITIVITY: dict[str, list[str]] = {
    "보수적": list(_SIGNAL_CONSERVATIVE),
    "균형": list(_SIGNAL_CONSERVATIVE) + list(_SIGNAL_BALANCED_EXTRA),
    "공격적": (
        list(_SIGNAL_CONSERVATIVE)
        + list(_SIGNAL_BALANCED_EXTRA)
        + list(_SIGNAL_AGGRESSIVE_EXTRA)
    ),
}

# hot_min: HOT 최소 점수 / hot_plus_score·hot_plus_watch: HOT+ 조건
HOT_THRESHOLDS: dict[str, dict[str, int]] = {
    "보수적": {"hot_min": 2, "hot_plus_score": 5, "hot_plus_watch": 2},
    "균형": {"hot_min": 1, "hot_plus_score": 4, "hot_plus_watch": 2},
    "공격적": {"hot_min": 1, "hot_plus_score": 3, "hot_plus_watch": 2},
}

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

/* 메인 키워드 필터 등 — 배경과 비슷하되 입력창으로 구분 */
[data-testid="stAppViewContainer"] .stTextInput input {
  background: #1a1f28 !important;
  color: var(--text) !important;
  border: 1px solid rgba(255, 255, 255, 0.12) !important;
  border-radius: 8px !important;
  font-size: 0.86rem !important;
  font-family: 'Noto Sans KR', sans-serif !important;
  caret-color: var(--accent) !important;
}
[data-testid="stAppViewContainer"] .stTextInput input::placeholder {
  color: var(--muted) !important;
  opacity: 1 !important;
}
[data-testid="stAppViewContainer"] .stTextInput input:focus {
  background: #1e2430 !important;
  border-color: var(--accent-border) !important;
  box-shadow: 0 0 0 1px rgba(110, 159, 255, 0.18) !important;
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

/* 로고 홈 링크 (iframe 밖 — 목록 복귀용) */
a.rd-brand-home {
  font-size: 1.55rem;
  font-weight: 800;
  color: #f3f5f9 !important;
  text-decoration: none !important;
  letter-spacing: -0.04em;
  line-height: 1.15;
  display: inline-block;
  cursor: pointer;
}
a.rd-brand-home:hover {
  color: #6e9fff !important;
}
.rd-brand-sub {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-soft);
  margin: 0.12rem 0 0 0;
  letter-spacing: 0.02em;
  line-height: 1.25;
}
.rd-brand-hint {
  font-size: 0.8rem;
  font-weight: 400;
  color: var(--muted);
  margin: 0.2rem 0 0.55rem 0;
  letter-spacing: -0.01em;
  line-height: 1.3;
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

/* 공통 필터 박스 (HOT 민감도 + 매체) — CRYPTO/STOCKS 열과 분리 */
.global-feed-kicker {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.06em;
  color: var(--accent);
  margin: 0 0 0.15rem 0;
}
.global-feed-sub {
  font-size: 0.7rem;
  color: var(--faint);
  margin: 0 0 0.55rem 0;
  line-height: 1.4;
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.global-feed-kicker) {
  background: rgba(110, 159, 255, 0.1);
  border: 1.5px solid rgba(110, 159, 255, 0.55) !important;
  border-radius: 8px;
  margin: 0.35rem 0 0.55rem 0;
  box-shadow: inset 0 0 0 1px rgba(110, 159, 255, 0.12);
}
div[data-testid="stVerticalBlockBorderWrapper"]:has(.global-feed-kicker)
  [data-testid="stCaption"] {
  font-size: 0.72rem !important;
  color: var(--muted) !important;
  margin-bottom: 0.15rem !important;
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
.home-ad-banner {
  margin: 0.55rem 0 0.75rem;
}
.home-ad-banner .ad-slot {
  min-height: 72px;
}
.signals-teaser {
  border: 1px solid rgba(232, 184, 74, 0.28);
  background: linear-gradient(
    135deg,
    rgba(232, 184, 74, 0.08),
    rgba(14, 18, 28, 0.4)
  );
  border-radius: 8px;
  padding: 1rem 1.15rem;
  margin-top: 0.25rem;
}
.signals-teaser.is-pro {
  border-color: rgba(110, 159, 255, 0.35);
  background: linear-gradient(
    135deg,
    rgba(110, 159, 255, 0.1),
    rgba(14, 18, 28, 0.4)
  );
}
.signals-kicker {
  font-size: 0.68rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--faint);
  margin-bottom: 0.35rem;
}
.signals-title {
  font-weight: 700;
  font-size: 1.05rem;
  margin-bottom: 0.35rem;
}
.signals-body {
  font-size: 0.88rem;
  color: var(--muted);
  line-height: 1.45;
}
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
/* 목록으로 등 secondary — 흰/연회색 기본 대신 hover 톤을 기본으로 */
section.stMain div.stButton > button[kind="secondary"],
section.stMain div.stButton > button[data-testid="baseButton-secondary"] {
  background-color: #2a2e36 !important;
  color: #f3f5f9 !important;
  border: 1px solid rgba(255, 255, 255, 0.14) !important;
}
section.stMain div.stButton > button[kind="secondary"]:hover,
section.stMain div.stButton > button[data-testid="baseButton-secondary"]:hover {
  background-color: #363b46 !important;
  color: #ffffff !important;
  border-color: rgba(255, 255, 255, 0.24) !important;
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
        # 패널별 정렬 (기본 HOT순). CRYPTO / STOCKS 독립
        "sort_hot_first_crypto": True,
        "sort_hot_first_stocks": True,
        "hot_sensitivity": "공격적",
        "media_region": "해외",
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
    # 레거시 공통 sort_hot_first → 패널별 키로 이전
    if "sort_hot_first_crypto" not in settings or "sort_hot_first_stocks" not in settings:
        legacy = bool(settings.get("sort_hot_first", True))
        settings.setdefault("sort_hot_first_crypto", legacy)
        settings.setdefault("sort_hot_first_stocks", legacy)
    sens = settings.get("hot_sensitivity", "공격적")
    if sens not in HOT_SENSITIVITY_OPTIONS:
        settings["hot_sensitivity"] = "공격적"
    else:
        settings.setdefault("hot_sensitivity", "공격적")
    region = settings.get("media_region", "해외")
    if region not in MEDIA_REGION_OPTIONS:
        settings["media_region"] = "해외"
    else:
        settings.setdefault("media_region", "해외")
    return settings


# 앱 내 Gemini 번역 토글 UI. False면 숨기고 코드·파이프라인은 보관
SHOW_APP_TRANSLATION_UI = False
# 매체 RSS 번역(보관용). 남용 방지용 숨은 상한(배너에 표시하지 않음)
SOFT_TRANSLATE_DAILY_CAP = 2000


def init_session_settings() -> None:
    if "settings" not in st.session_state:
        st.session_state.settings = load_settings_file()
    st.session_state.settings = _ensure_source_keys(st.session_state.settings)
    if not SHOW_APP_TRANSLATION_UI:
        st.session_state.settings["enable_translation"] = False
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
    _ensure_soft_translate_day()


def _is_logged_in() -> bool:
    return auth_quota.get_current_user() is not None


def _show_ads() -> bool:
    """Pro는 광고 없음. 개인 모드·핫리로드 중에는 광고 표시."""
    is_pro = getattr(auth_quota, "is_pro", None)
    if not callable(is_pro):
        return True
    try:
        return not bool(is_pro())
    except Exception:
        return True


def _ensure_soft_translate_day() -> None:
    today = datetime.now(KST).date().isoformat()
    if st.session_state.get("soft_translate_date") != today:
        st.session_state["soft_translate_date"] = today
        st.session_state["soft_translate_used"] = 0


def _translate_soft_remaining() -> int:
    """숨은 일일 soft cap 잔여 (UI에 노출하지 않음)."""
    _ensure_soft_translate_day()
    used = int(st.session_state.get("soft_translate_used", 0))
    return max(0, SOFT_TRANSLATE_DAILY_CAP - used)


def _translate_soft_consume(n: int) -> None:
    n = max(0, int(n))
    if n <= 0:
        return
    _ensure_soft_translate_day()
    st.session_state["soft_translate_used"] = min(
        SOFT_TRANSLATE_DAILY_CAP,
        int(st.session_state.get("soft_translate_used", 0)) + n,
    )


def _status_product_label() -> str:
    if billing.pro_billing_enabled() and auth_quota.is_pro():
        return f"Pro · 광고 없음 · 시그널 우선 ({billing.PRO_PRICE_LABEL})"
    if billing.pro_billing_enabled():
        return (
            f"검증 매체 속보 무료 · Pro는 광고 제거 + 시그널 우선 "
            f"({billing.PRO_PRICE_LABEL})"
        )
    return "검증 매체 속보 · 영어는 「원문 보기」 후 번역"


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


# 광고 슬롯 → Streamlit Secrets / .env 키 (나중에 AdSense 등 HTML 붙여넣기)
AD_SLOT_SECRET_KEYS: dict[str, str] = {
    "home-top": "AD_HTML_HOME_TOP",
    "crypto": "AD_HTML_CRYPTO",
    "stocks": "AD_HTML_STOCKS",
    "reader-left": "AD_HTML_READER_LEFT",
    "reader-right": "AD_HTML_READER_RIGHT",
}
_AD_SLOT_ALIASES: dict[str, str] = {
    "home": "home-top",
    "home-top": "home-top",
    "col-crypto": "crypto",
    "crypto": "crypto",
    "col-stocks": "stocks",
    "stocks": "stocks",
    "left": "reader-left",
    "reader-left": "reader-left",
    "right": "reader-right",
    "reader-right": "reader-right",
}

def _coupang_banner_html(width: int, height: int) -> str:
    """쿠팡파트너스 다이나믹 배너 HTML (고지 문구 포함)."""
    return (
        '<div style="font-size:10px;color:#888;margin:0 0 4px 0;line-height:1.35;">'
        "이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
        "이에 따른 일정액의 수수료를 제공받습니다."
        "</div>\n"
        '<script src="https://ads-partners.coupang.com/g.js"></script>\n'
        "<script>\n"
        "new PartnersCoupang.G("
        f'{{"id":1008366,"template":"carousel","trackingCode":"AF8699199",'
        f'"width":"{width}","height":"{height}","tsource":""}}'
        ");\n"
        "</script>"
    )


def _coupang_banner_html_custom(
    banner_id: int,
    width: int,
    height: int,
    *,
    tracking: str = "AF8699199",
    template: str = "carousel",
) -> str:
    """배너 id·크기가 다른 쿠팡 파트너스 HTML."""
    return (
        '<div style="font-size:10px;color:#888;margin:0 0 4px 0;line-height:1.35;">'
        "이 포스팅은 쿠팡 파트너스 활동의 일환으로, "
        "이에 따른 일정액의 수수료를 제공받습니다."
        "</div>\n"
        '<script src="https://ads-partners.coupang.com/g.js"></script>\n'
        "<script>\n"
        "new PartnersCoupang.G("
        f'{{"id":{banner_id},"template":"{template}","trackingCode":"{tracking}",'
        f'"width":"{width}","height":"{height}","tsource":""}}'
        ");\n"
        "</script>"
    )


# Secrets/환경변수가 비어 있을 때 쓰는 기본 광고 HTML (쿠팡파트너스)
_DEFAULT_AD_HTML: dict[str, str] = {
    "home-top": _coupang_banner_html(680, 120),
    "crypto": _coupang_banner_html(320, 100),
    # STOCKS 열 전용 배너 (id 1008369)
    "stocks": _coupang_banner_html_custom(1008369, 350, 100),
    # 읽기 좌·우 세로형 (id 1008369)
    "reader-left": _coupang_banner_html_custom(1008369, 120, 400),
    "reader-right": _coupang_banner_html_custom(1008369, 120, 400),
}


def _load_config_str(name: str) -> str:
    """Streamlit Secrets 우선, 없으면 .env / 환경변수."""
    try:
        if name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    load_dotenv(Path(__file__).resolve().parent / ".env")
    return os.getenv(name, "").strip()


def _resolve_ad_slot_key(slot_id: str) -> str:
    return _AD_SLOT_ALIASES.get(slot_id.strip().lower(), slot_id.strip().lower())


def _ad_html_for_slot(slot_key: str) -> str:
    """Secrets → 환경변수 → 코드 기본값 순."""
    secret_name = AD_SLOT_SECRET_KEYS.get(slot_key)
    if secret_name:
        custom = _load_config_str(secret_name)
        if custom:
            return custom
    return _DEFAULT_AD_HTML.get(slot_key, "")


def _ad_slot_placeholder_html(label: str, *, compact: bool = False) -> str:
    note = (
        "프로토타입 슬롯 · Secrets에 AD_HTML_* 연결"
        if compact
        else "프로토타입 슬롯<br/>Secrets에 AD_HTML_* 를 넣으면 여기에 표시됩니다"
    )
    return (
        f'<div class="ad-slot" data-ad-slot="{html.escape(label)}" '
        f'aria-label="광고 영역">'
        f'<div class="ad-label">Ad · {html.escape(label)}</div>'
        f'<div class="ad-note">{note}</div>'
        f"</div>"
    )


def _ad_iframe_height(slot_key: str, *, compact: bool) -> int:
    if slot_key in ("reader-left", "reader-right"):
        return 430  # 고지 + 120x400
    if slot_key == "home-top":
        return 160  # 고지 + 캐러셀(120)
    if slot_key in ("crypto", "stocks"):
        return 130  # 고지 + 열 상단 배너
    return 90 if compact else 100


def _render_ad_slot(
    slot_id: str,
    label: str,
    *,
    compact: bool = False,
    wrap_class: str = "",
) -> None:
    """
    Secrets HTML이 있으면 components.html 로 렌더, 없으면 플레이스홀더.
    60초 자동갱신과 별도 광고 강제 리프레시는 하지 않음.
    """
    if not _show_ads():
        return
    slot_key = _resolve_ad_slot_key(slot_id)
    custom = _ad_html_for_slot(slot_key)
    if custom:
        # components.html 은 별도 iframe — 자동갱신과 광고만 강제 리프레시하지 않음
        components.html(
            custom,
            height=_ad_iframe_height(slot_key, compact=compact),
            scrolling=False,
        )
        return

    html_block = _ad_slot_placeholder_html(label, compact=compact)
    if wrap_class:
        st.markdown(
            f'<div class="{html.escape(wrap_class)}">{html_block}</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(html_block, unsafe_allow_html=True)


def _render_home_ad(slot_id: str, label: str) -> None:
    wrap = "home-ad-banner" if _resolve_ad_slot_key(slot_id) == "home-top" else ""
    _render_ad_slot(
        slot_id,
        label,
        compact=(_resolve_ad_slot_key(slot_id) != "home-top"),
        wrap_class=wrap,
    )


def render_reader_page(article: dict[str, Any]) -> None:
    """Center article + left/right ad placeholders + CTA to original."""
    title = article.get("title", "")
    translated = article.get("translated") or title
    source = article.get("source", "")
    link = article.get("link", "")
    domain = _source_domain(link)
    pub_iso = article.get("published_iso", "")
    rel = _relative_time(pub_iso)
    abs_time = _format_time(pub_iso)
    same = translated.strip() == title.strip()
    show_ads = _show_ads()

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
        if show_ads:
            _render_ad_slot("reader-left", "Left")
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
            f"{html.escape(abs_time)}"
            f' · {html.escape(rel)}'
            f' · {html.escape(source)}'
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
            "헤드라인 안내입니다. 전문은 원문에서 확인하세요. "
            "영어는 「원문 보기」로 이동한 뒤, 그 사이트에서 번역해 주세요. "
            "(이 터미널 화면을 통째로 번역하면 오류가 날 수 있습니다.) "
            "좌·우 Ad는 광고 자리입니다."
            "</div>",
            unsafe_allow_html=True,
        )
    with right:
        if show_ads:
            _render_ad_slot("reader-right", "Right")


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
RSS_ENTRIES_PER_FEED = 40
# 화면에 보여줄 기사 발행 시각 상한 (현재 시각 기준)
FEED_MAX_AGE = timedelta(hours=48)

# 키워드 필터 별칭 (영문 티커 ↔ 표기/한글)
SEARCH_ALIASES: dict[str, list[str]] = {
    "samsung": ["samsung", "삼성전자", "삼성"],
    "hynix": ["hynix", "하이닉스", "sk hynix", "sk하이닉스"],
    "microsoft": ["microsoft", "msft"],
    "apple": ["apple", "aapl"],
    "nvidia": ["nvidia", "nvda"],
    "google": ["google", "alphabet", "googl", "goog"],
    "amazon": ["amazon", "amzn"],
    "tesla": ["tesla", "tsla"],
    "meta": ["meta", "facebook", "fb"],
}


def _is_within_feed_max_age(
    item: dict[str, Any],
    *,
    max_age: timedelta = FEED_MAX_AGE,
    now: datetime | None = None,
) -> bool:
    """발행 시각이 now 기준 max_age 이내인지. 파싱 실패 시 제외."""
    raw = item.get("published_iso") or ""
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc)
    except ValueError:
        return False
    ref = now or datetime.now(timezone.utc)
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    else:
        ref = ref.astimezone(timezone.utc)
    age = ref - dt
    return timedelta(0) <= age <= max_age


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
    매체 RSS 번역은 무료. 세션 메모리·서버 캐시 히트는 API/soft-cap 미차감.
    숨은 일일 soft cap(SOFT_TRANSLATE_DAILY_CAP)만 적용.
    """
    result: dict[str, str] = {}
    if not enabled or not API_KEY or not titles:
        return result

    if st.session_state.get("translate_circuit_open"):
        for t in titles:
            t = (t or "").strip()
            if not t:
                continue
            cached = _memory_get(category, t)
            if cached:
                result[t] = cached
        return result

    remaining = _translate_soft_remaining()
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
        # 서버 캐시 히트여도 동일 경로 — soft cap만 세션 단위로 기록
        _translate_soft_consume(len(unique))
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


def _normalize_hot_sensitivity(value: Any) -> str:
    if value in HOT_SENSITIVITY_OPTIONS:
        return str(value)
    return "공격적"


def _normalize_media_region(value: Any) -> str:
    if value in MEDIA_REGION_OPTIONS:
        return str(value)
    return "해외"


def _source_matches_media_region(source: str, media_region: str) -> bool:
    """매체 지역 필터. 전체면 통과, 해외/국내는 SOURCE_REGION 기준."""
    region = _normalize_media_region(media_region)
    if region == "전체":
        return True
    src_region = SOURCE_REGION.get(source, "overseas")
    if region == "해외":
        return src_region == "overseas"
    if region == "국내":
        return src_region == "domestic"
    return True


def _heat_info(
    text: str,
    watchlist: list[str],
    use_signal_keywords: bool,
    hot_sensitivity: str = "공격적",
) -> dict[str, Any]:
    """Watchlist + market signal keywords → heat score / labels."""
    sensitivity = _normalize_hot_sensitivity(hot_sensitivity)
    signal_terms = SIGNAL_KEYWORDS_BY_SENSITIVITY.get(
        sensitivity, SIGNAL_KEYWORDS_BY_SENSITIVITY["공격적"]
    )
    thresholds = HOT_THRESHOLDS.get(sensitivity, HOT_THRESHOLDS["공격적"])
    watch_hits = _matched_terms(text, watchlist)
    signal_hits = (
        _matched_terms(text, signal_terms) if use_signal_keywords else []
    )
    # 워치리스트 가중치 더 높게
    score = len(watch_hits) * 2 + len(signal_hits)
    if score >= thresholds["hot_plus_score"] or len(watch_hits) >= thresholds[
        "hot_plus_watch"
    ]:
        tier = "hot+"
    elif score >= thresholds["hot_min"]:
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


def _expand_query_tokens(tokens: list[str]) -> list[str]:
    """티커·별칭을 펼쳐 검색 재현율을 높임."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in tokens:
        key = raw.strip().lower()
        if not key:
            continue
        alts = SEARCH_ALIASES.get(key) or [raw.strip()]
        for alt in alts:
            a = alt.strip()
            if not a:
                continue
            low = a.lower()
            if low in seen:
                continue
            seen.add(low)
            out.append(a)
    return out


def _matches_query(item: dict[str, Any], translated: str, query: str) -> bool:
    if not query or not query.strip():
        return True
    blob = f"{item.get('title', '')} {translated}".lower()
    tokens = _expand_query_tokens(_query_tokens(query))
    if not tokens:
        return True
    # OR: any token matches (substring on the combined blob)
    return any(tok.lower() in blob for tok in tokens)


def inject_css() -> None:
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
    # 브라우저 자동번역이 Streamlit DOM을 깨며 removeChild 오류를 내는 경우 완화
    st.markdown(
        """
        <script>
        (function () {
          try {
            const doc = (window.parent && window.parent !== window)
              ? window.parent.document : document;
            [doc.documentElement, doc.body, doc.querySelector(".stApp")].forEach((el) => {
              if (!el) return;
              el.setAttribute("translate", "no");
              el.classList.add("notranslate");
            });
            if (!doc.querySelector('meta[name="google"][content="notranslate"]')) {
              const m = doc.createElement("meta");
              m.setAttribute("name", "google");
              m.setAttribute("content", "notranslate");
              doc.head.appendChild(m);
            }
          } catch (e) {}
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


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
    hot_sensitivity: str = "공격적",
    media_region: str = "해외",
    sort_hot_first: bool = True,
    fetched_at: str | None = None,
    enable_translation: bool = False,
    translate_limit: int = 6,
    translate_only_hot_new: bool = True,
) -> list[dict[str, Any]]:
    """소스·지역 필터 → 최근 48시간 → (키워드) → 후보 구성 → (번역) → 정렬 → limit."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = st.session_state.seen_ids
    fetched_at = fetched_at or _now_kst().strftime("%H:%M:%S")
    now_utc = datetime.now(timezone.utc)
    has_query = bool(query.strip())
    sensitivity = _normalize_hot_sensitivity(hot_sensitivity)
    region_filter = _normalize_media_region(media_region)
    # 키워드 없을 때만 후보 상한. 검색 시에는 48h 전체를 훑어 놓치지 않음.
    pool_cap = max(limit * 3, limit)

    for item in news:
        if not enabled_sources.get(item["source"], True):
            continue
        if not _source_matches_media_region(item["source"], region_filter):
            continue
        if not _is_within_feed_max_age(item, now=now_utc):
            continue

        title = item.get("title", "")
        if has_query and not _matches_query(item, title, query):
            continue

        heat = _heat_info(title, watchlist, use_signal_keywords, sensitivity)
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
        if not has_query and len(rows) >= pool_cap:
            break

    def _sort_key(r: dict[str, Any]) -> tuple[Any, ...]:
        return (
            r["heat_score"],
            1 if r["is_new"] else 0,
            r["item"].get("published_iso", ""),
        )

    if sort_hot_first:
        rows.sort(key=_sort_key, reverse=True)
    else:
        rows.sort(
            key=lambda r: r["item"].get("published_iso", ""),
            reverse=True,
        )

    # --- HOT/NEW 배치 번역 (매체 RSS 무료 + 숨은 soft cap) ---
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
            heat = _heat_info(blob, watchlist, use_signal_keywords, sensitivity)
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
    else:
        rows.sort(
            key=lambda r: r["item"].get("published_iso", ""),
            reverse=True,
        )

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
    """카드에 표시하는 시각 — 항상 KST(UTC+9). 당일이 아니면 날짜 포함."""
    try:
        raw = (iso or "").replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        local = dt.astimezone(KST)
        now = _now_kst()
        if local.date() == now.date():
            return f"{local.strftime('%H:%M')} KST"
        return f"{local.strftime('%m/%d %H:%M')} KST"
    except ValueError:
        return "--:--"


def _feed_sort_label(sort_hot_first: bool) -> str:
    return "HOT순" if sort_hot_first else "최신순"


def _sort_settings_key(panel: str) -> str:
    return "sort_hot_first_crypto" if panel == "crypto" else "sort_hot_first_stocks"


def _resolve_hot_sensitivity(settings: dict[str, Any]) -> str:
    """
    HOT 민감도 라디오(이전 런 값)를 settings에 반영.
    prepare_rows 보다 먼저 호출해야 점수·라벨이 바로 적용된다.
    """
    key = "hot_sensitivity_radio"
    label = st.session_state.get(key)
    if label not in HOT_SENSITIVITY_OPTIONS:
        label = _normalize_hot_sensitivity(settings.get("hot_sensitivity", "공격적"))
        st.session_state[key] = label
    settings["hot_sensitivity"] = label
    st.session_state.settings = settings
    return label


def _on_hot_sensitivity_change() -> None:
    label = st.session_state.get("hot_sensitivity_radio")
    if label not in HOT_SENSITIVITY_OPTIONS:
        return
    settings = st.session_state.get("settings")
    if isinstance(settings, dict):
        settings["hot_sensitivity"] = label
        st.session_state.settings = settings


def _resolve_media_region(settings: dict[str, Any]) -> str:
    """매체 지역 라디오(이전 런 값)를 settings에 반영. prepare_rows 전에 호출."""
    key = "media_region_radio"
    label = st.session_state.get(key)
    if label not in MEDIA_REGION_OPTIONS:
        label = _normalize_media_region(settings.get("media_region", "해외"))
        st.session_state[key] = label
    settings["media_region"] = label
    st.session_state.settings = settings
    return label


def _on_media_region_change() -> None:
    label = st.session_state.get("media_region_radio")
    if label not in MEDIA_REGION_OPTIONS:
        return
    settings = st.session_state.get("settings")
    if isinstance(settings, dict):
        settings["media_region"] = label
        st.session_state.settings = settings


def _render_global_feed_controls(settings: dict[str, Any]) -> None:
    """전역 컨트롤 · HOT 민감도 + 매체 (한 박스, CRYPTO/STOCKS 공통)."""
    hot_key = "hot_sensitivity_radio"
    region_key = "media_region_radio"
    if hot_key not in st.session_state:
        st.session_state[hot_key] = _normalize_hot_sensitivity(
            settings.get("hot_sensitivity", "공격적")
        )
    if region_key not in st.session_state:
        st.session_state[region_key] = _normalize_media_region(
            settings.get("media_region", "해외")
        )

    # 한 박스 안에서 HOT | 매체 가로 배치 (CRYPTO/STOCKS 열과 별개임을 문구로 명시)
    with st.container(border=True):
        st.markdown(
            '<div class="global-feed-kicker">공통 필터</div>'
            '<div class="global-feed-sub">'
            "아래 설정은 CRYPTO · STOCKS 두 패널에 동시에 적용됩니다."
            "</div>",
            unsafe_allow_html=True,
        )
        c_hot, c_region = st.columns(2, gap="medium")
        with c_hot:
            st.caption("HOT 민감도")
            st.radio(
                "HOT 민감도",
                list(HOT_SENSITIVITY_OPTIONS),
                horizontal=True,
                key=hot_key,
                label_visibility="collapsed",
                on_change=_on_hot_sensitivity_change,
            )
        with c_region:
            st.caption("매체")
            st.radio(
                "매체",
                list(MEDIA_REGION_OPTIONS),
                horizontal=True,
                key=region_key,
                label_visibility="collapsed",
                on_change=_on_media_region_change,
            )


def _resolve_panel_sort(settings: dict[str, Any], panel: str) -> bool:
    """
    해당 패널 정렬 라디오(이전 런 값)를 settings에 반영.
    prepare_rows 보다 먼저 호출해야 정렬이 바로 적용된다.
    CRYPTO / STOCKS 는 서로 독립.
    """
    sk = _sort_settings_key(panel)
    widget_key = f"feed_sort_{panel}"
    label = st.session_state.get(widget_key)
    if label not in ("최신순", "HOT순"):
        label = _feed_sort_label(bool(settings.get(sk, True)))
        st.session_state[widget_key] = label
    settings[sk] = label == "HOT순"
    st.session_state.settings = settings
    return bool(settings[sk])


def _on_feed_sort_change(panel: str) -> None:
    key = f"feed_sort_{panel}"
    label = st.session_state.get(key)
    if label not in ("최신순", "HOT순"):
        return
    settings = st.session_state.get("settings")
    if isinstance(settings, dict):
        settings[_sort_settings_key(panel)] = label == "HOT순"
        st.session_state.settings = settings


def _resolve_panel_query(panel: str) -> str:
    """패널별 키워드 필터 (CRYPTO / STOCKS 독립)."""
    key = f"feed_filter_{panel}"
    q = st.session_state.get(key)
    if q is None:
        q = ""
    return str(q)


def _render_feed_toolbar(settings: dict[str, Any], *, panel: str) -> None:
    """CRYPTO/STOCKS 제목 아래 · 정렬·키워드 필터 (패널별 독립)."""
    options = ["최신순", "HOT순"]
    desired = _feed_sort_label(bool(settings.get(_sort_settings_key(panel), True)))
    sort_key = f"feed_sort_{panel}"
    filter_key = f"feed_filter_{panel}"
    if sort_key not in st.session_state:
        st.session_state[sort_key] = desired
    if filter_key not in st.session_state:
        st.session_state[filter_key] = ""

    placeholder = (
        "btc, eth, etf…" if panel == "crypto" else "nvidia, earnings, fed…"
    )
    c_sort, c_filter = st.columns([1.15, 1.85], gap="small")
    with c_sort:
        st.caption("정렬")
        st.radio(
            "정렬",
            options,
            horizontal=True,
            key=sort_key,
            label_visibility="collapsed",
            on_change=_on_feed_sort_change,
            args=(panel,),
        )
    with c_filter:
        st.caption("키워드 필터")
        st.text_input(
            "키워드 필터",
            placeholder=placeholder,
            key=filter_key,
            label_visibility="collapsed",
        )


def render_feed_panel_head(
    title: str,
    css_class: str,
    sources_caption: str,
    ad_label: str | None = None,
) -> None:
    """패널 제목·소스 캡션 (HOT/매체 컨트롤은 제목과 정렬 사이에 전역 배치)."""
    if ad_label:
        _render_home_ad(f"col-{css_class}", ad_label)
    st.markdown(
        f'<div class="panel-head {css_class}">'
        f'<div class="panel-title {css_class}">{title}</div>'
        f'<div class="panel-meta">{sources_caption}</div>'
        f"</div>",
        unsafe_allow_html=True,
    )


def render_feed_panel_body(
    rows: list[dict[str, Any]],
    mode: DisplayMode,
    watchlist: list[str],
    sort_hot_first: bool = True,
    hot_sensitivity: str = "공격적",
    media_region: str = "해외",
    category: Category = "crypto",
) -> None:
    """정렬·키워드·피드 본문."""
    _render_feed_toolbar(
        st.session_state.settings,
        panel="crypto" if category == "crypto" else "stocks",
    )
    new_count = sum(1 for r in rows if r["is_new"])
    hot_count = sum(1 for r in rows if r["is_hot"])
    sort_label = _feed_sort_label(sort_hot_first)
    sens_label = _normalize_hot_sensitivity(hot_sensitivity)
    region_label = _normalize_media_region(media_region)
    st.markdown(
        f'<div class="feed-meta">{len(rows)} results'
        f' · 최근 48시간'
        f' · {new_count} new · {hot_count} hot'
        f' · HOT {html.escape(sens_label)}'
        f' · 매체 {html.escape(region_label)}'
        f' · {sort_label}'
        f' · sync {_now_kst().strftime("%H:%M:%S")} KST</div>',
        unsafe_allow_html=True,
    )

    if not rows:
        st.info(
            "표시할 속보가 없습니다. "
            "① 소스 체크 ② 매체(해외/국내) ③ 키워드 필터 ④ RSS 실패(상단 배너)를 확인해 주세요."
        )
        return

    for r in rows:
        _register_article(r, category)
    cards = "".join(_news_card_html(r, mode, watchlist) for r in rows)
    st.markdown(cards, unsafe_allow_html=True)


def _load_x_bearer_token() -> str:
    """X API Bearer Token (Secrets / .env). 없으면 빈 문자열."""
    return _load_config_str("X_BEARER_TOKEN")


def fetch_signals_feed() -> list[dict[str, Any]]:
    """
    X 인플루언서·시그널 피드 훅.
    토큰이 없거나 아직 미구현이면 빈 목록 (실 API 호출 없음).
    """
    token = _load_x_bearer_token()
    if not token:
        return []
    # 이후 스프린트: X API로 타임라인 수집 후 카드 형태로 반환
    _ = token
    return []


def _render_signals_teaser() -> None:
    """SIGNALS 영역 — 실데이터 없으면 출시 예정 티저."""
    st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

    signals = fetch_signals_feed()
    if signals:
        # 이후: 실피드 카드 렌더
        return

    # 개인 무료 모드: 구독 CTA 없이 준비 중 안내만
    if not billing.pro_billing_enabled():
        st.markdown(
            '<div class="signals-teaser">'
            "<div class=\"signals-kicker\">SIGNALS · 출시 예정</div>"
            "<div class=\"signals-title\">X 인플루언서·시그널 속보</div>"
            "<div class=\"signals-body\">"
            "X 인플루언서·시그널은 준비 중입니다. "
            "지금은 위쪽 CRYPTO · STOCKS 매체 RSS 속보를 이용해 주세요."
            "</div></div>",
            unsafe_allow_html=True,
        )
        return

    # (보관) Pro 빌링 ON 일 때만 아래 분기 사용
    if auth_quota.is_pro():
        st.markdown(
            '<div class="signals-teaser is-pro">'
            "<div class=\"signals-kicker\">SIGNALS · Pro</div>"
            "<div class=\"signals-title\">X 인플루언서·시그널 속보</div>"
            "<div class=\"signals-body\">"
            "시그널 피드는 준비 중입니다. 연결되는 대로 이 영역에 표시됩니다."
            "</div></div>",
            unsafe_allow_html=True,
        )
        return

    st.markdown(
        '<div class="signals-teaser">'
        "<div class=\"signals-kicker\">SIGNALS · Locked</div>"
        "<div class=\"signals-title\">X 인플루언서·시그널 속보</div>"
        "<div class=\"signals-body\">"
        "검증된 매체 RSS는 무료로 계속 볼 수 있습니다. "
        f"Pro({html.escape(billing.PRO_PRICE_LABEL)})는 "
        "시그널 우선 + 광고 제거입니다."
        "</div></div>",
        unsafe_allow_html=True,
    )


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
    product = _status_product_label()
    if not SHOW_APP_TRANSLATION_UI:
        del translate_limit, translate_only_hot_new, enable_translation
        return product, False

    del translate_limit, translate_only_hot_new  # 상태줄은 편의 메시지 우선
    if not API_KEY:
        return (
            "번역 불가 · API 키가 없습니다 (로컬 .env / 배포 Streamlit Secrets)",
            True,
        )
    if st.session_state.get("translate_circuit_open"):
        err = str(st.session_state.get("translate_last_error") or "").strip()
        brief = ""
        if err:
            brief = err.replace("\n", " ")
            if len(brief) > 80:
                brief = brief[:77] + "…"
            brief = f" · {brief}"
        return (
            f"번역 일시중지 · API 할당량/오류{brief} (사이드바에서 재시도)",
            True,
        )

    err = st.session_state.get("translate_last_error")
    if enable_translation and err and not st.session_state.get("translate_circuit_open"):
        return (
            f"번역 ON · 피드에서 바로 한국어 · 최근 오류 · {product}",
            True,
        )
    if not enable_translation:
        return f"번역 OFF · 원문만 표시 · {product}", False
    return f"번역 ON · 피드에서 바로 한국어 · {product}", False


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


def _render_billing_sidebar(user: dict[str, Any]) -> None:
    """로그인 사용자용 토스페이먼츠 빌링(카드 등록·해지)."""
    if not billing.pro_billing_enabled():
        return
    if st.session_state.pop("billing_just_activated", None):
        st.success(
            "Pro가 활성화되었습니다. 광고가 제거되며, "
            "시그널 속보를 우선 제공합니다."
        )

    if not billing.toss_configured():
        st.caption(
            "구독 미설정 · Secrets에 TOSS_CLIENT_KEY / TOSS_SECRET_KEY "
            f"(자동결제 빌링, {billing.PRO_PRICE_LABEL}) 를 넣으면 활성화됩니다."
        )
        return

    if auth_quota.is_pro(user):
        st.caption(
            f"Pro 구독 중 · 광고 없음 · 시그널 우선 ({billing.PRO_PRICE_LABEL})"
        )
        billed = billing.get_profile_billing(user["id"])
        next_at = billed.get("next_billing_at")
        if next_at:
            st.caption(f"다음 결제일(예정): {next_at}")
        if st.button("구독 해지", use_container_width=True, key="btn_cancel_pro"):
            if billing.cancel_pro(user["id"]):
                st.success("Pro 구독이 해지되었습니다.")
                st.rerun()
            else:
                st.warning(
                    st.session_state.get("billing_last_error")
                    or "해지에 실패했습니다."
                )
    else:
        st.caption("무료 · 매체 RSS · 홈 광고")
        st.caption(
            "Pro · 광고 제거 + 출시 예정 시그널 우선 · "
            f"카드 등록 시 {billing.PRO_AMOUNT:,}원 결제"
        )
        ck = billing.customer_key_for_user(user["id"])
        html_sdk = billing.billing_auth_html(
            customer_key=ck,
            customer_email=user.get("email") or "",
            customer_name=(user.get("email") or "회원").split("@")[0],
        )
        components.html(html_sdk, height=72)
        err = st.session_state.get("billing_last_error")
        if err:
            st.caption(f"결제 오류: {err}")


def _render_auth_sidebar() -> None:
    st.markdown('<div class="sidebar-label">계정</div>', unsafe_allow_html=True)
    if not billing.pro_billing_enabled():
        st.caption("개인 무료 단말 · 로그인·결제 없음")
        return

    if not auth_quota.auth_configured():
        st.caption(
            "Google 로그인 미설정 · Secrets에 SUPABASE_URL / "
            "SUPABASE_ANON_KEY / APP_URL 을 넣으면 Pro 결제가 활성화됩니다."
        )
        st.caption("검증 매체 속보·번역 편의는 로그인 없이 무료입니다.")
        return

    user = auth_quota.get_current_user()
    if user:
        email = user.get("email") or user.get("id", "")
        st.caption(f"로그인 · {email}")
        st.caption("검증 매체 속보 · 번역 편의 무료")
        _render_billing_sidebar(user)
        if st.button("로그아웃", use_container_width=True, key="btn_logout"):
            auth_quota.logout()
            st.rerun()
    else:
        st.caption("비로그인 · 검증 매체 속보·번역 편의 무료")
        oauth_url = auth_quota.get_google_oauth_url()
        if oauth_url:
            st.link_button(
                "Google로 로그인",
                oauth_url,
                use_container_width=True,
                type="primary",
            )
            st.caption(
                f"로그인 후 Pro({billing.PRO_PRICE_LABEL}) · "
                "광고 제거 + 시그널 우선"
            )
        else:
            st.warning("로그인 URL을 만들지 못했습니다. Secrets·Supabase 설정을 확인하세요.")
        err = st.session_state.get("auth_last_error")
        if err:
            st.caption(f"로그인 오류: {err}")


def render_sidebar() -> tuple[str, DisplayMode, dict[str, Any]]:
    settings = st.session_state.settings

    # 0) 계정 / Google 로그인
    _render_auth_sidebar()
    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)

    # 1) 검색 안내 (실제 필터는 각 패널 제목 아래)
    st.markdown('<div class="sidebar-label">검색</div>', unsafe_allow_html=True)
    st.caption(
        "키워드 필터는 CRYPTO / STOCKS 각 패널에서 따로 사용할 수 있습니다. "
        "콤마·공백은 OR입니다."
    )

    # 2) 표시 모드
    st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">표시</div>', unsafe_allow_html=True)
    if SHOW_APP_TRANSLATION_UI:
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
    else:
        mode = "en"
        st.caption("표시: 영어 원문")
    _limit_opts = [20, 40, 80]
    _cur_limit = settings.get("result_limit", 40)
    settings["result_limit"] = st.selectbox(
        "결과 수 (컬럼당)",
        options=_limit_opts,
        index=_limit_opts.index(_cur_limit) if _cur_limit in _limit_opts else 1,
    )

    # 브라우저 번역 안내 (앱 내 번역 토글 대체)
    st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
    st.markdown('<div class="sidebar-label">영어 읽기</div>', unsafe_allow_html=True)
    st.caption(
        "헤드라인 → 「원문 보기」 → 뉴스 사이트에서 Chrome·Edge **번역**을 쓰세요."
    )
    st.caption(
        "이 터미널(Streamlit) 화면을 통째로 번역하면 화면 오류가 날 수 있습니다."
    )

    if SHOW_APP_TRANSLATION_UI:
        st.markdown(
            '<div class="sidebar-hint">'
            "표시 모드 = 카드에 무엇을 보여줄지 · "
            "번역 = 앱 내 Gemini (보관용 UI)"
            "</div>",
            unsafe_allow_html=True,
        )
        st.caption(_status_product_label())
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
                help="한 번에 번역할 후보 개수(컬럼당).",
            )
            calls = int(st.session_state.get("translate_api_calls", 0))
            batch_n = int(st.session_state.get("translate_last_batch_size", 0))
            st.caption(f"이번 세션 API 호출: {calls}회 · 마지막 배치: {batch_n}건")
        else:
            st.caption("현재 번역 OFF · 메인 상단 스위치로 켤 수 있습니다.")
    else:
        settings["enable_translation"] = False

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
        "HOT 점수 = 워치×2 + 시그널 · 단어 단위 매칭 (ETH≠ETF). "
        "민감도(보수적·균형·공격적)는 메인 화면에서 바꿀 수 있습니다."
        "</div>",
        unsafe_allow_html=True,
    )
    settings["use_signal_keywords"] = st.checkbox(
        "시장 시그널 키워드 포함 (ETF, SEC, 실적…)",
        value=settings.get("use_signal_keywords", True),
        key="use_signal_keywords",
    )
    st.caption(
        "목록 정렬(최신순·HOT순)은 CRYPTO / STOCKS 각각 제목 아래에서 "
        "따로 바꿀 수 있습니다."
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
    if SHOW_APP_TRANSLATION_UI:
        if not API_KEY:
            st.warning(
                "`GEMINI_API_KEY`가 비어 있습니다. "
                "로컬은 `.env`, 배포는 Streamlit Secrets에 넣으세요."
            )
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
    return mode, settings


def _render_hamburger_only() -> None:
    """사이드바 햄버거만 iframe (로고는 페이지에서 목록 복귀 처리)."""
    components.html(
        """
        <style>
          html, body { margin: 0; padding: 0; background: transparent; overflow: hidden; }
          .hamburger-btn {
            display: inline-flex; align-items: center; justify-content: center;
            width: 36px; height: 36px; margin: 2px 0 0 0; padding: 0;
            background: transparent; border: none; border-radius: 6px; cursor: pointer;
          }
          .hamburger-btn:hover { background: rgba(255, 255, 255, 0.04); }
          .hamburger-btn:hover .bar { background: #c8ced8; }
          .bars { display: flex; flex-direction: column; justify-content: center; gap: 5px; width: 18px; height: 14px; }
          .bar { display: block; height: 2px; width: 100%; background: #9aa3b2; border-radius: 1px; }
        </style>
        <button class="hamburger-btn" id="hamburger-btn" title="메뉴" aria-label="사이드바 열기">
          <span class="bars" aria-hidden="true">
            <span class="bar"></span><span class="bar"></span><span class="bar"></span>
          </span>
        </button>
        <script>
        (function () {
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
        height=42,
        scrolling=False,
    )


def _render_brand_header() -> None:
    """
    햄버거 + 로고.
    로고는 iframe 밖 링크로 두어 읽기 화면(?view=read)에서도 목록(첫 화면)으로 돌아가게 함.
    """
    col_ham, col_brand = st.columns([0.55, 9.45], gap="small")
    with col_ham:
        _render_hamburger_only()
    with col_brand:
        st.markdown(
            '<a class="rd-brand-home" href="?go_list=1" title="목록으로">라디오 데스크</a>'
            '<div class="rd-brand-sub">Market News Terminal</div>'
            '<div class="rd-brand-hint">검증 매체 속보 · 영어는 원문 보기 후 번역</div>',
            unsafe_allow_html=True,
        )


def render_title_with_hamburger(settings: dict[str, Any]) -> dict[str, Any]:
    """Brand cluster (hamburger + title) | optional translation toggle (보관)."""
    if SHOW_APP_TRANSLATION_UI:
        left, right = st.columns([6.2, 1.3], vertical_alignment="center", gap="small")
        with left:
            _render_brand_header()
        with right:
            st.markdown(
                '<div class="rd-translate-anchor" aria-hidden="true"></div>',
                unsafe_allow_html=True,
            )
            settings["enable_translation"] = st.toggle(
                "번역",
                value=bool(settings.get("enable_translation", False)),
                key="main_enable_translation_toggle",
                help="앱 내 Gemini 번역(보관). HOT/NEW만 배치 번역합니다.",
            )
    else:
        _render_brand_header()
        settings["enable_translation"] = False
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
    auth_quota.init_auth()
    inject_css()

    # 로고(?go_list=1) 클릭 → 쿼리 제거 후 피드 목록(첫 화면)
    if "go_list" in st.query_params:
        st.query_params.clear()
        st.rerun()

    # ---- 읽기 페이지 프로토타입 (?view=read&id=...) ----
    view = str(st.query_params.get("view", "") or "")
    if view == "read":
        raw_id = st.query_params.get("id", "")
        article_id = unquote(str(raw_id or ""))
        # 읽기 화면에서는 60s 전체 리프레시 부담을 줄임
        settings = st.session_state.settings
        with st.sidebar:
            _render_auth_sidebar()
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
        mode, settings = render_sidebar()

    settings = render_title_with_hamburger(settings)
    query_crypto = _resolve_panel_query("crypto")
    query_stocks = _resolve_panel_query("stocks")

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
    sort_crypto = _resolve_panel_sort(settings, "crypto")
    sort_stocks = _resolve_panel_sort(settings, "stocks")
    hot_sensitivity = _resolve_hot_sensitivity(settings)
    media_region = _resolve_media_region(settings)

    if not crypto_news and not stock_news:
        st.error(
            "RSS를 가져오지 못했습니다. 네트워크·소스 상태를 확인한 뒤 잠시 후 새로고침해 주세요."
        )

    crypto_rows = prepare_rows(
        crypto_news,
        "crypto",
        query_crypto,
        enabled,
        watchlist,
        limit,
        use_signal_keywords=settings.get("use_signal_keywords", True),
        hot_sensitivity=hot_sensitivity,
        media_region=media_region,
        sort_hot_first=sort_crypto,
        fetched_at=fetched_at,
        enable_translation=enable_translation,
        translate_limit=translate_limit,
        translate_only_hot_new=translate_only_hot_new,
    )
    stock_rows = prepare_rows(
        stock_news,
        "stocks",
        query_stocks,
        enabled,
        watchlist,
        limit,
        use_signal_keywords=settings.get("use_signal_keywords", True),
        hot_sensitivity=hot_sensitivity,
        media_region=media_region,
        sort_hot_first=sort_stocks,
        fetched_at=fetched_at,
        enable_translation=enable_translation,
        translate_limit=translate_limit,
        translate_only_hot_new=translate_only_hot_new,
    )

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
    _render_home_ad("home-top", "Home")

    _update_seen_and_alerts(crypto_rows + stock_rows, settings)

    active_crypto = [
        s
        for s in (f["source"] for f in CRYPTO_FEEDS)
        if enabled.get(s, True) and _source_matches_media_region(s, media_region)
    ]
    active_stocks = [
        s
        for s in (f["source"] for f in STOCK_FEEDS)
        if enabled.get(s, True) and _source_matches_media_region(s, media_region)
    ]

    # 1) 패널 제목 → 2) HOT/매체(정렬 직전) → 3) 정렬·피드
    head_crypto, head_stocks = st.columns(2, gap="medium")
    with head_crypto:
        render_feed_panel_head(
            title="CRYPTO",
            css_class="crypto",
            sources_caption=" · ".join(active_crypto) or "No sources",
            ad_label="Crypto",
        )
    with head_stocks:
        render_feed_panel_head(
            title="STOCKS",
            css_class="stocks",
            sources_caption=" · ".join(active_stocks) or "No sources",
            ad_label="Stocks",
        )

    _render_global_feed_controls(settings)

    body_crypto, body_stocks = st.columns(2, gap="medium")
    with body_crypto:
        render_feed_panel_body(
            rows=crypto_rows,
            mode=mode,
            watchlist=watchlist,
            sort_hot_first=sort_crypto,
            hot_sensitivity=hot_sensitivity,
            media_region=media_region,
            category="crypto",
        )
    with body_stocks:
        render_feed_panel_body(
            rows=stock_rows,
            mode=mode,
            watchlist=watchlist,
            sort_hot_first=sort_stocks,
            hot_sensitivity=hot_sensitivity,
            media_region=media_region,
            category="stocks",
        )

    _render_signals_teaser()


if __name__ == "__main__":
    main()
