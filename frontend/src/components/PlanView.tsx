"use client";

import type { TripPlan } from "@/lib/api";

const currency = (n: number) => `₹${Math.round(n).toLocaleString("en-IN")}`;

/** Renders a plan. Every stop shows its source, because the backend rejects any stop
 *  without one -- surfacing it makes that guarantee visible rather than merely true. */
export default function PlanView({ plan }: { plan: TripPlan }) {
  const { itinerary, budget, verification, weather, requirements } = plan;
  if (!itinerary) return null;

  const stopCount = itinerary.days.reduce((n, d) => n + d.stops.length, 0);

  return (
    <>
      <div className="card">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2 style={{ margin: 0 }}>
            {requirements?.days ?? itinerary.days.length} days in{" "}
            {itinerary.resolved_location ?? itinerary.destination}
          </h2>
          {verification && (
            <span className={`badge ${verification.valid ? "badge-ok" : "badge-warn"}`}>
              {verification.valid ? "Constraints satisfied" : "Constraints unmet"}
            </span>
          )}
        </div>

        {itinerary.warnings.length > 0 && (
          <ul className="muted" style={{ fontSize: 13, paddingLeft: 18, marginBottom: 0 }}>
            {itinerary.warnings.map((w, i) => <li key={i}>{w}</li>)}
          </ul>
        )}

        {verification && !verification.valid && (
          <div style={{ marginTop: 12 }}>
            {verification.violations.map((v, i) => (
              <div key={i} style={{ fontSize: 13 }}>
                <code>{v.code}</code> {v.message}
              </div>
            ))}
            <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
              Reported after {verification.repair_attempts} repair attempt(s). The planner
              says so rather than returning a plan that quietly breaks the budget.
            </p>
          </div>
        )}
      </div>

      {budget && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Budget</h3>
          <table>
            <tbody>
              {(["transport", "lodging", "food", "activities", "buffer"] as const).map((k) => (
                <tr key={k}>
                  <td style={{ textTransform: "capitalize" }}>{k}</td>
                  <td style={{ textAlign: "right" }}>{currency(budget[k])}</td>
                </tr>
              ))}
              <tr>
                <td><strong>Total</strong></td>
                <td style={{ textAlign: "right" }}><strong>{currency(budget.total)}</strong></td>
              </tr>
            </tbody>
          </table>
          <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
            Estimates produced from trip parameters and a per-category rate table — not
            quoted prices.
          </p>
        </div>
      )}

      {weather && (
        <div className="card">
          <h3 style={{ marginTop: 0 }}>Weather</h3>
          <p style={{ margin: 0 }}>{weather.summary}</p>
          {weather.warnings.map((w, i) => (
            <p key={i} className="muted" style={{ fontSize: 13, marginBottom: 0 }}>{w}</p>
          ))}
        </div>
      )}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Itinerary <span className="muted">({stopCount} stops)</span></h3>
        {itinerary.days.map((day) => (
          <div key={day.day} style={{ marginBottom: 18 }}>
            <strong>Day {day.day}</strong>
            <p className="muted" style={{ fontSize: 13, margin: "4px 0 8px" }}>{day.narrative}</p>
            {day.stops.length === 0 ? (
              <p className="muted" style={{ fontSize: 13 }}>
                No verified attractions were available for this day.
              </p>
            ) : (
              <table>
                <thead>
                  <tr><th>Time</th><th>Stop</th><th>Travel</th><th>Cost</th><th>Source</th></tr>
                </thead>
                <tbody>
                  {day.stops.map((s, i) => (
                    <tr key={i}>
                      <td>{s.start_time}–{s.end_time}</td>
                      <td>{s.name}</td>
                      <td className="muted">{Math.round(s.travel_minutes_from_previous)} min</td>
                      <td>{currency(s.estimated_cost)}</td>
                      <td><code>{s.source}</code></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        ))}
      </div>
    </>
  );
}
