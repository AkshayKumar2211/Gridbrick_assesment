// Formatting helpers. The API speaks UTC; the desk thinks in UK time, so every
// timestamp shown to a user goes through Europe/London.

export const UK_TZ = "Europe/London";

const formatters = {
  time: new Intl.DateTimeFormat("en-GB", { timeZone: UK_TZ, hour: "2-digit", minute: "2-digit" }),
  dayTime: new Intl.DateTimeFormat("en-GB", {
    timeZone: UK_TZ,
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }),
  date: new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", weekday: "short", day: "numeric", month: "short", year: "numeric" }),
  shortDate: new Intl.DateTimeFormat("en-GB", { timeZone: "UTC", day: "numeric", month: "short" }),
  ukDay: new Intl.DateTimeFormat("en-GB", { timeZone: UK_TZ, day: "numeric", month: "short" }),
  parts: new Intl.DateTimeFormat("en-GB", {
    timeZone: UK_TZ,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }),
};

const DASH = "–";

/** "09:30" (UK) from an ISO timestamp or epoch ms. */
export const fmtTime = (t) => (t == null ? DASH : formatters.time.format(new Date(t)));

/** "Wed 14 Jan, 09:30" (UK). */
export const fmtDayTime = (t) => (t == null ? DASH : formatters.dayTime.format(new Date(t)));

/** "Thu 15 Jan 2026" from a calendar date "2026-01-15". */
export const fmtDate = (isoDate) => (isoDate ? formatters.date.format(new Date(`${isoDate}T12:00:00Z`)) : DASH);

/** "15 Jan" (UK) from an ISO timestamp or epoch ms. */
export const fmtUkDay = (t) => (t == null ? DASH : formatters.ukDay.format(new Date(t)));

/** "15 Jan" from a calendar date. */
export const fmtShortDate = (isoDate) =>
  isoDate ? formatters.shortDate.format(new Date(`${isoDate}T12:00:00Z`)) : DASH;

const int = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 0 });
const one = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const fmtMW = (v) => (v == null ? DASH : `${int.format(v)} MW`);

export const fmtSignedMW = (v) => (v == null ? DASH : `${v > 0 ? "+" : v < 0 ? "−" : ""}${int.format(Math.abs(v))} MW`);

export const fmtGWh = (mwh) => (mwh == null ? DASH : `${one.format(mwh / 1000)} GWh`);

export const fmtSignedGWh = (mwh) =>
  mwh == null ? DASH : `${mwh > 0 ? "+" : mwh < 0 ? "−" : ""}${one.format(Math.abs(mwh) / 1000)} GWh`;

export const fmtPct = (v, digits = 1) => (v == null ? DASH : `${v.toFixed(digits)}%`);

/** Axis ticks: 12000 -> "12k". */
export const fmtCompact = (v) => {
  if (v == null) return "";
  const abs = Math.abs(v);
  if (abs >= 1000) return `${v < 0 ? "−" : ""}${+(abs / 1000).toFixed(abs % 1000 === 0 ? 0 : 1)}k`;
  return `${v < 0 ? "−" : ""}${abs}`;
};

/** Shift a calendar date "YYYY-MM-DD" by n days. */
export function addDays(isoDate, n) {
  const d = new Date(`${isoDate}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** ISO timestamp -> "YYYY-MM-DDTHH:mm" in UK local time (for datetime-local inputs). */
export function toUkInputValue(t) {
  const p = Object.fromEntries(formatters.parts.formatToParts(new Date(t)).map((x) => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}`;
}

/** Minutes between two timestamps. */
export const minutesBetween = (a, b) => Math.round((new Date(b) - new Date(a)) / 60000);

export function fmtDuration(minutes) {
  if (minutes == null) return DASH;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h} h ${m ? `${m} min` : ""}`.trim() : `${m} min`;
}
