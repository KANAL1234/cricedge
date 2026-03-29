"use client";

import { useRouter } from "next/navigation";
import useSWR from "swr";
import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";
import { fetcher } from "@/lib/api";

const cn = (...args: any[]) => twMerge(clsx(args));

const PITCH_STYLES: Record<string, string> = {
  BATTING: "text-accent border-accent/30",
  BOWLING: "text-warning border-warning/30",
  BALANCED: "text-info border-info/30",
};

export default function VenuesPage() {
  const router = useRouter();
  const { data, isLoading } = useSWR("/venues?limit=50", fetcher);
  const venues = data?.data ?? [];

  return (
    <div className="max-w-screen-xl mx-auto px-4 py-6 space-y-4">
      <div className="flex items-center gap-3">
        <span className="font-mono text-accent text-xs font-bold tracking-[0.2em]">
          VENUES
        </span>
        <div className="h-px w-24 bg-border" />
      </div>

      {isLoading && venues.length === 0 ? (
        <div className="font-mono text-muted text-sm animate-pulse">LOADING VENUES...</div>
      ) : venues.length === 0 ? (
        <div className="border border-border rounded p-8 text-center font-mono text-muted text-sm">
          NO VENUES FOUND
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {venues.map((v: any) => {
            const pitchType = v.pitch_type?.toUpperCase() ?? "BALANCED";
            const pitchStyle = PITCH_STYLES[pitchType] ?? PITCH_STYLES.BALANCED;
            return (
              <button
                key={v.id}
                className="text-left border border-border rounded p-4 hover:border-accent/30 transition-colors bg-surface min-h-[44px] space-y-2"
                onClick={() => router.push(`/venues/${v.id}`)}
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="font-mono text-white font-semibold text-sm">{v.name}</div>
                  <span className={cn("font-mono text-[10px] border px-1.5 py-0.5 rounded shrink-0", pitchStyle)}>
                    {pitchType}
                  </span>
                </div>
                <div className="font-mono text-muted text-xs">
                  {v.city}{v.country ? `, ${v.country}` : ""}
                </div>
                {(v.avg_first_innings_score_t20 > 0) && (
                  <div className="font-mono text-xs text-muted">
                    T20 AVG:{" "}
                    <span className="text-accent">{v.avg_first_innings_score_t20?.toFixed(0)}</span>
                    {" "}/ {v.avg_second_innings_score_t20?.toFixed(0) ?? "—"}
                  </div>
                )}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
