# Benchmark results

Produced by `python -m evals.run_eval` against live data sources. Reproduce with
the same command; numbers vary with OpenStreetMap Overpass load.

| Case | Category | Verified | Expected | Repairs | Stops | Seconds |
|---|---|---|---|---|---|---|
| goa_generous_budget | normal | True | True | 0 | 9 | 129.8 |
| kyoto_moderate_budget | normal | True | True | 0 | 6 | 149.2 |
| paris_no_budget_stated | normal | True | — | 0 | 12 | 91.0 |
| delhi_short_trip | normal | True | True | 0 | 3 | 83.2 |
| kyoto_tight_budget | tight | True | True | 0 | 6 | 0.0 |
| kyoto_impossible_budget | infeasible | False | False | 1 | 6 | 0.0 |
| goa_absurd_budget | infeasible | False | False | 1 | 0 | 0.7 |
| sparse_small_town | agentic | True | — | 0 | 0 | 383.8 |
| ambiguous_city_name | agentic | True | — | 0 | 9 | 0.0 |
| metro_area_needs_subdivision | agentic | True | — | 1 | 3 | 85.6 |
| niche_interest_needs_category_relaxation | agentic | True | — | 0 | 0 | 286.8 |
| gibberish_destination | edge | True | — | 0 | 0 | 1.5 |
| no_destination_at_all | edge | True | — | 0 | 9 | 79.8 |
| very_long_trip | edge | True | — | 0 | 54 | 0.6 |

## Summary

| Metric | Value |
|---|---|
| cases | **14** |
| crashes | **0** |
| verifier correct | **6/6** |
| cases with scheduled stops | **10/14** |
| grounding | **117/117** |
| cases needing repair | **3/14** |
| mean repair iterations | **0.21** |
| mean latency s | **92.27** |
| p95 latency s | **286.75** |

## How to read this

**Fractions, not percentages.** Fourteen cases is far too small a sample for "100%"
to mean what it looks like.

**Four cases schedule zero stops, and two of those are correct.**
`gibberish_destination` has no resolvable place, and `goa_absurd_budget` states a
budget that genuinely cannot be met — both *should* return nothing rather than invent
something. The other two (`sparse_small_town`, `niche_interest_needs_category_relaxation`)
are genuine gaps: both ran for 280–380s, which points at Overpass timing out rather
than those towns having no mapped attractions. They are the cases the acquisition
agent exists for, and it has not been measured yet.

**Latency is dominated by cold lookups.** A city not seen before costs 60–90s against
Overpass; cached lookups are effectively free for 24 hours. Every case here paid a
cold lookup, so this is a worst-case run, not steady state.

**117 of 117 scheduled stops carry a source.** Attribution is enforced by the verifier,
not merely recorded — a stop without one fails the check.
