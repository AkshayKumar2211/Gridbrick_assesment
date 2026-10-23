import { describe, expect, it } from "vitest";
import { toCsv } from "./csv.js";
import { addDays, fmtCompact, fmtGWh, fmtSignedMW, fmtTime, toUkInputValue } from "./format.js";
import { API_BASE, buildUrl } from "./api.js";

describe("format", () => {
  it("shows UK local time, including during BST", () => {
    expect(fmtTime("2026-01-15T09:30:00Z")).toBe("09:30");
    expect(fmtTime("2026-07-15T09:30:00Z")).toBe("10:30");
  });

  it("formats energy and signed power", () => {
    expect(fmtGWh(128287)).toBe("128.3 GWh");
    expect(fmtSignedMW(1727)).toBe("+1,727 MW");
    expect(fmtSignedMW(-492)).toBe("−492 MW");
  });

  it("compacts axis ticks", () => {
    expect(fmtCompact(12000)).toBe("12k");
    expect(fmtCompact(2500)).toBe("2.5k");
    expect(fmtCompact(-4000)).toBe("−4k");
    expect(fmtCompact(500)).toBe("500");
  });

  it("shifts calendar dates across month ends", () => {
    expect(addDays("2026-01-31", 1)).toBe("2026-02-01");
    expect(addDays("2026-01-02", -1)).toBe("2026-01-01");
  });

  it("builds datetime-local values in UK time", () => {
    expect(toUkInputValue("2026-01-01T23:00:00Z")).toBe("2026-01-01T23:00");
  });
});

describe("csv", () => {
  it("escapes commas and quotes", () => {
    const csv = toCsv([{ a: 'x,"y"', b: null }], [{ key: "a", label: "A" }, { key: "b", label: "B" }]);
    expect(csv).toBe('A,B\n"x,""y""",');
  });
});

describe("api", () => {
  it("omits empty params", () => {
    expect(buildUrl("/api/x", { a: 1, b: null, c: "" })).toBe(`${API_BASE}/api/x?a=1`);
  });
});
