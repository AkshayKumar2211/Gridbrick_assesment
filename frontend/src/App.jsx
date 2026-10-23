import { useEffect, useState } from "react";
import { Notice } from "./components/ui.jsx";
import { fmtDayTime } from "./lib/format.js";
import { useApi } from "./lib/useApi.js";
import Accuracy from "./views/Accuracy.jsx";
import DayAhead from "./views/DayAhead.jsx";
import Explorer from "./views/Explorer.jsx";
import Methodology from "./views/Methodology.jsx";

const TABS = [
  { id: "desk", label: "Day-ahead desk", View: DayAhead },
  { id: "accuracy", label: "Forecast accuracy", View: Accuracy },
  { id: "explorer", label: "Explorer", View: Explorer },
  { id: "method", label: "Methodology", View: Methodology },
];

function useHashTab() {
  const read = () => {
    const id = window.location.hash.slice(1);
    return TABS.some((t) => t.id === id) ? id : TABS[0].id;
  };
  const [tab, setTab] = useState(read);
  useEffect(() => {
    const onChange = () => setTab(read());
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return [tab, (id) => (window.location.hash = id)];
}

function readTheme() {
  try {
    return localStorage.getItem("winddesk-theme");
  } catch {
    return null;
  }
}

function useTheme() {
  const [theme, setTheme] = useState(readTheme);
  useEffect(() => {
    const root = document.documentElement;
    if (theme) root.setAttribute("data-theme", theme);
    else root.removeAttribute("data-theme");
    try {
      if (theme) localStorage.setItem("winddesk-theme", theme);
    } catch {
      /* storage unavailable: the choice just won't persist */
    }
  }, [theme]);
  const isDark = theme ? theme === "dark" : window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  return [isDark, () => setTheme(isDark ? "light" : "dark")];
}

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden="true">
      <rect width="32" height="32" rx="8" fill="var(--accent)" />
      <path
        d="M7 12h12a3 3 0 1 0-3-3M7 17h17a3 3 0 1 1-3 3M7 22h8"
        stroke="white"
        strokeWidth="2.4"
        fill="none"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function App() {
  const [tab, setTab] = useHashTab();
  const [isDark, toggleTheme] = useTheme();
  const meta = useApi("/api/meta", {});
  const { View } = TABS.find((t) => t.id === tab);

  return (
    <>
      <header className="app-header">
        <div className="header-inner">
          <div className="brand">
            <BrandMark />
            <div>
              <div className="brand-name">WindDesk</div>
              <div className="brand-tag">GB wind forecasts for day-ahead purchasing</div>
            </div>
          </div>
          <div className="header-right">
            {meta.data && (
              <span className="pill" title={`Data loaded ${fmtDayTime(meta.data.loaded_at)}`}>
                <span className={`dot ${meta.data.source === "elexon-live" ? "live" : "warn"}`} />
                Elexon BMRS · {meta.data.source === "elexon-live" ? "live" : "snapshot"}
              </span>
            )}
            <button className="icon-btn" type="button" onClick={toggleTheme} aria-label="Toggle dark mode" title="Toggle dark mode">
              {isDark ? "☀" : "☾"}
            </button>
          </div>
          <nav className="tabs" role="tablist" aria-label="Sections">
            {TABS.map((t) => (
              <button
                key={t.id}
                type="button"
                role="tab"
                className="tab"
                aria-selected={tab === t.id}
                onClick={() => setTab(t.id)}
              >
                {t.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <main>
        {meta.data ? (
          <View meta={meta.data} />
        ) : meta.error ? (
          <Notice kind="error">
            Could not reach the WindDesk API: {meta.error.message}.{" "}
            <button className="btn small" type="button" onClick={() => window.location.reload()}>
              Retry
            </button>
          </Notice>
        ) : (
          <Notice busy>
            {meta.waiting
              ? "Waking up the data service and loading January 2026 data from Elexon. The first load can take up to a minute."
              : "Loading…"}
          </Notice>
        )}
      </main>

      <footer>
        Data: Elexon BMRS (FUELHH wind outturn, WINDFOR wind forecasts). All times are UK local time.
      </footer>
    </>
  );
}
