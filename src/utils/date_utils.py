"""Report period handling.

A report period is a plain dict so it serialises straight into JSON:
    {"mode": "yesterday", "from_date": date, "to_date": date,
     "label": "22-09-2026", "is_partial": False}
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from src.config import REPORT_TIMEZONE

DATE_FORMAT = "%d-%m-%Y"
MODES = ("yesterday", "today", "date", "range")


def now_local() -> datetime:
    """Current wall-clock time in the report timezone, as a naive datetime."""
    return datetime.now(ZoneInfo(REPORT_TIMEZONE)).replace(tzinfo=None, microsecond=0)


def parse_date(value: str | date) -> date:
    """Accept a date, 'DD-MM-YYYY' or ISO 'YYYY-MM-DD'."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    for fmt in (DATE_FORMAT, "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}'. Use DD-MM-YYYY (example: 17-03-2026).")


def format_date(value: date) -> str:
    return value.strftime(DATE_FORMAT)


def build_report_period(
    mode: str = "yesterday",
    from_date: str | date | None = None,
    to_date: str | date | None = None,
    today: date | None = None,
) -> dict:
    """Build a validated report period without any prompts (used by API/CLI flags)."""
    mode = (mode or "yesterday").lower()
    if mode not in MODES:
        raise ValueError(f"Unknown report mode '{mode}'. Choose one of: {', '.join(MODES)}")

    today = today or now_local().date()

    if mode == "yesterday":
        start = end = today - timedelta(days=1)
    elif mode == "today":
        start = end = today
    elif mode == "date":
        if from_date is None:
            raise ValueError("A date is required for mode 'date'.")
        start = end = parse_date(from_date)
    else:
        if from_date is None or to_date is None:
            raise ValueError("Both from and to dates are required for mode 'range'.")
        start, end = parse_date(from_date), parse_date(to_date)
        if end < start:
            raise ValueError("The end date is before the start date.")
        if (end - start).days > 30:
            raise ValueError("Date ranges are limited to 31 days.")

    if end > today:
        raise ValueError("The report period cannot end in the future.")

    label = format_date(start) if start == end else f"{format_date(start)}_to_{format_date(end)}"
    return {
        "mode": mode,
        "from_date": start,
        "to_date": end,
        "label": label,
        "is_partial": end == today,
    }


def period_bounds(period: dict, now: datetime | None = None) -> tuple[datetime, datetime]:
    """[start, end) of the period as naive report-timezone datetimes.

    For a period that includes today, `end` is the current minute, so
    'today so far' reports never expect data from the future.
    """
    start = datetime.combine(period["from_date"], time.min)
    end = datetime.combine(period["to_date"] + timedelta(days=1), time.min)
    now = now or now_local()
    if end > now:
        end = now.replace(second=0, microsecond=0)
    return start, end


def expected_minutes(period: dict, now: datetime | None = None) -> int:
    start, end = period_bounds(period, now)
    return max(0, int((end - start).total_seconds() // 60))


def ask_report_period() -> dict:
    """Interactive prompt used by `python -m src.main` when no flags are given."""
    print("\nSelect report period:")
    print("  1. Yesterday (default)")
    print("  2. Today so far")
    print("  3. Specific date")
    print("  4. Date range")
    choice = input("Enter choice [1-4]: ").strip() or "1"

    if choice == "1":
        return build_report_period("yesterday")
    if choice == "2":
        return build_report_period("today")
    if choice == "3":
        return build_report_period("date", input("Date (DD-MM-YYYY): ").strip())
    if choice == "4":
        start = input("From date (DD-MM-YYYY): ").strip()
        end = input("To date (DD-MM-YYYY): ").strip()
        return build_report_period("range", start, end)
    raise ValueError(f"Invalid choice '{choice}'. Enter 1, 2, 3 or 4.")
