# PersonaOS — Local Setup

Everything here is wired together and has been tested end-to-end (backend
test suite + a live cross-origin cookie auth check). This file is the exact
sequence to get it running on your machine.

## What's in this folder

```
personaos/
├── index.html, onboarding.html, dashboard.html, settings.html, login.html
├── css/style.css
├── js/{config.js, api.js, engine.js}      ← frontend
└── backend/
    ├── main.py, database.py, schemas.py, auth_utils.py
    ├── routes/{auth.py, engine.py, billing.py}
    ├── requirements.txt
    └── .env                                ← backend config (already filled in for local dev)
```

## 1. Start the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Leave this running. It creates `personaos.db` (SQLite) automatically on
first launch — no manual migration step. Confirm it's up:

```bash
curl [https://persona-8xev.onrender.com](https://persona-8xev.onrender.com)
# {"status":"ok"}
```

`.env` is already filled in with a real random session secret, ready for
local dev. You only need to touch it if you change ports or go to
production (see below).

## 2. Start the frontend

Open a second terminal. The frontend **must** be served over HTTP, not
opened as a `file://` path — cookie-based auth doesn't work reliably from
`file://`, and the backend's CORS is configured for a specific origin.

```bash
cd personaos        # the project root, not backend/
python3 -m http.server 5500
```

Then open **http://localhost:5500/login.html** in your browser.

(Any static server works — `npx serve -l 5500`, VS Code's Live Server on
port 5500, etc. — just make sure it's port 5500, since that's what
`backend/.env`'s `ALLOWED_ORIGINS` is already set to. If you use a
different port, update `ALLOWED_ORIGINS` in `backend/.env` and restart
uvicorn.)

## 3. Use it

1. **Create an account** on the login screen → lands you in onboarding.
2. **Onboarding**: paste ~40+ words of sample writing, answer the four
   forced-choice pairs, see your starting Profile Strength.
3. **Workspace**: paste a rough draft, hit Generate, then tap Off / Close /
   Locked In on the output to calibrate.
4. **Dashboard**: watch Profile Strength, the radar chart, and the
   Consistency Log update from what you just did.
5. **Settings**: export your profile as JSON, view source text on file,
   or test the plan buttons (these call a dev-only upgrade route — see
   below).

Everything here is in a real SQLite database now, not the browser's
localStorage — refreshing, closing the tab, or switching machines won't
lose any of it as long as the same backend/database is running.

## What's still a stand-in (by design, not by accident)

These were flagged in code comments too, but worth listing in one place:

- **Generation is a placeholder rewrite, not a real LLM call.**
  `backend/routes/engine.py` → `_mock_rewrite()`. Swap this for a call to
  your model of choice, passing `profile.markdown_profile` as the style
  spec in the system prompt. Nothing else needs to change — the route's
  request/response shape already matches what the frontend expects.

- **Billing has no real checkout yet.** The Settings page's plan buttons
  call `POST /billing/dev/upgrade`, which grants a tier with no payment
  involved. This route 404s automatically once you set `ENV=production`
  in `.env` — delete it for real, or wire up actual Lemon Squeezy
  Checkout links before launch. The webhook handler
  (`/billing/webhook/lemonsqueezy`) is real and signature-verified; it
  just needs a live Lemon Squeezy store pointed at it.

## Before this goes anywhere public

- **Set `COOKIE_SECURE=true`** in `.env` once this is served over HTTPS —
  it's `false` only because local dev is plain HTTP.
- **Rotate `SESSION_SECRET`** for production — the one in `.env` was
  generated for this local copy; treat it as compromised the moment this
  zip is shared with anyone.
- **Set a real `LEMON_SQUEEZY_WEBHOOK_SECRET`** from your Lemon Squeezy
  store's webhook settings — until then, the webhook route correctly
  refuses every payload (verified in testing), so no real purchases would
  be processed anyway.
- **Move off SQLite to Postgres** before multiple people hit this at once
  — change `DATABASE_URL` in `.env`; no model code changes needed, that's
  what `database.py`'s dialect-agnostic column types were for. The one
  thing to confirm post-move: `with_for_update()` in
  `routes/engine.py`'s `_deduct_words()` becomes a real row lock on
  Postgres (it's a no-op on SQLite today) — that's the function protecting
  against double-spending word balance under concurrent requests.
- **No CSRF protection yet.** SameSite=Lax on the session cookie covers
  the common cases, but if this grows beyond a single first-party
  frontend, add a CSRF token before launch.
