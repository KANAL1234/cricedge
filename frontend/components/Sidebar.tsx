"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { differenceInMinutes, parseISO } from "date-fns";
import { useMatchStore, useUIStore } from "@/lib/store";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

const cn = (...args: any[]) => twMerge(clsx(args));

function MatchCountdown({ match }: { match: any }) {
  const xiUpdates = useMatchStore((s) => s.xiUpdates);
  const xiConfirmed = match.xi_confirmed_at || xiUpdates[match.id];

  if (match.status === "live") {
    return (
      <span className="flex items-center gap-1 font-mono text-[10px] text-danger">
        <span className="w-1.5 h-1.5 rounded-full bg-danger animate-pulse" />
        LIVE
      </span>
    );
  }

  if (match.status === "completed") {
    return (
      <span className="font-mono text-[10px] text-muted">COMPLETED</span>
    );
  }

  const lockTime = match.lock_time_utc
    ? parseISO(match.lock_time_utc)
    : null;
  const startTime = parseISO(match.match_start_utc);
  const refTime = lockTime ?? startTime;
  const minsToLock = differenceInMinutes(refTime, new Date());

  if (minsToLock < 0) {
    return <span className="font-mono text-[10px] text-danger">LOCKED</span>;
  }

  if (minsToLock < 30) {
    return (
      <span className="font-mono text-[10px] text-danger animate-pulse-slow">
        LOCKED
      </span>
    );
  }

  const h = Math.floor(minsToLock / 60);
  const m = minsToLock % 60;
  const timeStr = h > 0 ? `${h}:${String(m).padStart(2, "0")}` : `${m}M`;

  return (
    <span className="font-mono text-[10px] text-muted">
      XI IN {timeStr}
    </span>
  );
}

export default function Sidebar() {
  const { matches, fetchMatches } = useMatchStore();
  const { sidebarOpen, toggleSidebar } = useUIStore();
  const router = useRouter();
  const xiUpdates = useMatchStore((s) => s.xiUpdates);

  useEffect(() => {
    fetchMatches();
  }, [fetchMatches]);

  const visibleMatches = matches.filter(
    (m) => m.status === "upcoming" || m.status === "live"
  );

  const sidebarContent = (
    <div className="flex flex-col h-full scrollbar-terminal overflow-y-auto">
      <div className="px-3 pt-3 pb-2">
        <span className="font-mono text-[10px] text-muted tracking-widest">
          UPCOMING
        </span>
      </div>

      {visibleMatches.length === 0 && (
        <div className="px-3 py-2 font-mono text-[10px] text-muted">
          NO MATCHES
        </div>
      )}

      {visibleMatches.map((match) => {
        const xiConfirmed = match.xi_confirmed_at || xiUpdates[match.id];
        return (
          <button
            key={match.id}
            className="text-left w-full px-3 py-2 border-b border-border/50 bg-surface hover:bg-surface-2 cursor-pointer transition-colors min-h-[44px]"
            onClick={() => {
              router.push(`/matches/${match.id}`);
              if (sidebarOpen) toggleSidebar();
            }}
          >
            <div className="font-mono text-xs text-white font-semibold">
              {match.team1_short} vs {match.team2_short}
            </div>
            <div className="flex items-center justify-between mt-0.5">
              <MatchCountdown match={match} />
              {xiConfirmed && (
                <span className="font-mono text-[10px] text-accent">
                  XI SET
                </span>
              )}
            </div>
          </button>
        );
      })}
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden md:block w-[220px] sticky top-12 h-[calc(100vh-3rem)] border-r border-border bg-background shrink-0">
        {sidebarContent}
      </aside>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div className="md:hidden fixed inset-0 z-50 flex">
          <div
            className="absolute inset-0 bg-background/80"
            onClick={toggleSidebar}
          />
          <aside className="relative w-[220px] bg-background border-r border-border h-full z-10 animate-in slide-in-from-left duration-200">
            {sidebarContent}
          </aside>
        </div>
      )}
    </>
  );
}
