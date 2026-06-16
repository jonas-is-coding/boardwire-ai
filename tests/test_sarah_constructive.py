from src.notifications import persona_voice as pv

_VALID_JSON = (
    '{"title": "River otters return after a 20-year cleanup.",'
    '"subtitle": "Their numbers are the highest in four decades, biologists say.",'
    '"description": "A two-decade cleanup restored the water quality that brought the otters back.",'
    '"hashtags": ["#Thames", "#Conservation"]}'
)


def _call():
    return pv.sarah_build_publish_package(
        title="Otters return to the river",
        source="Positive News",
        reason="A measurable conservation win",
        score=80,
        claire_note="",
        chloe_note="",
        post_text="",
        summary="Otters spotted again after the cleanup.",
    )


def test_sarah_uses_constructive_prompt_when_on(monkeypatch):
    captured = {}

    def fake_chain(system, user, max_output_tokens=420):
        captured["system"] = system
        return _VALID_JSON

    monkeypatch.delenv("BOARDWIRE_SARAH_PROVIDER", raising=False)
    monkeypatch.setattr(pv.sarah_generation, "generate_with_provider_chain", fake_chain)
    monkeypatch.setenv("BOARDWIRE_CONSTRUCTIVE_MODE", "true")

    pkg = _call()
    assert pkg is not None
    assert "constructive newsroom" in captured["system"]
    assert "good-news" in captured["system"].lower()


def test_sarah_uses_legacy_prompt_when_off(monkeypatch):
    captured = {}

    def fake_chain(system, user, max_output_tokens=420):
        captured["system"] = system
        return _VALID_JSON

    monkeypatch.delenv("BOARDWIRE_SARAH_PROVIDER", raising=False)
    monkeypatch.setattr(pv.sarah_generation, "generate_with_provider_chain", fake_chain)
    monkeypatch.setenv("BOARDWIRE_CONSTRUCTIVE_MODE", "false")

    pkg = _call()
    assert pkg is not None
    assert "AI news desk for builders" in captured["system"]
