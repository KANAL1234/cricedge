import axios, { AxiosRequestConfig } from "axios";
import { toast } from "sonner";

const BASE_URL =
  (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000") + "/api/v1";

export const api = axios.create({
  baseURL: BASE_URL,
  timeout: 10_000,
  headers: {
    "Content-Type": "application/json",
  },
});

// In-flight dedup: map of url -> pending Promise
const inFlightRequests = new Map<string, Promise<any>>();

// Auth interceptor placeholder (no auth implemented yet)
api.interceptors.request.use((config) => config);

// Log errors and show toast
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const message =
      error.response?.data?.error ?? error.message ?? "Unknown error";
    const url = error.config?.url ?? "";
    console.error(`[API Error] ${url}: ${message}`);
    if (typeof window !== "undefined") {
      toast.error(`API Error: ${message}`);
    }
    return Promise.reject(error);
  }
);

// Deduplicated GET wrapper
export function dedupedGet<T = any>(
  url: string,
  config?: AxiosRequestConfig
): Promise<T> {
  const key = url + (config?.params ? JSON.stringify(config.params) : "");

  if (inFlightRequests.has(key)) {
    return inFlightRequests.get(key)!;
  }

  const promise = api
    .get<T>(url, config)
    .then((res) => res.data)
    .finally(() => {
      inFlightRequests.delete(key);
    });

  inFlightRequests.set(key, promise);
  return promise;
}

// SWR-compatible fetcher
export const fetcher = (url: string) => api.get(url).then((res) => res.data);

// ---------- Typed Interfaces ----------

export interface PaginatedResponse<T> {
  data: T[];
  total: number;
  page: number;
  limit: number;
}

export interface MatchSummary {
  id: string;
  team1: string;
  team2: string;
  team1_short: string;
  team2_short: string;
  competition: string;
  format: string;
  status: "upcoming" | "live" | "completed";
  match_start_utc: string;
  lock_time_utc: string;
  venue: { id: string; name: string; city: string };
  playing_xi_team1: string[];
  playing_xi_team2: string[];
  xi_confirmed_at: string | null;
}

export interface MatchDetail extends MatchSummary {
  weather: {
    temp_c: number;
    condition: string;
    humidity: number;
    wind_kph: number;
    rain_chance: number;
  };
  venue_stats: {
    pitch_type: string;
    avg_first_innings_score_t20: number;
    avg_second_innings_score_t20: number;
    pace_wickets_pct: number;
    spin_wickets_pct: number;
    dew_factor: number;
  };
}

export interface PlayerDetail {
  id: string;
  name: string;
  full_name: string;
  short_name: string;
  country: string;
  role: "BAT" | "BOWL" | "AR" | "WK";
  dream11_price: number;
  batting_style: string;
  bowling_style: string;
  ipl_team: string;
  stats: {
    matches: number;
    avg_dream11_pts: number;
    [key: string]: any;
  };
}

export interface FormInning {
  match_id: string;
  dream11_points: number;
  runs?: number;
  wickets?: number;
  format?: string;
  date?: string;
}

export interface PlayerFormResponse {
  innings: FormInning[];
  games: number;
}

export interface OwnershipPrediction {
  player_id: string;
  predicted_ownership_pct: number;
  ownership_tier: "safe" | "mid" | "differential";
  is_recommended_differential: boolean;
  reasoning: string;
}

export interface OwnershipResponse {
  predictions: OwnershipPrediction[];
}

export interface CaptainPick {
  player_id: string;
  predicted_ownership: number;
  ev_score: number;
  captain_score: number;
  rationale: string;
  tier: string;
}

export interface CaptainResponse {
  captain: CaptainPick[];
  vice_captain: CaptainPick[];
  contest_type: string;
}

export interface DiffPick {
  player_id: string;
  predicted_ownership_pct: number;
  ownership_tier: string;
  is_recommended_differential: boolean;
  reasoning: string;
}

export interface DifferentialResponse {
  differentials: DiffPick[];
}

export interface ProjectionResponse {
  player_id: string;
  match_id: string;
  mean_points: number;
  p25_points: number;
  p75_points: number;
  p90_points: number;
  std_dev: number;
  boom_probability: number;
  bust_probability: number;
}

export interface VenueDetail {
  id: string;
  name: string;
  city: string;
  country: string;
  capacity?: number;
  total_matches?: number;
  pitch_type?: string;
}

export interface VenueStatsResponse {
  venue_id: string;
  format: string;
  avg_first_innings_score_t20: number;
  avg_second_innings_score_t20: number;
  pace_wickets_pct: number;
  spin_wickets_pct: number;
  dew_factor: number;
  chasing_wins_pct?: number;
  pitch_type: string;
}
