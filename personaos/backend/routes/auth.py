"""
routes/auth.py
Registration, login, logout, and "who am I" — sets/clears the httpOnly
session cookie on register and login.
"""

import os

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from database import get_db, User, Profile, Tier, TIER_CAPS
from auth_utils import (
    hash_password,
    verify_password,
    create_session_token,
    get_current_user,
    SESSION_COOKIE_NAME,
)
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
def register(payload: schemas.RegisterIn, response: Response, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=payload.email,
        hashed_password=hash_password(payload.password),
        tier=Tier.free,
        word_balance_packs=TIER_CAPS[Tier.free],  # the one-time 1,000 free words
    )
    db.add(user)
    db.flush()  # assign user.id before the dependent Profile row is created

    db.add(Profile(user_id=user.id, name="Default Voice"))
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
