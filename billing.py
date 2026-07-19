# ============================================================
# 토스페이먼츠 자동결제(빌링) — Pro 월 3,990원
# Pro: X·시그널 우선 + 광고 제거 (매체 RSS·번역은 무료)
# 개인 운영 기본: ENABLE_PRO_BILLING=False → UI/청구 비활성
# ============================================================

from __future__ import annotations

import base64
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import requests
import streamlit as st

# 개인 운영 기본값. True로 바꾸면 Pro/토스 UI·청구 재활성
ENABLE_PRO_BILLING = False

KST = timezone(timedelta(hours=9))
PRO_AMOUNT = 3990
PRO_PRICE_LABEL = "월 3,990원"
PRO_ORDER_NAME = "라디오 데스크 Pro"
TOSS_API = "https://api.tosspayments.com"
_SYNC_TS_KEY = "toss_sync_ts"
_SYNC_TTL_SEC = 120


def _secret_or_env(name: str) -> str:
    try:
        if hasattr(st, "secrets") and name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    return (os.getenv(name) or "").strip()


def pro_billing_enabled() -> bool:
    """UI·청구 게이트. Secrets와 무관하게 코드 플래그가 우선."""
    return bool(ENABLE_PRO_BILLING)


def toss_configured() -> bool:
    return bool(
        _secret_or_env("TOSS_SECRET_KEY") and _secret_or_env("TOSS_CLIENT_KEY")
    )


def service_role_configured() -> bool:
    return bool(
        _secret_or_env("SUPABASE_URL") and _secret_or_env("SUPABASE_SERVICE_ROLE_KEY")
    )


def app_redirect_url() -> str:
    url = _secret_or_env("APP_URL")
    if url:
        return url.rstrip("/")
    return "http://localhost:8501"


def client_key() -> str:
    return _secret_or_env("TOSS_CLIENT_KEY")


def get_service_client():
    if not service_role_configured():
        return None
    try:
        from supabase import create_client
    except ImportError:
        return None
    return create_client(
        _secret_or_env("SUPABASE_URL"),
        _secret_or_env("SUPABASE_SERVICE_ROLE_KEY"),
    )


def _auth_header() -> dict[str, str]:
    raw = (_secret_or_env("TOSS_SECRET_KEY") + ":").encode("utf-8")
    token = base64.b64encode(raw).decode("ascii")
    return {
        "Authorization": f"Basic {token}",
        "Content-Type": "application/json",
    }


def customer_key_for_user(user_id: str) -> str:
    """Toss customerKey: 유추 어려운 고정값 (user id 기반)."""
    # uuid 형태면 그대로, 아니면 안전하게 변환
    uid = (user_id or "").strip()
    if not uid:
        uid = uuid.uuid4().hex
    # Toss: 영문·숫자·-_.*= 등, 2~300자
    key = f"rd_{uid.replace('-', '')}"
    return key[:300]


def get_profile_billing(user_id: str) -> dict[str, Any]:
    client = get_service_client()
    if client is None:
        return {}
    try:
        res = (
            client.table("profiles")
            .select(
                "plan, email, toss_customer_key, toss_billing_key, next_billing_at"
            )
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        return getattr(res, "data", None) or {}
    except Exception:
        return {}


def _update_profile(
    user_id: str,
    *,
    plan: str | None = None,
    toss_customer_key: str | None = None,
    toss_billing_key: str | None = None,
    next_billing_at: str | None = None,
    clear_billing: bool = False,
) -> bool:
    client = get_service_client()
    if client is None:
        st.session_state["billing_last_error"] = (
            "SUPABASE_SERVICE_ROLE_KEY 가 없어 구독 상태를 저장하지 못했습니다."
        )
        return False
    payload: dict[str, Any] = {"id": user_id}
    if plan is not None:
        payload["plan"] = plan
    if toss_customer_key is not None:
        payload["toss_customer_key"] = toss_customer_key
    if clear_billing:
        payload["toss_billing_key"] = None
        payload["next_billing_at"] = None
    else:
        if toss_billing_key is not None:
            payload["toss_billing_key"] = toss_billing_key
        if next_billing_at is not None:
            payload["next_billing_at"] = next_billing_at
    try:
        client.table("profiles").upsert(payload, on_conflict="id").execute()
        return True
    except Exception as exc:
        st.session_state["billing_last_error"] = str(exc).split("\n")[0][:180]
        return False


def issue_billing_key(auth_key: str, customer_key: str) -> str | None:
    if not toss_configured():
        return None
    try:
        res = requests.post(
            f"{TOSS_API}/v1/billing/authorizations/issue",
            headers=_auth_header(),
            json={"authKey": auth_key, "customerKey": customer_key},
            timeout=30,
        )
        data = res.json() if res.content else {}
        if res.status_code >= 400:
            msg = data.get("message") or data.get("code") or res.text[:160]
            st.session_state["billing_last_error"] = str(msg)
            return None
        key = data.get("billingKey")
        return str(key) if key else None
    except Exception as exc:
        st.session_state["billing_last_error"] = str(exc).split("\n")[0][:180]
        return None


def _new_order_id() -> str:
    return f"rd_{uuid.uuid4().hex[:24]}"


def charge_billing(
    *,
    billing_key: str,
    customer_key: str,
    amount: int = PRO_AMOUNT,
    order_name: str = PRO_ORDER_NAME,
    customer_email: str | None = None,
) -> bool:
    if not toss_configured() or not billing_key or not customer_key:
        return False
    body: dict[str, Any] = {
        "customerKey": customer_key,
        "amount": int(amount),
        "orderId": _new_order_id(),
        "orderName": order_name,
    }
    if customer_email:
        body["customerEmail"] = customer_email
    try:
        res = requests.post(
            f"{TOSS_API}/v1/billing/{quote(billing_key, safe='')}",
            headers=_auth_header(),
            json=body,
            timeout=70,
        )
        data = res.json() if res.content else {}
        if res.status_code >= 400:
            msg = data.get("message") or data.get("code") or res.text[:160]
            st.session_state["billing_last_error"] = str(msg)
            return False
        status = (data.get("status") or "").upper()
        return status in ("DONE", "WAITING_FOR_DEPOSIT") or res.status_code == 200
    except Exception as exc:
        st.session_state["billing_last_error"] = str(exc).split("\n")[0][:180]
        return False


def delete_billing_key(billing_key: str) -> None:
    if not toss_configured() or not billing_key:
        return
    try:
        requests.delete(
            f"{TOSS_API}/v1/billing/{quote(billing_key, safe='')}",
            headers=_auth_header(),
            timeout=30,
        )
    except Exception:
        pass


def _next_billing_iso(days: int = 30) -> str:
    return (datetime.now(KST) + timedelta(days=days)).isoformat()


def start_pro_after_billing_auth(
    user_id: str,
    *,
    auth_key: str,
    customer_key: str,
    email: str | None = None,
) -> bool:
    """빌링키 발급 → 첫 달 청구 → plan=pro."""
    billing_key = issue_billing_key(auth_key, customer_key)
    if not billing_key:
        return False
    ok_charge = charge_billing(
        billing_key=billing_key,
        customer_key=customer_key,
        customer_email=email,
    )
    if not ok_charge:
        delete_billing_key(billing_key)
        return False
    ok = _update_profile(
        user_id,
        plan="pro",
        toss_customer_key=customer_key,
        toss_billing_key=billing_key,
        next_billing_at=_next_billing_iso(30),
    )
    if ok:
        st.session_state.pop(_SYNC_TS_KEY, None)
        st.session_state["billing_just_activated"] = True
        user = st.session_state.get("sb_user")
        if isinstance(user, dict):
            user["plan"] = "pro"
            user["toss_customer_key"] = customer_key
            st.session_state["sb_user"] = user
    return ok


def cancel_pro(user_id: str) -> bool:
    profile = get_profile_billing(user_id)
    billing_key = (profile.get("toss_billing_key") or "").strip()
    if billing_key:
        delete_billing_key(billing_key)
    ok = _update_profile(user_id, plan="free", clear_billing=True)
    if ok:
        st.session_state.pop(_SYNC_TS_KEY, None)
        user = st.session_state.get("sb_user")
        if isinstance(user, dict):
            user["plan"] = "free"
            st.session_state["sb_user"] = user
    return ok


def _parse_billing_at(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        if isinstance(raw, datetime):
            dt = raw
        else:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt.astimezone(KST)
    except ValueError:
        return None


def sync_subscription(user_id: str, *, force: bool = False) -> str:
    """
    next_billing_at 이 지났으면 재청구(lazy renewal).
    반환: 'pro' | 'free'
    """
    if not pro_billing_enabled():
        return "free"
    now_ts = time.time()
    if not force:
        last = float(st.session_state.get(_SYNC_TS_KEY) or 0)
        cached = st.session_state.get("sb_user", {})
        if (
            last
            and (now_ts - last) < _SYNC_TTL_SEC
            and isinstance(cached, dict)
            and cached.get("plan") in ("pro", "free")
        ):
            return cached["plan"]

    profile = get_profile_billing(user_id)
    plan = (profile.get("plan") or "free").strip().lower()
    billing_key = (profile.get("toss_billing_key") or "").strip()
    customer_key = (profile.get("toss_customer_key") or "").strip()
    next_at = _parse_billing_at(profile.get("next_billing_at"))

    if not billing_key or not customer_key:
        st.session_state[_SYNC_TS_KEY] = now_ts
        return "free" if plan != "pro" or not billing_key else plan

    now = datetime.now(KST)
    if next_at is None:
        # pro인데 만료일 없으면 유지(레거시) — 다음 접속부터 30일 설정
        if plan == "pro":
            _update_profile(user_id, plan="pro", next_billing_at=_next_billing_iso(30))
        st.session_state[_SYNC_TS_KEY] = now_ts
        return "pro" if plan == "pro" else "free"

    if next_at > now:
        st.session_state[_SYNC_TS_KEY] = now_ts
        return "pro" if plan == "pro" else plan

    # 갱신 청구
    ok = charge_billing(
        billing_key=billing_key,
        customer_key=customer_key,
        customer_email=profile.get("email"),
    )
    if ok:
        _update_profile(
            user_id,
            plan="pro",
            toss_customer_key=customer_key,
            toss_billing_key=billing_key,
            next_billing_at=_next_billing_iso(30),
        )
        plan = "pro"
    else:
        # 결제 실패 → free (키는 남겨 재시도 가능하도록 유지하지 않고 해지에 가깝게)
        _update_profile(user_id, plan="free", clear_billing=True)
        if billing_key:
            delete_billing_key(billing_key)
        plan = "free"
        st.session_state["billing_last_error"] = (
            st.session_state.get("billing_last_error")
            or "정기 결제에 실패해 Pro가 해지되었습니다."
        )

    st.session_state[_SYNC_TS_KEY] = now_ts
    return plan


def handle_toss_query(user_id: str | None, email: str | None = None) -> None:
    """?toss=billing&authKey=&customerKey= 또는 toss=fail 처리."""
    if not pro_billing_enabled():
        return
    try:
        toss = st.query_params.get("toss")
    except Exception:
        return
    if not toss:
        return

    if toss == "fail":
        code = st.query_params.get("code") or ""
        msg = st.query_params.get("message") or "결제가 취소되거나 실패했습니다."
        st.session_state["billing_last_error"] = f"{code} {msg}".strip()
    elif toss == "billing" and user_id:
        auth_key = str(st.query_params.get("authKey") or "").strip()
        customer_key = str(st.query_params.get("customerKey") or "").strip()
        expected = customer_key_for_user(user_id)
        if auth_key and customer_key:
            if customer_key != expected:
                st.session_state["billing_last_error"] = (
                    "결제 고객 키가 로그인 계정과 일치하지 않습니다."
                )
            else:
                start_pro_after_billing_auth(
                    user_id,
                    auth_key=auth_key,
                    customer_key=customer_key,
                    email=email,
                )

    try:
        drop = {
            "toss",
            "authKey",
            "customerKey",
            "code",
            "message",
            "checkout",
            "session_id",
        }
        params = {k: v for k, v in st.query_params.items() if k not in drop}
        st.query_params.clear()
        for k, v in params.items():
            st.query_params[k] = v
    except Exception:
        pass


def billing_auth_html(
    *,
    customer_key: str,
    customer_email: str = "",
    customer_name: str = "회원",
) -> str:
    """토스 빌링 인증창을 여는 작은 HTML (components.html용)."""
    ck = client_key()
    base = app_redirect_url()
    success = f"{base}/?toss=billing"
    fail = f"{base}/?toss=fail"
    # JS string escape
    def esc(s: str) -> str:
        return (
            s.replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", " ")
            .replace("<", "\\u003c")
        )

    return f"""
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <script src="https://js.tosspayments.com/v2/standard"></script>
  <style>
    body {{ margin: 0; font-family: system-ui, sans-serif; background: transparent; }}
    button {{
      width: 100%; padding: 0.65rem 0.8rem; border: none; border-radius: 6px;
      background: #3182f6; color: #fff; font-weight: 600; cursor: pointer;
    }}
    button:disabled {{ opacity: 0.5; cursor: wait; }}
    .err {{ color: #e11; font-size: 12px; margin-top: 6px; }}
  </style>
</head>
<body>
  <button id="btn" type="button">카드 등록 · Pro 시작</button>
  <div class="err" id="err"></div>
  <script>
    const clientKey = '{esc(ck)}';
    const customerKey = '{esc(customer_key)}';
    const successUrl = '{esc(success)}';
    const failUrl = '{esc(fail)}';
    const customerEmail = '{esc(customer_email or "")}';
    const customerName = '{esc(customer_name or "회원")}';
    const btn = document.getElementById('btn');
    const err = document.getElementById('err');
    btn.addEventListener('click', async () => {{
      btn.disabled = true;
      err.textContent = '';
      try {{
        const tossPayments = TossPayments(clientKey);
        const payment = tossPayments.payment({{ customerKey }});
        await payment.requestBillingAuth({{
          method: 'CARD',
          successUrl,
          failUrl,
          customerEmail: customerEmail || undefined,
          customerName,
        }});
      }} catch (e) {{
        err.textContent = (e && e.message) ? e.message : String(e);
        btn.disabled = false;
      }}
    }});
  </script>
</body>
</html>
"""
