from thesisound.web.error_messages import user_facing_error


def test_user_facing_error_distinguishes_common_failures() -> None:
    rate = user_facing_error("429 RESOURCE_EXHAUSTED rate limit", action="search")
    auth = user_facing_error("UNAUTHENTICATED invalid API key", action="search")
    network = user_facing_error("TimeoutError: deadline exceeded", action="search")
    assert "سهمیه" in rate
    assert "احراز هویت" in auth
    assert "قطع ارتباط" in network or "زمان‌پاسخ" in network
    assert rate != auth != network


def test_user_facing_error_keeps_clear_persian_messages() -> None:
    message = "حداقل یک منبع آماده را انتخاب کنید."
    assert user_facing_error(message, action="corpus") == message


def test_user_facing_error_action_changes_copy() -> None:
    err = RuntimeError("Live-run prerequisites are incomplete. See `/system-check`.")
    search = user_facing_error(err, action="search")
    audio = user_facing_error(err, action="audio")
    assert "جست‌وجو" in search
    assert "شنیداری" in audio or "صوت" in audio
    assert search != audio
