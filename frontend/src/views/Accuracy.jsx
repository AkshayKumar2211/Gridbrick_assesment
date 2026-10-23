import { useMemo, useState } from "react";
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Card,
  Notice,
  RoundedBar,
  SERIES,
  Segmented,
  StatTile,
  TooltipBox,
  axisProps,
  gridProps,
  useDebounced,
} from "../components/ui.jsx";
import {
  fmtCompact,
  fmtDate,
  fmtGWh,
  fmtMW,
  fmtPct,
  fmtShortDate,
  fmtSignedGWh,
  fmtSignedMW,
} from "../lib/format.js";
import { useApi } from "../lib/useApi.js";

const toMinutes = (hhmm) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};
const fromMinutes = (min) => `${String(Math.floor(min / 60)).padStart(2, "0")}:${String(min % 60).padStart(2, "0")}`;
const pctChange = (from, to) => ((to - from) / from) * 100;

/** Evenly spaced round ticks covering [lo, hi]. */
function niceTicks(lo, hi, step) {
  const ticks = [];
  for (let t = Math.floor(lo / step) * step; t <= Math.ceil(hi / step) * step; t += step) ticks.push(t);
  return ticks;
}

/** Value of a step profile at an arbitrary time: the last row at or before it. */
function profileAt(profile, hhmm) {
  const t = toMinutes(hhmm);
  return [...profile].reverse().find((r) => toMinutes(r.decision_time) <= t);
}

function findings(acc, timing, presets) {
  if (!acc) return [];
  const m = acc.metrics;
  const out = [];
  const days = acc.daily.filter((d) => d.energy_error_mwh != null);
  const overDays = days.filter((d) => d.energy_error_mwh > 0).length;
  out.push(
    `The forecast was too high on ${overDays} of ${days.length} delivery days. On average it overstated wind by ${fmtMW(m.bias)} (${Math.round((m.bias / m.mean_actual) * 100)}% of mean output), so the error is systematic, not random.`,
  );
  if (acc.adjusted_metrics) {
    const a = acc.adjusted_metrics;
    const rawDaily = days.reduce((s, d) => s + Math.abs(d.energy_error_mwh), 0);
    const adjDaily = days.reduce((s, d) => s + Math.abs(d.adjusted_energy_error_mwh ?? 0), 0);
    out.push(
      `Correcting each forecast with the errors seen over the previous 14 days (information available at decision time) cuts hourly MAE by ${Math.abs(pctChange(m.mae, a.mae)).toFixed(0)}% (${fmtMW(m.mae)} → ${fmtMW(a.mae)}) and total daily energy error by ${Math.abs(pctChange(rawDaily, adjDaily)).toFixed(0)}%.`,
    );
  }
  // error = forecast - actual, so actual = forecast - error: P90 error is the low side of actual.
  const q = acc.signed_error_quantiles;
  const side = (e) => `${fmtMW(Math.abs(e))} ${e >= 0 ? "below" : "above"}`;
  out.push(
    `In 80% of hours, actual wind landed between ${side(q.p90)} and ${side(q.p10)} the forecast. That spread is the volume risk to cover in intraday trading or imbalance.`,
  );
  if (acc.band_coverage_pct != null) {
    out.push(
      `The 10–90% uncertainty range contained the outcome in ${fmtPct(acc.band_coverage_pct)} of hours (target 80%), so it is well calibrated enough to size a prudent wind volume.`,
    );
  }
  if (timing && presets.length >= 2) {
    const [early, late] = presets;
    const a = profileAt(timing, early.time);
    const b = profileAt(timing, late.time);
    if (a && b) {
      out.push(
        `Timing: deciding at ${late.time} (${late.label}) rather than ${early.time} (${early.label}) means using the ${b.typical_publish_time} forecast instead of the ${a.typical_publish_time} one: MAE ${fmtMW(a.mae)} → ${fmtMW(b.mae)} (${pctChange(a.mae, b.mae).toFixed(1)}%). Bias matters far more than freshness.`,
      );
    }
  }
  const worst = days.reduce((x, y) => (Math.abs(y.energy_error_mwh) > Math.abs(x.energy_error_mwh) ? y : x), days[0]);
  if (worst) {
    out.push(
      `Largest miss: ${fmtDate(worst.delivery_date)}. Forecast ${fmtGWh(worst.forecast_energy_mwh)} vs actual ${fmtGWh(worst.actual_energy_mwh)} (${fmtSignedGWh(worst.energy_error_mwh)}).`,
    );
  }
  return out;
}

export default function Accuracy({ meta }) {
  const [mode, setMode] = useState("day_ahead");
  const [decisionTime, setDecisionTime] = useState(meta.default_decision_time);
  const [horizon, setHorizon] = useState(24);
  const debouncedHorizon = useDebounced(horizon);

  const validTime = /^\d\d:\d\d$/.test(decisionTime);
  const params =
    mode === "day_ahead"
      ? validTime
        ? { mode, decision_time: decisionTime }
        : null
      : { mode, horizon_hours: debouncedHorizon };
  const acc = useApi("/api/accuracy", params);
  const horizonProfile = useApi("/api/accuracy/horizon-profile", {});
  const timing = useApi("/api/accuracy/decision-time-profile", {});

  const data = acc.data;
  const m = data?.metrics;
  const a = data?.adjusted_metrics;
  const insights = useMemo(
    () => findings(data, timing.data, meta.decision_time_presets),
    [data, timing.data, meta.decision_time_presets],
  );

  const daily = useMemo(
    () =>
      (data?.daily ?? []).map((d) => ({
        ...d,
        raw: d.energy_error_mwh / 1000,
        adjusted: d.adjusted_energy_error_mwh == null ? null : d.adjusted_energy_error_mwh / 1000,
      })),
    [data],
  );

  const hist = useMemo(
    () => (data?.histogram ?? []).map((b) => ({ ...b, mid: (b.lo + b.hi) / 2, label: `${fmtCompact(b.lo)} to ${fmtCompact(b.hi)}` })),
    [data],
  );

  const histTicks = useMemo(
    () => (hist.length ? niceTicks(hist[0].lo, hist[hist.length - 1].hi, 2000) : [0]),
    [hist],
  );

  // Shared square scale so the diagonal really is "forecast = actual".
  const scatterTicks = useMemo(() => {
    const max = Math.max(0, ...(data?.scatter ?? []).flatMap((p) => [p.forecast, p.actual]));
    return niceTicks(0, max, 5000);
  }, [data]);

  const horizonRows = useMemo(
    () => (horizonProfile.data ?? []).map((r) => ({ ...r, range: [r.p10, r.p90] })),
    [horizonProfile.data],
  );

  const timingRows = useMemo(
    () => (timing.data ?? []).map((r) => ({ ...r, minutes: toMinutes(r.decision_time) })),
    [timing.data],
  );

  // The lead times a day-ahead decision actually uses (at the chosen decision time).
  const daRange = useMemo(() => {
    if (!timing.data || !validTime) return null;
    const row = profileAt(timing.data, decisionTime);
    if (!row?.mean_horizon_h) return null;
    return [Math.max(0, row.mean_horizon_h - 12), Math.min(47, row.mean_horizon_h + 12)];
  }, [timing.data, decisionTime, validTime]);

  return (
    <div className="view">
      <div className="view-head">
        <h1>Forecast accuracy</h1>
        <p>
          How good were the forecasts the desk would actually have used for decisions made in January 2026 (delivery{" "}
          {fmtShortDate(meta.delivery_dates.from)} – {fmtShortDate(meta.delivery_dates.to)})? Error = forecast −
          actual: positive means wind under-delivered and the desk was left short.
        </p>
      </div>

      <div className="filters">
        <div className="field">
          <span>Which forecast is evaluated</span>
          <Segmented
            label="Forecast selection rule"
            value={mode}
            onChange={setMode}
            options={[
              { value: "day_ahead", label: "Day-ahead decision" },
              { value: "horizon", label: "Fixed lead time" },
            ]}
          />
        </div>
        {mode === "day_ahead" ? (
          <>
            <label className="field">
              <span>Decision time (UK, day before)</span>
              <input
                className="input"
                type="time"
                value={decisionTime}
                max="22:59"
                onChange={(e) => setDecisionTime(e.target.value)}
              />
            </label>
            <div className="field">
              <span>Presets</span>
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
          </>
        ) : (
          <label className="field">
            <span>Minimum lead time</span>
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
        )}
      </div>

      {acc.error && <Notice kind="error">{acc.error.message}</Notice>}
      {!data && acc.loading && <Notice busy>Evaluating forecasts…</Notice>}

      {data && (
        <>
          <div className="tiles">
            <StatTile label="Mean absolute error" value={fmtMW(m.mae)} sub={<>WAPE {fmtPct(m.wape_pct)} of actual energy</>} />
            <StatTile label="Bias (mean error)" value={fmtSignedMW(m.bias)} sub={m.bias > 0 ? "Systematic over-forecast" : "Systematic under-forecast"} />
            <StatTile label="RMSE" value={fmtMW(m.rmse)} sub={<>Penalises large misses · r = {m.correlation}</>} />
            <StatTile label="90th percentile |error|" value={fmtMW(m.p90_abs)} sub={<>Worst hour {fmtSignedMW(m.max_over)}</>} />
            {a ? (
              <StatTile
                label="Bias-adjusted MAE"
                value={fmtMW(a.mae)}
                sub={
                  <>
                    <b>{pctChange(m.mae, a.mae).toFixed(0)}%</b> vs raw · range coverage {fmtPct(data.band_coverage_pct)}
                  </>
                }
                emphasis
              />
            ) : (
              <StatTile label="Mean lead time" value={`${data.selection.mean_horizon_h} h`} sub="Average age of forecast used" />
            )}
          </div>

          <section className="card">
            <div className="card-head">
              <div>
                <h2 className="card-title">Key findings</h2>
                <p className="card-sub">{data.selection.label}. Mean lead time {data.selection.mean_horizon_h} h, {m.n} hours evaluated.</p>
              </div>
            </div>
            <ol className="insights">
              {insights.map((text, i) => (
                <li key={i}>
                  <span className="num">{i + 1}</span>
                  <span>{text}</span>
                </li>
              ))}
            </ol>
          </section>

          <Card
            title="Daily energy error (GWh)"
            subtitle="Forecast minus actual wind energy per delivery day. Above zero: wind under-delivered and the desk was short."
            legend={[
              { label: "Raw forecast", color: SERIES.forecast, kind: "rect" },
              ...(a ? [{ label: "Bias-adjusted forecast", color: SERIES.adjusted, kind: "rect" }] : []),
            ]}
            stale={acc.loading}
            csvName="winddesk-daily-accuracy.csv"
            table={{
              rows: data.daily,
              columns: [
                { key: "delivery_date", label: "Delivery day" },
                { key: "forecast_energy_mwh", label: "Forecast GWh", format: (v) => (v / 1000).toFixed(1) },
                { key: "actual_energy_mwh", label: "Actual GWh", format: (v) => (v / 1000).toFixed(1) },
                { key: "energy_error_mwh", label: "Error GWh", format: (v) => (v / 1000).toFixed(1) },
                ...(a
                  ? [{ key: "adjusted_energy_error_mwh", label: "Adj. error GWh", format: (v) => (v == null ? "–" : (v / 1000).toFixed(1)) }]
                  : []),
                { key: "mae", label: "MAE MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                { key: "bias", label: "Bias MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
              ],
            }}
          >
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={daily} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barGap={2} barCategoryGap="18%">
                <CartesianGrid {...gridProps} />
                <XAxis {...axisProps} dataKey="delivery_date" tickFormatter={fmtShortDate} minTickGap={18} />
                <YAxis {...axisProps} width={44} axisLine={false} tickFormatter={(v) => `${v}`} />
                <ReferenceLine y={0} stroke="var(--axis)" />
                <Tooltip
                  cursor={{ fill: "var(--surface-2)" }}
                  content={({ active, payload }) =>
                    active && payload?.length ? (
                      <TooltipBox
                        title={fmtDate(payload[0].payload.delivery_date)}
                        rows={[
                          { label: "Raw forecast", value: fmtSignedGWh(payload[0].payload.energy_error_mwh), color: SERIES.forecast },
                          ...(payload[0].payload.adjusted_energy_error_mwh != null
                            ? [{ label: "Bias-adjusted", value: fmtSignedGWh(payload[0].payload.adjusted_energy_error_mwh), color: SERIES.adjusted }]
                            : []),
                          { label: "Actual energy", value: fmtGWh(payload[0].payload.actual_energy_mwh) },
                        ]}
                      />
                    ) : null
                  }
                />
                <Bar dataKey="raw" fill={SERIES.forecast} maxBarSize={14} shape={<RoundedBar />} isAnimationActive={false} />
                {a && <Bar dataKey="adjusted" fill={SERIES.adjusted} maxBarSize={14} shape={<RoundedBar />} isAnimationActive={false} />}
              </BarChart>
            </ResponsiveContainer>
          </Card>

          <div className="grid-2">
            <Card
              title="Error grows with lead time"
              subtitle="Every forecast vintage in scope, by hours between publication and target hour. The error band shows where 80% of errors fell."
              legend={[
                { label: "MAE", color: SERIES.forecast },
                { label: "10–90% of error", color: SERIES.forecast, kind: "rect" },
                ...(daRange ? [{ label: "Lead times a day-ahead decision uses", color: "var(--muted)", kind: "rect" }] : []),
              ]}
              stale={horizonProfile.loading}
              table={{
                rows: horizonRows,
                columns: [
                  { key: "horizon_h", label: "Lead time h" },
                  { key: "mae", label: "MAE MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                  { key: "bias", label: "Bias MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                  { key: "p10", label: "P10 MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                  { key: "p90", label: "P90 MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                  { key: "n", label: "Samples" },
                ],
              }}
            >
              <ResponsiveContainer width="100%" height={280}>
                <ComposedChart data={horizonRows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid {...gridProps} />
                  <XAxis {...axisProps} dataKey="horizon_h" type="number" domain={[0, 48]} ticks={[0, 6, 12, 18, 24, 30, 36, 42, 48]} tickFormatter={(v) => `${v}h`} />
                  <YAxis {...axisProps} width={44} axisLine={false} tickFormatter={fmtCompact} />
                  {daRange && <ReferenceArea x1={daRange[0]} x2={daRange[1]} fill="var(--muted)" fillOpacity={0.08} />}
                  <ReferenceLine y={0} stroke="var(--axis)" />
                  <Tooltip
                    cursor={{ stroke: "var(--axis)" }}
                    content={({ active, payload }) =>
                      active && payload?.length ? (
                        <TooltipBox
                          title={`${payload[0].payload.horizon_h}–${payload[0].payload.horizon_h + 1} h ahead`}
                          rows={[
                            { label: "MAE", value: fmtMW(payload[0].payload.mae), color: SERIES.forecast },
                            { label: "Bias", value: fmtSignedMW(payload[0].payload.bias) },
                            { label: "10–90%", value: `${fmtCompact(payload[0].payload.p10)} to ${fmtCompact(payload[0].payload.p90)} MW` },
                          ]}
                          note={`${payload[0].payload.n} forecast-hours`}
                        />
                      ) : null
                    }
                  />
                  <Area dataKey="range" stroke="none" fill={SERIES.forecast} fillOpacity={0.12} isAnimationActive={false} activeDot={false} />
                  <Line dataKey="mae" stroke={SERIES.forecast} strokeWidth={2} dot={false} isAnimationActive={false} />
                </ComposedChart>
              </ResponsiveContainer>
            </Card>

            <Card
              title="Does waiting for a fresher forecast help?"
              subtitle="Day-ahead MAE if the decision were taken at each time on the day before delivery. Steps occur at forecast publications. Axis does not start at zero."
              stale={timing.loading}
              table={{
                rows: timingRows,
                columns: [
                  { key: "decision_time", label: "Decision time" },
                  { key: "typical_publish_time", label: "Forecast used" },
                  { key: "mae", label: "MAE MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                  { key: "bias", label: "Bias MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                  { key: "mean_horizon_h", label: "Mean lead h" },
                ],
              }}
            >
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={timingRows} margin={{ top: 22, right: 16, bottom: 0, left: 0 }}>
                  <CartesianGrid {...gridProps} />
                  <XAxis
                    {...axisProps}
                    dataKey="minutes"
                    type="number"
                    domain={[0, 22 * 60 + 30]}
                    ticks={[0, 180, 360, 540, 720, 900, 1080, 1260]}
                    tickFormatter={fromMinutes}
                  />
                  <YAxis {...axisProps} width={48} axisLine={false} tickFormatter={fmtCompact} domain={["dataMin - 40", "dataMax + 40"]} />
                  {meta.decision_time_presets.map((p, i) => (
                    <ReferenceLine
                      key={p.time}
                      x={toMinutes(p.time)}
                      stroke="var(--ink-2)"
                      strokeOpacity={0.5}
                      label={{ value: p.time, position: "top", fill: "var(--ink-2)", fontSize: 11, dx: i === 0 ? -14 : 14 }}
                    />
                  ))}
                  <Tooltip
                    cursor={{ stroke: "var(--axis)" }}
                    content={({ active, payload }) =>
                      active && payload?.length ? (
                        <TooltipBox
                          title={`Decide at ${payload[0].payload.decision_time} on D-1`}
                          rows={[
                            { label: "MAE", value: fmtMW(payload[0].payload.mae), color: SERIES.forecast },
                            { label: "Forecast used", value: payload[0].payload.typical_publish_time },
                            { label: "Mean lead time", value: `${payload[0].payload.mean_horizon_h} h` },
                          ]}
                        />
                      ) : null
                    }
                  />
                  <Line type="stepAfter" dataKey="mae" stroke={SERIES.forecast} strokeWidth={2} dot={false} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </Card>

            <Card
              title="Distribution of hourly errors"
              subtitle={`Hours by error size (forecast − actual). Median ${fmtSignedMW(data.signed_error_quantiles.p50)}; 80% of hours fall between the two reference lines.`}
              stale={acc.loading}
              table={{
                rows: hist,
                columns: [
                  { key: "label", label: "Error MW" },
                  { key: "count", label: "Hours" },
                ],
              }}
            >
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={hist} margin={{ top: 22, right: 12, bottom: 0, left: 0 }} barCategoryGap={2}>
                  <CartesianGrid {...gridProps} />
                  <XAxis
                    {...axisProps}
                    dataKey="mid"
                    type="number"
                    domain={[histTicks[0], histTicks[histTicks.length - 1]]}
                    ticks={histTicks}
                    tickFormatter={fmtCompact}
                  />
                  <YAxis {...axisProps} width={36} axisLine={false} allowDecimals={false} />
                  <ReferenceLine x={0} stroke="var(--ink-2)" strokeOpacity={0.6} />
                  {["p10", "p90"].map((k) => (
                    <ReferenceLine
                      key={k}
                      x={data.signed_error_quantiles[k]}
                      stroke="var(--ink-2)"
                      strokeOpacity={0.5}
                      label={{ value: k.toUpperCase(), position: "top", fill: "var(--ink-2)", fontSize: 11 }}
                    />
                  ))}
                  <Tooltip
                    cursor={{ fill: "var(--surface-2)" }}
                    content={({ active, payload }) =>
                      active && payload?.length ? (
                        <TooltipBox
                          title={`${payload[0].payload.label} MW`}
                          rows={[{ label: "Hours", value: payload[0].payload.count, color: SERIES.forecast }]}
                        />
                      ) : null
                    }
                  />
                  <Bar dataKey="count" fill={SERIES.forecast} shape={<RoundedBar />} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </Card>

            <Card
              title="Forecast vs actual, hour by hour"
              subtitle="Points below the diagonal are hours where wind under-delivered against the forecast."
              stale={acc.loading}
              table={{
                rows: data.scatter,
                columns: [
                  { key: "time", label: "Hour (UTC)" },
                  { key: "forecast", label: "Forecast MW" },
                  { key: "actual", label: "Actual MW" },
                ],
              }}
            >
              <ResponsiveContainer width="100%" height={280}>
                <ScatterChart margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                  <CartesianGrid {...gridProps} vertical />
                  <XAxis
                    {...axisProps}
                    dataKey="forecast"
                    type="number"
                    name="Forecast"
                    domain={[0, scatterTicks[scatterTicks.length - 1]]}
                    ticks={scatterTicks}
                    tickFormatter={fmtCompact}
                    label={{ value: "Forecast MW", position: "insideBottomRight", offset: -4, fill: "var(--muted)", fontSize: 11 }}
                  />
                  <YAxis
                    {...axisProps}
                    dataKey="actual"
                    type="number"
                    name="Actual"
                    width={44}
                    axisLine={false}
                    domain={[0, scatterTicks[scatterTicks.length - 1]]}
                    ticks={scatterTicks}
                    tickFormatter={fmtCompact}
                  />
                  <ReferenceLine
                    segment={[
                      { x: 0, y: 0 },
                      { x: scatterTicks[scatterTicks.length - 1], y: scatterTicks[scatterTicks.length - 1] },
                    ]}
                    stroke="var(--ink-2)"
                    strokeOpacity={0.5}
                  />
                  <Tooltip
                    cursor={false}
                    content={({ active, payload }) =>
                      active && payload?.length ? (
                        <TooltipBox
                          title="Hour"
                          rows={[
                            { label: "Forecast", value: fmtMW(payload[0].payload.forecast), color: SERIES.forecast },
                            { label: "Actual", value: fmtMW(payload[0].payload.actual), color: SERIES.actual },
                          ]}
                        />
                      ) : null
                    }
                  />
                  <Scatter data={data.scatter} fill={SERIES.forecast} fillOpacity={0.55} shape="circle" isAnimationActive={false} />
                </ScatterChart>
              </ResponsiveContainer>
            </Card>
          </div>

          <Card
            title="Error by hour of day (UK)"
            subtitle="Mean absolute error for each delivery hour. Use it to see when in the day wind is hardest to predict."
            stale={acc.loading}
            table={{
              rows: data.by_hour,
              columns: [
                { key: "hour", label: "Hour", format: (h) => `${String(h).padStart(2, "0")}:00` },
                { key: "mae", label: "MAE MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                { key: "bias", label: "Bias MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                { key: "p10", label: "P10 MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
                { key: "p90", label: "P90 MW", format: (v) => Math.round(v).toLocaleString("en-GB") },
              ],
            }}
          >
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={data.by_hour} margin={{ top: 8, right: 12, bottom: 0, left: 0 }} barCategoryGap="20%">
                <CartesianGrid {...gridProps} />
                <XAxis {...axisProps} dataKey="hour" tickFormatter={(h) => `${String(h).padStart(2, "0")}`} />
                <YAxis {...axisProps} width={44} axisLine={false} tickFormatter={fmtCompact} />
                <Tooltip
                  cursor={{ fill: "var(--surface-2)" }}
                  content={({ active, payload }) =>
                    active && payload?.length ? (
                      <TooltipBox
                        title={`${String(payload[0].payload.hour).padStart(2, "0")}:00 UK`}
                        rows={[
                          { label: "MAE", value: fmtMW(payload[0].payload.mae), color: SERIES.forecast },
                          { label: "Bias", value: fmtSignedMW(payload[0].payload.bias) },
                        ]}
                      />
                    ) : null
                  }
                />
                <Bar dataKey="mae" fill={SERIES.forecast} maxBarSize={24} shape={<RoundedBar />} isAnimationActive={false} />
              </BarChart>
            </ResponsiveContainer>
          </Card>
        </>
      )}
    </div>
  );
}
