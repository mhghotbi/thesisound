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

  document.querySelectorAll("input[type=file]").forEach((input) => {
    input.addEventListener("change", () => {
      const label = input.closest(".drop-field");
      const title = label?.querySelector(".drop-field__title");
      if (title && input.files?.[0]) title.textContent = input.files[0].name;
    });
  });

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

  const refresh = document.querySelector("[data-auto-refresh]");
  if (refresh) {
    const interval = Number(refresh.dataset.autoRefresh || 3000);
    let timer = null;
    const schedule = () => {
      if (document.hidden || timer) return;
      timer = window.setTimeout(() => window.location.reload(), interval);
    };
    const cancel = () => {
      if (!timer) return;
      window.clearTimeout(timer);
      timer = null;
    };
    document.addEventListener("visibilitychange", () => {
      cancel();
      schedule();
    });
    schedule();
  }

  document.addEventListener("click", (event) => {
    document.querySelectorAll(".theme-switcher[open]").forEach((details) => {
      if (!details.contains(event.target)) details.removeAttribute("open");
    });
  });
})();
