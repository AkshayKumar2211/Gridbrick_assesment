# Demo video script (max 10 min)

Record at 1080p with the deployed Vercel app open. Before recording, open the app once so the Heroku dyno is
awake. Speaker notes are in plain text; **[screen]** says what to show.

---

## Part 1: Client pitch (≤ 5 min)

**Goal:** show the purchasing team that WindDesk answers their two questions: what forecast did I have when I
decided, and how far can I trust it.

**0:00–0:30 · The problem**
"Your desk buys in the GB day-ahead auction the day before delivery. Wind decides how much you need to buy
beyond renewables, and you only have a forecast when you decide. So you need two things: the right forecast
at the right moment, and an honest measure of how wrong it tends to be. That's what we built in this pilot,
using Elexon's national wind data for every decision you made in January 2026."
**[screen]** Landing page, Day-ahead desk.

**0:30–2:00 · Day-ahead desk**
**[screen]** Pick **25 Jan**. Point at the presets.
- "Decision time defaults to N2EX gate closure, 09:50 the day before. One click switches to EPEX's 09:20."
- "This tile shows exactly which forecast you had: the 09:30 publication, 20 minutes old, looking 13 to 37
  hours ahead."
- "Orange is that forecast, blue is what actually happened. The forecast was high again."
- "Aqua is our bias-adjusted forecast and the shaded band is a 10–90% range. Both are built only from
  errors you could have seen before deciding, so there's no hindsight."
- Read the headline: raw forecast 44 GWh too high, adjusted within about 8 GWh.
- "The plan-for range tile gives the prudent volume of wind to rely on."
**[screen]** Tick **Show earlier forecasts** to show how the forecast moved. Click **CSV** to show the export.

**2:00–3:45 · Forecast accuracy**
**[screen]** Forecast accuracy tab. Walk through the key findings.
- "Across 744 delivery hours the typical miss was about 2 GW, 17.6% of wind energy."
- "The important part is that the error isn't random. The forecast was too high on 27 of 31 days, by 1.7 GW on
  average. You were systematically short."
- "Because it's systematic, it's correctable. Our adjustment cuts the hourly error by 22% and daily energy
  error by 27%."
- "The range held the outcome 80.5% of the time against an 80% target, so you can size risk with it."
**[screen]** Point at the "Does waiting help?" chart.
- "Waiting from EPEX at 09:20 to N2EX at 09:50 gets you a fresher forecast, but that gains only 1.4%. Bias
  matters far more than timing."
**[screen]** Point at 28 Jan in the daily chart.
- "And this is honest about the tail: on 28 January wind delivered half the forecast. That's why the range
  matters."

**3:45–4:30 · Explorer and methodology**
**[screen]** Explorer: drag the lead-time slider from 4 h to 36 h.
- "Any period, any lead time. You can see accuracy degrade as forecasts look further ahead."
**[screen]** Methodology tab, briefly.

**4:30–5:00 · Close and next steps**
"In short: you always know which forecast you had, how wrong it tends to be, and a better number to plan
with. Next we'd add your demand forecast so the range becomes a purchase volume directly, extend to a full
year, and investigate the cause of the bias with NESO constraint data."

---

## Part 2: Technical review (≤ 5 min)

**Goal:** make the review easy. Cover architecture, key decisions, analysis correctness, code layout and
practices.

**0:00–0:45 · Architecture**
**[screen]** README architecture diagram.
"One repo, two deploys. The React and Vite SPA is on Vercel and talks to a FastAPI container on Heroku built
from `heroku.yml`. The API pulls two Elexon datasets, FUELHH wind outturn and WINDFOR forecasts, for exactly
the January-decision scope. It holds them in memory and serves analysis endpoints."

**0:45–2:00 · Backend walkthrough** (open the files in this order)
- `market.py`: the GB day-ahead calendar. The delivery day runs 23:00–23:00 UK and decisions fall on D-1.
  Everything is DST-aware; tests cover summer and the 23-hour clock-change day.
- `elexon.py`: async client. It splits requests into 14-day chunks, fetches them concurrently and retries
  only 5xx/429/network errors. Parsing drops the roughly 24 past hours that every WINDFOR publication repeats.
- `analysis.py`: the pure core. `select_latest_forecasts` uses `merge_asof` by target hour with
  `publish_time ≤ cutoff`, the point-in-time rule. `residual_quantiles` only uses outcomes known before the
  decision, so there's no look-ahead.
- `service.py` / `api.py`: thin routes that validate and delegate, with memoised results and Pydantic schemas
  driving `/docs`.
- `store.py`: loads in the background so the port binds immediately for Heroku. Requests get 503 with
  Retry-After until the data is ready, and the frontend retries.

**2:00–2:45 · Data and scope decisions**
- "Decisions in January mean delivery from 2 Jan to 1 Feb. No forecast after 31 Jan is ever loaded."
- "Forecasts are hourly and actuals half-hourly. MW metrics compare on the hour; energy integrates each series
  natively."
- "WAPE instead of MAPE. Bias-adjustment calibration is measured, not assumed."
- "A 165 KB snapshot is the fallback when Elexon is down, and `DATA_SOURCE` switches it on."

**2:45–3:45 · Frontend**
**[screen]** `src/` tree.
- "There's no state library. A `useApi` hook keeps the previous data during refetch so charts dim instead of
  flashing."
- "Every chart card has a table twin and CSV. The palette is CVD-validated, with a dedicated dark mode, and all
  times are in UK local time."

**3:45–4:30 · Practices**
**[screen]** Terminal: `docker build --target test backend` running ruff and pytest, then `npm test`.
- "44 backend tests run on synthetic data with no network, plus frontend unit tests."
- "CI runs lint, tests, build and Docker builds. The image is multi-stage with a test target and runs as a
  non-root user."
- "`docker compose up --build` runs the whole stack."

**4:30–5:00 · Trade-offs and next steps**
"An in-memory store is right for a fixed month. Production would move to scheduled ingestion into a database.
The error model is simple and transparent; next it needs a year of validation, and demand data to turn wind
risk into volume."
