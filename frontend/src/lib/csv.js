// Client-side CSV export for tables the desk wants in a spreadsheet.

const escape = (value) => {
  if (value == null) return "";
  const s = String(value);
  return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/** columns: [{ key, label, value?: (row) => any }] */
export function toCsv(rows, columns) {
  const header = columns.map((c) => escape(c.label)).join(",");
  const body = rows.map((row) => columns.map((c) => escape(c.value ? c.value(row) : row[c.key])).join(","));
  return [header, ...body].join("\n");
}

export function downloadCsv(filename, rows, columns) {
  const blob = new Blob([toCsv(rows, columns)], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
