/** Thin API client. Types mirror the backend's Pydantic schemas. */
const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface ScheduledStop {
  name: string;
  category: string;
  start_time: string;
  end_time: string;
  travel_minutes_from_previous: number;
  estimated_cost: number;
  /** Which lookup produced this. Stops without it fail backend verification. */
  source: string;
}

export interface DayPlan {
  day: number;
  narrative: string;
  stops: ScheduledStop[];
}

export interface Itinerary {
  destination: string;
  resolved_location: string | null;
  days: DayPlan[];
  warnings: string[];
}

export interface BudgetBreakdown {
  transport: number;
  lodging: number;
  food: number;
  activities: number;
  buffer: number;
  total: number;
}

export interface Violation {
  code: string;
  message: string;
  repairable: boolean;
  overspend: number | null;
}

export interface Verification {
  valid: boolean;
  violations: Violation[];
  repair_attempts: number;
}

export interface TrajectoryStep {
  index: number;
  kind: string;
  name: string;
  arguments?: Record<string, unknown> | null;
  observation?: unknown;
  reasoning?: string | null;
  duration_ms?: number | null;
  error?: string | null;
}

export interface Trajectory {
  agent: string;
  goal: string;
  steps: TrajectoryStep[];
  outcome: string | null;
  summary: string | null;
  tool_calls_used: number;
  tool_call_budget: number | null;
  wall_clock_ms: number | null;
}

export interface TripPlan {
  requirements: {
    destination: string | null;
    days: number | null;
    travelers: number | null;
    budget: number | null;
    interests: string[];
  } | null;
  weather: {
    summary: string;
    avg_high_c: number | null;
    rain_chance_pct: number | null;
    suitability: number;
    warnings: string[];
  } | null;
  budget: BudgetBreakdown | null;
  itinerary: Itinerary | null;
  verification: Verification | null;
  trajectories: Trajectory[];
  logs: string[];
}

export async function createPlan(query: string, origin = "Mumbai"): Promise<TripPlan> {
  const response = await fetch(`${API_URL}/api/v1/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, origin }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Planning failed (${response.status}): ${detail.slice(0, 200)}`);
  }
  return response.json();
}
