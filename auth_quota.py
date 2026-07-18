# ============================================================
# Google 로그인 (Supabase) + 일일 번역 쿼터
# Secrets/환경변수 없으면 None 반환 → 앱은 세션 맛보기만 사용
# ============================================================

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

import streamlit as st

KST = timezone(timedelta(hours=9))
FREE_TRANSLATE_DAILY_LIMIT = 30

_SESSION_ACCESS = "sb_access_token"
_SESSION_REFRESH = "sb_refresh_token"
_SESSION_USER = "sb_user"
_SESSION_DAILY_USED = "sb_daily_used"
_SESSION_DAILY_DATE = "sb_daily_date"
_STORAGE_PREFIX = "sb_kv_"


class _StreamlitAuthStorage:
    """PKCE code_verifier 등을 Streamlit session_state에 보관."""

    def get_item(self, key: str) -> str | None:
        return st.session_state.get(f"{_STORAGE_PREFIX}{key}")

    def set_item(self, key: str, value: str) -> None:
        st.session_state[f"{_STORAGE_PREFIX}{key}"] = value

    def remove_item(self, key: str) -> None:
        st.session_state.pop(f"{_STORAGE_PREFIX}{key}", None)


def _secret_or_env(name: str) -> str:
    try:
        if hasattr(st, "secrets") and name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    return (os.getenv(name) or "").strip()


def auth_configured() -> bool:
    return bool(_secret_or_env("SUPABASE_URL") and _secret_or_env("SUPABASE_ANON_KEY"))


def app_redirect_url() -> str:
    url = _secret_or_env("APP_URL")
    if url:
        return url.rstrip("/")
    return "http://localhost:8501"


def today_kst() -> str:
    return datetime.now(KST).date().isoformat()


def _make_client():
    if not auth_configured():
        return None
    try:
        from supabase import ClientOptions, create_client
    except ImportError:
        return None

    options = ClientOptions(
        storage=_StreamlitAuthStorage(),
        flow_type="pkce",
    )
    return create_client(
        _secret_or_env("SUPABASE_URL"),
        _secret_or_env("SUPABASE_ANON_KEY"),
        options=options,
    )


def get_authed_client():
    """JWT가 설정된 Supabase 클라이언트. 로그인 안 됐으면 None."""
    client = _make_client()
    if client is None:
        return None
    access = st.session_state.get(_SESSION_ACCESS)
    refresh = st.session_state.get(_SESSION_REFRESH)
    if not access or not refresh:
        return None
    try:
        client.auth.set_session(access, refresh)
        session = client.auth.get_session()
        if session and getattr(session, "access_token", None):
            st.session_state[_SESSION_ACCESS] = session.access_token
            if getattr(session, "refresh_token", None):
                st.session_state[_SESSION_REFRESH] = session.refresh_token
        return client
    except Exception:
        _clear_local_session()
        return None


def _clear_local_session() -> None:
    for key in (
        _SESSION_ACCESS,
        _SESSION_REFRESH,
        _SESSION_USER,
        _SESSION_DAILY_USED,
        _SESSION_DAILY_DATE,
        "sb_oauth_url",
    ):
        st.session_state.pop(key, None)
    # PKCE storage keys
    for key in list(st.session_state.keys()):
        if str(key).startswith(_STORAGE_PREFIX):
            st.session_state.pop(key, None)


def _user_from_supabase_user(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    uid = getattr(user, "id", None) or (user.get("id") if isinstance(user, dict) else None)
    email = getattr(user, "email", None) or (
        user.get("email") if isinstance(user, dict) else None
    )
    if not uid:
        return None
    return {"id": str(uid), "email": str(email or ""), "plan": "free"}


def _ensure_profile(client, user: dict[str, Any]) -> None:
    try:
        client.table("profiles").upsert(
            {
                "id": user["id"],
                "email": user.get("email") or None,
                "plan": "free",
            },
            on_conflict="id",
        ).execute()
    except Exception:
        pass


def _load_plan(client, user: dict[str, Any]) -> str:
    try:
        res = (
            client.table("profiles")
            .select("plan")
            .eq("id", user["id"])
            .maybe_single()
            .execute()
        )
        data = getattr(res, "data", None) or {}
        plan = (data.get("plan") or "free").strip().lower()
        return plan if plan else "free"
    except Exception:
        return "free"


def _strip_oauth_query_params() -> None:
    try:
        params = {k: v for k, v in st.query_params.items() if k not in ("code", "state")}
        st.query_params.clear()
        for k, v in params.items():
            st.query_params[k] = v
    except Exception:
        pass


def exchange_code_from_query() -> bool:
    """OAuth PKCE 콜백: ?code=... 를 세션으로 교환. 성공 시 True."""
    if not auth_configured():
        return False
    try:
        code = st.query_params.get("code")
    except Exception:
        code = None
    if not code:
        return False
    code = str(code).strip()
    if not code:
        return False

    client = _make_client()
    if client is None:
        return False
    try:
        result = client.auth.exchange_code_for_session({"auth_code": code})
        session = getattr(result, "session", None)
        user = getattr(result, "user", None)
        if session is None and hasattr(result, "data"):
            data = result.data
            session = getattr(data, "session", None) or (
                data.get("session") if isinstance(data, dict) else None
            )
            user = user or getattr(data, "user", None) or (
                data.get("user") if isinstance(data, dict) else None
            )
        if isinstance(result, dict):
            session = session or result.get("session")
            user = user or result.get("user")

        access = None
        refresh = None
        if session is not None:
            access = getattr(session, "access_token", None)
            refresh = getattr(session, "refresh_token", None)
            if isinstance(session, dict):
                access = access or session.get("access_token")
                refresh = refresh or session.get("refresh_token")
                user = user or session.get("user")

        if not access or not refresh:
            st.session_state["auth_last_error"] = "OAuth 세션 토큰을 받지 못했습니다."
            _strip_oauth_query_params()
            return False

        st.session_state[_SESSION_ACCESS] = access
        st.session_state[_SESSION_REFRESH] = refresh
        st.session_state.pop("sb_oauth_url", None)
        parsed = _user_from_supabase_user(user)
        if parsed:
            authed = get_authed_client()
            if authed:
                _ensure_profile(authed, parsed)
                parsed["plan"] = _load_plan(authed, parsed)
            st.session_state[_SESSION_USER] = parsed
            _refresh_daily_cache(force=True)

        _strip_oauth_query_params()
        return True
    except Exception as exc:
        st.session_state["auth_last_error"] = str(exc).split("\n")[0][:180]
        _strip_oauth_query_params()
        return False


def get_google_oauth_url() -> str | None:
    # 자동 새로고침마다 PKCE verifier가 바뀌면 로그인이 깨지므로 캐시
    cached = st.session_state.get("sb_oauth_url")
    if cached:
        return str(cached)

    client = _make_client()
    if client is None:
        return None
    try:
        result = client.auth.sign_in_with_oauth(
            {
                "provider": "google",
                "options": {
                    "redirect_to": app_redirect_url(),
                    "skip_browser_redirect": True,
                },
            }
        )
        url = getattr(result, "url", None)
        if url is None and hasattr(result, "data"):
            data = result.data
            url = getattr(data, "url", None) or (
                data.get("url") if isinstance(data, dict) else None
            )
        if isinstance(result, dict):
            url = url or result.get("url")
        if url:
            st.session_state["sb_oauth_url"] = str(url)
            return str(url)
        return None
    except Exception as exc:
        st.session_state["auth_last_error"] = str(exc).split("\n")[0][:180]
        return None


def get_current_user() -> dict[str, Any] | None:
    """로그인 사용자 dict 또는 None."""
    cached = st.session_state.get(_SESSION_USER)
    if cached and st.session_state.get(_SESSION_ACCESS):
        return cached

    client = get_authed_client()
    if client is None:
        return None
    try:
        res = client.auth.get_user()
        user = getattr(res, "user", None) or (
            res.get("user") if isinstance(res, dict) else None
        )
        parsed = _user_from_supabase_user(user)
        if not parsed:
            return None
        _ensure_profile(client, parsed)
        parsed["plan"] = _load_plan(client, parsed)
        st.session_state[_SESSION_USER] = parsed
        return parsed
    except Exception:
        _clear_local_session()
        return None


def logout() -> None:
    client = get_authed_client()
    if client is not None:
        try:
            client.auth.sign_out()
        except Exception:
            pass
    _clear_local_session()


def _refresh_daily_cache(*, force: bool = False) -> int:
    """오늘(KST) 사용량 캐시. 반환 used_count."""
    today = today_kst()
    if (
        not force
        and st.session_state.get(_SESSION_DAILY_DATE) == today
        and _SESSION_DAILY_USED in st.session_state
    ):
        return int(st.session_state[_SESSION_DAILY_USED])

    used = 0
    client = get_authed_client()
    user = st.session_state.get(_SESSION_USER) or None
    if client and user:
        try:
            res = (
                client.table("translate_usage")
                .select("used_count")
                .eq("user_id", user["id"])
                .eq("usage_date", today)
                .maybe_single()
                .execute()
            )
            data = getattr(res, "data", None)
            if data:
                used = int(data.get("used_count") or 0)
        except Exception:
            used = int(st.session_state.get(_SESSION_DAILY_USED, 0))

    st.session_state[_SESSION_DAILY_USED] = used
    st.session_state[_SESSION_DAILY_DATE] = today
    return used


def get_daily_used() -> int:
    return _refresh_daily_cache(force=False)


def get_daily_limit(user: dict[str, Any] | None = None) -> int:
    u = user if user is not None else get_current_user()
    if u and (u.get("plan") or "free").lower() == "pro":
        return 10_000
    return FREE_TRANSLATE_DAILY_LIMIT


def get_daily_remaining(user: dict[str, Any] | None = None) -> int:
    u = user if user is not None else get_current_user()
    if not u:
        return 0
    return max(0, get_daily_limit(u) - get_daily_used())


def consume_daily(n: int) -> int:
    """성공 번역 n건 차감. 반환: 차감 후 잔여."""
    n = max(0, int(n))
    user = get_current_user()
    client = get_authed_client()
    if not user or client is None:
        return 0
    limit = get_daily_limit(user)
    if n <= 0:
        return get_daily_remaining(user)

    try:
        res = client.rpc(
            "consume_translate_quota",
            {"p_n": n, "p_limit": limit},
        ).execute()
        remaining = res.data
        if remaining is None:
            remaining = max(0, limit - (get_daily_used() + n))
        remaining = max(0, int(remaining))
        st.session_state[_SESSION_DAILY_USED] = limit - remaining
        st.session_state[_SESSION_DAILY_DATE] = today_kst()
        return remaining
    except Exception:
        today = today_kst()
        used = get_daily_used()
        new_used = min(limit, used + n)
        try:
            client.table("translate_usage").upsert(
                {
                    "user_id": user["id"],
                    "usage_date": today,
                    "used_count": new_used,
                },
                on_conflict="user_id,usage_date",
            ).execute()
            st.session_state[_SESSION_DAILY_USED] = new_used
            st.session_state[_SESSION_DAILY_DATE] = today
            return max(0, limit - new_used)
        except Exception as exc:
            st.session_state["auth_last_error"] = str(exc).split("\n")[0][:180]
            return get_daily_remaining(user)


def init_auth() -> None:
    """매 런 시작 시: 콜백 code 처리 + 세션 복원."""
    if not auth_configured():
        return
    if exchange_code_from_query():
        return
    if st.session_state.get(_SESSION_ACCESS) and not st.session_state.get(_SESSION_USER):
        get_current_user()
