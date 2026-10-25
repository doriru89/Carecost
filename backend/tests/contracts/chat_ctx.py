"""Validation context for chat fixtures (filled in with the chat validators)."""


def fixture_context(body: dict) -> dict:
    return {"allow_placeholders": True}
