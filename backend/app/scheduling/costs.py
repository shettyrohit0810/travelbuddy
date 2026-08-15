# Flat per-category cost heuristic, same honesty level as budget_estimator.py's
# rate table — a labeled estimate for budget enforcement, not a live-pricing claim.
# Keys are common OpenTripMap "kinds" values.
ACTIVITY_COST_BY_CATEGORY = {
    "natural": 0.0,
    "beaches": 0.0,
    "view_points": 0.0,
    "urban_environment": 0.0,
    "religion": 5.0,
    "shops": 5.0,
    "architecture": 10.0,
    "historic": 10.0,
    "foods": 10.0,
    "cultural": 15.0,
    "museums": 15.0,
    "sport": 20.0,
    "theatres_and_entertainments": 20.0,
    "amusements": 30.0,
}
DEFAULT_ACTIVITY_COST = 15.0


class StaticCostEstimator:
    def estimate(self, category: str) -> float:
        return ACTIVITY_COST_BY_CATEGORY.get(category, DEFAULT_ACTIVITY_COST)
