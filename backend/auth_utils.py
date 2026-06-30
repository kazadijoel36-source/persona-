"""
auth_utils.py
Password hashing + session handling.

Decision worth flagging explicitly: sessions are a JWT carried in an
httpOnly cookie, not a JWT in localStorage with an Authorization header.
For a product whose entire pitch is "trust us with your private writing,"
httpOnly cookies are the more defensible answer if a customer or investor
ever asks how auth works — a stored XSS payload can't read this token,
where it could trivially read localStorage. The cost is some CORS setup
(see main.py) if the frontend ends up on a different origin.
"""

import os
import datetime as dt
from typing import Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db, User

SECRET_KEY = os.getenv("SESSION_SECRET", "dev-only-change-me")
ALGORITHM = "HS256"
SESSION_COOKIE_NAME = "personaos_session"
TOKEN_TTL_HOURS = int(os.getenv("SESSION_TTL_HOURS", "720"))  # 30 days default


def hash_password(password: str) -> str:
    # bcrypt has a hard 72-byte input limit; truncate defensively rather
    # than error on unusually long pastes into the password field.
    truncated = password.encode("utf-8")[:72]
    return bcrypt.hashpw(truncated, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    truncated = password.encode("utf-8")[:72]
    return bcrypt.checkpw(truncated, hashed.encode("utf-8"))


def create_session_token(user_id: str) -> str:
    now = dt.datetime.utcnow()
    payload = {
        "sub": user_id,
        "iat": now,
        "exp": now + dt.timedelta(hours=TOKEN_TTL_HOURS),
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_session_token(token: str) -> Optional[dict]:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_session_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Session expired or invalid")

    user = db.query(User).filter(User.id == payload["sub"]).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return user
