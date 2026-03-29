"use client";

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

interface FormData {
  innings: Array<{
    PlayerInnings: {
      runs: number;
      wickets: number;
      dream11_points: number;
    };
  }>;
  games: number;
}

export default function PlayerFormCard({
  playerId,
  form,
}: {
  playerId: string;
  form: FormData;
}) {
  const chartData = form.innings
    .map((row, i) => ({
      game: `G${form.innings.length - i}`,
      points: row.PlayerInnings?.dream11_points ?? 0,
      runs: row.PlayerInnings?.runs ?? 0,
    }))
    .reverse();

  const avgPoints =
    chartData.reduce((s, d) => s + d.points, 0) / Math.max(chartData.length, 1);

  return (
    <div className="border border-border rounded p-4 space-y-4">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm text-muted tracking-widest">
          FORM (LAST {form.games} GAMES)
        </span>
        <span className="font-mono text-accent text-sm font-semibold">
          AVG {avgPoints.toFixed(1)} PTS
        </span>
      </div>

      <ResponsiveContainer width="100%" height={120}>
        <LineChart data={chartData}>
          <XAxis
            dataKey="game"
            tick={{ fontSize: 10, fill: "#8B949E", fontFamily: "IBM Plex Mono" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis hide />
          <Tooltip
            contentStyle={{
              background: "#0D1117",
              border: "1px solid #21262D",
              borderRadius: 4,
              fontFamily: "IBM Plex Mono",
              fontSize: 11,
            }}
            labelStyle={{ color: "#8B949E" }}
            itemStyle={{ color: "#00FF88" }}
          />
          <Line
            type="monotone"
            dataKey="points"
            stroke="#00FF88"
            strokeWidth={2}
            dot={{ fill: "#00FF88", r: 3 }}
            activeDot={{ r: 5 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
