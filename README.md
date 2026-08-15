# TravelBuddy

A trip planner where the itinerary is decided by a constraint solver, not by a language
model.

Most LLM trip planners ask a model to write a plan and hope the result respects the
traveller's budget. This one inverts that. A 0/1 knapsack selects attractions under a
hard budget ceiling, a travel-time-aware step sequences them within real day lengths,
and an arithmetic verifier re-checks the assembled plan before anyone sees it. The
model's only job is prose over a schedule it cannot change — it cannot reorder, rename,
drop, or invent a stop.

```
understanding → geocode → [ weather ∥ transport ∥ POI lookup ] → budget
                                                                   ↓
                              itinerary → verify → (repair → itinerary)* → plan
```

**The interesting part is the loop.** `verify` checks the plan against hard constraints
using arithmetic, so a violation is a fact the graph can route on rather than an opinion.
`repair` makes one targeted deterministic change — reduce an allocation by exactly the
overspend — and the scheduler re-solves. It terminates on success, an unrepairable
violation, an attempt cap, or exhausted headroom. Bounded on purpose: an unbounded
repair loop is a cost incident with extra steps.

---

## What it guarantees

**Every scheduled stop traces to a real lookup.** Each stop carries a `source`, and a
stop without one *fails verification*. That makes "nothing is invented" a check the code
enforces rather than a claim in a README.

**The budget is enforced, not requested.** It is a knapsack capacity and a verifier
assertion. No model is trusted with arithmetic that decides whether a plan is valid.

**Failure is reported, not hidden.** If a destination has no mapped attractions, the
plan says so and schedules nothing. If a budget is genuinely impossible, the response
says `valid: false` with the shortfall rather than returning a plan that quietly breaks
it.

---

## Quick start

Needs Docker. No API keys required — points of interest come from OpenStreetMap and
weather from Open-Meteo, both open.

```bash
docker compose up --build
```

Then open <http://localhost:3000>. The API is on <http://localhost:8000>, docs at
`/docs`.

The first lookup for a city queries Overpass directly and takes 60–90 seconds; results
are cached for 24 hours, after which repeat plans are effectively instant.

### Optional: the agent layer

Setting any one of `OPENAI_API_KEY` (a `gsk_` prefix routes to Groq) or `XAI_API_KEY` in
`backend/.env` enables a bounded acquisition agent that widens the search when a
destination returns too few attractions. Without a key the app runs fully; the agent
records `unavailable` and the plan proceeds on whatever the deterministic lookup found.

---

## Design decisions worth reading

**Geocoding resolves through Nominatim, not a populated-places gazetteer.** Open-Meteo's
geocoder ranks by population and contains no administrative regions, which produces
silent, badly wrong answers: it resolves *"Goa"* to **Genoa, Italy** — an entire
itinerary of Italian churches under an Indian beach-trip heading — and returns nothing
at all for regions. Nominatim gets both right. Open-Meteo remains as a fallback, and
whichever wins, the plan states which place it actually planned.

**Search radius comes from the resolved place's bounding box.** A fixed radius is wrong
for the same reason: an 8 km circle around the centroid of Goa, a *state*, found one
obscure archaeological site, which the planner then repeated for three days. Sizing the
radius to the place's real extent turned that into nine genuine attractions.

**Attraction ranking uses Wikidata sitelink counts.** OpenStreetMap has no rating field.
Rather than invent one, prominence is proxied by how many language editions link to an
entity — Kinkaku-ji has 57, a neighbourhood shrine has 0–2. It is explicitly a
significance proxy, not a quality rating, and a missing signal falls back per-POI
instead of reordering the pool.

**Missing cost data is never treated as free.** OSM's `fee` tag is absent on most
features. Absent maps to a category rate; only an explicit `fee=no` yields zero. Treating
absence as free lets unpriced stops slip past the budget ceiling — a property-based test
caught exactly that class of bug in the knapsack, where sub-cent costs quantised to zero
and were selected as free.

**Lodging is out of scope.** An earlier hotel integration was deleted rather than left
unverified, and with it an LLM path that invented hotel names and nightly rates. Those
fabricated prices flowed into the budget the verifier treats as ground truth — a
hallucinated number inside the correctness layer is precisely what this architecture
exists to prevent.

---

## Testing

```bash
cd backend && pytest -q
```

134 tests. The scheduler carries **property-based tests** (Hypothesis) asserting that
its output always satisfies the validator and that it is deterministic run-to-run. That
suite found a real soundness bug: costs were quantised to integer cents for the knapsack
but charged at full float precision, so a sub-cent cost rounded to zero, was selected as
free against a zero budget, and was then billed to the trip total.

API tests run against in-memory SQLite so authorisation behaviour is verified without a
live database — requiring Postgres to check "does an unauthenticated request get 401"
would mean CI skips exactly the checks that matter most.

---

## Benchmarks

`python -m evals.run_eval` runs 14 cases spanning ordinary requests, tight-but-repairable
budgets, genuinely infeasible ones, adversarial input, and cases that need data-acquisition
judgement. Numbers are reported as fractions, not percentages — n is far too small for
"100%" to mean what it looks like.

Results are recorded in [DECISIONS.md](DECISIONS.md) alongside the reasoning, including
the cases that got *worse* after a change and why.

---

## Known limitations

Stated plainly, because a repo that names its own weaknesses is easier to trust than one
that doesn't.

- **The agent layer is bounded and optional, not autonomous.** It widens data retrieval
  and nothing else. It never touches the scheduler, the verifier, or budget arithmetic —
  it improves *coverage*, never *correctness*, and that separation is deliberate.
- **Some destinations genuinely have little OpenStreetMap coverage.** Those plans come
  back sparse or empty with a warning. That is the honest outcome, not a bug to paper
  over with invented places.
- **Costs are labelled estimates, not quoted prices.** Transport uses distance bands;
  attractions use a per-category rate table. Neither claims to be live pricing.
- **Travel time is haversine distance at an assumed average speed**, not routed against
  real roads or traffic. Grounded in real coordinates, but not a routing engine.
- **Overpass is a shared community service** and does return 504s and timeouts under
  load. The client retries across a mirror and degrades to empty results rather than
  fabricating.

---

## Stack

FastAPI · LangGraph · PostgreSQL · Alembic · SQLAlchemy 2 · Pydantic v2 · Next.js 15 ·
TypeScript · Docker · GitHub Actions

Data sources: OpenStreetMap (Overpass + Nominatim), Open-Meteo, Wikidata — all keyless.
