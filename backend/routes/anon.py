"""
routes/anon.py
The pre-signup, value-first trial. No account, no cookie — just a
client-generated session_id (a UUID the frontend creates and stores in
localStorage on first visit) sent as the `X-Anon-Session` header.

This intentionally duplicates a thin slice of routes/engine.py's logic
(word counting, the mock rewrite) rather than trying to unify anonymous
and authenticated users into one code path. The two flows have different
identity models (header vs. cookie) and different storage (AnonSession vs.
User/Profile); forcing them through shared logic would mean a lot of
`if anonymous:` branches threaded through engine.py for a flow that's
deleted the moment the user converts anyway.
"""

import datetime as dt

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from database import get_db, AnonSession, ANON_WORD_CAP, default_axes
import schemas
from routes.engine import _mock_rewrite, _word_count

router = APIRouter(prefix="/anon", tags=["anon"])


def get_or_create_anon_session(
    db: Session = Depends(get_db),
    x_anon_session: str = Header(..., alias="X-Anon-Session"),
) -> AnonSession:
    if not x_anon_session or len(x_anon_session) > 64:
        raise HTTPException(status_code=400, detail="Missing or invalid X-Anon-Session header")

    session = db.query(AnonSession).filter(AnonSession.id == x_anon_session).first()
    if not session:
        session = AnonSession(id=x_anon_session, words_used=0, axes_json=default_axes())
        db.add(session)
        db.commit()
        db.refresh(session)
    return session


def _status_out(session: AnonSession) -> schemas.AnonStatusOut:
    remaining = max(0, ANON_WORD_CAP - session.words_used)
    return schemas.AnonStatusOut(
        words_used=session.words_used,
        words_remaining=remaining,
        cap=ANON_WORD_CAP,
        axes=session.axes_json,
    )


@router.get("/status", response_model=schemas.AnonStatusOut)
def anon_status(session: AnonSession = Depends(get_or_create_anon_session)):
    return _status_out(session)


@router.post("/onboarding", response_model=schemas.AnonStatusOut)
def anon_onboarding(
    payload: schemas.AnonOnboardingIn,
    db: Session = Depends(get_db),
    session: AnonSession = Depends(get_or_create_anon_session),
):
    """Stores the quick pre-generation calibration (a few slider/forced-choice
    answers) so the first 'aha!' generation is already somewhat personalized,
    and so this data can be carried straight into the real Profile on signup
    instead of asking the same questions twice."""
    session.axes_json = {**session.axes_json, **payload.axes}
    if payload.source_text:
        session.source_text = (session.source_text + "\n\n" + payload.source_text).strip()
    db.add(session)
    db.commit()
    db.refresh(session)
    return _status_out(session)


@router.post("/generate", response_model=schemas.AnonGenerateOut)
def anon_generate(
    payload: schemas.AnonGenerateIn,
    db: Session = Depends(get_db),
    session: AnonSession = Depends(get_or_create_anon_session),
):
    cost = max(_word_count(payload.raw_input), 15)
    if session.words_used + cost > ANON_WORD_CAP:
        raise HTTPException(
            status_code=402,
            detail="You've used your 1,000 free words. Sign up free to keep going + claim 500 bonus words.",
        )

    output = _mock_rewrite(payload.raw_input, payload.format)
    session.words_used += cost
    db.add(session)
    db.commit()
    db.refresh(session)

    return schemas.AnonGenerateOut(output=output, cost=cost, status=_status_out(session))
