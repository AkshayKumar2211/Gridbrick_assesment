import { useMemo, useState } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, Notice, SERIES, StatTile, TooltipBox, axisProps, gridProps } from "../components/ui.jsx";
import {
  addDays,
  fmtCompact,
  fmtDate,
  fmtDayTime,
  fmtDuration,
  fmtGWh,
  fmtMW,
  fmtSignedGWh,
  fmtTime,
} from "../lib/format.js";
import { useApi } from "../lib/useApi.js";

const HOUR_MS = 3600 * 1000;

function DayTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const row = payload[0].payload;
  const rows = [
    { label: "Actual", value: fmtMW(row.actual), color: SERIES.actual },
    row.forecast != null && { label: "Forecast", value: fmtMW(row.forecast), color: SERIES.forecast },
    row.adjusted != null && { label: "Bias-adjusted", value: fmtMW(row.adjusted), color: SERIES.adjusted },
    row.band && { label: "10–90% range", value: `${fmtCompact(row.band[0])}–${fmtCompact(row.band[1])} MW` },
  ].filter(Boolean);
  return <TooltipBox title={`${fmtDayTime(row.t)} (UK)`} rows={rows} />;
}

function headline(data) {
  const s = data.summary;
  if (!s.actual_complete || s.energy_error_mwh == null) return null;
  const hours = data.points.filter((p) => p.forecast != null && p.actual != null);
  const short = hours.filter((p) => p.forecast > p.actual).length;
  const adjustedGap = Math.abs(s.adjusted_energy_mwh - s.actual_energy_mwh);
  const rawGap = Math.abs(s.energy_error_mwh);
  const better = s.adjusted_energy_mwh != null && adjustedGap < rawGap;
  const direction =
    s.energy_error_mwh > 0
      ? `Wind came in ${fmtGWh(rawGap)} below the day-ahead forecast. Buying to the raw forecast would have left the desk short in ${short} of ${hours.length} hours.`
      : `Wind came in ${fmtGWh(rawGap)} above the day-ahead forecast. Buying to the raw forecast would have left the desk long in ${hours.length - short} of ${hours.length} hours.`;
  const adjusted = better
    ? ` The bias-adjusted forecast was ${fmtGWh(rawGap - adjustedGap)} closer.`
    : s.adjusted_energy_mwh != null
      ? " The bias-adjusted forecast did not help on this day."
      : "";
  return { text: direction + adjusted, good: better };
}

export default function DayAhead({ meta }) {
  const first = meta.delivery_dates.from;
  const last = meta.delivery_dates.to;
  const [date, setDate] = useState(last);
  const [decisionTime, setDecisionTime] = useState(meta.default_decision_time);
  const [showVintages, setShowVintages] = useState(false);
  const latestDecision = `${String(meta.delivery_day_start_hour - 1).padStart(2, "0")}:59`;

  const params = /^\d\d:\d\d$/.test(decisionTime) ? { delivery_date: date, decision_time: decisionTime } : null;
  const { data, error, loading } = useApi("/api/day-ahead", params);

  const rows = useMemo(() => {
    if (!data) return [];
    const vintages = new Map();
    data.earlier_forecasts.forEach((v, i) =>
      v.points.forEach((p) => vintages.set(p.time, { ...vintages.get(p.time), [`v${i}`]: p.forecast })),
    );
    return data.points.map((p) => ({
      t: Date.parse(p.time),
      actual: p.actual,
      forecast: p.forecast,
      adjusted: p.adjusted,
      band: p.band_low != null && p.band_high != null ? [p.band_low, p.band_high] : null,
      ...vintages.get(p.time),
    }));
  }, [data]);

  const ticks = useMemo(() => {
    if (!data) return [];
    const start = Date.parse(data.window.start);
    const end = Date.parse(data.window.end);
    const out = [];
    for (let t = start; t <= end; t += 3 * HOUR_MS) out.push(t);
    return out;
  }, [data]);

  const s = data?.summary;
  const story = data ? headline(data) : null;

  const legend = [
    { label: "Actual outturn", color: SERIES.actual },
    { label: "Latest forecast at decision", color: SERIES.forecast },
    { label: "Bias-adjusted forecast", color: SERIES.adjusted },
    { label: "10–90% range", color: SERIES.adjusted, kind: "rect" },
    ...(showVintages ? [{ label: "Earlier forecasts", color: SERIES.vintage }] : []),
  ];

  const tableColumns = [
    { key: "t", label: "Time (UK)", format: fmtTime },
    { key: "actual", label: "Actual MW", format: (v) => (v == null ? "–" : Math.round(v).toLocaleString("en-GB")) },
    { key: "forecast", label: "Forecast MW", format: (v) => (v == null ? "–" : Math.round(v).toLocaleString("en-GB")) },
    { key: "adjusted", label: "Adjusted MW", format: (v) => (v == null ? "–" : Math.round(v).toLocaleString("en-GB")) },
    { key: "low", label: "P10 MW", value: (r) => r.band?.[0], format: (v) => (v == null ? "–" : Math.round(v).toLocaleString("en-GB")) },
    { key: "high", label: "P90 MW", value: (r) => r.band?.[1], format: (v) => (v == null ? "–" : Math.round(v).toLocaleString("en-GB")) },
  ];

  return (
    <div className="view">
      <div className="view-head">
        <h1>Day-ahead desk</h1>
        <p>
          The wind forecast you would have had in hand at the moment of the day-ahead purchase decision, and how
          the day actually turned out.
        </p>
      </div>

      <div className="filters">
        <label className="field">
          <span>Delivery day</span>
          <div className="stepper">
            <button className="btn" type="button" aria-label="Previous day" disabled={date <= first} onClick={() => setDate(addDays(date, -1))}>
              ‹
            </button>
            <input
              className="input"
              type="date"
              value={date}
              min={first}
              max={last}
              onChange={(e) => e.target.value && setDate(e.target.value)}
            />
            <button className="btn" type="button" aria-label="Next day" disabled={date >= last} onClick={() => setDate(addDays(date, 1))}>
              ›
            </button>
          </div>
        </label>
        <label className="field">
          <span>Decision time (UK, day before)</span>
          <input
            className="input"
            type="time"
            value={decisionTime}
            max={latestDecision}
            onChange={(e) => setDecisionTime(e.target.value)}
          />
        </label>
        <div className="field">
          <span>Gate closure presets</span>
          <div className="chips">
            {meta.decision_time_presets.map((p) => (
              <button
                key={p.time}
                type="button"
                className="chip"
                aria-pressed={decisionTime === p.time}
                onClick={() => setDecisionTime(p.time)}
              >
                {p.label} · {p.time}
              </button>
            ))}
          </div>
        </div>
        <label className="toggle">
          <input type="checkbox" checked={showVintages} onChange={(e) => setShowVintages(e.target.checked)} />
          Show earlier forecasts
        </label>
      </div>

      {error && <Notice kind="error">{error.message}</Notice>}

      {data && (
        <>
          <div className="context">
            <span>
              Delivery <strong>{fmtDate(data.delivery_date)}</strong> · {fmtDayTime(data.window.start)} →{" "}
              {fmtDayTime(data.window.end)}
            </span>
            <span>
              Decision <strong>{fmtDayTime(data.decision_at)}</strong>
            </span>
          </div>

          <div className="tiles">
            <StatTile
              label="Forecast used"
              value={data.forecast_publish_time ? `Published ${fmtTime(data.forecast_publish_time)}` : "None available"}
              sub={
                data.forecast_publish_time && (
                  <>
                    {fmtDuration(data.forecast_age_minutes)} before decision · {data.horizon_range_h[0]}–
                    {data.horizon_range_h[1]} h ahead
                  </>
                )
              }
            />
            <StatTile
              label="Forecast wind energy"
              value={fmtGWh(s.forecast_energy_mwh)}
              sub={
                <>
                  <span className="key" style={{ background: SERIES.adjusted }} />
                  Bias-adjusted <b>{fmtGWh(s.adjusted_energy_mwh)}</b>
                </>
              }
            />
            <StatTile
              label="Plan-for range (10–90%)"
              value={`${fmtGWh(s.low_case_energy_mwh).replace(" GWh", "")}–${fmtGWh(s.high_case_energy_mwh)}`}
              sub={<>Low-wind case is the prudent volume to rely on</>}
              emphasis
            />
            <StatTile
              label="Actual wind energy"
              value={s.actual_complete ? fmtGWh(s.actual_energy_mwh) : "Incomplete"}
              sub={
                s.energy_error_mwh != null && (
                  <>
                    Forecast error <b>{fmtSignedGWh(s.energy_error_mwh)}</b>
                    {s.energy_error_mwh > 0 ? " (over-forecast)" : " (under-forecast)"}
                  </>
                )
              }
            />
            <StatTile
              label="Hourly error (MAE)"
              value={fmtMW(s.metrics.mae)}
              sub={
                <>
                  Bias-adjusted <b>{fmtMW(s.adjusted_metrics.mae)}</b> · in range {s.band_coverage_pct ?? "–"}% of hours
                </>
              }
            />
          </div>

          {story && <Notice kind={`headline${story.good ? " good" : ""}`}>{story.text}</Notice>}

          <Card
            title="Wind generation, delivery day (MW)"
            subtitle={`Forecast and range are what was knowable at ${fmtDayTime(data.decision_at)}. The range is built from the forecast errors of the previous ${data.band.lookback_days} days at similar lead times.`}
            legend={legend}
            stale={loading}
            table={{ rows, columns: tableColumns }}
            csvName={`winddesk-day-ahead-${data.delivery_date}.csv`}
          >
            <ResponsiveContainer width="100%" height={360}>
              <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                <CartesianGrid {...gridProps} />
                <XAxis
                  {...axisProps}
                  dataKey="t"
                  type="number"
                  scale="time"
                  domain={[ticks[0], ticks[ticks.length - 1]]}
                  ticks={ticks}
                  tickFormatter={fmtTime}
                />
                <YAxis {...axisProps} width={44} tickFormatter={fmtCompact} axisLine={false} />
                <Tooltip content={<DayTooltip />} cursor={{ stroke: "var(--axis)" }} />
                <Area
                  dataKey="band"
                  stroke="none"
                  fill={SERIES.adjusted}
                  fillOpacity={0.14}
                  connectNulls
                  isAnimationActive={false}
                  activeDot={false}
                />
                {showVintages &&
                  data.earlier_forecasts.map((v, i) => (
                    <Line
                      key={v.publish_time}
                      dataKey={`v${i}`}
                      stroke={SERIES.vintage}
                      strokeWidth={1.25}
                      dot={false}
                      activeDot={false}
                      connectNulls
                      isAnimationActive={false}
                    />
                  ))}
                <Line
                  dataKey="adjusted"
                  stroke={SERIES.adjusted}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  dataKey="forecast"
                  stroke={SERIES.forecast}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
                <Line
                  dataKey="actual"
                  stroke={SERIES.actual}
                  strokeWidth={2}
                  dot={false}
                  connectNulls
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
            {showVintages && data.earlier_forecasts.length > 0 && (
              <p className="card-sub">
                Earlier forecasts: published{" "}
                {data.earlier_forecasts.map((v) => fmtDayTime(v.publish_time)).join(", ")}.
              </p>
            )}
          </Card>
        </>
      )}

      {!data && loading && <Notice busy>Loading delivery day…</Notice>}
    </div>
  );
}
