"""Fetch the in-scope data from Elexon and write the bundled offline snapshot.

The API uses the snapshot only if Elexon is unreachable (DATA_SOURCE=auto) or when
explicitly asked to (DATA_SOURCE=snapshot). Re-run after changing the scope settings:

    python -m scripts.build_snapshot          (from the backend/ directory)
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.dataset import build_dataset, data_windows, fetch_live, write_snapshot  # noqa: E402
from app.market import MarketCalendar  # noqa: E402


async def main() -> None:
    settings = get_settings()
    windows = data_windows(settings, MarketCalendar(settings.delivery_day_start_hour))
    actuals, forecasts = await fetch_live(settings, windows)
    dataset = build_dataset(actuals, forecasts, windows, source="elexon-live")  # validates the payload parses
    write_snapshot(settings.snapshot_path, actuals, forecasts)
    print(
        f"Wrote {settings.snapshot_path}: {len(dataset.actuals)} actual half-hours, "
        f"{len(dataset.forecasts)} forecast rows from {dataset.forecasts['publish_time'].nunique()} publishes"
    )


if __name__ == "__main__":
    asyncio.run(main())
