/* ==========================================================================
   PersonaOS — landing.js
   Drives index.html's value-first trial flow: generate first, account
   second. Exposes window.PersonaLanding(), called by engine.js's boot
   sequence once it sees <body data-page="landing"> (a public page, so it
   deliberately skips the cookie-based requireAuth() guard).
   ========================================================================== */

(function () {
  "use strict";

  function PersonaLanding() {
    const trialFill = document.querySelector("#trialFill");
    const trialLabel = document.querySelector("#trialLabel");
    const miniOnboard = document.querySelector("#miniOnboard");
    const generatePanel = document.querySelector("#generatePanel");
    const pairContainer = document.querySelector("#pairContainer");
    const skipOnboard = document.querySelector("#skipOnboard");
    const landingInput = document.querySelector("#landingInput");
    const inputCount = document.querySelector("#inputCount");
    const formatSelect = document.querySelector("#formatSelect");
    const generateBtn = document.querySelector("#generateBtn");
    const outputWrap = document.querySelector("#outputWrap");
    const landingOutput = document.querySelector("#landingOutput");
    const pricingModal = document.querySelector("#pricingModal");
    const closePricing = document.querySelector("#closePricing");

    function updateTrialBar(status) {
      const pct = Math.min(100, (status.words_used / status.cap) * 100);
      trialFill.style.width = pct + "%";
      trialFill.classList.toggle("warn", status.words_remaining <= 150);
      trialLabel.textContent = status.words_remaining.toLocaleString() + " / " + status.cap.toLocaleString() + " words left";
    }

    function showPricingModal() {
      pricingModal.style.display = "flex";
    }

    closePricing.addEventListener("click", () => {
      pricingModal.style.display = "none";
    });
    pricingModal.addEventListener("click", (e) => {
      if (e.target === pricingModal) pricingModal.style.display = "none";
    });

    /* ---------------- Mini onboarding (2 forced-choice pairs) ---------------- */
    const pairs = [
      ["I wanted to follow up on this.", "Circling back on this — any update?"],
      ["Thanks for your patience.", "Appreciate you bearing with me here."],
    ];
    let pairIndex = 0;
    const axisShifts = { formality: 0, directness: 0, warmth: 0 };

    function clampAxis(v) {
      return Math.max(0, Math.min(100, v));
    }

    function finishMiniOnboard(submitAxes) {
      miniOnboard.style.display = "none";
      generatePanel.style.display = "block";
      if (submitAxes) {
        const axes = {
          formality: clampAxis(50 + axisShifts.formality),
          directness: clampAxis(50 + axisShifts.directness),
          warmth: clampAxis(50 + axisShifts.warmth),
        };
        PersonaAPI.anonOnboarding(axes).catch(() => {});
      }
    }

    function renderPair() {
      if (pairIndex >= pairs.length) {
        finishMiniOnboard(true);
        return;
      }
      const [a, b] = pairs[pairIndex];
      pairContainer.innerHTML = `
        <button class="btn btn-block pair-option sharp" data-side="a">${a}</button>
        <button class="btn btn-block pair-option sharp" data-side="b">${b}</button>
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
    renderPair();

    skipOnboard.addEventListener("click", () => finishMiniOnboard(false));

    /* ---------------- Generate ---------------- */
    landingInput.addEventListener("input", () => {
      const n = (landingInput.value.trim().match(/\S+/g) || []).length;
      inputCount.textContent = n + " words";
    });

    generateBtn.addEventListener("click", () => {
      const text = landingInput.value.trim();
      if (!text) return;
      generateBtn.disabled = true;
      generateBtn.textContent = "Generating…";

      PersonaAPI.anonGenerate({
        rawInput: text,
        tone: 50,
        format: formatSelect.value,
      })
        .then(({ output, status }) => {
          outputWrap.style.display = "block";
          landingOutput.textContent = output;
          updateTrialBar(status);
          if (status.words_remaining <= 0) showPricingModal();
          outputWrap.scrollIntoView({ behavior: "smooth", block: "nearest" });
        })
        .catch((err) => {
          if (err.code === 402) {
            showPricingModal();
          } else {
            outputWrap.style.display = "block";
            landingOutput.innerHTML = `<span class="danger">${err.message || "Something went wrong."}</span>`;
          }
        })
        .finally(() => {
          generateBtn.disabled = false;
          generateBtn.textContent = "Generate →";
        });
    });

    /* ---------------- Initial status (resume an in-progress trial) ---------------- */
    PersonaAPI.anonStatus()
      .then((status) => {
        updateTrialBar(status);
        if (status.words_remaining <= 0) showPricingModal();
        // Returning visitor who already answered the mini onboarding —
        // skip straight to the generate panel instead of asking again.
        if (status.words_used > 0) finishMiniOnboard(false);
      })
      .catch(() => {
        updateTrialBar({ words_used: 0, words_remaining: 1000, cap: 1000 });
      });
  }

  window.PersonaLanding = PersonaLanding;
})();
