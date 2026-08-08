from thesisound.audio import script_hash
from thesisound.domain import Script, ScriptTurn
from thesisound.services.tts_segmenter import TtsSegmenter


def test_segmenter_preserves_speaker_turn_and_stable_hashes() -> None:
    text = (
        "جمله نخست برای آزمون تقسیم‌بندی صوت است و باید بدون حذف یا تغییر "
        "در یک قطعه مستقل باقی بماند. "
        "جمله دوم نیز اطلاعات کافی دارد تا مجموع دو جمله از سقف مجاز قطعه "
        "عبور کند و مرز جمله حفظ شود."
    )
    script = Script(
        title="آزمون",
        turns=[
            ScriptTurn(
                turn_id="turn-1",
                segment_id="seg-1",
                speaker="A",
                spoken_text_fa=text,
                claim_ids=["claim-1"],
                evidence_ids=["evidence-1"],
            )
        ],
    )
    segmenter = TtsSegmenter(max_characters=120, words_per_minute=120)

    first = segmenter.segment(
        script,
        script_hash=script_hash(script),
        model="tts-model",
        voices={"A": "Kore", "B": "Puck"},
        style_prompt="calm",
    )
    second = segmenter.segment(
        script,
        script_hash=script_hash(script),
        model="tts-model",
        voices={"A": "Kore", "B": "Puck"},
        style_prompt="calm",
    )

    assert len(first) == 2
    assert [chunk.content_hash for chunk in first] == [chunk.content_hash for chunk in second]
    assert all(chunk.speaker == "A" for chunk in first)
    assert all(chunk.source_turn_ids == ["turn-1"] for chunk in first)
    rendered = "".join(chunk.text.replace(" ", "") for chunk in first)
    assert rendered == text.replace(" ", "")
