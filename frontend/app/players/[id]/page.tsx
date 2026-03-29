"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { ArrowLeft } from "lucide-react";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { fetcher } from "@/lib/api";
import { useMatchStore } from "@/lib/store";

const cn = (...args: any[]) => twMerge(clsx(args));

const ROLE_LABELS: Record<string, string> = {
  BAT: "BATSMAN",
  BOWL: "BOWLER",
  AR: "ALL-ROUNDER",
  WK: "WICKET-KEEPER",
};
const ROLE_COLORS: Record<string, string> = {
  BAT: "text-info border-info/30 bg-info/5",
  BOWL: "text-warning border-warning/30 bg-warning/5",
  AR: "text-accent border-accent/30 bg-accent/5",
  WK: "text-danger border-danger/30 bg-danger/5",
};

function FormDot({ pts }: { pts: number }) {
  return (
    <span
      className={cn(
        "w-2 h-2 rounded-full inline-block",
        pts > 40 ? "bg-accent" : pts > 20 ? "bg-warning" : "bg-danger"
      )}
      title={`${pts} pts`}
    />
  );
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-surface border border-border rounded p-2 font-mono text-xs">
      <div className="text-muted">Match {label}</div>
      <div className="text-accent font-semibold">{payload[0].value} pts</div>
    </div>
  );
};

export default function PlayerPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { matches } = useMatchStore();
  const [format, setFormat] = useState<"ALL" | "T20" | "ODI" | "TEST">("ALL");

  const { data: player, isLoading: playerLoading } = useSWR(
    id ? `/players/${id}` : null,
    fetcher
  );
  const { data: formData } = useSWR(
    id ? `/players/${id}/form` : null,
    fetcher,
    { refreshInterval: 60_000 }
  );

  // Try to project against the soonest upcoming match
  const soonestMatch = matches.find((m) => m.status === "upcoming");
  const { data: projection } = useSWR(
    id && soonestMatch?.id
      ? `/predictions/player/${id}/projection?match_id=${soonestMatch.id}`
      : null,
    fetcher
  );

  if (playerLoading && !player) {
    return (
      <div className="flex items-center justify-center h-64 font-mono text-muted text-sm animate-pulse">
        LOADING PLAYER DATA...
      </div>
    );
  }

  if (!player) {
    return (
      <div className="flex items-center justify-center h-64 font-mono text-danger text-sm">
        PLAYER NOT FOUND
      </div>
    );
  }

  const innings: any[] = formData?.innings ?? [];
  const recentInnings = innings.slice(-15).reverse();
  const chartData = recentInnings.map((inn: any, i: number) => ({
    match: i + 1,
    pts: inn.dream11_points ?? 0,
    date: inn.match_date ?? "",
  }));

  const last5 = innings.slice(-5);

  // Stats computation
  const allPts = innings.map((i: any) => i.dream11_points ?? 0);
  const avgPts = allPts.length > 0 ? allPts.reduce((a: number, b: number) => a + b, 0) / allPts.length : 0;
  const bestPts = allPts.length > 0 ? Math.max(...allPts) : 0;

  return (
    <div className="max-w-screen-lg mx-auto px-4 py-4 space-y-6">
      {/* Back */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-1 font-mono text-xs text-muted hover:text-white transition-colors"
      >
        <ArrowLeft size={12} /> BACK
      </button>

      {/* ── Player Header ── */}
      <div className="border border-border rounded p-4 space-y-2">
        <div className="flex items-start justify-between flex-wrap gap-2">
          <div>
            <div className="font-mono text-accent text-xl font-bold">
              {player.name}
            </div>
            <div className="font-mono text-muted text-xs mt-0.5">
              {player.ipl_team && <span>{player.ipl_team} · </span>}
              {player.country}
            </div>
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <span
              className={cn(
                "font-mono text-xs border px-2 py-0.5 rounded",
                ROLE_COLORS[player.role] ?? "text-muted border-border"
              )}
            >
              {ROLE_LABELS[player.role] ?? player.role}
            </span>
            <span className="font-mono text-warning text-sm font-semibold border border-warning/30 px-2 py-0.5 rounded">
              {player.dream11_price?.toFixed(1)} CR
            </span>
          </div>
        </div>

        {/* Form dots */}
        {last5.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-muted">FORM</span>
            <div className="flex gap-1">
              {last5.map((inn: any, i: number) => (
                <FormDot key={i} pts={inn.dream11_points ?? 0} />
              ))}
            </div>
            <span className="font-mono text-[10px] text-muted">LAST 5</span>
          </div>
        )}
      </div>

      {/* ── Form Chart ── */}
      {chartData.length > 0 && (
        <div className="border border-border rounded p-4 space-y-2">
          <div className="font-mono text-xs text-muted tracking-widest">
            FORM (LAST {chartData.length} MATCHES)
          </div>
          <ResponsiveContainer width="100%" height={160}>
            <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
              <XAxis
                dataKey="match"
                tick={{ fill: "#8B949E", fontSize: 9, fontFamily: "IBM Plex Mono" }}
                axisLine={{ stroke: "#21262D" }}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: "#8B949E", fontSize: 9, fontFamily: "IBM Plex Mono" }}
                axisLine={false}
                tickLine={false}
                width={28}
              />
              <Tooltip content={<CustomTooltip />} />
              <ReferenceLine
                y={40}
                stroke="#FFB800"
                strokeDasharray="3 3"
                label={{ value: "40", fill: "#FFB800", fontSize: 9 }}
              />
              <Line
                type="monotone"
                dataKey="pts"
                stroke="#00FF88"
                strokeWidth={1.5}
                dot={{ fill: "#00FF88", r: 2, strokeWidth: 0 }}
                activeDot={{ r: 4, fill: "#00FF88" }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Stats ── */}
      <div className="border border-border rounded p-4 space-y-3">
        <div className="flex items-center gap-3">
          <span className="font-mono text-xs text-muted tracking-widest">STATS</span>
          <div className="flex gap-1">
            {(["ALL", "T20", "ODI", "TEST"] as const).map((f) => (
              <button
                key={f}
                onClick={() => setFormat(f)}
                className={cn(
                  "font-mono text-[10px] px-2 py-0.5 rounded min-h-[28px] transition-colors",
                  format === f
                    ? "bg-accent text-background font-bold"
                    : "text-muted border border-border hover:text-white"
                )}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-surface-2 rounded p-3">
            <div className="font-mono text-[10px] text-muted">MATCHES</div>
            <div className="font-mono text-white text-lg font-semibold">
              {player.stats?.matches ?? innings.length}
            </div>
          </div>
          <div className="bg-surface-2 rounded p-3">
            <div className="font-mono text-[10px] text-muted">AVG D11 PTS</div>
            <div className="font-mono text-accent text-lg font-semibold">
              {(player.stats?.avg_dream11_pts ?? avgPts).toFixed(1)}
            </div>
          </div>
          <div className="bg-surface-2 rounded p-3">
            <div className="font-mono text-[10px] text-muted">BEST SCORE</div>
            <div className="font-mono text-warning text-lg font-semibold">
              {bestPts > 0 ? bestPts.toFixed(0) : "—"}
            </div>
          </div>
          <div className="bg-surface-2 rounded p-3">
            <div className="font-mono text-[10px] text-muted">LAST 5 AVG</div>
            <div className="font-mono text-info text-lg font-semibold">
              {last5.length > 0
                ? (last5.reduce((a: number, b: any) => a + (b.dream11_points ?? 0), 0) / last5.length).toFixed(1)
                : "—"}
            </div>
          </div>
        </div>
        {player.batting_style && (
          <div className="font-mono text-xs text-muted">
            BAT: {player.batting_style}
            {player.bowling_style && ` · BOWL: ${player.bowling_style}`}
          </div>
        )}
      </div>

      {/* ── Points Projection ── */}
      {projection && (
        <div className="border border-border rounded p-4 space-y-3">
          <div className="font-mono text-xs text-muted tracking-widest">
            POINTS PROJECTION — {soonestMatch?.team1_short} vs {soonestMatch?.team2_short}
          </div>
          <div className="space-y-2">
            {[
              { label: "P90 (BOOM)", value: projection.p90_points, color: "bg-accent" },
              { label: "P75", value: projection.p75_points, color: "bg-accent/60" },
              { label: "MEDIAN", value: projection.mean_points, color: "bg-info" },
              { label: "P25", value: projection.p25_points, color: "bg-warning/60" },
            ].map(({ label, value, color }) => (
              <div key={label} className="flex items-center gap-3">
                <div className="font-mono text-[10px] text-muted w-20">{label}</div>
                <div className="flex-1 h-1.5 bg-surface-2 rounded overflow-hidden">
                  <div
                    className={cn("h-full rounded", color)}
                    style={{ width: `${Math.min((value / 100) * 100, 100)}%` }}
                  />
                </div>
                <div className="font-mono text-xs text-white w-8 text-right">
                  {value?.toFixed(0) ?? "—"}
                </div>
              </div>
            ))}
          </div>
          <div className="flex gap-4 font-mono text-xs">
            <span className="text-muted">
              BOOM: <span className="text-accent">{((projection.boom_probability ?? 0) * 100).toFixed(0)}%</span>
            </span>
            <span className="text-muted">
              BUST: <span className="text-danger">{((projection.bust_probability ?? 0) * 100).toFixed(0)}%</span>
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
