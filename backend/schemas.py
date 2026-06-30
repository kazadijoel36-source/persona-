"""
schemas.py
Pydantic request/response contracts. Kept separate from database.py's ORM
models on purpose: the API's shape and the DB's shape are allowed to drift
(e.g. hashed_password should never round-trip into a response) without
that drift becoming a bug.
"""

import datetime as dt
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, ConfigDict


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    email: EmailStr
    tier: str
    created_at: dt.datetime


# ---------------------------------------------------------------------------
# Engine — onboarding / profile
# ---------------------------------------------------------------------------
class IngestIn(BaseModel):
    text: str = Field(min_length=1)


class OnboardingCompleteIn(BaseModel):
    axes: dict[str, float]


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    markdown_profile: str
    axes_json: dict
    strength_score: float
    strength_history_json: list


class SourceTextOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    text: str
    created_at: dt.datetime


# ---------------------------------------------------------------------------
# Engine — generation / calibration
# ---------------------------------------------------------------------------
class GenerateIn(BaseModel):
    raw_input: str = Field(min_length=1)
    tone: int = 50
    format: str = "email"


class BalanceOut(BaseModel):
    tier: str
    pack_balance: int
    subscription_used: int
    subscription_cap: int
    total_available: int


class GenerateOut(BaseModel):
    output: str
    cost: int
    balance: BalanceOut


class CalibrateIn(BaseModel):
    direction: int = Field(ge=-1, le=1)  # -1 Off, 0 Close, 1 Locked In
    snippet: Optional[str] = ""
    axis_shifts: Optional[dict[str, float]] = None


class FeedbackLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    input_text: str
    direction: int
    delta: float
    created_at: dt.datetime


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------
class DevUpgradeIn(BaseModel):
    tier: str


# ---------------------------------------------------------------------------
# Anonymous trial (value-first, pre-signup flow)
# ---------------------------------------------------------------------------
class AnonOnboardingIn(BaseModel):
    axes: dict[str, float]
    source_text: Optional[str] = ""


class AnonGenerateIn(BaseModel):
    raw_input: str = Field(min_length=1)
    tone: int = 50
    format: str = "email"


class AnonStatusOut(BaseModel):
    words_used: int
    words_remaining: int
    cap: int
    axes: dict


class AnonGenerateOut(BaseModel):
    output: str
    cost: int
    status: AnonStatusOut
