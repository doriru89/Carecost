"""Question set Q0-Q14: every question and every answer must route somewhere real."""

from __future__ import annotations

from app.care_paths import validator


def test_question_ids_are_q0_to_q14(bundle):
    ids = [q.id for q in bundle.questions.questions]
    assert ids == [f"Q{i}" for i in range(15)]


def test_every_answer_has_a_route(bundle):
    for q in bundle.questions.questions:
        assert q.answers, f"{q.id} has no answers"
        for a in q.answers:
            assert a.routes_to, f"{q.id}={a.value} routes nowhere"


def test_every_route_target_resolves(bundle):
    problems = validator.check_question_routes(bundle)
    assert not problems, "\n".join(problems)


def test_every_question_changes_something(bundle):
    """A question whose answers only say 'go to the next question' doesn't earn its place."""
    for q in bundle.questions.questions:
        kinds = {t.split(":", 1)[0] for a in q.answers for t in a.routes_to}
        assert kinds - {"next"}, f"{q.id} never changes a path, card, stop or tier"


def test_path_entry_conditions_use_declared_answers(bundle):
    problems = validator.check_entry_answers(bundle)
    assert not problems, "\n".join(problems)


def test_route_declarations_match_path_entries(bundle):
    """If Q2=no_injury says it routes to the chronic shoulder path, that path's entry must use it."""
    problems = validator.check_routes_match_entries(bundle)
    assert not problems, "\n".join(problems)


def test_a_question_that_routes_nowhere_is_caught(mutable_bundle):
    q = mutable_bundle.questions.questions[5]
    q.answers[0].routes_to = ["path:does_not_exist"]
    assert validator.check_question_routes(mutable_bundle)
