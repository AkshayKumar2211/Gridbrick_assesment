import { fmtDate, fmtDayTime } from "../lib/format.js";

export default function Methodology({ meta }) {
  return (
    <div className="view">
      <div className="view-head">
        <h1>Methodology</h1>
        <p>How the numbers in WindDesk are produced, so the desk can trust and challenge them.</p>
      </div>

      <section className="card prose">
        <h2>Data</h2>
        <ul>
          <li>
            <strong>Actual generation:</strong> Elexon BMRS <code>FUELHH</code>, fuel type <code>WIND</code>.
            Half-hourly national outturn in MW.
          </li>
          <li>
            <strong>Forecasts:</strong> Elexon BMRS <code>WINDFOR</code>. Hourly national wind forecasts, re-published
            about 8 times a day (UK times {meta.publish_schedule.join(", ")}), each looking up to ~2–3 days ahead.
            Rows that a publication repeats for hours already elapsed are not forecasts and are discarded.
          </li>
          <li>
            Loaded: {meta.actuals.count.toLocaleString("en-GB")} actual half-hours and{" "}
            {meta.forecasts.count.toLocaleString("en-GB")} forecast values from {meta.forecasts.publishes} publications
            (source: {meta.source === "snapshot" ? "bundled snapshot of Elexon data" : "Elexon API, live"}).
          </li>
        </ul>
      </section>

      <section className="card prose">
        <h2>Scope: decisions made in January 2026</h2>
        <p>
          A purchase decision on day D-1 buys power for delivery day D. Decisions made between{" "}
          {fmtDate(meta.decision_dates.from)} and {fmtDate(meta.decision_dates.to)} therefore cover delivery days{" "}
          {fmtDate(meta.delivery_dates.from)} to {fmtDate(meta.delivery_dates.to)}.
        </p>
        <p>
          Following the GB day-ahead auctions, a delivery day runs from {meta.delivery_day_start_hour}:00 UK time on
          D-1 to {meta.delivery_day_start_hour}:00 on D (the evaluated window is {fmtDayTime(meta.scope.start)} to{" "}
          {fmtDayTime(meta.scope.end)}). The default decision time is the N2EX gate closure,{" "}
          {meta.default_decision_time} UK time on D-1. EPEX&apos;s GB hourly auction closes earlier, at 09:20. No
          forecast published after the last decision day is ever used.
        </p>
      </section>

      <section className="card prose">
        <h2>Which forecast counts</h2>
        <p>
          For every delivery hour we take the <strong>most recent forecast published at or before the decision
          time</strong>. That is exactly what a trader could have seen, with no hindsight. In the Explorer and the
          &quot;fixed lead time&quot; mode, the cut-off is instead <em>N</em> hours before each target hour.
        </p>
        <p>
          Forecasts are hourly and actuals half-hourly. MW error metrics compare them at matching on-the-hour
          timestamps. Daily energy (MWh) integrates each series at its own resolution.
        </p>
      </section>

      <section className="card prose">
        <h2>Error metrics</h2>
        <ul>
          <li>
            <strong>Error = forecast − actual.</strong> Positive means wind under-delivered, so a desk that relied on
            the forecast was short.
          </li>
          <li>
            <strong>MAE</strong> is the typical hourly miss in MW. <strong>RMSE</strong> weights large misses more
            heavily. <strong>Bias</strong> is the mean error, i.e. systematic over- or under-forecasting.
          </li>
          <li>
            <strong>WAPE</strong> = Σ|error| ÷ Σactual. Used instead of MAPE, which explodes in low-wind hours.
          </li>
          <li>
            <strong>Percentiles</strong> of the error (P10/P90) give the range the outcome fell in for 80% of hours.
          </li>
        </ul>
      </section>

      <section className="card prose">
        <h2>Bias adjustment and uncertainty range</h2>
        <p>
          At each decision we look at the forecast errors whose outcome was already known: the previous{" "}
          {meta.error_lookback_days} days, at lead times within ±3 h of the hour being forecast. Their median gives
          the <strong>bias-adjusted forecast</strong>. Their 10th and 90th percentiles give the{" "}
          <strong>10–90% range</strong>. Only information available before the decision is used. The range should
          contain the actual about 80% of the time, and the accuracy page reports how often it really did.
        </p>
        <p>
          The daily low-wind case sums hourly 10th percentiles. Because hourly errors are strongly correlated within
          a day, this is a reasonable and slightly conservative planning volume.
        </p>
      </section>

      <section className="card prose">
        <h2>Limitations and next steps</h2>
        <ul>
          <li>
            The forecast runs persistently above outturn, even a few hours ahead. One plausible contributor is wind
            curtailed for network constraints (forecasts describe available wind, outturn is what was metered). This
            should be confirmed with NESO data before relying on a cause.
          </li>
          <li>
            Demand, prices and other renewables are out of scope for this pilot. Adding demand forecasts would turn
            the wind range directly into a residual volume to buy.
          </li>
          <li>One month of history is a small sample. The error model should be re-validated over a full year.</li>
        </ul>
      </section>
    </div>
  );
}
