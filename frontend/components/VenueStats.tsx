"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

interface VenueStatsData {
  avg_first_innings_score?: number;
  avg_second_innings_score?: number;
  pace_wickets_pct?: number;
  spin_wickets_pct?: number;
  chasing_wins_pct?: number;
  highest_score?: number;
  matches_played?: number;
}

export default function VenueStats({
  venueId,
  format,
}: {
  venueId: string;
  format?: string;
}) {
  const [stats, setStats] = useState<VenueStatsData | null>(null);
  const [venueName, setVenueName] = useState("");

  useEffect(() => {
    const load = async () => {
      try {
        const res = await api.get(`/venues/${venueId}/stats`, {
          params: format ? { format } : {},
        });
        setStats(res.data.stats);
        const venueRes = await api.get(`/venues/${venueId}`);
        setVenueName(venueRes.data.name);
      } catch {
        // venue stats optional
      }
    };
    load();
  }, [venueId, format]);

  if (!stats) return null;

  const rows = [
    { label: "AVG 1ST INN", value: stats.avg_first_innings_score?.toFixed(0) },
    { label: "AVG 2ND INN", value: stats.avg_second_innings_score?.toFixed(0) },
    { label: "PACE WKT %", value: stats.pace_wickets_pct ? `${stats.pace_wickets_pct}%` : undefined },
    { label: "SPIN WKT %", value: stats.spin_wickets_pct ? `${stats.spin_wickets_pct}%` : undefined },
    { label: "CHASE WIN %", value: stats.chasing_wins_pct ? `${stats.chasing_wins_pct}%` : undefined },
    { label: "MATCHES", value: stats.matches_played?.toString() },
  ].filter((r) => r.value !== undefined);

  return (
    <div className="border border-border rounded p-4 space-y-3">
      <div className="font-mono text-sm text-muted tracking-widest">
        VENUE — {venueName.toUpperCase()}{format ? ` · ${format}` : ""}
      </div>
      <div className="grid grid-cols-2 gap-2">
        {rows.map((row) => (
          <div key={row.label} className="space-y-0.5">
            <div className="font-mono text-[10px] text-muted">{row.label}</div>
            <div className="font-mono text-white text-sm font-semibold">{row.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
