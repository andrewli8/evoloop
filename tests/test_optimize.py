import pytest

from evoloop import optimize as O
from evoloop.config import Config
from evoloop.providers import MockProvider


def test_immutable_components_cannot_be_mutated():
    for bad in ({"auto_merge": True}, {"mode": "pr"}, {"high_risk_terms": []}, {"budget": {"max_model_calls": 10**6}}, {"enabled": True}):
        with pytest.raises(O.ImmutableViolation):
            O.mutate(bad)


def test_hard_limits_enforced():
    with pytest.raises(O.ImmutableViolation):
        O.mutate({"search": {"branches": 50}}).apply(Config())
    c = O.mutate({"search": {"branches": 4}}).apply(Config())
    assert c.search.branches == 4 and Config().search.branches == 5


def test_pareto_not_scalar():
    a = O.Metrics(1, 1, 10, 5, 1)
    cheaper_but_unsafe = O.Metrics(1, 1, 5, 5, 0)
    cheaper = O.Metrics(1, 1, 5, 5, 1)
    assert not cheaper_but_unsafe.dominates(a)
    assert cheaper.dominates(a) and not a.dominates(cheaper)


def test_benchmark_runs_on_fixture(repo):
    m = O.run_benchmark([repo], O.Strategy(), lambda: MockProvider())
    assert m.correctness == 1.0 and m.cost > 0 and m.safety == 1.0
