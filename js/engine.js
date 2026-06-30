/* ==========================================================================
   PersonaOS — engine.js
   DOM logic shared across every page, plus per-page initializers.
   Pages opt in by setting <body data-page="workspace|onboarding|dashboard|settings">
   ========================================================================== */

(function () {
  "use strict";

  /* ---------------------------------------------------------------------
     Shared: auth guard + logout
     --------------------------------------------------------------------- */
  // Every protected page calls this before initializing. If there's no
  // valid session cookie, the backend's /auth/me returns 401 and we bounce
  // to the login screen rather than letting the page render half-broken.
  function requireAuth() {
    return PersonaAPI.getCurrentUser().catch(() => {
      window.location.href = "login.html";
      return Promise.reject(new Error("not authenticated"));
    });
  }

  function initLogout() {
    document.querySelectorAll("[data-logout]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.preventDefault();
        PersonaAPI.logout().then(() => {
          window.location.href = "login.html";
        });
      });
    });
  }

  /* ---------------------------------------------------------------------
     Shared: topbar word balance + active nav link
     --------------------------------------------------------------------- */
  function renderTopbar() {
    PersonaAPI.getWordBalance()
      .then((bal) => {
        const pill = document.querySelector("[data-balance-pill]");
        if (!pill) return;

        if (bal.tier === "pro") {
          // Pro has a real monthly cap, so show progress against it.
          // Leftover pack credits (if any) are spent after the
          // subscription pool, so they're not part of this bar.
          const pct = Math.min(100, (bal.subscriptionUsed / bal.subscriptionCap) * 100);
          pill.innerHTML = `
            <span>${bal.label}</span>
            <span class="balance-track"><span class="balance-fill" style="width:${pct}%"></span></span>
            <strong>${bal.remaining.toLocaleString()}</strong>
            <span class="faint">words left</span>
          `;
        } else {
          // Free/Starter/Creator are pack credits with no fixed cycle cap —
          // just show what's left rather than implying a bar against a cap
          // that doesn't exist.
          pill.innerHTML = `
            <span>${bal.label}</span>
            <strong>${bal.remaining.toLocaleString()}</strong>
            <span class="faint">words left</span>
          `;
        }
      })
      .catch(() => {});

    const page = document.body.dataset.page;
    document.querySelectorAll("[data-nav]").forEach((a) => {
      a.classList.toggle("active", a.dataset.nav === page);
    });
  }

  /* ---------------------------------------------------------------------
     Shared: SVG chart helpers
     --------------------------------------------------------------------- */
  function radarChartSVG(axes, opts) {
    opts = opts || {};
    const labels = Object.keys(axes);
    const n = labels.length;
    const size = opts.size || 260;
    const cx = size / 2,
      cy = size / 2;
    const r = size / 2 - 38;
    const angleFor = (i) => (Math.PI * 2 * i) / n - Math.PI / 2;

    function pointAt(i, value) {
      const a = angleFor(i);
      const dist = (value / 100) * r;
      return [cx + dist * Math.cos(a), cy + dist * Math.sin(a)];
    }

    // grid rings
    let rings = "";
    [0.25, 0.5, 0.75, 1].forEach((f) => {
      const pts = labels
        .map((_, i) => pointAt(i, f * 100).join(","))
        .join(" ");
      rings += `<polygon points="${pts}" fill="none" stroke="var(--border)" stroke-width="1" />`;
    });

    // axis lines + labels
    let axisLines = "";
    let labelEls = "";
    labels.forEach((label, i) => {
      const [x, y] = pointAt(i, 100);
      axisLines += `<line x1="${cx}" y1="${cy}" x2="${x}" y2="${y}" stroke="var(--border)" stroke-width="1" />`;
      const lx = cx + (r + 26) * Math.cos(angleFor(i));
      const ly = cy + (r + 26) * Math.sin(angleFor(i));
      labelEls += `<text x="${lx}" y="${ly}" text-anchor="middle" dominant-baseline="middle"
        font-family="JetBrains Mono, monospace" font-size="9.5" fill="var(--text-faint)"
        text-transform="uppercase">${label}</text>`;
    });

    // data polygon(s)
    function polygonFor(values, color, fillOpacity) {
      const pts = labels.map((l, i) => pointAt(i, values[l]).join(",")).join(" ");
      return `<polygon points="${pts}" fill="${color}" fill-opacity="${fillOpacity}" stroke="${color}" stroke-width="1.5" />`;
    }

    let dataLayer = "";
    if (opts.compareAxes) {
      dataLayer += polygonFor(opts.compareAxes, "var(--text-faint)", 0.04);
    }
    dataLayer += polygonFor(axes, "var(--accent)", 0.12);

    return `
      <svg viewBox="0 0 ${size} ${size}" width="100%" height="100%" style="overflow:visible">
        ${rings}${axisLines}${dataLayer}${labelEls}
      </svg>`;
  }

  function sparklineSVG(history, opts) {
    opts = opts || {};
    const w = opts.width || 280;
    const h = opts.height || 56;
    const pad = 4;
    if (!history || history.length < 2) history = [0, 0];
    const min = Math.min(...history);
    const max = Math.max(...history, min + 1);
    const stepX = (w - pad * 2) / (history.length - 1);
    const pts = history.map((v, i) => {
      const x = pad + i * stepX;
      const y = h - pad - ((v - min) / (max - min)) * (h - pad * 2);
      return [x, y];
    });
    const path = pts.map((p, i) => (i === 0 ? `M${p[0]},${p[1]}` : `L${p[0]},${p[1]}`)).join(" ");
    const last = pts[pts.length - 1];
    return `
      <svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">
        <path d="${path}" fill="none" stroke="var(--accent)" stroke-width="1.5" />
        <circle cx="${last[0]}" cy="${last[1]}" r="2.5" fill="var(--accent)" />
      </svg>`;
  }

  /* ---------------------------------------------------------------------
     Page: Workspace (index.html)
     --------------------------------------------------------------------- */
  function initWorkspace() {
    const rawInput = document.querySelector("#rawInput");
    const output = document.querySelector("#output");
    const generateBtn = document.querySelector("#generateBtn");
    const toneSlider = document.querySelector("#toneSlider");
    const formatSelect = document.querySelector("#formatSelect");
    const calMeter = document.querySelector("#calMeter");
    const calConfirm = document.querySelector("#calConfirm");
    const inputCount = document.querySelector("#inputCount");
    const emptyState = document.querySelector("#outputEmpty");

    if (!generateBtn) return; // not this page

    rawInput.addEventListener("input", () => {
      const n = (rawInput.value.trim().match(/\S+/g) || []).length;
      inputCount.textContent = n + " words";
    });

    generateBtn.addEventListener("click", () => {
      const text = rawInput.value.trim();
      if (!text) return;
      generateBtn.disabled = true;
      generateBtn.textContent = "Generating…";
      output.style.opacity = "0.4";

      PersonaAPI.generateDraft({
        rawInput: text,
        tone: Number(toneSlider.value),
        format: formatSelect.value,
      })
        .then(({ output: result }) => {
          emptyState.style.display = "none";
          output.style.display = "block";
          output.textContent = result;
          output.style.opacity = "1";
          calMeter.style.display = "flex";
          renderTopbar();
        })
        .catch((err) => {
          output.style.display = "block";
          output.style.opacity = "1";
          output.innerHTML = `<span class="danger">${err.message || "Out of words. Upgrade or buy a pack to continue."}</span>`;
        })
        .finally(() => {
          generateBtn.disabled = false;
          generateBtn.textContent = "Generate →";
        });
    });

    calMeter.querySelectorAll(".seg").forEach((seg) => {
      seg.addEventListener("click", () => {
        calMeter.querySelectorAll(".seg").forEach((s) => s.classList.remove("active", "danger-seg"));
        seg.classList.add("active");
        const direction = Number(seg.dataset.direction);
        if (direction === -1) seg.classList.add("danger-seg");

        PersonaAPI.submitCalibration({
          direction,
          snippet: rawInput.value.slice(0, 90),
          axisShifts: direction === 1 ? { directness: 1.2, warmth: 0.6 } : null,
        }).then((profile) => {
          if (direction === 1) {
            calConfirm.textContent = `Profile updated · strength ${profile.strength.toFixed(1)}%`;
          } else if (direction === -1) {
            calConfirm.textContent = "Noted — won't reinforce this pattern.";
          } else {
            calConfirm.textContent = "Logged as close. No profile change.";
          }
          calConfirm.classList.add("show");
        });
      });
    });
  }

  /* ---------------------------------------------------------------------
     Page: Onboarding
     --------------------------------------------------------------------- */
  function initOnboarding() {
    const steps = document.querySelectorAll("[data-step]");
    if (!steps.length) return;

    let current = 1;
    const total = steps.length;
    const progressFill = document.querySelector("#progressFill");
    const progressLabel = document.querySelector("#progressLabel");

    function showStep(n) {
      steps.forEach((s) => (s.style.display = Number(s.dataset.step) === n ? "block" : "none"));
      progressFill.style.width = (n / total) * 100 + "%";
      progressLabel.textContent = `Step ${n} of ${total}`;
    }
    showStep(current);

    // Step 1 — ingest
    const ingestText = document.querySelector("#ingestText");
    const ingestCount = document.querySelector("#ingestCount");
    const toStep2 = document.querySelector("#toStep2");
    if (ingestText) {
      ingestText.addEventListener("input", () => {
        const n = (ingestText.value.trim().match(/\S+/g) || []).length;
        ingestCount.textContent = n.toLocaleString() + " words ingested";
        toStep2.disabled = n < 40;
      });
    }
    if (toStep2) {
      toStep2.addEventListener("click", () => {
        PersonaAPI.addSourceText(ingestText.value);
        current = 2;
        showStep(current);
      });
    }

    // Step 2 — calibration MCQs (forced-choice pairs)
    const pairs = [
      ["I wanted to follow up on this.", "Circling back on this — any update?"],
      ["Thanks for your patience.", "Appreciate you bearing with me here."],
      ["Let me know if that works.", "Flag it if that doesn't land."],
      ["I think we should move forward.", "Let's just move on this."],
    ];
    let pairIndex = 0;
    const axisShifts = { formality: 0, directness: 0, warmth: 0 };
    const pairContainer = document.querySelector("#pairContainer");
    const toStep3 = document.querySelector("#toStep3");

    function renderPair() {
      if (pairIndex >= pairs.length) {
        pairContainer.innerHTML = `<p class="dim">Calibration sample complete.</p>`;
        toStep3.disabled = false;
        return;
      }
      const [a, b] = pairs[pairIndex];
      pairContainer.innerHTML = `
        <p class="eyebrow" style="margin-bottom:14px">Which is closer to how you'd actually phrase this?</p>
        <div class="flex-col gap-sm">
          <button class="btn btn-block pair-option sharp" data-side="a" style="justify-content:flex-start;text-align:left;padding:14px 16px">${a}</button>
          <button class="btn btn-block pair-option sharp" data-side="b" style="justify-content:flex-start;text-align:left;padding:14px 16px">${b}</button>
        </div>
      `;
      pairContainer.querySelectorAll(".pair-option").forEach((btn) => {
        btn.addEventListener("click", () => {
          const side = btn.dataset.side;
          axisShifts.directness += side === "b" ? 4 : -2;
          axisShifts.formality += side === "a" ? 4 : -2;
          pairIndex++;
          renderPair();
        });
      });
    }
    if (pairContainer) renderPair();

    if (toStep3) {
      toStep3.addEventListener("click", () => {
        current = 3;
        showStep(current);
        const initialAxes = {
          formality: clampAxis(50 + axisShifts.formality),
          directness: clampAxis(50 + axisShifts.directness),
          warmth: clampAxis(50 + axisShifts.warmth),
          sentenceVariance: 50,
          vocabRange: 50,
        };
        PersonaAPI.completeOnboarding(initialAxes).then((profile) => {
          document.querySelector("#strengthValue").textContent = profile.strength.toFixed(0) + "%";
          document.querySelector("#radarHolder").innerHTML = radarChartSVG(profile.axes);
        });
      });
    }
    function clampAxis(v) {
      return Math.max(0, Math.min(100, v));
    }

    const finishBtn = document.querySelector("#finishOnboarding");
    if (finishBtn) {
      finishBtn.addEventListener("click", () => {
        window.location.href = "index.html";
      });
    }
  }

  /* ---------------------------------------------------------------------
     Page: Dashboard
     --------------------------------------------------------------------- */
  function initDashboard() {
    const holder = document.querySelector("#dashboardRoot");
    if (!holder) return;

    Promise.all([PersonaAPI.getProfile(), PersonaAPI.getWordBalance()]).then(
      ([profile, balance]) => {
        document.querySelector("#strengthBig").textContent = profile.strength.toFixed(1) + "%";
        document.querySelector("#sparklineHolder").innerHTML = sparklineSVG(profile.strengthHistory);
        document.querySelector("#radarHolder").innerHTML = radarChartSVG(profile.axes);

        if (balance.tier === "pro") {
          const pct = Math.min(100, (balance.subscriptionUsed / balance.subscriptionCap) * 100);
          document.querySelector("#usageFill").style.width = pct + "%";
          document.querySelector("#usageUsed").textContent = balance.subscriptionUsed.toLocaleString();
          document.querySelector("#usageCap").textContent = balance.subscriptionCap.toLocaleString();
        } else {
          // Free/Starter/Creator are pack credits with no fixed cycle cap,
          // so there's nothing meaningful to show a percentage against —
          // just show the remaining balance.
          document.querySelector("#usageFill").style.width = "0%";
          document.querySelector("#usageUsed").textContent = "—";
          document.querySelector("#usageCap").textContent = balance.remaining.toLocaleString() + " left";
        }
        document.querySelector("#usageTier").textContent = balance.label;

        const logRoot = document.querySelector("#calLog");
        if (!profile.calibrationLog.length) {
          logRoot.innerHTML = `<p class="dim" style="padding:18px">No calibrations logged yet. Lock in a rewrite from the Workspace to start training your profile.</p>`;
        } else {
          logRoot.innerHTML = profile.calibrationLog
            .map((entry) => {
              const dir =
                entry.direction === 1
                  ? '<span class="badge badge-accent">locked in</span>'
                  : entry.direction === -1
                  ? '<span class="badge" style="border-color:var(--danger);color:var(--danger)">off</span>'
                  : '<span class="badge">close</span>';
              const date = new Date(entry.ts).toLocaleString(undefined, {
                month: "short",
                day: "numeric",
                hour: "numeric",
                minute: "2-digit",
              });
              return `
                <div class="flex between center" style="padding:12px 18px;border-bottom:1px solid var(--border)">
                  <div class="flex-col gap-xs">
                    <span style="font-size:13px">${entry.snippet ? escapeHtml(entry.snippet) : "(no input captured)"}</span>
                    <span class="mono faint" style="font-size:11px">${date}</span>
                  </div>
                  <div class="flex gap-sm center">
                    ${dir}
                    <span class="mono faint" style="font-size:11px">${entry.delta > 0 ? "+" : ""}${entry.delta}%</span>
                  </div>
                </div>`;
            })
            .join("");
        }
      }
    );
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  /* ---------------------------------------------------------------------
     Page: Settings
     --------------------------------------------------------------------- */
  function initSettings() {
    const exportBtn = document.querySelector("#exportBtn");
    const deleteBtn = document.querySelector("#deleteBtn");
    const sourceList = document.querySelector("#sourceList");
    if (!exportBtn) return;

    PersonaAPI.getProfile().then((profile) => {
      if (!profile.sourceTexts.length) {
        sourceList.innerHTML = `<p class="dim" style="padding:18px">No source text on file yet.</p>`;
      } else {
        sourceList.innerHTML = profile.sourceTexts
          .map(
            (s, i) => `
            <div style="padding:14px 18px;border-bottom:1px solid var(--border)">
              <div class="flex between center" style="margin-bottom:6px">
                <span class="mono faint" style="font-size:11px">SOURCE_${String(i + 1).padStart(3, "0")}</span>
                <span class="mono faint" style="font-size:11px">${new Date(s.ts).toLocaleDateString()}</span>
              </div>
              <p class="dim" style="font-size:13px">${escapeHtml(s.text.slice(0, 220))}${s.text.length > 220 ? "…" : ""}</p>
            </div>`
          )
          .join("");
      }
    });

    exportBtn.addEventListener("click", () => {
      PersonaAPI.exportProfile().then((json) => {
        const blob = new Blob([json], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "personaos-voice-profile.json";
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      });
    });

    deleteBtn.addEventListener("click", () => {
      const modal = document.querySelector("#deleteModal");
      modal.style.display = "flex";
    });

    const cancelDelete = document.querySelector("#cancelDelete");
    const confirmDelete = document.querySelector("#confirmDelete");
    if (cancelDelete) {
      cancelDelete.addEventListener("click", () => {
        document.querySelector("#deleteModal").style.display = "none";
      });
    }
    if (confirmDelete) {
      confirmDelete.addEventListener("click", () => {
        PersonaAPI.deleteProfile().then(() => {
          window.location.href = "onboarding.html";
        });
      });
    }
  }

  /* ---------------------------------------------------------------------
     Boot
     --------------------------------------------------------------------- */
  document.addEventListener("DOMContentLoaded", () => {
    if (document.body.dataset.page === "login") return; // login.html runs its own inline script

    if (document.body.dataset.page === "landing") {
      // Public page — no session cookie required. Anonymous usage is
      // tracked via X-Anon-Session instead (see PersonaAPI.anon* + the
      // landing-page script at the bottom of index.html).
      initLanding();
      return;
    }

    requireAuth().then(() => {
      renderTopbar();
      initLogout();
      initWorkspace();
      initOnboarding();
      initDashboard();
      initSettings();
    });
  });

  // expose chart helpers + the landing initializer hook in case a page
  // wants to call it directly (index.html sets window.initLanding before
  // engine.js's DOMContentLoaded handler runs, since script tags execute
  // in order and DOMContentLoaded fires after all of them are parsed).
  window.PersonaEngine = { radarChartSVG, sparklineSVG };
  function initLanding() {
    if (typeof window.PersonaLanding === "function") window.PersonaLanding();
  }
})();
