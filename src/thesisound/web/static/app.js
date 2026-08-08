(() => {
  const otp = document.querySelector(".otp-input");
  if (otp) {
    otp.addEventListener("input", () => {
      otp.value = otp.value.replace(/[^\d۰-۹]/g, "").slice(0, 6);
    });
  }

  document.querySelectorAll("input[type=file]").forEach((input) => {
    input.addEventListener("change", () => {
      const label = input.closest(".drop-field");
      const title = label?.querySelector(".drop-field__title");
      if (title && input.files?.[0]) {
        title.textContent = input.files[0].name;
      }
    });
  });
})();
