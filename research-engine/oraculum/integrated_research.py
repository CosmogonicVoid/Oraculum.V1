"""Milestones 1 + 2: adjusted technical research with automatic filing evidence.

This enriches research only. It does not feed the separate buy/paper-order engine.
"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import time
from urllib.error import HTTPError

from .contracts import IST, UTC, ValidationError, day, iso, timestamp
from .corporate_actions import adjusted_series, linked_tail, parse_actions, parse_renames, rename_chain, symbol_at
from .features import annualized_volatility, mean_turnover, momentum, trend
from .financials import (INDUSTRY_URL, METRICS, attach_peer_comparisons, filing_key, filing_plan,
                         parse_industries, parse_xbrl, profile_from_filings, validate_filing)
from .market_calendar import closed_window
from .market_research import SETTINGS, build_research, max_drawdown, technical_score, write_json
from .nse_evidence import (MASTER_URL, RENAMES_URL, EvidenceStore, actions_url, catalogue_url,
                           download, evidence_reference, parse_catalogue, parse_master)
from .serialization import digest, load_json

SCHEMA = "oraculum-integrated-research-v1"
LIMITATIONS = [
    "Ranks and highlights use the disclosed technical heuristic only. Financial metrics and the separate financial screen do not change the score.",
    "No validated investment edge, return forecast or buy recommendation is established. This report cannot authorize paper orders.",
    "Only explicit exchange split, bonus and cash-dividend terms are adjusted. Unsupported, ambiguous or conflicting events block a stock's technical eligibility.",
    "Cash-dividend back-adjustment uses (previous close - dividend) / previous close; this is not an exact dividend-reinvestment return index.",
    "Corporate-action coverage depends on the exchange endpoint. Missing exchange events cannot be detected with certainty; raw extreme-move checks are not a substitute for complete coverage.",
    "Fundamental coverage fills in bounded resumable batches, prioritizing technical highlights and liquid stocks. Missing data is not a neutral value or a financial pass.",
    "Financial parsing currently supports nonfinancial IndAS instance XML. Bank, NBFC, insurance and other specialist schemas need separate models. Annual selection currently targets March year-ends; other annual periods are left unavailable.",
    "Annual P/E uses the latest supported full-year EPS, not TTM. Share actions after year-end withhold P/E pending comparability review. Borrowings/equity excludes lease liabilities.",
    "Industry mapping covers current Nifty Total Market constituents only. Peer valuation uses the available cached sample with at least five other matched peers, not a complete sector valuation.",
    "Universe is today's NSE EQ/STK/F1 rows, including supported ampersand symbols, not all historical listings or BSE. Survivorship bias and download-time availability prevent valid historical performance claims.",
    "News sentiment and non-financial corporate announcements remain unassessed. This is an end-of-day feed; public sources can be delayed, changed or unavailable.",
]


def build_adjusted(snapshots, calendar, calendar_raw, calendar_info, *, as_of, actions, renames, master):
    window = closed_window(calendar, as_of, SETTINGS["history_sessions"])
    for evidence in (actions, renames, master):
        if timestamp(evidence["received_at"], "receipt") > as_of:
            raise ValidationError("Adjustment/identity evidence not received by cutoff")
    action_data = actions["data"]
    if day(action_data["coverage_start"], "start") > window[0] or day(action_data["coverage_end"], "end") < window[-1]:
        raise ValidationError("Corporate-action source does not cover the price window")
    # Reuse existing complete-session/receipt validation and report envelope.
    report = build_research(snapshots, calendar, calendar_raw, calendar_info, as_of=as_of)
    maps = {day(s["session"], "session"): {r["symbol"]: r for r in s["rows"]} for s in snapshots}
    action_rows, changes, identities = action_data["actions"], renames["data"], master["data"]
    by_new, actions_by_symbol = defaultdict(list), defaultdict(list)
    for r in changes:
        by_new[r["new"]].append(r)
    for a in action_rows:
        actions_by_symbol[a["symbol"]].append(a)
    for asset in report["assets"]:
        symbol = asset["symbol"]
        chain = rename_chain(symbol, window[-1], by_new)
        aliases = {symbol} | {r["old"] for r in chain}
        stock_actions = [a for name in aliases for a in actions_by_symbol[name]]
        tail, blockers, warnings = linked_tail(symbol, maps, window, chain, stock_actions)
        prices, volumes, action_blocks, applied = adjusted_series(symbol, tail, window, stock_actions, chain)
        blockers += action_blocks
        latest = maps[window[-1]][symbol]
        identity = identities.get(symbol)
        asset["isin"], asset["company_name"] = latest.get("isin"), latest.get("company_name", symbol)
        if identity and latest.get("isin") and identity["isin"] != latest["isin"]:
            blockers.append("Latest price identity differs from security master; review required")
        closes = [float(x) for x in prices]
        recent = prices[-50:]
        average_volume = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else None
        raw_prices = [Decimal(r["close"]) for _, r in tail]
        metrics = {
            "close_inr": float(latest["close"]), "momentum_20d": momentum(closes), "trend_50d": trend(closes),
            "volume_ratio_20d": float(volumes[-1] / average_volume) if average_volume else None,
            "turnover_20d_inr": mean_turnover([float(r["turnover_inr"]) for _, r in tail]),
            "volatility_20d_annualized": annualized_volatility(closes),
            "return_1d": closes[-1]/closes[-2]-1 if len(closes) >= 2 else None,
            "raw_return_1d": float(raw_prices[-1]/raw_prices[-2]-1) if len(raw_prices) >= 2 else None,
            "drawdown_50d": max_drawdown(closes[-50:]) if len(closes) >= 50 else None,
            "max_absolute_daily_move_50d": float(max(abs(b/a-1) for a,b in zip(recent,recent[1:]))) if len(recent) == 50 else None}
        if len(tail) < 50:
            blockers.append(f"Only {len(tail)} consecutive traded sessions; 50 required")
        if metrics["turnover_20d_inr"] is not None and metrics["turnover_20d_inr"] < 50_000_000:
            blockers.append("20-session average turnover below INR 5 crore")
        if metrics["volatility_20d_annualized"] is not None and metrics["volatility_20d_annualized"] > .8:
            blockers.append("Annualized 20-session volatility exceeds 80%")
        if metrics["max_absolute_daily_move_50d"] is not None and metrics["max_absolute_daily_move_50d"] >= .2:
            blockers.append("At least one adjusted daily move is 20% or larger; extreme move or missing action review required")
        required = ("momentum_20d", "trend_50d", "volume_ratio_20d", "volatility_20d_annualized")
        if not blockers and any(metrics[k] is None for k in required):
            blockers.append("Insufficient valid adjusted feature observations")
        score, components = (None, {}) if blockers else technical_score(metrics)
        reasons = []
        if not blockers:
            reasons = [f"Adjusted 20-session price change {metrics['momentum_20d']:+.2%}",
                       f"Close {metrics['trend_50d']:+.2%} versus adjusted 50-session mean",
                       f"Split/bonus-adjusted volume {metrics['volume_ratio_20d']:.2f}x prior 20-session mean",
                       f"Actual 20-session turnover INR {metrics['turnover_20d_inr']/1e7:.2f} crore/day"]
            if metrics["volatility_20d_annualized"] > .4:
                warnings.append("High recent price volatility")
            if metrics["trend_50d"] > .15:
                warnings.append("Price more than 15% above adjusted mean; possible overextension")
        asset.update(metrics=metrics, score=score, components=components, blockers=blockers, warnings=warnings,
                     reasons=reasons, status="excluded" if blockers else "eligible", rank=None, highlight=False,
                     consecutive_sessions=len(tail), adjustments=applied,
                     symbol_history=chain,
                     adjustment_status="blocked" if action_blocks else "supported_events_applied" if applied else "no_events_in_traded_tail")
    eligible = sorted((a for a in report["assets"] if not a["blockers"]), key=lambda a: (-a["score"], a["symbol"]))
    for rank, asset in enumerate(eligible, 1):
        asset["rank"] = rank
    positive = [a for a in eligible if a["metrics"]["momentum_20d"] > 0 and a["metrics"]["trend_50d"] > 0 and a["score"] >= 55]
    for asset in positive[:10]:
        asset["highlight"] = True
    report["assets"].sort(key=lambda a: (a["rank"] is None, a["rank"] or 0, a["symbol"]))
    moves = [a["metrics"]["raw_return_1d"] for a in report["assets"] if a["metrics"]["raw_return_1d"] is not None]
    report.update(report_schema=SCHEMA, algorithm="nse-adjusted-technical-with-filings-v1", limitations=list(LIMITATIONS),
                  highlights=[a["instrument_id"] for a in positive[:10]],
                  exclusion_counts=dict(Counter(b for a in report["assets"] for b in a["blockers"])))
    report["counts"].update(eligible=len(eligible), excluded=len(report["assets"])-len(eligible), positive_setups=len(positive), highlights=min(10,len(positive)),
        advanced=sum(x>0 for x in moves), declined=sum(x<0 for x in moves), unchanged=sum(x==0 for x in moves), breadth_observations=len(moves),
        adjusted_stocks=sum(bool(a["adjustments"]) for a in report["assets"]), action_blocked=sum(a["adjustment_status"] == "blocked" for a in report["assets"]))
    report["coverage"].update(corporate_action_adjustments="supported_events_only", fundamentals="pending")
    report["adjustment_coverage"] = {"start": action_data["coverage_start"], "end": action_data["coverage_end"], "events": len(action_rows),
                                     "price_method": "backward factors; raw execution quotes preserved"}
    report["evidence_sources"] = [evidence_reference(e) for e in (actions, renames, master)]
    report["report_id"] = digest({k:v for k,v in report.items() if k != "report_id"})
    return report


def integrate(folder, store, calendar, raw, info, window, *, offline=False, max_filings=60, progress=print,
              clock=None, downloader=None, pause=None):
    if type(max_filings) is not int or not 0 <= max_filings <= 10000:
        raise ValidationError("max-filings must be between 0 and 10000")
    folder = Path(folder)
    clock, downloader, pause = clock or (lambda: datetime.now(UTC)), downloader or download, pause or time.sleep
    cache = EvidenceStore(folder / "evidence.sqlite3")
    today = clock().astimezone(IST).date()
    ttl = timedelta(hours=24)
    start = today - timedelta(days=450)
    shared = {"offline": offline, "clock": clock, "downloader": downloader, "max_age": ttl}
    progress("Loading official security identities, symbol changes and corporate actions...")
    master = cache.fetch("master", "equity", MASTER_URL, parse_master, **shared)
    renames = cache.fetch("renames", "equity", RENAMES_URL, parse_renames, **shared)
    action_key = f"{start}:{today}"
    actions = cache.fetch("actions", action_key, actions_url(start, today), lambda b: parse_actions(b,start,today), **shared)
    progress("Loading the financial filing catalogue (individual documents resume from cache)...")
    catalogue = cache.fetch("catalogue", str(today), catalogue_url(today), parse_catalogue, **shared)
    warnings = []
    industries = None
    try:
        industries = cache.fetch("industries", "nifty-total-market", INDUSTRY_URL, parse_industries, **shared)
    except (OSError, ValidationError) as exc:
        warnings.append(f"Industry mapping unavailable: {exc}; peer comparison withheld")
    snapshots = store.research_snapshots(start=window[0], end=window[-1])
    report = build_adjusted(snapshots, calendar, raw, info, as_of=clock(), actions=actions, renames=renames, master=master)
    report["evidence_sources"].append(evidence_reference(catalogue))
    if industries:
        report["evidence_sources"].append(evidence_reference(industries))
    attempts_path = folder / "fundamental-attempts.json"
    from .filing_policy import read_attempts, failure_record, provider_pause
    attempts = read_attempts(attempts_path, clock())
    blocked_until = provider_pause(attempts)
    if blocked_until:
        warnings.append(f"Filing provider cooldown until {blocked_until}; cached evidence is used without new filing requests")
    indexed = defaultdict(list)
    for record in catalogue["data"]:
        indexed[record["symbol"]].append(record)
    downloaded, failed, pending_urls, memo, halted = 0, 0, set(), {}, bool(blocked_until)
    candidates = sorted(report["assets"], key=lambda a: (not a["highlight"], a["rank"] is None,
                        -(a["metrics"].get("turnover_20d_inr") or 0), a["symbol"]))
    for asset_index, asset in enumerate(candidates, 1):
        if asset_index == 1 or asset_index % 100 == 0:
            progress(f"Financial profiles [{asset_index}/{len(candidates)}]: {downloaded} documents downloaded, {failed} failed; cached evidence reused.")
        symbol = asset["symbol"]
        aliases = {symbol} | {r["old"] for r in asset["symbol_history"]}
        records = [r for alias in aliases for r in indexed[alias]]
        plan = filing_plan(records, aliases, as_of=clock())
        available = {}
        notes = []
        identity = master["data"].get(symbol)
        if not identity or not asset["isin"] or identity["isin"] != asset["isin"]:
            plan = {"status": "identity_review", "records": {}, "notes": ["No matching current master/price ISIN; automatic filing join withheld"]}
        for role, record in plan["records"].items():
            url, key = record["url"], filing_key(record)
            publication_day = timestamp(record["published_at"], "publication").astimezone(IST).date()
            allowed_symbols = {symbol_at(symbol, publication_day, window[-1], asset["symbol_history"])}
            if key not in memo:
                memo[key] = cache.latest("filing", key, as_of=clock())
                if memo[key] is None and not offline and not halted and downloaded+failed < max_filings and key not in attempts:
                    progress(f"Financial filing [{downloaded+failed+1}/{max_filings}]: {symbol} {record['period_end']} {record['basis']}")
                    pause(.35)
                    try:
                        def parse(content, rec=record, isin=asset["isin"], allowed=allowed_symbols):
                            data = parse_xbrl(content)
                            validate_filing(data, rec, isin, allowed_symbols=allowed)
                            return data
                        memo[key] = cache.fetch("filing", key, url, parse, clock=clock, downloader=downloader)
                        downloaded += 1
                    except (OSError, ValidationError) as exc:
                        failed += 1
                        attempts[key] = failure_record(exc, clock())
                        if isinstance(exc, HTTPError) and exc.code in (401,403,429):
                            halted = True
                            warnings.append(f"Exchange denied or rate-limited filings ({exc.code}); batch stopped without retries")
                        # Persist cooldown and completed evidence even if this run is interrupted.
                        write_json(attempts_path, attempts)
            evidence = memo[key]
            if evidence:
                try:
                    validate_filing(evidence["data"], record, asset["isin"], allowed_symbols=allowed_symbols)
                    available[role] = evidence
                except ValidationError as exc:
                    notes.append(str(exc))
            else:
                pending_urls.add(key)
                notes.append(f"{role}: " + (attempts[key]["error"] if key in attempts else "not cached yet; rerun integrated research to resume"))
        profile = profile_from_filings(plan, available, close=asset["metrics"]["close_inr"], today=today, symbol=symbol,
                                       actions=actions["data"]["actions"], action_start=start, aliases=aliases)
        profile["notes"].extend(sorted(set(notes)))
        if industries:
            industry = industries["data"].get(symbol)
            if industry and industry["isin"] == asset["isin"]:
                profile["industry"] = industry["industry"]
                profile["industry_source_id"] = industries["source_id"]
                profile["industry_available_at"] = industries["received_at"]
        # P/E availability includes raw price, catalogue, and action-comparability evidence.
        for metric in profile["metrics"].values():
            if metric:
                metric["source_ids"] = sorted(set(metric["source_ids"] + [catalogue["source_id"], master["source_id"], renames["source_id"]]))
                metric["available_at"] = iso(max(timestamp(metric["available_at"], "availability"), timestamp(catalogue["received_at"], "receipt"), timestamp(master["received_at"], "receipt"), timestamp(renames["received_at"], "receipt")))
        pe = profile["metrics"]["annual_pe"]
        if pe:
            price_source = report["sources"][-1]
            pe["source_ids"] = sorted(set(pe["source_ids"] + [price_source["source_id"], actions["source_id"]]))
            pe["available_at"] = iso(max(timestamp(pe["available_at"],"availability"), timestamp(price_source["received_at"],"receipt"), timestamp(actions["received_at"],"receipt")))
        asset["fundamentals"] = profile
    attach_peer_comparisons(report["assets"])
    statuses = Counter(a["fundamentals"]["status"] for a in report["assets"])
    metric_counts = {m:sum(a["fundamentals"]["metrics"][m] is not None for a in report["assets"]) for m in METRICS}
    report["fundamental_coverage"] = {"statuses": dict(statuses), "metrics": metric_counts, "downloaded_this_run": downloaded,
                                      "failed_this_run": failed, "pending_documents": len(pending_urls), "batch_limit": max_filings,
                                      "cooldown_documents": len(attempts), "provider_retry_at": provider_pause(attempts),
                                      "collection_mode": "offline" if offline else "provider_cooldown" if halted else "bounded_online",
                                      "financial_screen_passes": sum(a["fundamentals"]["financial_screen"] == "passes" for a in report["assets"])}
    report["coverage"]["fundamentals"] = "partial" if any(metric_counts.values()) else "no_usable_metrics_yet"
    report["refresh_warnings"] = warnings
    report["as_of"] = iso(clock())
    if closed_window(calendar, timestamp(report["as_of"],"cutoff")) != window:
        raise ValidationError("A new session closed during filing refresh. Rerun to include its price file.")
    report["report_id"] = digest({k:v for k,v in report.items() if k != "report_id"})
    progress(f"Financial coverage: {statuses.get('available',0)} with all four screen metrics; {statuses.get('partial',0)} partial; {len(pending_urls)} uncached documents remain.")
    from .combined_ranking import apply_combined_ranking
    return apply_combined_ranking(report)
