"""Reviewed NSE cash-market schedule for the first automatic research release.

This is a bounded calendar, not a weekday guess for arbitrary years. In
particular, we stop BEFORE the announced 8 November Muhurat session because
its hours have not been verified. A failed price download never removes a day.
"""
from datetime import date, datetime, time, timedelta

from .contracts import IST, ValidationError, iso
from .local_data import load_calendar

CALENDAR_VERSION = "nse-cm-eod-2026-jul-nov-reviewed-20261014"
START = date(2026, 7, 1)
END = date(2026, 11, 7)
SOURCE = "https://nsearchives.nseindia.com/content/circulars/CMTR71775.pdf"
TIMES_SOURCE = "https://www.nseindia.com/resources/exchange-communication-holidays"
CAS_SOURCE = "https://www.nseindia.com/static/products-services/closing-auction-session"
HOLIDAYS = {date(2026, 9, 14), date(2026, 10, 2), date(2026, 10, 20)}
CALENDAR_NOTE = ("Bundled calendar covers 1 July–7 November 2026 and was reviewed on 14 October. "
                 "Update it before the 8 November Muhurat session; special hours are not assumed. "
                 "Unannounced exchange changes still require a calendar update.")


def research_calendar(as_of: datetime, path=None):
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValidationError("Research cutoff must have a timezone")
    if path:
        calendar, raw = load_calendar(path, as_of=as_of)
        return calendar, raw, {"version": "user-supplied", "note": "Calendar supplied by this installation; review exchange changes."}
    if not START <= as_of.astimezone(IST).date() <= END:
        raise ValidationError(
            "Bundled NSE calendar covers 2026-07-01 through 2026-11-07. "
            "Install a calendar update, or use research --calendar PATH with a complete sourced calendar. "
            "The 2026-11-08 special session has not been assigned guessed hours.")
    calendar, session = {}, START
    while session <= END:
        if session.weekday() < 5 and session not in HOLIDAYS:
            calendar[session] = {
                "open_at": datetime.combine(session, time(9, 15), tzinfo=IST),
                # Whole-file EOD bar cutoff includes post-close trading, not just
                # the continuous session (CAS ends at 15:35 for eligible stocks).
                "close_at": datetime.combine(session, time(16, 0), tzinfo=IST),
            }
        session += timedelta(days=1)
    raw = {"coverage_start": str(START), "coverage_end": str(END), "source_uri": SOURCE,
           "sessions": [{"session": str(s), **{k: iso(v) for k, v in e.items()}}
                        for s, e in calendar.items()]}
    return calendar, raw, {"version": CALENDAR_VERSION, "note": CALENDAR_NOTE,
                           "reviewed_on": "2026-10-14", "times_source": TIMES_SOURCE,
                           "closing_auction_source": CAS_SOURCE,
                           "eod_cutoff_note": "16:00 IST is the whole-day bar cutoff including post-close trading, not the continuous-session close. Final-file availability is checked separately."}


def closed_window(calendar, as_of, size=60):
    closed = sorted(s for s, entry in calendar.items() if entry["close_at"] <= as_of)
    if len(closed) < size:
        raise ValidationError(f"Calendar needs at least {size} completed sessions; found {len(closed)}")
    return closed[-size:]
