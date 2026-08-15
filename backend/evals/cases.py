"""Benchmark cases for the planner.

Deliberately includes cases that SHOULD fail. A harness that only measures happy
paths tells you nothing about whether the verifier actually catches anything --
the infeasible cases are the ones that prove the constraint enforcement is real
rather than decorative.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EvalCase:
    name: str
    query: str
    category: str
    # None = no budget stated, so no budget constraint to satisfy.
    expect_satisfiable: Optional[bool] = None
    notes: str = ""


CASES = [
    # --- ordinary requests -------------------------------------------------
    EvalCase(
        name="goa_generous_budget",
        query="Plan a 3 day beach trip to Goa for 2 people with a budget of 60000",
        category="normal",
        expect_satisfiable=True,
        notes="Comfortable budget; should need no repair.",
    ),
    EvalCase(
        name="kyoto_moderate_budget",
        query="Plan a 2 day cultural trip to Kyoto for 2 people with a budget of 20000",
        category="normal",
        expect_satisfiable=True,
    ),
    EvalCase(
        name="paris_no_budget_stated",
        query="Plan a 4 day trip to Paris for 1 person",
        category="normal",
        expect_satisfiable=None,
        notes="No budget stated -- nothing to violate, but must not crash.",
    ),
    EvalCase(
        name="delhi_short_trip",
        query="Plan a 1 day trip to Delhi for 1 person with a budget of 15000",
        category="normal",
        expect_satisfiable=True,
    ),

    # --- tight but repairable ---------------------------------------------
    EvalCase(
        name="kyoto_tight_budget",
        query="Plan a 2 day cultural trip to Kyoto for 2 people with a budget of 16000",
        category="tight",
        expect_satisfiable=True,
        notes="Overruns on first pass; the repair loop should absorb it into activities.",
    ),

    # --- genuinely infeasible ---------------------------------------------
    EvalCase(
        name="kyoto_impossible_budget",
        query="Plan a 2 day cultural trip to Kyoto for 2 people with a budget of 5000",
        category="infeasible",
        expect_satisfiable=False,
        notes="Transport alone exceeds the budget. Must report failure, not fake success.",
    ),
    EvalCase(
        name="goa_absurd_budget",
        query="Plan a 5 day trip to Goa for 4 people with a budget of 100",
        category="infeasible",
        expect_satisfiable=False,
        notes="Must terminate quickly rather than spinning on repairs.",
    ),

    # --- cases that specifically require agency ----------------------------
    # These exist to measure the acquisition agent, not the scheduler. Each one is a
    # situation where the deterministic lookup returns too little and several different
    # recovery strategies are defensible -- which is the only honest reason to put a
    # model in the loop at all.
    EvalCase(
        name="sparse_small_town",
        query="Plan a 2 day trip to Chikmagalur for 2 people with a budget of 20000",
        category="agentic",
        notes="Real town, thin OSM coverage. Needs a wider radius or relaxed notability.",
    ),
    EvalCase(
        name="ambiguous_city_name",
        query="Plan a 3 day trip to Goa for 2 people with a budget of 40000",
        category="agentic",
        notes="Geocodes to Goa, Philippines by exact match; the Indian state is absent "
              "from Open-Meteo entirely. Requires reasoning over resolution candidates.",
    ),
    EvalCase(
        name="metro_area_needs_subdivision",
        query="Plan a 4 day trip to National Capital Region for 2 people with a budget of 50000",
        category="agentic",
        notes="A region rather than a city centre; a single radius search around the "
              "centroid misses most of it.",
    ),
    EvalCase(
        name="niche_interest_needs_category_relaxation",
        query="Plan a 2 day street-art trip to Lucknow for 1 person with a budget of 15000",
        category="agentic",
        notes="Notability filter is likely to return too few; needs relaxing.",
    ),

    # --- malformed / adversarial input ------------------------------------
    EvalCase(
        name="gibberish_destination",
        query="Plan a 2 day trip to Zzqxwblahfake123 for 1 person with a budget of 20000",
        category="edge",
        notes="Unresolvable destination must degrade honestly, not fabricate places.",
    ),
    EvalCase(
        name="no_destination_at_all",
        query="I want to go somewhere nice for a few days",
        category="edge",
        notes="Vague request must still produce a coherent plan or a clear failure.",
    ),
    EvalCase(
        name="very_long_trip",
        query="Plan a 30 day trip to Goa for 2 people with a budget of 500000",
        category="edge",
        notes="Upper bound on days; scheduler must not blow up.",
    ),
]
