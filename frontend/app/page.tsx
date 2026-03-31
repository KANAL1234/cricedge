"use client";

import { useEffect } from "react";
import { differenceInHours, parseISO } from "date-fns";
import useSWR from "swr";
import Link from "next/link";
import { useMatchStore } from "@/lib/store";
import { fetcher } from "@/lib/api";
import MatchCard from "@/components/MatchCard";
import { SkeletonCard, SkeletonRow } from "@/components/Skeleton";
import { trackEvent } from "@/lib/analytics";

function ownershipColor(pct: number) {
  if (pct < 20) return "text-accent";
  if (pct < 50) return "text-warning";
  return "text-danger";
}

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 mb-4">
      <span className="font-mono text-accent text-xs font-bold tracking-[0.2em]">
        {label}
      </span>
      <div className="flex-1 h-px bg-border" />
    </div>
  );
}

export default function DashboardPage() {
  const { matches, fetchMatches, isLoading, xiUpdates } = useMatchStore();

  useEffect(() => {
    fetchMatches();
    const iv = setInterval(fetchMatches, 30_000);
    trackEvent("page_viewed", { page: "dashboard" });
    return () => clearInterval(iv);
  }, [fetchMatches]);

  const now = new Date();
  const todayMatches = matches.filter((m) => {
    if (!m.match_start_utc) return false;
    if (m.status === "completed") return false;
    const diff = differenceInHours(parseISO(m.match_start_utc), now);
    return diff >= -2 && diff <= 48;
  });

  const soonestUpcoming =
    matches.find((m) => m.status === "upcoming" && m.xi_confirmed_at) ??
    matches.find((m) => m.status === "upcoming");

  const { data: diffData } = useSWR(
    soonestUpcoming?.id
      ? `/predictions/match/${soonestUpcoming.id}/differential`
      : null,
    fetcher,
    { refreshInterval: 60_000 }
  );

  const completedMatches = matches.filter((m) => m.status === "completed");
  const tickerParts: string[] = [
    ...completedMatches
      .slice(0, 4)
      .map((m) => `${m.team1_short} vs ${m.team2_short} · COMPLETED`),
    ...Object.keys(xiUpdates).map((mid) => {
      const m = matches.find((x) => x.id === mid);
      return m ? `⚡ ${m.team1_short} XI CONFIRMED` : "";
    }),
    ...matches
      .filter((m) => m.status === "live")
      .map((m) => `● LIVE — ${m.team1_short} vs ${m.team2_short}`),
  ].filter(Boolean);
  const tickerContent =
    tickerParts.length > 0
      ? tickerParts.join("  ·  ")
      : "CRICEDGE TERMINAL  ·  FANTASY CRICKET INTELLIGENCE  ·  DATA-DRIVEN PICKS  ·  OWNERSHIP EDGE";

  const differentials = diffData?.differentials ?? [];

  return (
    <div className="max-w-screen-xl mx-auto px-4 py-6 space-y-10">
      {/* ── Section 1: Today's Matches ── */}
      <section>
        <SectionHeader label="TODAY'S MATCHES" />
        {isLoading && todayMatches.length === 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <SkeletonCard />
            <SkeletonCard />
            <SkeletonCard />
          </div>
        ) : todayMatches.length === 0 ? (
          <div className="border border-border rounded p-6 text-center font-mono text-muted text-sm">
            NO MATCHES IN THE NEXT 48 HOURS
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {todayMatches.map((m) => (
              <MatchCard key={m.id} match={m} />
            ))}
          </div>
        )}
      </section>

      {/* ── Section 2: Top Differentials ── */}
      <section>
        <SectionHeader label="TOP DIFFERENTIALS TODAY" />
        {!soonestUpcoming ? (
          <div className="border border-border rounded p-4 font-mono text-muted text-sm">
            NO UPCOMING MATCHES
          </div>
        ) : !soonestUpcoming.xi_confirmed_at ? (
          <div className="border border-warning/30 bg-warning/5 rounded p-4">
            <span className="font-mono text-warning text-sm">
              ⏳ AWAITING XI CONFIRMATION
            </span>
            <span className="font-mono text-muted text-xs ml-2">
              — differentials available after lineup drop
            </span>
          </div>
        ) : !diffData ? (
          <div className="space-y-2">
            <SkeletonRow />
            <SkeletonRow />
            <SkeletonRow />
          </div>
        ) : differentials.length === 0 ? (
          <div className="border border-border rounded p-4 font-mono text-muted text-sm">
            NO DIFFERENTIALS AVAILABLE YET
          </div>
        ) : (
          <div className="border border-border rounded overflow-hidden">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="border-b border-border bg-surface">
                  <th className="text-left px-4 py-2 text-muted tracking-wider">
                    PLAYER
                  </th>
                  <th className="text-left px-4 py-2 text-muted tracking-wider hidden sm:table-cell">
                    TIER
                  </th>
                  <th className="text-right px-4 py-2 text-muted tracking-wider">
                    OWN %
                  </th>
                  <th className="text-left px-4 py-2 text-muted tracking-wider hidden md:table-cell">
                    WHY
                  </th>
                </tr>
              </thead>
              <tbody>
                {differentials.map((d: any) => (
                  <tr
                    key={d.player_id}
                    className="border-b border-border/50 hover:bg-surface transition-colors"
                  >
                    <td className="px-4 py-3">
                      <Link
                        href={`/players/${d.player_id}`}
                        className="text-white hover:text-accent transition-colors"
                      >
                        {d.name ?? d.short_name ?? `${d.player_id?.slice(0, 8)}…`}
                      </Link>
                    </td>
                    <td className="px-4 py-3 hidden sm:table-cell">
                      <span className="text-accent border border-accent/30 px-1.5 py-0.5 rounded text-[10px]">
                        {d.ownership_tier?.toUpperCase() ?? "DIFF"}
                      </span>
                    </td>
                    <td
                      className={`px-4 py-3 text-right font-semibold ${ownershipColor(d.predicted_ownership_pct ?? 0)}`}
                    >
                      {(d.predicted_ownership_pct ?? 0).toFixed(1)}%
                    </td>
                    <td className="px-4 py-3 text-muted hidden md:table-cell max-w-xs truncate">
                      {d.reasoning ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* ── Section 3: Ticker ── */}
      <div className="border-y border-border -mx-4 overflow-hidden bg-surface">
        <div className="py-2 overflow-hidden">
          <div className="ticker-scroll inline-block whitespace-nowrap">
            <span className="font-mono text-[11px] text-muted px-8">
              {tickerContent}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{tickerContent}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
