from __future__ import annotations

from thesisound.services.script_checks import _specifics_in_spoken


def test_a_short_quoted_term_is_not_treated_as_a_citation() -> None:
    """Persian guillemets mark terminology as often as quotation.

    Flagging every «...» span made `unsupported_specifics` fire on ordinary
    vocabulary -- including the source's own title -- on every turn, which is what
    hid the one real detection among the false ones.
    """

    spoken = "آرنت «حیات فعال» را از «حیات نظری» جدا می‌کند."
    assert _specifics_in_spoken(spoken) == []


def test_a_quoted_sentence_is_still_treated_as_a_citation() -> None:
    spoken = "او می‌نویسد «انسان موجودی است که در جهان با دیگران ظاهر می‌شود»."
    found = _specifics_in_spoken(spoken)
    assert found, "a clause-length quotation must still be checked"


def test_a_date_is_checked_regardless_of_quoting() -> None:
    """The defect that survived a verifier pass: a fabricated year in plain prose."""

    assert "۱۹۵۸" in _specifics_in_spoken("آرنت این را در سال ۱۹۵۸ نوشت.")
    assert "1958" in _specifics_in_spoken("Arendt wrote this in 1958.")
