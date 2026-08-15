# Decisions

A running log of what was built, what running it revealed, and what was deliberately
cut. Written as things were measured, so where a number changed, the earlier one and the
reason are both still here.

## Geocoding: why not the obvious provider

The first implementation used Open-Meteo's geocoding API, which is free and needs no
key. It produced silently, confidently wrong plans:

- **"Goa" resolved to Genoa, Italy.** Open-Meteo is a populated-places gazetteer that
  ranks by population; the Indian state is absent from it entirely and Genoa (pop 580k)
  is the most populous fuzzy match. An entire itinerary of Italian churches — *Abbazia
  di San Siro*, *Aquarium of Genoa* — rendered under a heading that said Goa.
- **"National Capital Region" resolved to nothing**, because regions are not places in
  that dataset.

Preferring an exact name match helps but does not fix it: Open-Meteo has no entry for
Goa the state at any ranking, so the best it can do is Goa, Philippines — right name,
wrong country, which is the most dangerous kind of wrong.

Nominatim resolves both correctly and treats administrative regions as first-class. It
now leads, with Open-Meteo retained as a fallback because Nominatim is a donated service
with a strict rate limit. Whichever answers, the resolved place is stated in the plan:
when a name is genuinely ambiguous, naming the winner is the only honest option, and a
substring check is not enough — *"Goa"* is a substring of *"Goa, Philippines"*, so the
single most dangerous case would pass silently.

## Search radius: a constant was the wrong shape

With geocoding fixed, Goa scheduled exactly one stop — *Chandor Excavated Site* — and
the repeat-fallback showed it on all three days. The cause was a fixed 8 km search
radius applied to the centroid of a **state** whose attractions span roughly 100 km.

Radius is now derived from the resolved place's bounding box, floored at 8 km and capped
at 45 km. Derived from the box rather than the place *type* on purpose: type names vary
by country and provider ("state", "region", "administrative"), while a bounding box
means the same thing everywhere.

Measured effect on the same request:

| | Before | After |
|---|---|---|
| Unique stops for a 3-day Goa trip | 1 (repeated ×3) | **9** |
| Examples | Chandor Excavated Site | Dudhsagar Falls, Sé Cathedral, Shri Manguesh Temple, Convent of St. Francis of Assisi |

## Ranking: OpenStreetMap has no ratings

The scheduler's knapsack maximises a value term, and OSM has no rating field to supply
one. An early proxy scored every Wikidata-linked feature 4.0–4.5, which left the knapsack
with nothing to separate them, so ties broke alphabetically — *"Anyo Temple"* was
scheduled while Kinkaku-ji sat unselected in the same pool.

Prominence now comes from **Wikidata sitelink counts**: the number of language editions
linking to an entity. Kinkaku-ji has 57; a neighbourhood shrine has 0–2. Counts are
compressed logarithmically because the distribution is extremely skewed, and a POI with
no Wikidata match keeps its tag-based score rather than dropping to a floor — a partial
API response must not reorder the whole pool.

It is a *significance* proxy and is documented as one. It is not a quality rating and
should never be shown to a user as one.

## Cost data: absence is not zero

OSM's `fee` tag is missing on most features, so "no cost data" is the common case rather
than an edge case. Absence maps to a per-category rate; only an explicit `fee=no` yields
0.0. The `charge` tag is ignored even when present — its values carry mixed currencies
("500 JPY", "£3.50") and converting them needs an FX source this project does not have,
so using them would silently corrupt a single-currency total the verifier trusts.

This policy exists because the opposite bug already happened once. A property-based test
found that costs were quantised to integer cents for the knapsack but charged at full
float precision, so a sub-cent cost rounded to **0 cents**, was selected as free against
a zero budget, and was then billed to the trip total. Quantisation is now conservative in
both directions: budget rounds down, costs round up.

## Lodging: deleted rather than left unverified

An Amadeus hotel integration existed but had never once executed against the live API,
because no key was ever configured. It was removed rather than left in the tree implying
a capability the project does not have.

The more important removal was alongside it: an **LLM fallback that invented hotels** —
names, nightly rates, ratings, generated with no source. Those fabricated prices flowed
into `budget.lodging`, which the verifier treats as ground truth when deciding whether a
plan fits. A hallucinated number inside the correctness layer is exactly the failure this
architecture exists to prevent, and it would have switched itself on silently the moment
an LLM key was added. A regression test now asserts the module contains no LLM or
provider imports at all.

## Repair: levers, floors, and a termination bug

Repair spends an overspend down across `activities → food → lodging → transport`, each
bounded by a floor. Transport is last and floored highest because it maps to a concrete
priced option — writing it down far is closer to lying about the price than to planning
a cheaper trip.

Floors are anchored to a **baseline captured on the first pass**. An earlier version
computed them from the *current* value, which let each pass shave another fraction: the
lever approached zero without ever reaching a floor, so `exhausted` never fired and the
loop only stopped on the attempt cap. A regression test pins it.

The router also checks headroom *before* dispatching a repair. Catching it one node later
meant re-running the whole scheduler to arrive at an identical plan.

## Verification caught a wrong test, not a wrong plan

Two benchmark cases expected a 2-day Kyoto trip for two people to fit in ₹20,000 and the
verifier disagreed. Mumbai→Kyoto is 6,373 km, roughly ₹70,000 for two at the distance-band
rate — the budget was never satisfiable and the cases were wrong. Corrected the premises
rather than relaxing the check.

This is the second time a test premise turned out to be false rather than the code. The
first: a case asserted a zero activities budget schedules nothing, when genuinely free
attractions legitimately still fit.

## Parallelism: measured, and smaller than it looked

The research branches are genuinely independent and run concurrently, verified by
measuring peak-concurrent execution and wall clock rather than reading the edge list.

An early single-run benchmark reported a **3.39× speedup**. Repeated runs (5 per
topology, alternating which goes first) put it at **~1.07× cold**. The original figure
came from one sequential run that happened to hit an Overpass retry round and took 287 s
against a 72–95 s norm.

The honest explanation is Amdahl's law, measured rather than argued: the cold POI lookup
is 75–85 s of an ~85 s request and the other branches cost about a second combined. The
topology is correct and would pay off if the other branches did real network work; today
it does not, and the number says so.

## Security

- Access and refresh tokens use **separate secrets** and carry a `type` claim that is
  checked on decode. One secret for both means a stolen refresh token is accepted as an
  access token; checking only the signature means the same thing.
- Every trip route derives the owner from the bearer token. No route accepts a `user_id`
  argument, because a client-supplied identifier is an assertion, not proof.
- Reading another user's trip returns **404, not 403** — a 403 confirms the id exists.
- Failed login returns an identical response for an unknown email and a wrong password,
  so it cannot be used to enumerate registered addresses.
- `assert_production_ready()` refuses to start with development-default secrets, a key
  shorter than the 32 bytes HMAC-SHA256 needs, or the same secret reused for both. The
  original defaults were 23 and 27 bytes, which PyJWT warns about at runtime.

## Schema ownership

Alembic owns the schema; the app never calls `create_all()`. `env.py` imports the model
modules explicitly, because `Base.metadata` is only populated as a side effect of the
mapped classes being imported — without it, autogenerate compares against empty metadata
and emits a migration whose body is `pass`. That failure mode is worth naming: it
produces a real-looking migration file that does nothing, and it stays invisible until a
column change silently fails to apply. CI gates on drift for exactly that reason.

## Benchmark: 14 cases against live data

| Metric | Value |
|---|---|
| Cases / crashes | 14 / **0** |
| Verifier matched expectation | **6/6** constrained cases |
| Cases scheduling stops | **10/14** |
| Stops grounded | **117/117** |
| Cases needing repair | 3/14, mean 0.21 iterations |
| Mean / p95 latency | 92.3 s / 286.8 s |

Latency is a worst case, not steady state: every case in this run paid a cold Overpass
lookup (60–90 s per unseen city), and cached lookups are effectively free for 24 hours.

**On the four cases that scheduled nothing** — two are the correct outcome.
`gibberish_destination` has no resolvable place and `goa_absurd_budget` states a budget
that cannot be met; both should return empty rather than fabricate. The remaining two,
`sparse_small_town` (Chikmagalur) and `niche_interest_needs_category_relaxation`
(Lucknow), are genuine gaps — and both ran 280–380 s, which points at Overpass timing
out rather than those towns having nothing mapped. They are precisely the cases the
bounded acquisition agent exists to recover, and that agent has **not been measured**:
it is wired and makes real API calls, but has never executed a decision because no
funded model key has been available. Until it has, no recovery claim is made for it.
