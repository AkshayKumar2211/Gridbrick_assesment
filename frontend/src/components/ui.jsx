import { useEffect, useState } from "react";
import { downloadCsv } from "../lib/csv.js";

export function StatTile({ label, value, sub, emphasis = false }) {
  return (
    <div className={`tile${emphasis ? " emphasis" : ""}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {sub && <div className="tile-sub">{sub}</div>}
    </div>
  );
}

/** Legend items: { label, color, kind: "line" | "rect" }. Always shown for 2+ series. */
export function Legend({ items }) {
  return (
    <div className="legend" role="list">
      {items.map((item) => (
        <span className="legend-item" role="listitem" key={item.label}>
          <span
            className={item.kind === "rect" ? "legend-rect" : "legend-line"}
            style={{ background: item.color, opacity: item.kind === "rect" ? 0.35 : 1 }}
          />
          {item.label}
        </span>
      ))}
    </div>
  );
}

/** columns: [{ key, label, value?: (row) => raw, format?: (raw) => string }] */
export function DataTable({ rows, columns }) {
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col">
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i}>
              {columns.map((c) => {
                const raw = c.value ? c.value(row) : row[c.key];
                return <td key={c.key}>{c.format ? c.format(raw) : (raw ?? "–")}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A chart card. Every chart has a table twin (`table`) so no value is gated
 * behind hover or colour, and optionally a CSV export.
 */
export function Card({ title, subtitle, legend, table, csvName, stale = false, children }) {
  const [showTable, setShowTable] = useState(false);
  const csvColumns = table?.columns.map((c) => ({ label: c.label, value: (r) => (c.value ? c.value(r) : r[c.key]) }));
  return (
    <section className="card">
      <div className="card-head">
        <div>
          <h2 className="card-title">{title}</h2>
          {subtitle && <p className="card-sub">{subtitle}</p>}
        </div>
        {table && (
          <div className="card-actions">
            <button className="btn small" type="button" aria-pressed={showTable} onClick={() => setShowTable((v) => !v)}>
              {showTable ? "Chart" : "Table"}
            </button>
            {csvName && (
              <button className="btn small" type="button" onClick={() => downloadCsv(csvName, table.rows, csvColumns)}>
                CSV
              </button>
            )}
          </div>
        )}
      </div>
      {!showTable && legend && <Legend items={legend} />}
      <div className={`chart${stale ? " stale" : ""}`}>{showTable ? <DataTable {...table} /> : children}</div>
    </section>
  );
}

export function Segmented({ options, value, onChange, label }) {
  return (
    <div className="seg" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.value} type="button" aria-pressed={value === o.value} onClick={() => onChange(o.value)}>
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function Notice({ kind = "", children, busy = false }) {
  return (
    <div className={`notice ${kind}`} role={kind === "error" ? "alert" : "status"}>
      {busy && <span className="spinner" aria-hidden="true" />}
      <div>{children}</div>
    </div>
  );
}

/** Tooltip body: value leads, label follows; series keyed by a short line. */
export function TooltipBox({ title, rows, note }) {
  return (
    <div className="tooltip">
      <div className="tooltip-title">{title}</div>
      {rows.map((r) => (
        <div className="tooltip-row" key={r.label}>
          <span className="legend-line" style={{ background: r.color ?? "transparent" }} />
          <span>{r.label}</span>
          <strong>{r.value}</strong>
        </div>
      ))}
      {note && <div className="tooltip-note">{note}</div>}
    </div>
  );
}

/** Bar with a 4px rounded data-end and a square baseline, for positive and negative values. */
export function RoundedBar({ x, y, width, height, fill, value }) {
  let top = y;
  let h = height;
  if (h < 0) {
    top = y + h;
    h = -h;
  }
  if (!h || !width) return null;
  const v = Array.isArray(value) ? value[1] - value[0] : value;
  const r = Math.min(4, width / 2, h);
  const right = x + width;
  const bottom = top + h;
  const d =
    v >= 0
      ? `M${x},${bottom}V${top + r}Q${x},${top} ${x + r},${top}H${right - r}Q${right},${top} ${right},${top + r}V${bottom}Z`
      : `M${x},${top}V${bottom - r}Q${x},${bottom} ${x + r},${bottom}H${right - r}Q${right},${bottom} ${right},${bottom - r}V${top}Z`;
  return <path d={d} fill={fill} />;
}

export function useDebounced(value, ms = 250) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(id);
  }, [value, ms]);
  return debounced;
}

export const axisProps = {
  stroke: "var(--axis)",
  tick: { fill: "var(--muted)", fontSize: 12 },
  tickLine: false,
};

export const gridProps = { stroke: "var(--grid)", vertical: false };

export const SERIES = {
  actual: "var(--series-1)",
  forecast: "var(--series-2)",
  adjusted: "var(--series-3)",
  vintage: "var(--vintage)",
};
