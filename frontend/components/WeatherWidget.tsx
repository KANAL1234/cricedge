interface WeatherData {
  temp_c?: number;
  condition?: string;
  humidity?: number;
  wind_kph?: number;
  rain_chance?: number;
}

export default function WeatherWidget({
  matchId,
  weather,
}: {
  matchId: string;
  weather: WeatherData;
}) {
  if (!weather || Object.keys(weather).length === 0) return null;

  const rows = [
    { label: "TEMP", value: weather.temp_c !== undefined ? `${weather.temp_c}°C` : null },
    { label: "HUMIDITY", value: weather.humidity !== undefined ? `${weather.humidity}%` : null },
    { label: "WIND", value: weather.wind_kph !== undefined ? `${weather.wind_kph} kph` : null },
    { label: "RAIN CHANCE", value: weather.rain_chance !== undefined ? `${weather.rain_chance}%` : null },
  ].filter((r) => r.value !== null);

  const rainRisk = (weather.rain_chance ?? 0) > 40;

  return (
    <div className="border border-border rounded p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="font-mono text-sm text-muted tracking-widest">WEATHER</span>
        {rainRisk && (
          <span className="font-mono text-xs text-danger animate-pulse-slow">
            ⚠ RAIN RISK
          </span>
        )}
      </div>

      {weather.condition && (
        <div className="font-mono text-white text-sm">{weather.condition}</div>
      )}

      <div className="grid grid-cols-2 gap-2">
        {rows.map((row) => (
          <div key={row.label} className="space-y-0.5">
            <div className="font-mono text-[10px] text-muted">{row.label}</div>
            <div className="font-mono text-white text-sm font-semibold">{row.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
