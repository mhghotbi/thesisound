(() => {
  const root = document.documentElement;
  const validThemes = new Set(["cobalt", "wood", "olive", "slate"]);
  const validModes = new Set(["simple", "operator"]);
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";

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
