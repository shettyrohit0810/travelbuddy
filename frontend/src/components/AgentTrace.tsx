"use client";

import { useState } from "react";
import type { Trajectory } from "@/lib/api";

const OUTCOME: Record<string, { label: string; cls: string }> = {
  succeeded: { label: "Recovered", cls: "badge-ok" },
  gave_up: { label: "Gave up (honestly)", cls: "badge-warn" },
  budget_exhausted: { label: "Hit tool-call budget", cls: "badge-warn" },
  timeout: { label: "Hit time budget", cls: "badge-warn" },
  error: { label: "Errored", cls: "badge-err" },
  unavailable: { label: "Not run — no model configured", cls: "badge-warn" },
};

const preview = (v: unknown, max = 400) => {
  if (v === null || v === undefined) return "—";
  const text = typeof v === "string" ? v : JSON.stringify(v, null, 1);
  return text.length > max ? `${text.slice(0, max)}…` : text;
};

/** Shows what the acquisition agent tried, observed, and decided.
 *  The agent only widens data retrieval — the scheduler, budget arithmetic and
 *  verifier are deterministic and deliberately not represented here. */
export default function AgentTrace({ trajectories }: { trajectories: Trajectory[] }) {
  const [open, setOpen] = useState<string | null>(null);

  if (trajectories.length === 0) {
    return (
      <div className="card">
        <h3 style={{ marginTop: 0 }}>Agent trace</h3>
        <p className="muted" style={{ marginBottom: 0, fontSize: 14 }}>
          No agent ran. The deterministic lookup found enough attractions on its own,
          which is the expected path for a well-mapped destination.
        </p>
      </div>
    );
  }

  return (
    <div className="card">
      <h3 style={{ marginTop: 0 }}>Agent trace</h3>
      <p className="muted" style={{ fontSize: 13, marginTop: 0 }}>
        Every tool call, what came back, and why the next step was chosen. The agent
        decides only <strong>what data to fetch</strong>.
      </p>

      {trajectories.map((t, ti) => {
        const style = OUTCOME[t.outcome ?? ""] ?? { label: t.outcome ?? "unknown", cls: "badge-warn" };
        return (
          <div key={ti} style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginTop: 12 }}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong style={{ textTransform: "capitalize" }}>{t.agent} agent</strong>
              <span className={`badge ${style.cls}`}>{style.label}</span>
            </div>
            <p className="muted" style={{ fontSize: 13 }}>{t.goal}</p>
            <p className="muted" style={{ fontSize: 12 }}>
              Tool calls: {t.tool_calls_used}
              {t.tool_call_budget ? ` / ${t.tool_call_budget}` : ""}
              {t.wall_clock_ms != null && ` · ${(t.wall_clock_ms / 1000).toFixed(2)}s`}
            </p>
            {t.summary && <p style={{ fontSize: 13 }}>{t.summary}</p>}

            <ol style={{ paddingLeft: 18, fontSize: 13 }}>
              {t.steps.map((step) => {
                const key = `${ti}-${step.index}`;
                const isOpen = open === key;
                return (
                  <li key={key} style={{ marginBottom: 6 }}>
                    <button
                      onClick={() => setOpen(isOpen ? null : key)}
                      style={{ background: "none", color: "var(--text)", padding: 0, fontWeight: 600 }}
                    >
                      {step.name} <span className="muted">({step.kind})</span>
                      {step.duration_ms != null && <span className="muted"> · {Math.round(step.duration_ms)}ms</span>}
                    </button>
                    {step.reasoning && (
                      <div className="muted" style={{ fontSize: 12 }}>{step.reasoning}</div>
                    )}
                    {isOpen && (
                      <>
                        {step.arguments && <pre>{preview(step.arguments)}</pre>}
                        <pre>{step.error ?? preview(step.observation)}</pre>
                      </>
                    )}
                  </li>
                );
              })}
            </ol>
          </div>
        );
      })}
    </div>
  );
}
