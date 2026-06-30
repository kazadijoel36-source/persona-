"""
routes/billing.py
Lemon Squeezy webhook handling + a dev-only manual upgrade endpoint.

The webhook is signature-verified before anything in the payload is
trusted. An unverified billing webhook is the single easiest way for this
product to get free Pro upgrades handed out — anyone who finds the URL
could POST a fake "subscription activated" event. _verify_signature()
refuses to process anything it can't verify, including refusing outright
if no secret is configured, rather than failing open.
"""

import os
import json
import hmac
import hashlib
import datetime as dt

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.orm import Session

from database import get_db, User, Tier, TIER_CAPS
from auth_utils import get_current_user
import schemas

router = APIRouter(prefix="/billing", tags=["billing"])

LEMON_SQUEEZY_WEBHOOK_SECRET = os.getenv("LEMON_SQUEEZY_WEBHOOK_SECRET", "")

# Map your actual Lemon Squeezy variant names to word grants here.
PACK_WORD_GRANTS = {
    "starter-pack": TIER_CAPS[Tier.starter],
    "creator-pack": TIER_CAPS[Tier.creator],
}


def _verify_signature(raw_body: bytes, signature_header: str) -> bool:
    if not LEMON_SQUEEZY_WEBHOOK_SECRET:
        return False  # fail closed — never trust an unsigned payload
    digest = hmac.new(LEMON_SQUEEZY_WEBHOOK_SECRET.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature_header or "")


@router.post("/webhook/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request, db: Session = Depends(get_db)):
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not _verify_signature(raw_body, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(raw_body)
    event_name = payload.get("meta", {}).get("event_name", "")
    custom_data = payload.get("meta", {}).get("custom_data", {})
    user_id = custom_data.get("user_id")

    if not user_id:
        raise HTTPException(status_code=400, detail="Missing user_id in custom_data")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if event_name in ("subscription_created", "subscription_payment_success"):
        user.tier = Tier.pro
        user.subscription_cap = TIER_CAPS[Tier.pro]
        user.word_balance_subscription_used = 0
        user.cycle_resets_at = dt.datetime.utcnow() + dt.timedelta(days=30)

    elif event_name in ("subscription_cancelled", "subscription_expired"):
        user.tier = Tier.free
        user.subscription_cap = 0
        user.cycle_resets_at = None

    elif event_name == "order_created":
        variant = (
            payload.get("data", {})
            .get("attributes", {})
            .get("first_order_item", {})
            .get("variant_name", "")
        )
        grant = PACK_WORD_GRANTS.get(variant)
        if grant:
            user.word_balance_packs += grant
            if user.tier == Tier.free:
                user.tier = Tier.starter if variant == "starter-pack" else Tier.creator

    db.add(user)
    db.commit()
    return {"ok": True}


@router.post("/dev/upgrade")
def dev_manual_upgrade(
    payload: schemas.DevUpgradeIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    DEV-ONLY. Lets the Settings page's plan buttons work before real Lemon
    Squeezy checkout is wired in. Bypasses payment entirely — gated behind
    ENV so it 404s the moment ENV=production is set. Delete this route, or
    leave the gate in place, before taking real money.
    """
    if os.getenv("ENV", "development") == "production":
        raise HTTPException(status_code=404)

    valid_tiers = {t.value for t in Tier}
    if payload.tier not in valid_tiers:
        raise HTTPException(status_code=400, detail="Unknown tier")

    tier = Tier(payload.tier)
    current_user.tier = tier

    if tier == Tier.pro:
        current_user.subscription_cap = TIER_CAPS[Tier.pro]
        current_user.word_balance_subscription_used = 0
        current_user.cycle_resets_at = dt.datetime.utcnow() + dt.timedelta(days=30)
    elif tier in (Tier.starter, Tier.creator):
        current_user.word_balance_packs += TIER_CAPS[tier]

    db.add(current_user)
    db.commit()
    return {"ok": True, "tier": current_user.tier.value}
