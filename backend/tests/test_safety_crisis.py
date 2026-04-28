from app.services.safety_crisis import crisis_scan_messages, crisis_scan_text


def test_crisis_scan_positive() -> None:
    assert crisis_scan_text("I want to kill myself today")
    assert crisis_scan_text("thinking about suicide")
    assert crisis_scan_messages("ok", [{"role": "user", "content": "I want to end my life"}])


def test_crisis_scan_negative_medical() -> None:
    assert not crisis_scan_text("blood in stool for 3 days")
    assert not crisis_scan_text("routine screening colonoscopy")

