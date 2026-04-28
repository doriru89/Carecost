"""Smoke: `app.main` imports with only production deps (see CI prod-requirements step)."""


def test_import_main_module() -> None:
    import app.main  # noqa: F401
