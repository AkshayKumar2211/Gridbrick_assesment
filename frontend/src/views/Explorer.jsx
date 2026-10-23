import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, Notice, SERIES, StatTile, TooltipBox, axisProps, gridProps, useDebounced } from "../components/ui.jsx";
import { fmtCompact, fmtDayTime, fmtMW, fmtSignedMW, fmtTime, fmtUkDay, toUkInputValue } from "../lib/format.js";
import { useApi } from "../lib/useApi.js";

const DAY_MS = 24 * 3600 * 1000;

function ExplorerTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  return (
    <TooltipBox
      title={`${fmtDayTime(row.t)} (UK)`}
      rows={[
        { label: "Actual", value: fmtMW(row.actual), color: SERIES.actual },
        ...(row.forecast != null ? [{ label: "Forecast", value: fmtMW(row.forecast), color: SERIES.forecast }] : []),
      ]}
      note={row.publish_time ? `Forecast published ${fmtDayTime(row.publish_time)} · ${row.horizon_h} h ahead` : null}
    />
  );
}

export default function Explorer({ meta }) {
  const scopeStart = Date.parse(meta.scope.start);
  const scopeEnd = Date.parse(meta.scope.end);
  const presets = useMemo(() => {
    const weeks = [];
    for (let i = 0; scopeStart + i * 7 * DAY_MS < scopeEnd; i++) {
      const s = scopeStart + i * 7 * DAY_MS;
      weeks.push({ label: `Week ${i + 1}`, start: s, end: Math.min(s + 7 * DAY_MS, scopeEnd) });
    }
    return [...weeks, { label: "Whole period", start: scopeStart, end: scopeEnd }];
  }, [scopeStart, scopeEnd]);

  const [range, setRange] = useState({ start: toUkInputValue(presets[0].start), end: toUkInputValue(presets[0].end) });
  const [horizon, setHorizon] = useState(4);
  const debouncedHorizon = useDebounced(horizon);
  const valid = range.start && range.end && range.start < range.end;

  const { data, error, loading } = useApi(
    "/api/explorer",
    valid ? { start: range.start, end: range.end, horizon_hours: debouncedHorizon } : null,
  );

  const rows = useMemo(
    () => (data?.points ?? []).map((p) => ({ ...p, t: Date.parse(p.time) })),
    [data],
  );
  const days = rows.length ? (rows[rows.length - 1].t - rows[0].t) / DAY_MS : 0;
  // Ticks on UK midnights (or every 6 h for short ranges), thinned to at most ~10.
  const ticks = useMemo(() => {
    const stepHours = days > 2 ? 24 : 6;
    const candidates = rows
      .filter((r) => {
        const [h, m] = fmtTime(r.t).split(":").map(Number);
        return m === 0 && h % stepHours === 0;
      })
      .map((r) => r.t);
    const every = Math.max(1, Math.ceil(candidates.length / 10));
    return candidates.filter((_, i) => i % every === 0);
  }, [rows, days]);
  const m = data?.metrics;
  const meanLead = useMemo(() => {
    const h = rows.map((r) => r.horizon_h).filter((v) => v != null);
    return h.length ? (h.reduce((a, b) => a + b, 0) / h.length).toFixed(1) : null;
  }, [rows]);

  return (
    <div className="view">
      <div className="view-head">
        <h1>Explorer</h1>
        <p>
          Compare actual wind with the latest forecast that was at least <em>N</em> hours old at each target hour.
          Slide the lead time to see how forecasts degrade the further ahead they look.
        </p>
      </div>

      <div className="filters">
        <label className="field">
          <span>From (UK)</span>
          <input
            className="input"
            type="datetime-local"
            value={range.start}
            min={toUkInputValue(scopeStart)}
            max={toUkInputValue(scopeEnd)}
            onChange={(e) => setRange((r) => ({ ...r, start: e.target.value }))}
          />
        </label>
        <label className="field">
          <span>To (UK)</span>
          <input
            className="input"
            type="datetime-local"
            value={range.end}
            min={toUkInputValue(scopeStart)}
            max={toUkInputValue(scopeEnd)}
            onChange={(e) => setRange((r) => ({ ...r, end: e.target.value }))}
          />
        </label>
        <div className="field">
          <span>Quick ranges</span>
          <div className="chips">
            {presets.map((p) => {
              const value = { start: toUkInputValue(p.start), end: toUkInputValue(p.end) };
              return (
                <button
                  key={p.label}
                  type="button"
                  className="chip"
                  aria-pressed={range.start === value.start && range.end === value.end}
                  onClick={() => setRange(value)}
                >
                  {p.label}
                </button>
              );
            })}
          </div>
        </div>
        <label className="field">
          <span>Minimum forecast lead time</span>
          <div className="range">
            <input
              type="range"
              min={0}
              max={meta.max_horizon_hours}
              step={1}
              value={horizon}
              onChange={(e) => setHorizon(Number(e.target.value))}
            />
            <output>{horizon} h</output>
          </div>
        </label>
      </div>

      {!valid && <Notice kind="error">Choose a start before the end.</Notice>}
      {error && <Notice kind="error">{error.message}</Notice>}
      {!data && loading && <Notice busy>Loading…</Notice>}

      {data && (
        <>
          <div className="tiles">
            <StatTile label="Mean absolute error" value={fmtMW(m.mae)} sub={<>WAPE {m.wape_pct ?? "–"}%</>} />
            <StatTile label="Bias (mean error)" value={fmtSignedMW(m.bias)} sub="Positive = forecast too high" />
            <StatTile label="RMSE" value={fmtMW(m.rmse)} sub={<>Correlation r = {m.correlation ?? "–"}</>} />
            <StatTile label="Mean lead time used" value={meanLead ? `${meanLead} h` : "–"} sub={<>{m.n} hours compared</>} />
          </div>

          <Card
            title="Actual vs forecast (MW)"
            subtitle={`Forecast = latest published at least ${data.horizon_hours} h before each hour. Actuals are half-hourly; forecasts are hourly.`}
            legend={[
              { label: "Actual outturn", color: SERIES.actual },
              { label: `Forecast (≥ ${data.horizon_hours} h ahead)`, color: SERIES.forecast },
            ]}
            stale={loading}
            csvName="winddesk-explorer.csv"
            table={{
              rows,
              columns: [
                { key: "t", label: "Time (UK)", format: fmtDayTime },
                { key: "actual", label: "Actual MW" },
                { key: "forecast", label: "Forecast MW", format: (v) => v ?? "–" },
                { key: "publish_time", label: "Forecast published", format: (v) => (v ? fmtDayTime(v) : "–") },
                { key: "horizon_h", label: "Lead h", format: (v) => v ?? "–" },
              ],
            }}
          >
            <ResponsiveContainer width="100%" height={380}>
              <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid {...gridProps} />
                <XAxis
                  {...axisProps}
                  dataKey="t"
                  type="number"
                  scale="time"
                  domain={["dataMin", "dataMax"]}
                  ticks={ticks}
                  tickFormatter={(t) => (days > 2 ? fmtUkDay(t) : fmtDayTime(t))}
                />
                <YAxis {...axisProps} width={44} axisLine={false} tickFormatter={fmtCompact} />
                <Tooltip content={<ExplorerTooltip />} cursor={{ stroke: "var(--axis)" }} />
                <Line dataKey="forecast" stroke={SERIES.forecast} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
                <Line dataKey="actual" stroke={SERIES.actual} strokeWidth={2} dot={false} connectNulls isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </Card>
        </>
      )}
    </div>
  );
}
