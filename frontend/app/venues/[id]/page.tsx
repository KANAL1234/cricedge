"use client";

import { useParams, useRouter } from "next/navigation";
import useSWR from "swr";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { ArrowLeft } from "lucide-react";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { fetcher } from "@/lib/api";

const cn = (...args: any[]) => twMerge(clsx(args));

const PITCH_STYLES: Record<string, string> = {
  BATTING: "text-accent border-accent/30 bg-accent/5",
  BOWLING: "text-warning border-warning/30 bg-warning/5",
  BALANCED: "text-info border-info/30 bg-info/5",
};

const CustomTooltip = ({ active, payload }: any) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-surface border border-border rounded p-2 font-mono text-xs">
      <div className="text-muted">{payload[0].name}</div>
      <div className="text-accent font-semibold">{payload[0].value?.toFixed(0)} runs</div>
    </div>
  );
};

export default function VenuePage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const { data: venue, isLoading } = useSWR(id ? `/venues/${id}` : null, fetcher);
  const { data: statsData } = useSWR(
    id ? `/venues/${id}/stats?format=T20` : null,
    fetcher
  );

  if (isLoading && !venue) {
    return (
      <div className="flex items-center justify-center h-64 font-mono text-muted text-sm animate-pulse">
        LOADING VENUE DATA...
      </div>
    );
  }

  if (!venue) {
    return (
      <div className="flex items-center justify-center h-64 font-mono text-danger text-sm">
        VENUE NOT FOUND
      </div>
    );
  }

  const pitchType = venue.pitch_type?.toUpperCase() ?? "BALANCED";
  const pitchStyle = PITCH_STYLES[pitchType] ?? PITCH_STYLES.BALANCED;

  const avg1st = venue.avg_first_innings_score_t20 ?? 0;
  const avg2nd = venue.avg_second_innings_score_t20 ?? 0;
  const pace = venue.pace_wickets_pct ?? 50;
  const spin = venue.spin_wickets_pct ?? 50;
  const dew = venue.dew_factor ?? 0;

  const scoringData = [
    { name: "1ST INN", runs: avg1st },
    { name: "2ND INN", runs: avg2nd },
  ];

  const pieData = [
    { name: "PACE", value: pace },
    { name: "SPIN", value: spin },
  ];

  const dewLabel =
    dew > 0.6 ? { label: "HIGH", color: "text-danger" }
    : dew > 0.4 ? { label: "MED", color: "text-warning" }
    : { label: "LOW", color: "text-muted" };

  return (
    <div className="max-w-screen-lg mx-auto px-4 py-4 space-y-6">
      {/* Back */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-1 font-mono text-xs text-muted hover:text-white transition-colors"
      >
        <ArrowLeft size={12} /> BACK
      </button>

      {/* ── Venue Header ── */}
      <div className="border border-border rounded p-4 space-y-2">
        <div className="flex items-start justify-between flex-wrap gap-2">
          <div>
            <div className="font-mono text-accent text-xl font-bold">{venue.name}</div>
            <div className="font-mono text-muted text-xs mt-0.5">
              {venue.city}{venue.country ? `, ${venue.country}` : ""}
              {venue.capacity ? ` · ${venue.capacity.toLocaleString()} capacity` : ""}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className={cn("font-mono text-xs border px-2 py-0.5 rounded", pitchStyle)}>
              {pitchType}
            </span>
            {venue.total_matches != null && (
              <span className="font-mono text-xs text-muted border border-border px-2 py-0.5 rounded">
                {venue.total_matches} MATCHES
              </span>
            )}
          </div>
        </div>
      </div>

      {/* ── Stats Grid ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-surface border border-border rounded p-3">
          <div className="font-mono text-[10px] text-muted">AVG 1ST INN</div>
          <div className="font-mono text-accent text-xl font-semibold">
            {avg1st > 0 ? avg1st.toFixed(0) : "—"}
          </div>
        </div>
        <div className="bg-surface border border-border rounded p-3">
          <div className="font-mono text-[10px] text-muted">AVG 2ND INN</div>
          <div className="font-mono text-info text-xl font-semibold">
            {avg2nd > 0 ? avg2nd.toFixed(0) : "—"}
          </div>
        </div>
        <div className="bg-surface border border-border rounded p-3">
          <div className="font-mono text-[10px] text-muted">DEW FACTOR</div>
          <div className={cn("font-mono text-xl font-semibold", dewLabel.color)}>
            {dewLabel.label}
          </div>
        </div>
        <div className="bg-surface border border-border rounded p-3">
          <div className="font-mono text-[10px] text-muted">PITCH TYPE</div>
          <div className={cn("font-mono text-lg font-semibold", pitchStyle.split(" ")[0])}>
            {pitchType.slice(0, 4)}
          </div>
        </div>
      </div>

      {/* ── Charts Row ── */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Scoring Patterns */}
        {avg1st > 0 && (
          <div className="border border-border rounded p-4 space-y-2">
            <div className="font-mono text-xs text-muted tracking-widest">
              T20 SCORING PATTERNS
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <BarChart data={scoringData} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
                <XAxis
                  dataKey="name"
                  tick={{ fill: "#8B949E", fontSize: 9, fontFamily: "IBM Plex Mono" }}
                  axisLine={{ stroke: "#21262D" }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: "#8B949E", fontSize: 9, fontFamily: "IBM Plex Mono" }}
                  axisLine={false}
                  tickLine={false}
                  width={32}
                />
                <Tooltip content={<CustomTooltip />} />
                <Bar dataKey="runs" fill="#00FF88" radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}

        {/* Pace vs Spin */}
        {(pace > 0 || spin > 0) && (
          <div className="border border-border rounded p-4 space-y-2">
            <div className="font-mono text-xs text-muted tracking-widest">
              PACE vs SPIN (WICKETS)
            </div>
            <ResponsiveContainer width="100%" height={160}>
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={40}
                  outerRadius={65}
                  paddingAngle={3}
                  dataKey="value"
                  label={({ name, value }: any) =>
                    `${name} ${value?.toFixed(0)}%`
                  }
                  labelLine={false}
                >
                  <Cell fill="#00FF88" />
                  <Cell fill="#2979FF" />
                </Pie>
                <Tooltip
                  formatter={(v: any, name: any) => [`${Number(v).toFixed(1)}%`, name]}
                  contentStyle={{
                    background: "#0D1117",
                    border: "1px solid #21262D",
                    fontFamily: "IBM Plex Mono",
                    fontSize: 11,
                    color: "#fff",
                  }}
                />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex justify-center gap-4 font-mono text-[10px]">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-accent inline-block" />
                PACE {pace.toFixed(0)}%
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full bg-info inline-block" />
                SPIN {spin.toFixed(0)}%
              </span>
            </div>
          </div>
        )}
      </div>

      {/* ── Detailed Stats from /stats endpoint ── */}
      {statsData && (
        <div className="border border-border rounded p-4 space-y-4">
          <div className="font-mono text-xs text-muted tracking-widest">
            DETAILED STATS (T20)
          </div>

          {/* Scoring patterns */}
          {statsData.scoring_patterns && (
            <div className="grid grid-cols-3 gap-3">
              <div className="bg-surface border border-border rounded p-3">
                <div className="font-mono text-[10px] text-muted">AVG 1ST INN</div>
                <div className="font-mono text-accent text-xl font-semibold">
                  {statsData.scoring_patterns.avg_first_innings?.toFixed(0) ?? "—"}
                </div>
              </div>
              <div className="bg-surface border border-border rounded p-3">
                <div className="font-mono text-[10px] text-muted">AVG 2ND INN</div>
                <div className="font-mono text-info text-xl font-semibold">
                  {statsData.scoring_patterns.avg_second_innings?.toFixed(0) ?? "—"}
                </div>
              </div>
              <div className="bg-surface border border-border rounded p-3">
                <div className="font-mono text-[10px] text-muted">MATCHES</div>
                <div className="font-mono text-white text-xl font-semibold">
                  {statsData.scoring_patterns.matches_sampled ?? "—"}
                </div>
              </div>
            </div>
          )}

          {/* Pace vs Spin raw counts */}
          {statsData.pace_vs_spin && (
            <div className="grid grid-cols-2 gap-3">
              <div className="bg-surface border border-border rounded p-3 flex items-center gap-3">
                <span className="w-2 h-2 rounded-full bg-accent shrink-0" />
                <div>
                  <div className="font-mono text-[10px] text-muted">PACE WICKETS</div>
                  <div className="font-mono text-accent text-sm font-semibold">
                    {statsData.pace_vs_spin.pace_wickets ?? 0}
                    {statsData.pace_vs_spin.pace_pct != null && (
                      <span className="text-muted text-[10px] ml-1">
                        ({statsData.pace_vs_spin.pace_pct.toFixed(0)}%)
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="bg-surface border border-border rounded p-3 flex items-center gap-3">
                <span className="w-2 h-2 rounded-full bg-info shrink-0" />
                <div>
                  <div className="font-mono text-[10px] text-muted">SPIN WICKETS</div>
                  <div className="font-mono text-info text-sm font-semibold">
                    {statsData.pace_vs_spin.spin_wickets ?? 0}
                    {statsData.pace_vs_spin.spin_pct != null && (
                      <span className="text-muted text-[10px] ml-1">
                        ({statsData.pace_vs_spin.spin_pct.toFixed(0)}%)
                      </span>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Dew + pitch */}
          <div className="flex items-center gap-3 flex-wrap">
            <div className="bg-surface border border-border rounded px-3 py-2 flex items-center gap-2">
              <span className="font-mono text-[10px] text-muted">PITCH</span>
              <span className={cn(
                "font-mono text-xs font-semibold border px-1.5 py-0.5 rounded",
                PITCH_STYLES[(statsData.pitch_type?.toUpperCase() ?? "BALANCED")] ?? PITCH_STYLES.BALANCED
              )}>
                {statsData.pitch_type?.toUpperCase() ?? "—"}
              </span>
            </div>
            <div className="bg-surface border border-border rounded px-3 py-2 flex items-center gap-2">
              <span className="font-mono text-[10px] text-muted">DEW FACTOR</span>
              <span className={cn(
                "font-mono text-xs font-semibold",
                statsData.dew_factor ? "text-warning" : "text-muted"
              )}>
                {statsData.dew_factor ? "YES" : "NO"}
              </span>
            </div>
            <span className="font-mono text-[10px] text-muted">FORMAT: {statsData.format}</span>
          </div>
        </div>
      )}
    </div>
  );
}
