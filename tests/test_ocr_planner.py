
from thesisound.services.ocr_planner import detect_script, plan_page


def test_page_planner_keeps_healthy_digital_text_native() -> None:
    text = "This is a healthy digital PDF page with enough words for reliable extraction. " * 4
    assert plan_page(1, native_text=text).route == "native"


def test_page_planner_uses_lightweight_ocr_for_scan() -> None:
    assert plan_page(2, native_text="", is_image=True).route == "lightweight_ocr"


def test_page_planner_uses_layout_path_for_complex_page() -> None:
    assert plan_page(3, native_text="", explicit_complex_layout=True).route == "layout_ocr"


def test_script_detection_covers_persian_english_and_mixed() -> None:
    assert detect_script("این یک متن فارسی است") == "persian"
    assert detect_script("This is English") == "latin"
    assert detect_script("مدل Transformer جدید") == "mixed"
