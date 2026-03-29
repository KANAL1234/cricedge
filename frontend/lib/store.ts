import { create } from "zustand";
import { api } from "./api";

// ---------- Types ----------

export interface Match {
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
  venue: {
    id: string;
    name: string;
    city: string;
  };
  playing_xi_team1: string[];
  playing_xi_team2: string[];
  xi_confirmed_at: string | null;
  weather?: {
    temp_c: number;
    condition: string;
    humidity: number;
    wind_kph: number;
    rain_chance: number;
  };
  venue_stats?: {
    pitch_type: string;
    avg_first_innings_score_t20: number;
    avg_second_innings_score_t20: number;
    pace_wickets_pct: number;
    spin_wickets_pct: number;
    dew_factor: number;
  };
}

export interface Player {
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

// ---------- Match Store ----------

interface MatchStore {
  matches: Match[];
  isLoading: boolean;
  error: string | null;
  xiUpdates: Record<string, string>;
  fetchMatches: () => Promise<void>;
  markXIConfirmed: (matchId: string, team: string) => void;
}

export const useMatchStore = create<MatchStore>((set) => ({
  matches: [],
  isLoading: false,
  error: null,
  xiUpdates: {},

  fetchMatches: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await api.get("/matches", {
        params: { limit: 50, page: 1 },
      });
      set({ matches: res.data.data ?? [] });
    } catch (err: any) {
      set({ error: err.message });
    } finally {
      set({ isLoading: false });
    }
  },

  markXIConfirmed: (matchId: string, team: string) => {
    set((state) => ({
      xiUpdates: { ...state.xiUpdates, [matchId]: team },
      matches: state.matches.map((m) =>
        m.id === matchId
          ? { ...m, xi_confirmed_at: new Date().toISOString() }
          : m
      ),
    }));
  },
}));

// ---------- Player Store ----------

interface PlayerStore {
  players: Record<string, Player>;
  fetchPlayer: (id: string) => Promise<void>;
}

export const usePlayerStore = create<PlayerStore>((set, get) => ({
  players: {},

  fetchPlayer: async (id: string) => {
    if (get().players[id]) return;
    try {
      const res = await api.get(`/players/${id}`);
      set((state) => ({
        players: { ...state.players, [id]: res.data },
      }));
    } catch (err) {
      console.error(`[PlayerStore] Failed to fetch player ${id}`, err);
    }
  },
}));

// ---------- UI Store ----------

interface UIStore {
  contestType: "mega" | "small";
  setContestType: (t: "mega" | "small") => void;
  sidebarOpen: boolean;
  toggleSidebar: () => void;
}

export const useUIStore = create<UIStore>((set) => ({
  contestType: "mega",
  sidebarOpen: false,

  setContestType: (t) => set({ contestType: t }),
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
}));

// ---------- Auth Store ----------

interface AuthStore {
  user: any | null;
  subscriptionTier: "free" | "pro" | "elite";
  isLoading: boolean;
  setUser: (user: any | null) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthStore>((set) => ({
  user: null,
  subscriptionTier: "free",
  isLoading: false,

  setUser: (user) =>
    set({
      user,
      subscriptionTier: user?.user_metadata?.subscription_tier ?? "free",
    }),

  logout: () => set({ user: null, subscriptionTier: "free" }),
}));
