from app.scheduling.costs import StaticCostEstimator, ACTIVITY_COST_BY_CATEGORY, DEFAULT_ACTIVITY_COST
from app.scheduling.ports import CostEstimator


def test_static_cost_estimator_returns_known_category_costs():
    estimator = StaticCostEstimator()
    for category, expected_cost in ACTIVITY_COST_BY_CATEGORY.items():
        assert estimator.estimate(category) == expected_cost


def test_static_cost_estimator_falls_back_to_default_for_unknown_category():
    estimator = StaticCostEstimator()
    assert estimator.estimate("some_totally_unknown_category") == DEFAULT_ACTIVITY_COST


def test_static_cost_estimator_satisfies_the_protocol_structurally():
    assert isinstance(StaticCostEstimator(), CostEstimator)
