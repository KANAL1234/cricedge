const TIER_COLORS: Record<string, string> = {
  safe: "bg-warning",
  mid: "bg-info",
  differential: "bg-accent",
};

const TIER_LABELS: Record<string, string> = {
  safe: "SAFE",
  mid: "MID",
  differential: "DIFF",
};

interface OwnershipPlayer {
  player_id: string;
  predicted_ownership_pct: number;
  ownership_tier: "safe" | "mid" | "differential";
  ev_score?: number;
}

export default function OwnershipBar({ player }: { player: OwnershipPlayer }) {
  const barColor = TIER_COLORS[player.ownership_tier] ?? "bg-muted";
  const tierLabel =
    TIER_LABELS[player.ownership_tier] ??
    player.ownership_tier.toUpperCase();
  const pct = player.predicted_ownership_pct ?? 0;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between font-mono text-xs">
        <span className="text-white truncate max-w-[120px]">
          {player.player_id.slice(0, 8)}…
        </span>
        <div className="flex items-center gap-3">
          {player.ev_score != null && (
            <span className="text-muted">EV {player.ev_score.toFixed(0)}</span>
          )}
          <span
            className={`px-1.5 py-0.5 rounded text-[10px] font-semibold ${
              player.ownership_tier === "differential"
                ? "bg-accent/10 text-accent"
                : player.ownership_tier === "mid"
                ? "bg-info/10 text-info"
                : "bg-warning/10 text-warning"
            }`}
          >
            {tierLabel}
          </span>
          <span className="text-white font-semibold w-12 text-right">
            {pct.toFixed(1)}%
          </span>
        </div>
      </div>

      <div className="h-1.5 bg-surface-2 rounded overflow-hidden">
        <div
          className={`h-full rounded transition-all duration-500 ${barColor}`}
          style={{ width: `${Math.min(pct, 100)}%` }}
        />
      </div>
    </div>
  );
}
