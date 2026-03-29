"use client";

import Link from "next/link";
import { formatDistanceToNow, parseISO } from "date-fns";
import { trackEvent } from "@/lib/analytics";

interface Match {
  id: string;
  team1: string;
  team2: string;
  team1_short: string;
  team2_short: string;
  competition: string;
  format: string;
  status: string;
  match_start_utc: string;
  lock_time_utc?: string;
  xi_confirmed_at?: string | null;
  venue?: { id: string; name: string; city: string };
}

const STATUS_COLORS: Record<string, string> = {
  live: "text-accent animate-pulse-slow",
  upcoming: "text-warning",
  completed: "text-muted",
  abandoned: "text-danger",
};

function shortName(full: string, abbr: string | null): string {
  if (abbr) return abbr;
  return full.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 4);
}

export default function MatchCard({ match }: { match: Match }) {
  const statusClass = STATUS_COLORS[match.status] ?? "text-muted";
  const t1 = shortName(match.team1, match.team1_short);
  const t2 = shortName(match.team2, match.team2_short);
  const startTime = match.match_start_utc
    ? formatDistanceToNow(parseISO(match.match_start_utc), { addSuffix: true })
    : "—";

  const xiConfirmed = !!match.xi_confirmed_at;
  const isLive = match.status === "live";

  return (
    <Link
      href={`/matches/${match.id}`}
      onClick={() =>
        trackEvent("match_card_clicked", {
          match_id: match.id,
          team1: match.team1,
          team2: match.team2,
          xi_status: match.xi_confirmed_at ? "confirmed" : "pending",
        })
      }
    >
      <div className="border border-border rounded p-4 hover:border-accent/40 transition-colors cursor-pointer space-y-2 min-h-[44px]">
        <div className="flex items-center justify-between">
          <span className="font-mono text-white font-semibold text-base">
            {t1}{" "}
            <span className="text-muted text-sm">vs</span>{" "}
            {t2}
          </span>
          <div className="flex items-center gap-2">
            {isLive && (
              <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse" />
            )}
            <span className={`font-mono text-xs uppercase ${statusClass}`}>
              {match.status}
            </span>
          </div>
        </div>

        <div className="font-mono text-muted text-xs truncate">
          {match.competition}
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <span className="font-mono text-xs bg-surface-2 text-info px-2 py-0.5 rounded">
            {match.format}
          </span>
          <span className="font-mono text-xs text-muted">{startTime}</span>
          {match.venue?.city && (
            <span className="font-mono text-xs text-muted">
              {match.venue.city}
            </span>
          )}
          {xiConfirmed && (
            <span className="font-mono text-[10px] text-accent border border-accent/30 px-1.5 py-0.5 rounded">
              XI SET
            </span>
          )}
          {!xiConfirmed && match.status === "upcoming" && (
            <span className="font-mono text-[10px] text-muted border border-border px-1.5 py-0.5 rounded">
              AWAITING XI
            </span>
          )}
        </div>
      </div>
    </Link>
  );
}
