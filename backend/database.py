"""
database.py
DB connection, session factory, and ORM models.

Defaults to SQLite for local dev. Swapping to Postgres later is a one-line
change to DATABASE_URL — no model code changes needed, since everything
below uses SQLAlchemy's dialect-agnostic column types. The one exception is
`with_for_update()` in routes/engine.py, which is a no-op on SQLite but
becomes a real row lock the moment this points at Postgres.
"""

import os
import enum
import uuid
import datetime as dt

from dotenv import load_dotenv
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    JSON,
    Enum as SAEnum,
    create_engine,
)
from sqlalchemy.orm import sessionmaker, declarative_base, relationship

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./personaos.db")
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def gen_id() -> str:
    return str(uuid.uuid4())


def default_axes() -> dict:
    return {
        "formality": 50,
        "directness": 50,
        "warmth": 50,
        "sentenceVariance": 50,
        "vocabRange": 50,
    }


class Tier(str, enum.Enum):
    free = "free"
    starter = "starter"
    creator = "creator"
    pro = "pro"


# Word grants per tier. For starter/creator these are one-time PAYG packs
# added to the lifetime pack balance. For pro this is the *monthly*
# subscription allotment. Free is a one-time grant, same pool as packs.
TIER_CAPS = {
    Tier.free: 1000,
    Tier.starter: 10000,
    Tier.creator: 25000,
    Tier.pro: 30000,
}


class AnonSession(Base):
    """Pre-signup, value-first flow. One row per anonymous visitor (keyed by
    a client-generated UUID stored in localStorage), tracking the free
    1,000-word trial before any account exists. Consumed and deleted the
    moment the visitor registers — see routes/auth.py register()."""

    __tablename__ = "anon_sessions"

    id = Column(String, primary_key=True)  # the client-generated session_id, not gen_id()
    words_used = Column(Integer, default=0, nullable=False)
    axes_json = Column(JSON, default=default_axes, nullable=False)
    source_text = Column(Text, default="", nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)


ANON_WORD_CAP = 1000
SIGNUP_BONUS_WORDS = 500


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=gen_id)
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    tier = Column(SAEnum(Tier), default=Tier.free, nullable=False)

    # Two separate pools, deliberately not one `word_balance` int:
    # - word_balance_packs: lifetime, only ever added to (PAYG packs + the
    #   one-time free grant). Never expires, never resets.
    # - subscription_cap / word_balance_subscription_used: Pro's monthly
    #   allotment. Resets to 0-used every cycle; unused words don't roll over.
    word_balance_packs = Column(Integer, default=0, nullable=False)
    subscription_cap = Column(Integer, default=0, nullable=False)
    word_balance_subscription_used = Column(Integer, default=0, nullable=False)
    cycle_resets_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=dt.datetime.utcnow)

    profiles = relationship("Profile", back_populates="user", cascade="all, delete-orphan")
    drafts = relationship("Draft", back_populates="user", cascade="all, delete-orphan")
    feedback_logs = relationship("FeedbackLog", back_populates="user", cascade="all, delete-orphan")


class Profile(Base):
    __tablename__ = "profiles"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)

    # name + is_default makes this one-to-many: Pro's "multiple saved
    # personas" is just additional rows here, not a schema change later.
    name = Column(String, default="Default Voice", nullable=False)
    is_default = Column(Boolean, default=True, nullable=False)

    # The narrative version, injected straight into the LLM system prompt.
    markdown_profile = Column(Text, default="", nullable=False)
    # The numeric version, for the Dashboard's radar chart. Kept separate
    # from markdown_profile on purpose — one's prose, one's chart data,
    # and parsing one out of the other is a needless extra failure point.
    axes_json = Column(JSON, default=default_axes, nullable=False)

    strength_score = Column(Float, default=0.0, nullable=False)
    strength_history_json = Column(JSON, default=list, nullable=False)

    created_at = Column(DateTime, default=dt.datetime.utcnow)
    updated_at = Column(DateTime, default=dt.datetime.utcnow, onupdate=dt.datetime.utcnow)

    user = relationship("User", back_populates="profiles")
    source_texts = relationship("SourceText", back_populates="profile", cascade="all, delete-orphan")
    feedback_logs = relationship("FeedbackLog", back_populates="profile", cascade="all, delete-orphan")
    drafts = relationship("Draft", back_populates="profile", cascade="all, delete-orphan")


class SourceText(Base):
    """Every excerpt used to train a profile — what the Settings page lists."""

    __tablename__ = "source_texts"

    id = Column(String, primary_key=True, default=gen_id)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=dt.datetime.utcnow)

    profile = relationship("Profile", back_populates="source_texts")


class FeedbackLog(Base):
    """One row per calibration tap — backs the Dashboard's Consistency Log."""

    __tablename__ = "feedback_logs"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)

    input_text = Column(Text, default="")  # snippet shown in the log
    direction = Column(Integer, nullable=False)  # -1 = Off, 0 = Close, 1 = Locked In
    axis_shifts_json = Column(JSON, default=dict)  # which axes moved, and by how much
    delta = Column(Float, default=0.0)  # net change to strength_score

    created_at = Column(DateTime, default=dt.datetime.utcnow)

    user = relationship("User", back_populates="feedback_logs")
    profile = relationship("Profile", back_populates="feedback_logs")


class Draft(Base):
    """Every generation — backs the Workspace's draft history rail."""

    __tablename__ = "drafts"

    id = Column(String, primary_key=True, default=gen_id)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    profile_id = Column(String, ForeignKey("profiles.id"), nullable=False)

    raw_input = Column(Text, nullable=False)
    output = Column(Text, nullable=False)
    format = Column(String, default="email")
    cost = Column(Integer, default=0)  # words deducted for this draft

    created_at = Column(DateTime, default=dt.datetime.utcnow)

    user = relationship("User", back_populates="drafts")
    profile = relationship("Profile", back_populates="drafts")
