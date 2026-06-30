/* ==========================================================================
   PersonaOS — api.js
   Talks to the real FastAPI backend (see /backend). Every method here keeps
   the exact same name and call signature as the localStorage-backed mock
   this replaced, so engine.js needed almost no changes — only the topbar's
   balance rendering changed shape, since the real backend tracks two word
   pools (pack credits vs. the Pro subscription allotment) instead of one.

   Auth: session is an httpOnly cookie set by the backend on register/login.
   Every request below sends credentials: "include" so the cookie rides
   along automatically; there is no token to manage on this side.
   ========================================================================== */

(function () {
  "use strict";

  const API_BASE = window.API_BASE;

  const TIER_LABELS = { free: "Free", starter: "Starter", creator: "Creator", pro: "Pro" };

  // The anonymous trial session id. Created once per browser on first
  // visit to the landing page and reused for every /anon/* call until the
  // visitor registers, at which point auth/register() sends it one last
  // time so the backend can migrate the bonus words + onboarding data.
  const ANON_SESSION_KEY = "personaos_anon_session";
  function getAnonSessionId() {
    let id = localStorage.getItem(ANON_SESSION_KEY);
    if (!id) {
      id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : "anon-" + Date.now() + "-" + Math.random().toString(16).slice(2);
      localStorage.setItem(ANON_SESSION_KEY, id);
    }
    return id;
  }
  function clearAnonSessionId() {
    localStorage.removeItem(ANON_SESSION_KEY);
  }

  function request(path, options) {
    options = options || {};
    return fetch(API_BASE + path, {
      method: options.method || "GET",
      credentials: "include",
      headers: Object.assign({ "Content-Type": "application/json" }, options.headers || {}),
      body: options.body,
    }).then((res) => {
      if (res.status === 204) return null;
      return res
        .json()
        .catch(() => null)
        .then((body) => {
          if (!res.ok) {
            const message = (body && body.detail) || res.statusText || "Request failed";
            return Promise.reject({ code: res.status, message });
          }
          return body;
        });
    });
  }

  function adaptProfile(p) {
    return {
      id: p.id,
      name: p.name,
      strength: p.strength_score,
      axes: p.axes_json,
      strengthHistory: p.strength_history_json,
    };
  }

  const PersonaAPI = {
    /* ---------- auth ---------- */
    register(email, password) {
      return request("/auth/register", {
        method: "POST",
        headers: { "X-Anon-Session": getAnonSessionId() },
        body: JSON.stringify({ email, password }),
      }).then((user) => {
        clearAnonSessionId(); // claimed (or there was none) — don't resend it
        return user;
      });
    },
    login(email, password) {
      return request("/auth/login", { method: "POST", body: JSON.stringify({ email, password }) });
    },
    logout() {
      return request("/auth/logout", { method: "POST" });
    },
    getCurrentUser() {
      return request("/auth/me");
    },

    /* ---------- onboarding ---------- */
    addSourceText(text) {
      return request("/engine/ingest", { method: "POST", body: JSON.stringify({ text }) });
    },
    completeOnboarding(initialAxes) {
      return request("/engine/onboarding/complete", {
        method: "POST",
        body: JSON.stringify({ axes: initialAxes }),
      }).then(adaptProfile);
    },

    /* ---------- profile / balance ---------- */
    getProfile() {
      return Promise.all([
        request("/engine/profile"),
        request("/engine/calibration-log"),
        request("/engine/source-texts"),
      ]).then(([profile, log, sources]) => {
        const adapted = adaptProfile(profile);
        adapted.calibrationLog = log.map((e) => ({
          ts: new Date(e.created_at).getTime(),
          snippet: e.input_text,
          direction: e.direction,
          delta: e.delta,
        }));
        adapted.sourceTexts = sources.map((s) => ({
          ts: new Date(s.created_at).getTime(),
          text: s.text,
        }));
        return adapted;
      });
    },

    getWordBalance() {
      return request("/engine/balance").then((b) => ({
        tier: b.tier,
        label: TIER_LABELS[b.tier] || b.tier,
        packBalance: b.pack_balance,
        subscriptionUsed: b.subscription_used,
        subscriptionCap: b.subscription_cap,
        remaining: b.total_available,
      }));
    },

    /* ---------- generation ---------- */
    generateDraft({ rawInput, tone, length, format }) {
      return request("/engine/generate", {
        method: "POST",
        body: JSON.stringify({ raw_input: rawInput, tone: Number(tone), format }),
      });
    },

    /* ---------- calibration ---------- */
    submitCalibration({ direction, snippet, axisShifts }) {
      return request("/engine/calibrate", {
        method: "POST",
        body: JSON.stringify({ direction, snippet: snippet || "", axis_shifts: axisShifts || null }),
      }).then(adaptProfile);
    },

    /* ---------- privacy / data ownership ---------- */
    exportProfile() {
      return request("/engine/export").then((data) => JSON.stringify(data, null, 2));
    },
    deleteProfile() {
      return request("/engine/profile", { method: "DELETE" });
    },

    /* ---------- billing ----------
       Hits the dev-only convenience route until real Lemon Squeezy
       checkout is wired in — see backend/routes/billing.py. */
    upgradeTier(tier) {
      return request("/billing/dev/upgrade", { method: "POST", body: JSON.stringify({ tier }) });
    },

    /* ---------- anonymous trial (value-first, pre-signup) ----------
       No cookie yet — identified by a client-generated id sent as the
       X-Anon-Session header. Used on the landing page before signup. */
    anonStatus() {
      return request("/anon/status", { headers: { "X-Anon-Session": getAnonSessionId() } });
    },
    anonOnboarding(axes, sourceText) {
      return request("/anon/onboarding", {
        method: "POST",
        headers: { "X-Anon-Session": getAnonSessionId() },
        body: JSON.stringify({ axes, source_text: sourceText || "" }),
      });
    },
    anonGenerate({ rawInput, tone, format }) {
      return request("/anon/generate", {
        method: "POST",
        headers: { "X-Anon-Session": getAnonSessionId() },
        body: JSON.stringify({ raw_input: rawInput, tone: Number(tone), format }),
      });
    },
  };

  window.PersonaAPI = PersonaAPI;
})();
