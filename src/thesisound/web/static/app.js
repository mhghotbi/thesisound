(() => {
  const root = document.documentElement;
  const validThemes = new Set(["cobalt", "wood", "olive", "slate"]);
  const validModes = new Set(["simple", "operator"]);
  let csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

  const applyCsrf = (token) => {
    if (!token) return;
    csrf = token;
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta) meta.setAttribute("content", token);
    document.querySelectorAll('input[name="csrf_token"]').forEach((input) => {
      input.value = token;
    });
  };

  const refreshCsrf = async () => {
    const response = await fetch("/csrf/refresh", {
      method: "POST",
      credentials: "same-origin",
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) return;
    const data = await response.json();
    applyCsrf(data.csrf_token);
  };

  // Shared HTML caches can embed a CSRF token that no longer matches the
  // browser session cookie. Refresh from a POST (never CDN-cached) first.
  refreshCsrf().catch(() => {});

  document.addEventListener(
    "submit",
    (event) => {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) return;
      if (!form.querySelector('input[name="csrf_token"]')) return;
      if (form.dataset.csrfSynced === "1") {
        delete form.dataset.csrfSynced;
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      // Keep the clicked submit control across the CSRF re-post. Bare
      // requestSubmit()/submit() omit named button values, so "confirm"
      // would fall through to the server default of "save".
      const submitter = event.submitter instanceof HTMLElement ? event.submitter : null;
      refreshCsrf()
        .catch(() => {})
        .finally(() => {
          form.dataset.csrfSynced = "1";
          if (typeof form.requestSubmit === "function") {
            if (submitter) form.requestSubmit(submitter);
            else form.requestSubmit();
          } else if (submitter && submitter.name) {
            const hidden = document.createElement("input");
            hidden.type = "hidden";
            hidden.name = submitter.name;
            hidden.value = submitter.value;
            form.appendChild(hidden);
            try {
              form.submit();
            } finally {
              hidden.remove();
            }
          } else {
            form.submit();
          }
        });
    },
    true,
  );

  const persistPreference = async (field, value) => {
    if (!csrf) return;
    const body = new URLSearchParams({ csrf_token: csrf, [field]: value });
    try {
      await fetch("/ui/preferences", {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
        credentials: "same-origin",
      });
    } catch (_) {
      // Local persistence remains authoritative for the current browser.
    }
  };

  const syncPressedStates = () => {
    document.querySelectorAll("[data-theme-value]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.themeValue === root.dataset.theme));
    });
    document.querySelectorAll("[data-mode-value]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.modeValue === root.dataset.mode));
    });
  };

  document.querySelectorAll("[data-theme-value]").forEach((button) => {
    button.addEventListener("click", () => {
      const theme = button.dataset.themeValue;
      if (!validThemes.has(theme)) return;
      root.dataset.theme = theme;
      localStorage.setItem("maqaal-theme", theme);
      localStorage.removeItem("thesisound-theme");
      syncPressedStates();
      persistPreference("theme", theme);
      button.closest("details")?.removeAttribute("open");
    });
  });

  document.querySelectorAll("[data-mode-value]").forEach((button) => {
    button.addEventListener("click", () => {
      const mode = button.dataset.modeValue;
      if (!validModes.has(mode)) return;
      root.dataset.mode = mode;
      localStorage.setItem("maqaal-mode", mode);
      localStorage.removeItem("thesisound-mode");
      syncPressedStates();
      persistPreference("mode", mode);
    });
  });

  syncPressedStates();

  const digitMap = {
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
  };

  const toAsciiDigits = (value) =>
    Array.from(value, (character) => digitMap[character] ?? character).join("");

  const normalizePhoneInput = (value) => {
    let digits = "";
    for (const character of toAsciiDigits(value)) {
      if (character >= "0" && character <= "9") digits += character;
    }
    if (digits.startsWith("0098")) digits = `0${digits.slice(4)}`;
    else if (digits.startsWith("98") && digits.length >= 12) digits = `0${digits.slice(2)}`;
    else if (digits.startsWith("9")) digits = `0${digits}`;
    return digits.slice(0, 11);
  };

  const isValidPhone = (value) => /^09\d{9}$/.test(value);

  document.querySelectorAll("[data-phone-form]").forEach((form) => {
    const input = form.querySelector('input[name="phone"]');
    const submit = form.querySelector('button[type="submit"]');
    if (!input || !submit) return;

    const syncPhoneField = () => {
      const normalized = normalizePhoneInput(input.value);
      if (input.value !== normalized) input.value = normalized;
      const valid = isValidPhone(normalized);
      submit.disabled = !valid;
      input.setCustomValidity(valid || !normalized ? "" : "شماره باید ۱۱ رقم و با 09 شروع شود.");
    };

    input.addEventListener("input", syncPhoneField);
    input.addEventListener("blur", syncPhoneField);
    form.addEventListener("submit", (event) => {
      syncPhoneField();
      if (!isValidPhone(input.value)) event.preventDefault();
    });
    syncPhoneField();
  });

  const otp = document.querySelector(".otp-input");
  if (otp) {
    otp.addEventListener("input", () => {
      otp.value = toAsciiDigits(otp.value).replace(/\D/g, "").slice(0, 6);
    });
  }

  // "Drop files here" has to be true, so the zone accepts a drop as well as a pick,
  // and either one uploads immediately rather than waiting for a second click.
  const upload = document.querySelector("[data-upload-field]");
  const dropZone = upload?.closest(".drop-zone");
  if (upload && dropZone) {
    const title = dropZone.querySelector(".drop-zone__title");
    const send = () => {
      if (!upload.files?.length) return;
      if (title) title.textContent = `در حال افزودن ${upload.files[0].name}…`;
      dropZone.requestSubmit();
    };

    upload.addEventListener("change", send);

    ["dragenter", "dragover"].forEach((name) => {
      dropZone.addEventListener(name, (event) => {
        event.preventDefault();
        dropZone.classList.add("is-dragging");
      });
    });
    ["dragleave", "dragend"].forEach((name) => {
      dropZone.addEventListener(name, () => dropZone.classList.remove("is-dragging"));
    });
    dropZone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropZone.classList.remove("is-dragging");
      const [file] = event.dataTransfer?.files || [];
      if (!file) return;
      const transfer = new DataTransfer();
      transfer.items.add(file);
      upload.files = transfer.files;
      send();
    });
  }

  // Picking a source is a tick, not a trip through a button: the surrounding form
  // posts the toggle straight away. Without JS the noscript button does the same.
  document.querySelectorAll("[data-toggle-source]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      checkbox.disabled = true;
      checkbox.form?.requestSubmit();
    });
  });

  document.querySelectorAll("[data-source-trace]").forEach((details) => {
    details.addEventListener("toggle", () => {
      if (!details.open || details.dataset.traced === "1") return;
      details.dataset.traced = "1";
      const projectId = details.dataset.projectId;
      if (!projectId) return;
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
      const body = new URLSearchParams({ csrf_token: csrf });
      fetch(`/projects/${projectId}/script/source-trace`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
        credentials: "same-origin",
      }).catch(() => {
        // Metrics must never block reading the source trace.
      });
      details.querySelectorAll("[data-evidence-context]").forEach((slot) => {
        const evidenceId = slot.dataset.evidenceId;
        if (!evidenceId || slot.dataset.loaded === "1") return;
        slot.dataset.loaded = "1";
        fetch(`/projects/${projectId}/script/evidence/${encodeURIComponent(evidenceId)}`, {
          credentials: "same-origin",
          headers: { Accept: "text/html" },
        })
          .then((response) => {
            if (!response.ok) return null;
            return response.text();
          })
          .then((html) => {
            if (!html) return;
            slot.innerHTML = html;
            slot.hidden = false;
          })
          .catch(() => {
            // Context is additive; excerpt and locator already render without JS.
          });
      });
    });
  });

  document.querySelectorAll("[data-plan-list-open]").forEach((details) => {
    details.addEventListener("toggle", () => {
      if (!details.open || details.dataset.traced === "1") return;
      details.dataset.traced = "1";
      const projectId = details.dataset.projectId;
      const origin = details.dataset.planListOpen;
      if (!projectId || !origin) return;
      const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
      const body = new URLSearchParams({ csrf_token: csrf, origin });
      fetch(`/projects/${projectId}/episode/list-opened`, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body,
        credentials: "same-origin",
      }).catch(() => {
        // Metrics must never block reading the list.
      });
    });
  });

  document.querySelectorAll("[data-duration-cost]").forEach((form) => {
    const input = form.querySelector("[data-duration-input]");
    const hint =
      form.querySelector("[data-duration-cost-hint]") ||
      form.parentElement?.querySelector("[data-duration-cost-hint]");
    const match = form.action && form.action.match(/\/projects\/([^/]+)\/episode\/duration/);
    const projectId = match ? match[1] : null;
    if (!input || !hint || !projectId) return;
    let timer = null;
    const refresh = () => {
      const minutes = Number(input.value);
      if (!Number.isFinite(minutes) || minutes < 5) return;
      fetch(`/projects/${projectId}/episode/duration-cost?minutes=${encodeURIComponent(minutes)}`, {
        credentials: "same-origin",
        headers: { Accept: "text/html" },
      })
        .then((response) => (response.ok ? response.text() : null))
        .then((text) => {
          if (text) hint.textContent = text;
        })
        .catch(() => {
          // Keep the server-rendered hint if the live check fails.
        });
    };
    input.addEventListener("input", () => {
      clearTimeout(timer);
      timer = setTimeout(refresh, 250);
    });
  });

  const applyJudgementState = (root, verdict) => {
    root.dataset.verdict = verdict || "";
    root.querySelectorAll("[data-verdict='correct'], [data-verdict='incorrect']").forEach((button) => {
      button.classList.toggle("is-selected", Boolean(verdict) && button.dataset.verdict === verdict);
    });
    const clearBtn = root.querySelector("[data-verdict='cleared']");
    if (clearBtn) clearBtn.hidden = !verdict || verdict === "cleared";
    const reasonPanel = root.querySelector(".evidence-judgement__reason");
    if (reasonPanel) reasonPanel.hidden = true;
  };

  const postJudgement = (root, verdict, reason = "", note = "") => {
    const projectId = root.dataset.projectId;
    const evidenceId = root.dataset.evidenceId;
    const claimId = root.dataset.claimId;
    const turnId = root.dataset.turnId;
    if (!projectId || !evidenceId || !claimId || !turnId) return;
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
    const body = new URLSearchParams({
      csrf_token: csrf,
      turn_id: turnId,
      claim_id: claimId,
      verdict,
      reason,
      note,
    });
    fetch(`/projects/${projectId}/script/evidence/${encodeURIComponent(evidenceId)}/judgement`, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body,
      credentials: "same-origin",
    })
      .then((response) => {
        if (!response.ok) return;
        applyJudgementState(root, verdict === "cleared" ? "" : verdict);
      })
      .catch(() => {
        // Judgement must never block reading.
      });
  };

  document.querySelectorAll("[data-evidence-judgement]").forEach((root) => {
    root.addEventListener("click", (event) => {
      const target = event.target;
      if (!(target instanceof HTMLElement)) return;
      const submit = target.closest("[data-submit-incorrect]");
      if (submit) {
        const selected = root.querySelector("input[type='radio']:checked");
        if (!(selected instanceof HTMLInputElement) || !selected.value) return;
        const note = root.querySelector("textarea")?.value || "";
        postJudgement(root, "incorrect", selected.value, note);
        return;
      }
      const button = target.closest("[data-verdict]");
      if (!(button instanceof HTMLElement)) return;
      const verdict = button.dataset.verdict;
      if (verdict === "incorrect") {
        const reasonPanel = root.querySelector(".evidence-judgement__reason");
        if (reasonPanel) reasonPanel.hidden = false;
        return;
      }
      if (verdict === "correct" || verdict === "cleared") {
        postJudgement(root, verdict);
      }
    });
  });

  // Chapter rows seek the one player on the page; without JS they stay plain labels
  // next to their timestamps, which still tells you where each part begins.
  const episodeAudio = document.querySelector("[data-episode-audio]");
  if (episodeAudio) {
    document.querySelectorAll("[data-seek-to]").forEach((button) => {
      button.addEventListener("click", () => {
        const start = Number(button.dataset.seekTo);
        if (!Number.isFinite(start)) return;
        const seek = () => {
          episodeAudio.currentTime = start;
          episodeAudio.play().catch(() => {
            // Autoplay can be refused; the position is set either way.
          });
        };
        if (episodeAudio.readyState) seek();
        else episodeAudio.addEventListener("loadedmetadata", seek, { once: true });
      });
    });
  }

  const search = document.querySelector("[data-project-search]");
  if (search) {
    search.addEventListener("input", () => {
      const query = search.value.trim().toLocaleLowerCase("fa");
      document.querySelectorAll("[data-project-row]").forEach((row) => {
        row.hidden = Boolean(query) && !row.textContent.toLocaleLowerCase("fa").includes(query);
      });
      document.querySelectorAll("[data-project-group]").forEach((group) => {
        group.hidden = !group.querySelector("[data-project-row]:not([hidden])");
      });
    });
  }

  // Live regions poll themselves through HTMX. A hidden tab has nobody watching, so
  // its polls are dropped and pick up again on the next visible tick.
  document.body.addEventListener("htmx:beforeRequest", (event) => {
    if (document.hidden && event.detail.elt?.hasAttribute?.("data-live-region")) {
      event.preventDefault();
    }
  });

  document.addEventListener("click", (event) => {
    document.querySelectorAll(".theme-switcher[open]").forEach((details) => {
      if (!details.contains(event.target)) details.removeAttribute("open");
    });
  });
})();
