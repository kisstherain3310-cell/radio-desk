# ============================================================
# Stripe 월 구독 (KRW 2,990) — Checkout / Portal / sync
# Secrets 없으면 비활성 (앱은 free 쿼터만 사용)
# ============================================================

from __future__ import annotations

import os
import time
from typing import Any

import streamlit as st

PRO_PRICE_LABEL = "월 2,990원"
_SYNC_TS_KEY = "stripe_sync_ts"
_SYNC_TTL_SEC = 300  # 로그인 후 Stripe 재조회 최소 간격


def _secret_or_env(name: str) -> str:
    try:
        if hasattr(st, "secrets") and name in st.secrets:
            return str(st.secrets[name]).strip()
    except Exception:
        pass
    return (os.getenv(name) or "").strip()


def stripe_configured() -> bool:
    return bool(
        _secret_or_env("STRIPE_SECRET_KEY") and _secret_or_env("STRIPE_PRICE_ID")
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


def _stripe():
    if not stripe_configured():
        return None
    try:
        import stripe
    except ImportError:
        return None
    stripe.api_key = _secret_or_env("STRIPE_SECRET_KEY")
    return stripe


def get_service_client():
    """plan/stripe 필드 갱신용 (RLS 우회)."""
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


def _update_profile_billing(
    user_id: str,
    *,
    plan: str,
    stripe_customer_id: str | None = None,
    stripe_subscription_id: str | None = None,
) -> bool:
    client = get_service_client()
    if client is None:
        st.session_state["billing_last_error"] = (
            "SUPABASE_SERVICE_ROLE_KEY 가 없어 구독 상태를 저장하지 못했습니다."
        )
        return False
    payload: dict[str, Any] = {"id": user_id, "plan": plan}
    if stripe_customer_id is not None:
        payload["stripe_customer_id"] = stripe_customer_id
    if stripe_subscription_id is not None:
        payload["stripe_subscription_id"] = stripe_subscription_id
    try:
        client.table("profiles").upsert(payload, on_conflict="id").execute()
        return True
    except Exception as exc:
        st.session_state["billing_last_error"] = str(exc).split("\n")[0][:180]
        return False


def get_profile_billing(user_id: str) -> dict[str, Any]:
    client = get_service_client()
    if client is None:
        return {}
    try:
        res = (
            client.table("profiles")
            .select("plan, stripe_customer_id, stripe_subscription_id, email")
            .eq("id", user_id)
            .maybe_single()
            .execute()
        )
        return getattr(res, "data", None) or {}
    except Exception:
        return {}


def create_checkout_session(user_id: str, email: str) -> str | None:
    stripe = _stripe()
    if stripe is None:
        return None
    price_id = _secret_or_env("STRIPE_PRICE_ID")
    base = app_redirect_url()
    profile = get_profile_billing(user_id)
    customer_id = (profile.get("stripe_customer_id") or "").strip() or None

    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{base}/?checkout=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/?checkout=cancel",
        "client_reference_id": user_id,
        "metadata": {"supabase_user_id": user_id},
        "subscription_data": {"metadata": {"supabase_user_id": user_id}},
        "allow_promotion_codes": True,
    }
    if customer_id:
        params["customer"] = customer_id
    elif email:
        params["customer_email"] = email

    try:
        session = stripe.checkout.Session.create(**params)
        return getattr(session, "url", None) or session.get("url")
    except Exception as exc:
        st.session_state["billing_last_error"] = str(exc).split("\n")[0][:180]
        return None


def create_portal_session(customer_id: str) -> str | None:
    stripe = _stripe()
    if stripe is None or not customer_id:
        return None
    base = app_redirect_url()
    try:
        session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=base + "/",
        )
        return getattr(session, "url", None) or session.get("url")
    except Exception as exc:
        st.session_state["billing_last_error"] = str(exc).split("\n")[0][:180]
        return None


def fulfill_checkout_session(session_id: str, expected_user_id: str) -> bool:
    """Checkout 성공 콜백: session 검증 후 plan=pro."""
    stripe = _stripe()
    if stripe is None or not session_id:
        return False
    try:
        session = stripe.checkout.Session.retrieve(
            session_id,
            expand=["subscription"],
        )
    except Exception as exc:
        st.session_state["billing_last_error"] = str(exc).split("\n")[0][:180]
        return False

    status = getattr(session, "status", None) or (
        session.get("status") if isinstance(session, dict) else None
    )
    payment_status = getattr(session, "payment_status", None) or (
        session.get("payment_status") if isinstance(session, dict) else None
    )
    if status not in ("complete",) and payment_status not in ("paid", "no_payment_required"):
        # subscription mode: complete + paid
        if status != "complete":
            st.session_state["billing_last_error"] = "Checkout이 완료되지 않았습니다."
            return False

    meta = getattr(session, "metadata", None) or {}
    if hasattr(meta, "get"):
        meta_uid = meta.get("supabase_user_id") or ""
    else:
        meta_uid = ""
    ref = getattr(session, "client_reference_id", None) or (
        session.get("client_reference_id") if isinstance(session, dict) else None
    )
    uid = str(meta_uid or ref or "").strip()
    if uid and uid != expected_user_id:
        st.session_state["billing_last_error"] = "결제 사용자와 로그인 계정이 일치하지 않습니다."
        return False
    if not uid:
        uid = expected_user_id

    customer = getattr(session, "customer", None) or (
        session.get("customer") if isinstance(session, dict) else None
    )
    if hasattr(customer, "id"):
        customer = customer.id
    customer_id = str(customer or "").strip() or None

    sub = getattr(session, "subscription", None) or (
        session.get("subscription") if isinstance(session, dict) else None
    )
    if hasattr(sub, "id"):
        sub_id = sub.id
    else:
        sub_id = str(sub or "").strip() or None

    ok = _update_profile_billing(
        uid,
        plan="pro",
        stripe_customer_id=customer_id,
        stripe_subscription_id=sub_id,
    )
    if ok:
        st.session_state.pop(_SYNC_TS_KEY, None)
        st.session_state["billing_just_activated"] = True
    return ok


def sync_subscription(user_id: str, *, force: bool = False) -> str:
    """
    Stripe 구독 상태를 조회해 profiles.plan 을 맞춘다.
    반환: 'pro' | 'free'
    """
    now = time.time()
    if not force:
        last = float(st.session_state.get(_SYNC_TS_KEY) or 0)
        cached_plan = st.session_state.get("sb_user", {}).get("plan")
        if last and (now - last) < _SYNC_TTL_SEC and cached_plan in ("pro", "free"):
            return cached_plan

    profile = get_profile_billing(user_id)
    plan = (profile.get("plan") or "free").strip().lower()
    customer_id = (profile.get("stripe_customer_id") or "").strip()

    stripe = _stripe()
    if stripe is None or not customer_id:
        st.session_state[_SYNC_TS_KEY] = now
        return plan if plan in ("pro", "free") else "free"

    try:
        subs = stripe.Subscription.list(customer=customer_id, status="all", limit=10)
        data = getattr(subs, "data", None) or []
        active = None
        for s in data:
            status = getattr(s, "status", None) or (
                s.get("status") if isinstance(s, dict) else None
            )
            if status in ("active", "trialing"):
                active = s
                break

        if active is not None:
            sub_id = getattr(active, "id", None) or (
                active.get("id") if isinstance(active, dict) else None
            )
            _update_profile_billing(
                user_id,
                plan="pro",
                stripe_customer_id=customer_id,
                stripe_subscription_id=str(sub_id) if sub_id else None,
            )
            plan = "pro"
        else:
            _update_profile_billing(
                user_id,
                plan="free",
                stripe_customer_id=customer_id,
                stripe_subscription_id=profile.get("stripe_subscription_id"),
            )
            plan = "free"
    except Exception as exc:
        st.session_state["billing_last_error"] = str(exc).split("\n")[0][:180]

    st.session_state[_SYNC_TS_KEY] = now
    return plan


def handle_checkout_query(user_id: str | None) -> None:
    """?checkout=success&session_id=... 처리 후 query 정리."""
    try:
        checkout = st.query_params.get("checkout")
        session_id = st.query_params.get("session_id")
    except Exception:
        return
    if not checkout:
        return

    if checkout == "success" and session_id and user_id:
        fulfill_checkout_session(str(session_id), user_id)
        sync_subscription(user_id, force=True)

    # query 정리 (view/id 등은 유지)
    try:
        params = {
            k: v
            for k, v in st.query_params.items()
            if k not in ("checkout", "session_id")
        }
        st.query_params.clear()
        for k, v in params.items():
            st.query_params[k] = v
    except Exception:
        pass
