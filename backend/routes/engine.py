"""
routes/engine.py
Profile extraction and rewrite logic. Every endpoint here mirrors a method
already called against the frontend's mock `PersonaAPI` in js/api.js — the
intent is that swapping the frontend from localStorage to this backend is a
matter of pointing fetch() at these URLs, not redesigning the call sites.
"""

import re
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db, User, Profile, SourceText, FeedbackLog, Draft, Tier
import schemas
from auth_utils import get_current_user

router = APIRouter(prefix="/engine", tags=["engine"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_default_profile(db: Session, user: User) -> Profile:
    profile = (
        db.query(Profile)
        .filter(Profile.user_id == user.id, Profile.is_default.is_(True))
        .first()
    )
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found for user")
    return profile


def _word_count(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


def _build_markdown_profile(axes: dict) -> str:
    return (
        "# Voice Profile\n\n"
        f"- Formality: {axes.get('formality', 50)}/100\n"
        f"- Directness: {axes.get('directness', 50)}/100\n"
        f"- Warmth: {axes.get('warmth', 50)}/100\n"
        f"- Sentence length variance: {axes.get('sentenceVariance', 50)}/100\n"
        f"- Vocabulary range: {axes.get('vocabRange', 50)}/100\n\n"
        "Rewrite the user's raw input to match this calibration. Prefer "
        "their own recurring phrasing patterns over generic phrasing.\n"
    )


def _refresh_subscription_cycle(db: Session, user: User) -> None:
    """Lazily reset the monthly Pro allotment once the cycle has elapsed.

    No cron job needed for an MVP: every balance check or deduction passes
    through here first, so the reset happens on next access rather than on
    a schedule. Move this to a scheduled task once usage-pattern analytics
    need accurate "as of midnight" cycle boundaries.
    """
    if user.tier == Tier.pro and user.cycle_resets_at and dt.datetime.utcnow() >= user.cycle_resets_at:
        user.word_balance_subscription_used = 0
        user.cycle_resets_at = dt.datetime.utcnow() + dt.timedelta(days=30)
        db.add(user)
        db.commit()
        db.refresh(user)


def _available_words(user: User) -> int:
    sub_remaining = 0
    if user.tier == Tier.pro:
        sub_remaining = max(0, user.subscription_cap - user.word_balance_subscription_used)
    return sub_remaining + user.word_balance_packs


def _deduct_words(db: Session, user: User, amount: int) -> User:
    """Atomic balance deduction.

    Locks the user row for the transaction (a real lock once this points
    at Postgres; a no-op on SQLite, whose single-writer model already
    serializes the write) so two concurrent /generate calls can't both
    pass the balance check before either decrements it.

    Spends the expiring subscription allotment before the lifetime pack
    balance — packs never expire, so the use-it-or-lose-it pool should
    always be drawn down first.
    """
    locked_user = db.query(User).filter(User.id == user.id).with_for_update().first()
    _refresh_subscription_cycle(db, locked_user)

    if amount > _available_words(locked_user):
        raise HTTPException(status_code=402, detail="Word balance exhausted")

    if locked_user.tier == Tier.pro:
        sub_remaining = max(0, locked_user.subscription_cap - locked_user.word_balance_subscription_used)
        from_subscription = min(sub_remaining, amount)
        locked_user.word_balance_subscription_used += from_subscription
        amount -= from_subscription

    locked_user.word_balance_packs -= amount
    db.add(locked_user)
    db.commit()
    db.refresh(locked_user)
    return locked_user


def _balance_out(user: User) -> schemas.BalanceOut:
    return schemas.BalanceOut(
        tier=user.tier.value if isinstance(user.tier, Tier) else user.tier,
        pack_balance=user.word_balance_packs,
        subscription_used=user.word_balance_subscription_used if user.tier == Tier.pro else 0,
        subscription_cap=user.subscription_cap if user.tier == Tier.pro else 0,
        total_available=_available_words(user),
    )


def _mock_rewrite(text: str, fmt: str) -> str:
    """Placeholder rewrite. Swap for a real LLM call — pass profile.markdown_profile
    as the system prompt's style spec — without touching any route signature."""
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", text.strip()) if s]
    body = " ".join(s[:1].upper() + s[1:] for s in sentences)
    if fmt == "email":
        return f"Hi,\n\n{body}\n\nBest,"
    return body


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------
@router.post("/ingest")
def ingest_source_text(
    payload: schemas.IngestIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_default_profile(db, current_user)
    db.add(SourceText(profile_id=profile.id, text=payload.text))
    db.commit()
    return {"word_count": _word_count(payload.text)}


@router.post("/onboarding/complete", response_model=schemas.ProfileOut)
def complete_onboarding(
    payload: schemas.OnboardingCompleteIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_default_profile(db, current_user)
    profile.axes_json = {**profile.axes_json, **payload.axes}
    profile.strength_score = 41.0
    profile.strength_history_json = [4, 9, 18, 27, 35, 41]
    profile.markdown_profile = _build_markdown_profile(profile.axes_json)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Profile + balance reads
# ---------------------------------------------------------------------------
@router.get("/profile", response_model=schemas.ProfileOut)
def get_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _get_default_profile(db, current_user)


@router.get("/balance", response_model=schemas.BalanceOut)
def get_balance(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _refresh_subscription_cycle(db, current_user)
    return _balance_out(current_user)


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
@router.post("/generate", response_model=schemas.GenerateOut)
def generate_draft(
    payload: schemas.GenerateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_default_profile(db, current_user)
    cost = max(_word_count(payload.raw_input), 15)

    output = _mock_rewrite(payload.raw_input, payload.format)
    user = _deduct_words(db, current_user, cost)  # raises 402 if insufficient

    db.add(
        Draft(
            user_id=user.id,
            profile_id=profile.id,
            raw_input=payload.raw_input,
            output=output,
            format=payload.format,
            cost=cost,
        )
    )
    db.commit()

    return schemas.GenerateOut(output=output, cost=cost, balance=_balance_out(user))


# ---------------------------------------------------------------------------
# Calibration (the Workspace meter -> the Dashboard's Consistency Log)
# ---------------------------------------------------------------------------
@router.post("/calibrate", response_model=schemas.ProfileOut)
def calibrate(
    payload: schemas.CalibrateIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    profile = _get_default_profile(db, current_user)

    delta = 0.4 if payload.direction == 1 else (-0.1 if payload.direction == -1 else 0.0)

    if payload.direction == 1 and payload.axis_shifts:
        axes = dict(profile.axes_json)
        for axis, shift in payload.axis_shifts.items():
            if axis in axes:
                axes[axis] = max(0, min(100, axes[axis] + shift))
        profile.axes_json = axes

    profile.strength_score = max(0.0, min(100.0, profile.strength_score + delta))
    history = list(profile.strength_history_json or [])
    history.append(round(profile.strength_score, 1))
    profile.strength_history_json = history[-30:]
    db.add(profile)

    db.add(
        FeedbackLog(
            user_id=current_user.id,
            profile_id=profile.id,
            input_text=(payload.snippet or "")[:200],
            direction=payload.direction,
            axis_shifts_json=payload.axis_shifts or {},
            delta=delta,
        )
    )
    db.commit()
    db.refresh(profile)
    return profile


@router.get("/calibration-log", response_model=list[schemas.FeedbackLogOut])
def calibration_log(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return (
        db.query(FeedbackLog)
        .filter(FeedbackLog.user_id == current_user.id)
        .order_by(FeedbackLog.created_at.desc())
        .limit(25)
        .all()
    )


# ---------------------------------------------------------------------------
# Data ownership — Settings page
# ---------------------------------------------------------------------------
@router.get("/source-texts", response_model=list[schemas.SourceTextOut])
def list_source_texts(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = _get_default_profile(db, current_user)
    return profile.source_texts


@router.get("/export")
def export_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = _get_default_profile(db, current_user)
    return {
        "name": profile.name,
        "strength": profile.strength_score,
        "axes": profile.axes_json,
        "strength_history": profile.strength_history_json,
        "markdown_profile": profile.markdown_profile,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


@router.delete("/profile")
def delete_profile(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    profile = _get_default_profile(db, current_user)
    db.query(SourceText).filter(SourceText.profile_id == profile.id).delete()
    db.query(FeedbackLog).filter(FeedbackLog.profile_id == profile.id).delete()
    db.query(Draft).filter(Draft.profile_id == profile.id).delete()

    profile.markdown_profile = ""
    profile.axes_json = {
        "formality": 50,
        "directness": 50,
        "warmth": 50,
        "sentenceVariance": 50,
        "vocabRange": 50,
    }
    profile.strength_score = 0.0
    profile.strength_history_json = []
    db.add(profile)
    db.commit()
    return {"ok": True}
