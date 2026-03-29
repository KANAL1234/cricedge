"use client";

import { useEffect } from "react";
import { useMatchStore } from "@/lib/store";
import MatchCard from "@/components/MatchCard";
import { SkeletonCard } from "@/components/Skeleton";

const STATUS_ORDER: Record<string, number> = {
  live: 0,
  upcoming: 1,
  completed: 2,
  abandoned: 3,
};

export default function MatchesPage() {
  const { matches, fetchMatches, isLoading } = useMatchStore();

  useEffect(() => {
    fetchMatches();
    const iv = setInterval(fetchMatches, 30_000);
    return () => clearInterval(iv);
  }, [fetchMatches]);

  const sorted = [...matches].sort(
    (a, b) =>
      (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9)
  );

  return (
    <div className="max-w-screen-xl mx-auto px-4 py-6 space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-mono text-accent text-xs font-bold tracking-[0.2em]">
            MATCHES
          </span>
          <div className="h-px w-24 bg-border" />
        </div>
        <span className="font-mono text-muted text-[10px] animate-pulse-slow">
          ● REFRESH 30s
        </span>
      </div>

      {isLoading && sorted.length === 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : sorted.length === 0 ? (
        <div className="border border-border rounded p-8 text-center font-mono text-muted text-sm">
          NO MATCHES FOUND
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {sorted.map((m) => (
            <MatchCard key={m.id} match={m} />
          ))}
        </div>
      )}
    </div>
  );
}
