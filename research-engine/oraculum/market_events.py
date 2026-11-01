"""Resumable event refresh; optional evidence never changes the scoring policy."""
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import sqlite3
from urllib.error import HTTPError

from .contracts import UTC, ValidationError, iso, timestamp
from .event_sources import FEEDS, download_feed, feed_url
from .event_store import EventStore
from .market_research import workflow_lock


def event_status(folder, *, now=None):
    now = now or datetime.now(UTC)
    store = EventStore(Path(folder)/"events.sqlite3")
    try:
        states = store.states()
        identity, cursor = store.identity(), store.cursor()
    except (OSError,ValueError,OverflowError,sqlite3.Error) as exc:
        return {"initialized":store.path.exists(),"sources":[],"cursor":0,"store_identity":None,"error":str(exc)[:800],"as_of":iso(now)}
    sources = []
    for feed in FEEDS:
        state = states.get(feed["id"], {})
        success = state.get("last_success_at")
        stale = not success or now-timestamp(success,"last event refresh") > timedelta(hours=36)
        sources.append({"feed_id":feed["id"], "name":feed["name"],"kind":feed["kind"],"home":feed["home"],
                        **state,"stale":stale,"state":state.get("state","not_started")})
    return {"initialized":store.path.exists(),"sources":sources,"as_of":iso(now),"cursor":cursor,"store_identity":identity,
            "coverage":"NSE seven-day announcement window, rolling board RSS and Economic Times stock RSS; partial coverage, not an archive of all market news."}


def retry_delay(exc, now):
    delay = timedelta(hours=24 if isinstance(exc,HTTPError) and exc.code in (401,403,429) else 1)
    header = exc.headers.get("Retry-After") if isinstance(exc,HTTPError) and exc.headers else None
    if header:
        try:
            if header.strip().isdigit():
                extra = timedelta(seconds=min(int(header),86400*7))
            else:
                stamp = parsedate_to_datetime(header)
                extra = stamp.astimezone(UTC)-now if stamp.tzinfo else timedelta()
            delay = max(delay,min(extra,timedelta(days=7)))
        except (ValueError,OverflowError,TypeError):
            pass
    return delay


def refresh_events(folder, assets, *, offline=False, clock=None, downloader=None, progress=print, feeds=None):
    clock = clock or (lambda:datetime.now(UTC))
    downloader = downloader or download_feed
    store = EventStore(Path(folder)/"events.sqlite3")
    feeds = FEEDS if feeds is None else feeds
    if offline:
        result = event_status(folder,now=clock())
        result["mode"] = "offline"
        progress("News: offline; using existing event receipts only.")
        return result
    with workflow_lock(Path(folder)/"events"):
        states = store.states()
        for feed in feeds:
            now = clock()
            previous = states.get(feed["id"],{})
            next_at = previous.get("next_attempt_at")
            if next_at and now < timestamp(next_at,"next event attempt"):
                progress(f"News: {feed['name']} cached/cooling down until {next_at}.")
                continue
            url = feed_url(feed,now)
            state = {**previous,"state":"refreshing","last_attempt_at":iso(now),"request_url":url,"error":None}
            # A crashed process cannot hammer a failed provider on immediate restart.
            state["next_attempt_at"] = iso(now+timedelta(hours=1))
            store.set_state(feed["id"],state)
            try:
                progress(f"News: collecting {feed['name']}...")
                raw = downloader(url)
                received = clock()  # Actual receipt; never substitute the publication date.
                counts = store.ingest(raw,feed,url,assets,received_at=received)
                state.update(state="ready",last_success_at=iso(received),error=None,counts=counts,
                             next_attempt_at=iso(received+timedelta(hours=2)))
                progress(f"News: {feed['name']}: {counts['accepted']} items, {counts['new_revisions']} new/revised, {counts['matched_items']} matched; {counts['skipped']} skipped.")
            except (OSError,ValidationError,ValueError,OverflowError) as exc:
                ended = clock()
                state.update(state="failed",error=(str(exc) or type(exc).__name__)[:800],
                             next_attempt_at=iso(ended+retry_delay(exc,ended)))
                progress(f"News: {feed['name']} unavailable; cached items kept. {state['error']}")
            store.set_state(feed["id"],state)
    return {**event_status(folder,now=clock()),"mode":"online"}


def collect_report_events(folder, report, *, offline=False, clock=None, progress=print):
    clock = clock or (lambda:datetime.now(UTC))
    try:
        status = refresh_events(folder,report["assets"],offline=offline,clock=clock,progress=progress)
        if status.get("error"):
            raise ValidationError(status["error"])
        cutoff = clock()
        store = EventStore(Path(folder)/"events.sqlite3")
        total = store.query(as_of=cutoff,cursor=status["cursor"],limit=1)["total"]
        matched = store.query(as_of=cutoff,cursor=status["cursor"],match="matched",limit=1)["total"]
        return {**status,"as_of":iso(cutoff),"state":"partial" if any(s["stale"] or s["state"] != "ready" for s in status["sources"]) else "ready",
                "items_30d":total,"matched_items_30d":matched,"scored":False}
    except (OSError,ValueError,OverflowError,sqlite3.Error) as exc:
        progress(f"News evidence unavailable: {exc}. Continuing price/fundamental research.")
        return {"state":"unavailable","as_of":iso(clock()),"cursor":0,"error":str(exc)[:800],"scored":False}


def report_events(folder, report, *, symbol="", isin="", limit=30, **filters):
    coverage = report.get("event_coverage")
    if not coverage or coverage.get("state") == "unavailable":
        return {"items":[],"total":0,"next_offset":None,"offset":0,"days":30,"as_of":report["as_of"],
                "notice":"No news snapshot was captured for this report. Open News for the current collection."}
    try:
        store = EventStore(Path(folder)/"events.sqlite3")
        if store.identity() != coverage.get("store_identity") or (coverage["cursor"] and not store.path.exists()):
            raise ValidationError("The event database for this report is unavailable; rankings remain intact")
        return store.query(as_of=coverage["as_of"],cursor=coverage["cursor"],symbol=symbol,isin=isin,limit=limit,**filters)
    except (OSError,ValueError,OverflowError,sqlite3.Error) as exc:
        return {"items":[],"total":0,"next_offset":None,"offset":0,"days":30,"as_of":coverage["as_of"],"notice":str(exc)[:800]}

