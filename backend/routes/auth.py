"""
routes/auth.py
Registration, login, logout, and "who am I" — sets/clears the httpOnly
session cookie on register and login.

register() also claims any pre-signup anonymous trial: if the client sends
the X-Anon-Session header it used during the value-first "Try Now" flow,
we (a) hand the new account a 500-word signup bonus on top of the normal
1,000 free words, (b) carry over whatever calibration axes / source text
were collected pre-signup so the user doesn't repeat the onboarding survey,
and (c) delete the now-redundant AnonSession row. A missing or unknown
session id is not an error — it just means they registered directly
without trying the product first, which is a perfectly normal path too.
"""

import os
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Response, Header
from sqlalchemy.orm import Session

from database import (
    get_db,
    User,
    Profile,
    Tier,
    TIER_CAPS,
    AnonSession,
    SourceText,
    SIGNUP_BONUS_WORDS,
    default_axes,
)
from auth_utils import (
    hash_password,
    verify_password,
    create_session_token,
    get_current_user,
    SESSION_COOKIE_NAME,
)
from routes.engine import _build_markdown_profile
import schemas

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"
COOKIE_MAX_AGE = int(os.getenv("SESSION_TTL_HOURS", "720")) * 3600


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=COOKIE_SECURE,  # set true once served over HTTPS
        samesite="lax",
        max_age=COOKIE_MAX_AGE,
        path="/",
    )


@router.post("/register", response_model=schemas.UserOut)
def register(
    payload: schemas.RegisterIn,
    response: Response,
    db: Session = Depends(get_db),
    x_anon_session: str | None = Header(default=None, alias="X-Anon-Session"),
):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    anon_session = None
    if x_anon_session:
        anon_session = db.query(AnonSession).filter(AnonSession.id == x_anon_session).first()

    word_grant = TIER_CAPS[Tier.free] + (SIGNUP_BONUS_WORDS if anon_session else 0)

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        tier=Tier.free,
        word_balance_packs=word_grant,
    )
    db.add(user)
    db.flush()  # assign user.id before the dependent Profile row is created

    profile = Profile(user_id=user.id, name="Default Voice", axes_json=default_axes())

    # Carry the pre-signup trial's calibration straight into the real
    # profile so the user lands in the Workspace already configured,
    # instead of being sent through the onboarding survey a second time.
    if anon_session and (anon_session.words_used > 0 or anon_session.source_text):
        profile.axes_json = {**profile.axes_json, **(anon_session.axes_json or {})}
        profile.markdown_profile = _build_markdown_profile(profile.axes_json)
        profile.strength_score = 18.0
        profile.strength_history_json = [4, 9, 14, 18]

    db.add(profile)
    db.flush()

    if anon_session and anon_session.source_text:
        db.add(SourceText(profile_id=profile.id, text=anon_session.source_text))

    if anon_session:
        db.delete(anon_session)

    db.commit()
    db.refresh(user)

    _set_session_cookie(response, create_session_token(user.id))
    return user


@router.post("/login", response_model=schemas.UserOut)
def login(payload: schemas.LoginIn, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _set_session_cookie(response, create_session_token(user.id))
    return user


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=schemas.UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user
