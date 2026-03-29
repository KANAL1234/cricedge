"use client";

import { useState } from "react";

interface CaptainRec {
  player_id: string;
  predicted_ownership: number;
  ev_score: number;
  captain_score: number;
  rationale: string;
  tier: string;
}

interface CaptainPickerProps {
  recommendations: {
    captain: CaptainRec[];
    vice_captain: CaptainRec[];
    contest_type: string;
  };
}

export default function CaptainPicker({ recommendations }: CaptainPickerProps) {
  const [tab, setTab] = useState<"captain" | "vice_captain">("captain");
  const list = tab === "captain" ? recommendations.captain : recommendations.vice_captain;

  return (
    <div className="border border-border rounded p-4 space-y-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm text-muted tracking-widest">
          C/VC PICKS — {recommendations.contest_type.toUpperCase()} CONTEST
        </span>
        <div className="flex border border-border rounded overflow-hidden">
          {(["captain", "vice_captain"] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`font-mono text-xs px-3 py-1 transition-colors ${
                tab === t
                  ? "bg-accent text-background font-semibold"
                  : "text-muted hover:text-white"
              }`}
            >
              {t === "captain" ? "C" : "VC"}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-3">
        {list.slice(0, 3).map((rec, idx) => (
          <div
            key={rec.player_id}
            className="flex items-center gap-3 p-3 bg-surface-2 rounded"
          >
            <span className="font-mono text-2xl text-border font-bold w-6 text-center">
              {idx + 1}
            </span>
            <div className="flex-1 min-w-0">
              <div className="font-mono text-white text-sm font-semibold truncate">
                {rec.player_id.slice(0, 8)}…
              </div>
              <div className="font-mono text-muted text-xs truncate">{rec.rationale}</div>
            </div>
            <div className="text-right shrink-0">
              <div className="font-mono text-accent text-sm font-semibold">
                {rec.captain_score.toFixed(0)}
              </div>
              <div className="font-mono text-muted text-[10px]">SCORE</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
