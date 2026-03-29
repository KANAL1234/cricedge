"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import useSWR, { mutate } from "swr";
import { format, parseISO, differenceInSeconds } from "date-fns";
import { ChevronUp, ChevronDown, ArrowLeft } from "lucide-react";
import { toast } from "sonner";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

import { fetcher, api } from "@/lib/api";
import { trackEvent } from "@/lib/analytics";
import { subscribeToMatch, unsubscribeFromMatch } from "@/lib/socket";
import getSocket from "@/lib/socket";
// getSocket used for event listening; subscribeToMatch/unsubscribeFromMatch for room management
import { useMatchStore, useUIStore, usePlayerStore } from "@/lib/store";
import WeatherWidget from "@/components/WeatherWidget";
import { SkeletonRow } from "@/components/Skeleton";

const cn = (...args: any[]) => twMerge(clsx(args));
const toArr = (v: any): string[] => (Array.isArray(v) ? v : []);

function toIST(utcStr: string) {
  return new Date(utcStr).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    hour: "2-digit",
    minute: "2-digit",
    day: "numeric",
    month: "short",
  });
}

function RoleBadge({ role }: { role: string }) {
  const map: Record<string, { label: string; color: string }> = {
    BAT: { label: "B", color: "bg-info/20 text-info" },
    BOWL: { label: "P", color: "bg-warning/20 text-warning" },
    AR: { label: "A", color: "bg-accent/20 text-accent" },
    WK: { label: "K", color: "bg-danger/20 text-danger" },
  };
  const r = map[role] ?? { label: "?", color: "bg-surface-2 text-muted" };
  return (
    <span className={cn("font-mono text-[9px] px-1 py-0.5 rounded font-bold", r.color)}>
      {r.label}
    </span>
  );
}

function FormDots({ innings }: { innings: number[] }) {
  return (
    <div className="flex gap-0.5">
      {innings.slice(-5).map((pts, i) => (
        <span
          key={i}
          className={cn(
            "w-1.5 h-1.5 rounded-full inline-block",
            pts > 40 ? "bg-accent" : pts > 20 ? "bg-warning" : "bg-danger"
          )}
          title={`${pts} pts`}
        />
      ))}
    </div>
  );
}

function CountdownTimer({ targetUtc }: { targetUtc: string }) {
  const [secs, setSecs] = useState(() =>
    differenceInSeconds(parseISO(targetUtc), new Date())
  );

  useEffect(() => {
    const iv = setInterval(() => {
      setSecs(differenceInSeconds(parseISO(targetUtc), new Date()));
    }, 1000);
    return () => clearInterval(iv);
  }, [targetUtc]);

  if (secs <= 0) return <span className="text-danger font-mono text-xs">LOCKED</span>;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  return (
    <span className="font-mono text-warning text-2xl font-bold tracking-widest">
      {h > 0 ? `${h}:` : ""}
      {String(m).padStart(2, "0")}:{String(s).padStart(2, "0")}
    </span>
  );
}

type SortDir = "asc" | "desc";

export default function MatchPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { markXIConfirmed } = useMatchStore();
  const { contestType, setContestType } = useUIStore();
  const { players, fetchPlayer } = usePlayerStore();

  const [sortCol, setSortCol] = useState<string>("predicted_ownership_pct");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  const matchSWRKey = id ? `/matches/${id}` : null;
  const { data: match, isLoading: matchLoading } = useSWR(matchSWRKey, fetcher, {
    refreshInterval: 30_000,
  });

  const isCompleted = match?.status === "completed";
  const xiConfirmed = !!match?.xi_confirmed_at || isCompleted;

  const { data: ownershipData } = useSWR(
    xiConfirmed ? `/predictions/match/${id}/ownership` : null,
    fetcher,
    { refreshInterval: 60_000 }
  );
  const { data: captainData } = useSWR(
    xiConfirmed ? `/predictions/match/${id}/captain?contest_type=${contestType}` : null,
    fetcher,
    { refreshInterval: 60_000 }
  );
  const { data: diffData } = useSWR(
    xiConfirmed ? `/predictions/match/${id}/differential` : null,
    fetcher,
    { refreshInterval: 60_000 }
  );

  // Track page view when match data loads
  useEffect(() => {
    if (!match) return;
    trackEvent("match_detail_viewed", {
      match_id: id,
      team1: match.team1,
      team2: match.team2,
      format: match.format,
    });
  }, [id, match?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Socket.io subscription
  useEffect(() => {
    if (!id) return;
    const s = getSocket();
    subscribeToMatch(id);

    const onXI = (data: { match_id: string; team: string }) => {
      if (data.match_id === id) {
        markXIConfirmed(id, data.team);
        toast.success(`⚡ ${data.team} XI Confirmed`, {
          description: "Playing lineup is now available",
          duration: 5000,
        });
        mutate(matchSWRKey);
      }
    };

    s.on("xi_confirmed", onXI);
    return () => {
      s.off("xi_confirmed", onXI);
      unsubscribeFromMatch(id);
    };
  }, [id, markXIConfirmed, matchSWRKey]);

  // Pre-fetch player names for ownership list
  useEffect(() => {
    if (!ownershipData?.predictions) return;
    ownershipData.predictions.forEach((p: any) => {
      if (!players[p.player_id]) fetchPlayer(p.player_id);
    });
  }, [ownershipData, players, fetchPlayer]);

  // Pre-fetch captain player names
  useEffect(() => {
    if (!captainData) return;
    [...(captainData.captain ?? []), ...(captainData.vice_captain ?? [])].forEach(
      (r: any) => {
        if (r.player_id && !players[r.player_id]) fetchPlayer(r.player_id);
      }
    );
  }, [captainData, players, fetchPlayer]);

  function toggleSort(col: string) {
    if (sortCol === col) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortCol(col); setSortDir("desc"); }
  }

  function SortIcon({ col }: { col: string }) {
    if (sortCol !== col) return <ChevronDown size={10} className="text-border" />;
    return sortDir === "asc" ? (
      <ChevronUp size={10} className="text-accent" />
    ) : (
      <ChevronDown size={10} className="text-accent" />
    );
  }

  if (matchLoading && !match) {
    return (
      <div className="flex items-center justify-center h-64 font-mono text-muted text-sm animate-pulse">
        LOADING MATCH DATA...
      </div>
    );
  }

  if (!match) {
    return (
      <div className="flex items-center justify-center h-64 font-mono text-danger text-sm">
        MATCH NOT FOUND
      </div>
    );
  }

  const ownership: any[] = ownershipData?.predictions ?? [];
  const captains: any[] = captainData?.captain ?? [];
  const vcs: any[] = captainData?.vice_captain ?? [];
  const differentials: any[] = diffData?.differentials ?? [];

  // Combine playing XI with ownership for table
  const allPlayerIds = [
    ...toArr(match.playing_xi_team1),
    ...toArr(match.playing_xi_team2),
  ];

  const ownershipMap = Object.fromEntries(
    ownership.map((p: any) => [p.player_id, p])
  );

  // If XI not available, fall back to ownership predictions list (squad-based for completed matches)
  let tableRows = allPlayerIds.length > 0
    ? allPlayerIds.map((pid: string) => {
        const own = ownershipMap[pid];
        return {
          player_id: pid,
          name: own?.name ?? players[pid]?.name ?? pid.slice(0, 8) + "…",
          role: own?.role ?? players[pid]?.role ?? "?",
          dream11_price: own?.dream11_price ?? players[pid]?.dream11_price ?? 0,
          ...own,
        };
      })
    : ownership.map((p: any) => ({
        player_id: p.player_id,
        name: p.name ?? players[p.player_id]?.name ?? p.player_id.slice(0, 8) + "…",
        role: p.role ?? players[p.player_id]?.role ?? "?",
        dream11_price: p.dream11_price ?? players[p.player_id]?.dream11_price ?? 0,
        ...p,
      }));

  // Sort
  tableRows.sort((a, b) => {
    const av = a[sortCol] ?? 0;
    const bv = b[sortCol] ?? 0;
    if (typeof av === "string") return sortDir === "asc" ? av.localeCompare(bv) : bv.localeCompare(av);
    return sortDir === "asc" ? av - bv : bv - av;
  });

  const pitchType = match.venue_stats?.pitch_type?.toUpperCase() ?? "UNKNOWN";
  const pitchColor =
    pitchType === "BATTING" ? "text-accent border-accent/30 bg-accent/5"
    : pitchType === "BOWLING" ? "text-warning border-warning/30 bg-warning/5"
    : "text-info border-info/30 bg-info/5";

  const lockTarget =
    match.lock_time_utc ??
    (match.match_start_utc
      ? new Date(new Date(match.match_start_utc).getTime() - 30 * 60_000).toISOString()
      : null);

  function ownershipColor(pct: number) {
    if (pct < 20) return "text-accent";
    if (pct < 50) return "text-warning";
    return "text-danger";
  }

  function rowBorder(tier: string) {
    if (tier === "differential") return "border-l-2 border-l-accent";
    if (tier === "mid") return "border-l-2 border-l-warning";
    return "";
  }

  return (
    <div className="max-w-screen-xl mx-auto px-4 py-4 space-y-6">
      {/* Back */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-1 font-mono text-xs text-muted hover:text-white transition-colors"
      >
        <ArrowLeft size={12} /> BACK
      </button>

      {/* ── Match Header ── */}
      <div className="border border-border rounded p-4 space-y-2">
        <div className="flex items-start justify-between flex-wrap gap-2">
          <div>
            <div className="font-mono text-accent text-2xl font-bold leading-tight">
              {match.team1_short}{" "}
              <span className="text-muted text-base font-normal">vs</span>{" "}
              {match.team2_short}
            </div>
            <div className="font-mono text-muted text-xs mt-0.5">
              {match.team1} vs {match.team2}
            </div>
          </div>
          <div className="flex flex-wrap gap-2 items-center">
            {match.status === "live" && (
              <span className="flex items-center gap-1 font-mono text-xs text-danger border border-danger/30 px-2 py-0.5 rounded">
                <span className="w-1.5 h-1.5 rounded-full bg-danger animate-pulse" />
                LIVE
              </span>
            )}
            <span className="font-mono text-xs text-info border border-info/30 px-2 py-0.5 rounded">
              {match.format}
            </span>
            <span className="font-mono text-xs text-muted border border-border px-2 py-0.5 rounded">
              {match.status?.toUpperCase()}
            </span>
          </div>
        </div>
        <div className="flex flex-wrap gap-4 font-mono text-xs text-muted">
          {match.venue && (
            <span>
              📍 {match.venue.name}, {match.venue.city}
            </span>
          )}
          {match.match_start_utc && (
            <span>🕐 {toIST(match.match_start_utc)} IST</span>
          )}
          {lockTarget && !isCompleted && (
            <span className="text-danger">
              LOCK: {toIST(lockTarget)} IST
            </span>
          )}
        </div>
        <div className="flex flex-wrap gap-2 items-center font-mono text-xs text-muted">
          {match.competition && <span>{match.competition}</span>}
          {match.result && (
            <span className="text-accent font-semibold">· {match.result}</span>
          )}
        </div>
      </div>

      {/* ── Two Column Layout ── */}
      <div className="grid grid-cols-1 lg:grid-cols-[60%_40%] gap-4">
        {/* LEFT COLUMN */}
        <div className="space-y-4">
          {/* Weather */}
          {match.weather && Object.keys(match.weather).length > 0 && (
            <WeatherWidget matchId={id} weather={match.weather} />
          )}

          {/* Pitch Report */}
          {match.venue_stats && (
            <div className="border border-border rounded p-4 space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-muted tracking-widest">
                  PITCH REPORT
                </span>
                <span className={cn("font-mono text-xs border px-2 py-0.5 rounded", pitchColor)}>
                  {pitchType}
                </span>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <div className="font-mono text-[10px] text-muted mb-1">
                    PACE ({match.venue_stats.pace_wickets_pct?.toFixed(0)}%)
                  </div>
                  <div className="h-1.5 bg-surface-2 rounded overflow-hidden">
                    <div
                      className="h-full bg-accent rounded"
                      style={{ width: `${match.venue_stats.pace_wickets_pct ?? 50}%` }}
                    />
                  </div>
                </div>
                <div>
                  <div className="font-mono text-[10px] text-muted mb-1">
                    SPIN ({match.venue_stats.spin_wickets_pct?.toFixed(0)}%)
                  </div>
                  <div className="h-1.5 bg-surface-2 rounded overflow-hidden">
                    <div
                      className="h-full bg-info rounded"
                      style={{ width: `${match.venue_stats.spin_wickets_pct ?? 50}%` }}
                    />
                  </div>
                </div>
              </div>
              {match.venue_stats.dew_factor != null && (
                <div className="font-mono text-xs">
                  <span className="text-muted">DEW FACTOR: </span>
                  <span className={match.venue_stats.dew_factor > 0.6 ? "text-danger" : match.venue_stats.dew_factor > 0.4 ? "text-warning" : "text-muted"}>
                    {match.venue_stats.dew_factor > 0.6 ? "HIGH" : match.venue_stats.dew_factor > 0.4 ? "MED" : "LOW"}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Playing XI */}
          <div className="border border-border rounded p-4 space-y-3">
            <div className="font-mono text-xs text-muted tracking-widest">
              PLAYING XI
            </div>
            {!xiConfirmed ? (
              <div className="text-center py-8 space-y-3">
                <div className="font-mono text-muted text-sm">AWAITING LINEUP</div>
                {lockTarget && (
                  <div className="space-y-1">
                    <div className="font-mono text-[10px] text-muted">LOCK IN</div>
                    <CountdownTimer targetUtc={lockTarget} />
                  </div>
                )}
                <div className="font-mono text-[10px] text-muted">
                  XI drops ~30 min before match start
                </div>
              </div>
            ) : isCompleted && toArr(match.playing_xi_team1).length === 0 ? (
              <div className="text-center py-6">
                <div className="font-mono text-muted text-xs">XI data not captured for this match</div>
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                {/* Team 1 */}
                <div>
                  <div className="font-mono text-[10px] text-muted tracking-wider mb-2 pb-1 border-b border-border">
                    {match.team1_short}
                  </div>
                  <div className="space-y-1">
                    {toArr(match.playing_xi_team1).map((pid: string) => (
                      <div key={pid} className="flex items-center gap-1.5">
                        <RoleBadge role={players[pid]?.role ?? "BAT"} />
                        <span
                          className="font-mono text-xs text-white hover:text-accent cursor-pointer transition-colors truncate"
                          onClick={() => router.push(`/players/${pid}`)}
                        >
                          {players[pid]?.short_name ?? players[pid]?.name ?? pid.slice(0, 8) + "…"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
                {/* Team 2 */}
                <div>
                  <div className="font-mono text-[10px] text-muted tracking-wider mb-2 pb-1 border-b border-border">
                    {match.team2_short}
                  </div>
                  <div className="space-y-1">
                    {toArr(match.playing_xi_team2).map((pid: string) => (
                      <div key={pid} className="flex items-center gap-1.5">
                        <RoleBadge role={players[pid]?.role ?? "BAT"} />
                        <span
                          className="font-mono text-xs text-white hover:text-accent cursor-pointer transition-colors truncate"
                          onClick={() => router.push(`/players/${pid}`)}
                        >
                          {players[pid]?.short_name ?? players[pid]?.name ?? pid.slice(0, 8) + "…"}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* RIGHT COLUMN */}
        <div className="space-y-4">
          {/* Contest Type Toggle */}
          <div className="flex border border-border rounded overflow-hidden">
            {(["mega", "small"] as const).map((t) => (
              <button
                key={t}
                onClick={() => {
                  setContestType(t);
                  trackEvent("contest_type_toggled", { match_id: id, new_type: t === "mega" ? "differential" : "safe" });
                }}
                className={cn(
                  "flex-1 font-mono text-xs py-2 min-h-[44px] transition-colors",
                  contestType === t
                    ? "bg-accent text-background font-semibold"
                    : "text-muted hover:text-white"
                )}
              >
                {t === "mega" ? "MEGA CONTEST" : "SMALL LEAGUE"}
              </button>
            ))}
          </div>

          {/* Captain Picks */}
          <div className="border border-border rounded p-4 space-y-3">
            <div className="font-mono text-xs text-muted tracking-widest">
              CAPTAIN RECOMMENDATIONS
            </div>
            {isCompleted ? (
              <div className="font-mono text-muted text-xs py-2">
                Match completed — pre-match predictions no longer available
              </div>
            ) : !xiConfirmed ? (
              <div className="font-mono text-muted text-xs py-2">
                Available after XI confirmation
              </div>
            ) : captains.length === 0 ? (
              <div className="font-mono text-muted text-xs animate-pulse">Loading...</div>
            ) : (
              <>
                <div className="space-y-2">
                  <div className="font-mono text-[10px] text-accent tracking-wider">C PICKS</div>
                  {captains.slice(0, 3).map((rec: any, idx: number) => (
                    <div key={rec.player_id} className="flex items-center gap-2 bg-surface-2 rounded p-2">
                      <span className="font-mono text-muted text-xs w-4">{idx + 1}</span>
                      <div className="flex-1 min-w-0">
                        <div className="font-mono text-white text-xs truncate">
                          {players[rec.player_id]?.name ?? rec.player_id.slice(0, 12) + "…"}
                        </div>
                        <div className="h-1 bg-border rounded mt-1 overflow-hidden">
                          <div
                            className="h-full bg-accent rounded"
                            style={{ width: `${Math.min(rec.captain_score ?? 0, 100)}%` }}
                          />
                        </div>
                      </div>
                      <span className="font-mono text-muted text-[10px] shrink-0">
                        {(rec.predicted_ownership ?? 0).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
                <div className="space-y-2 pt-2 border-t border-border">
                  <div className="font-mono text-[10px] text-warning tracking-wider">VC PICKS</div>
                  {vcs.slice(0, 3).map((rec: any, idx: number) => (
                    <div key={rec.player_id} className="flex items-center gap-2 bg-surface-2 rounded p-2">
                      <span className="font-mono text-muted text-xs w-4">{idx + 1}</span>
                      <div className="flex-1 min-w-0">
                        <div className="font-mono text-white text-xs truncate">
                          {players[rec.player_id]?.name ?? rec.player_id.slice(0, 12) + "…"}
                        </div>
                        <div className="h-1 bg-border rounded mt-1 overflow-hidden">
                          <div
                            className="h-full bg-warning rounded"
                            style={{ width: `${Math.min(rec.captain_score ?? 0, 100)}%` }}
                          />
                        </div>
                      </div>
                      <span className="font-mono text-muted text-[10px] shrink-0">
                        {(rec.predicted_ownership ?? 0).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>

          {/* Differential Alerts */}
          {xiConfirmed && differentials.length > 0 && (
            <div className="border border-accent/30 bg-accent/5 rounded p-4 space-y-3">
              <div className="font-mono text-xs text-accent tracking-wider">
                ⚡ DIFFERENTIAL ALERTS
              </div>
              {differentials.slice(0, 2).map((d: any) => (
                <div
                  key={d.player_id}
                  className="space-y-1 pb-2 border-b border-accent/10 last:border-0 last:pb-0"
                >
                  <div className="flex items-center justify-between">
                    <span
                      className="font-mono text-white text-xs cursor-pointer hover:text-accent"
                      onClick={() => router.push(`/players/${d.player_id}`)}
                    >
                      {players[d.player_id]?.name ?? d.player_id.slice(0, 12) + "…"}
                    </span>
                    <span className="font-mono text-accent text-xs font-semibold">
                      {(d.predicted_ownership_pct ?? 0).toFixed(1)}%
                    </span>
                  </div>
                  {d.reasoning && (
                    <div className="font-mono text-muted text-[10px]">{d.reasoning}</div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Full Player Table ── */}
      {xiConfirmed && (
        <div className="space-y-3">
          <div className="font-mono text-xs text-muted tracking-widest">
            PLAYER COMPARISON
          </div>
          <div className="border border-border rounded overflow-x-auto scrollbar-terminal">
            <table className="w-full text-xs font-mono min-w-[640px]">
              <thead>
                <tr className="border-b border-border bg-surface">
                  {[
                    { key: "name", label: "PLAYER" },
                    { key: "role", label: "ROLE" },
                    { key: "dream11_price", label: "CR" },
                    { key: "predicted_ownership_pct", label: "OWN %" },
                    { key: "ownership_tier", label: "TIER" },
                  ].map(({ key, label }) => (
                    <th
                      key={key}
                      className="text-left px-3 py-2 text-muted tracking-wider cursor-pointer hover:text-white select-none"
                      onClick={() => toggleSort(key)}
                    >
                      <div className="flex items-center gap-1">
                        {label}
                        <SortIcon col={key} />
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {tableRows.length === 0
                  ? Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)
                  : tableRows.map((row) => (
                      <tr
                        key={row.player_id}
                        className={cn(
                          "border-b border-border/40 hover:bg-surface transition-colors",
                          rowBorder(row.ownership_tier)
                        )}
                      >
                        <td className="px-3 py-2">
                          <span
                            className="text-white hover:text-accent cursor-pointer transition-colors"
                            onClick={() => router.push(`/players/${row.player_id}`)}
                          >
                            {row.name}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <RoleBadge role={row.role} />
                        </td>
                        <td className="px-3 py-2 text-muted">
                          {row.dream11_price > 0 ? `${row.dream11_price.toFixed(1)}` : "—"}
                        </td>
                        <td className={cn("px-3 py-2 font-semibold", ownershipColor(row.predicted_ownership_pct ?? 0))}>
                          {row.predicted_ownership_pct != null
                            ? `${row.predicted_ownership_pct.toFixed(1)}%`
                            : "—"}
                        </td>
                        <td className="px-3 py-2">
                          {row.ownership_tier && (
                            <span className={cn(
                              "text-[10px] px-1.5 py-0.5 rounded border",
                              row.ownership_tier === "differential"
                                ? "text-accent border-accent/30 bg-accent/5"
                                : row.ownership_tier === "mid"
                                ? "text-info border-info/30 bg-info/5"
                                : "text-muted border-border"
                            )}>
                              {row.ownership_tier.toUpperCase()}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
