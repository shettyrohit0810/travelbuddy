"use client";

import { useState } from "react";

import AgentTrace from "@/components/AgentTrace";
import PlanView from "@/components/PlanView";
import { createPlan, type TripPlan } from "@/lib/api";

const EXAMPLES = [
  "Plan a 3 day beach trip to Goa for 2 people with a budget of 60000",
  "Plan a 2 day cultural trip to Kyoto for 2 people with a budget of 40000",
  "Plan a 4 day trip to Paris for 1 person",
];

export default function Home() {
  const [query, setQuery] = useState(EXAMPLES[0]);
  const [plan, setPlan] = useState<TripPlan | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setPlan(null);
    try {
      setPlan(await createPlan(query));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="wrap">
      <h1 style={{ marginBottom: 4 }}>TravelBuddy</h1>
      <p className="muted" style={{ marginTop: 0 }}>
        The itinerary is chosen by a constraint solver, not a language model. Every stop
        comes from a real lookup and carries its source; the budget is enforced
        arithmetically and re-checked before you see the plan.
      </p>

      <form onSubmit={submit} className="card">
        <div className="row">
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Describe your trip…"
            aria-label="Trip description"
          />
          <button type="submit" disabled={loading || query.trim().length < 3}>
            {loading ? "Planning…" : "Plan trip"}
          </button>
        </div>
        <div className="row" style={{ marginTop: 10 }}>
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => setQuery(ex)}
              style={{ background: "var(--surface-2)", color: "var(--muted)", fontSize: 12, padding: "6px 10px" }}
            >
              {ex.split(" to ")[1]?.split(" for ")[0] ?? ex}
            </button>
          ))}
        </div>
        {loading && (
          <p className="muted" style={{ fontSize: 13, marginBottom: 0 }}>
            First lookup for a new city queries OpenStreetMap directly and can take up to
            90 seconds. Repeat lookups are cached for a day.
          </p>
        )}
      </form>

      {error && (
        <div className="card">
          <span className="badge badge-err">Error</span>
          <p style={{ marginBottom: 0 }}>{error}</p>
        </div>
      )}

      {plan && (
        <>
          <PlanView plan={plan} />
          <AgentTrace trajectories={plan.trajectories} />
        </>
      )}
    </main>
  );
}
