"""Fictional fixtures; no network calls or model inference."""

from .contracts import DAILY_METRICS, FUNDAMENTAL_METRICS


def make_demo_bundle() -> dict:
    close_at = "2026-10-09T10:00:00Z"
    available = "2026-10-09T10:05:00Z"
    fundamental_at = "2026-08-12T04:30:00Z"
    news_at = "2026-10-08T06:00:00Z"
    event_at = "2026-10-07T06:00:00Z"
    sources = []
    for sid, kind, date in (
        ("demo-prices", "prices", available),
        ("demo-fundamentals", "fundamentals", fundamental_at),
        ("demo-news", "news", news_at),
        ("demo-announcements", "announcement", event_at),
    ):
        sources.append({
            "id": sid, "kind": kind, "title": f"Fictional {kind} fixture; not a real source",
            "uri": f"fixture://oraculum/{sid}", "published_at": date, "available_at": date,
            "content_sha256": None,
        })
    baseline = {
        "close_inr": 250.0, "turnover_20d_inr": 50_000_000.0,
        "volatility_20d_annualized": .24, "momentum_20d": .08, "trend_50d": .06,
        "volume_ratio_20d": 1.8, "roce": .26, "revenue_growth_yoy": .22,
        "debt_to_equity": .4, "pe_to_sector_median": .8,
        "news_sentiment": .6, "announcement_impact": .7,
    }
    cases = [
        ("SIM-ASTER", "industrials", {}),
        ("SIM-BANYAN", "technology", {"momentum_20d": .06, "news_sentiment": None,
                                     "announcement_impact": None}),
        ("SIM-CEDAR", "consumer", {"momentum_20d": 0, "trend_50d": 0, "volume_ratio_20d": 1,
                                   "roce": .2, "revenue_growth_yoy": .1, "debt_to_equity": 1,
                                   "pe_to_sector_median": 1, "news_sentiment": 0,
                                   "announcement_impact": 0, "volatility_20d_annualized": .2}),
        ("SIM-DUNE", "materials", {"momentum_20d": -.1, "trend_50d": -.08, "volume_ratio_20d": 3,
                                   "news_sentiment": -.7, "announcement_impact": -.8,
                                   "volatility_20d_annualized": .5}),
        ("SIM-EMBER", "energy", {"turnover_20d_inr": 200_000.0}),
        ("SIM-FERN", "healthcare", {"roce": None, "revenue_growth_yoy": None,
                                    "pe_to_sector_median": None, "news_sentiment": None,
                                    "announcement_impact": None}),
        ("SIM-GROVE", "financials", {}),
        ("SIM-HARBOR", "industrials", {"volatility_20d_annualized": .95}),
    ]
    assets = []
    for symbol, sector, changes in cases:
        metrics = {}
        for name, value in {**baseline, **changes}.items():
            if name in DAILY_METRICS:
                observed, known, sid = close_at, available, "demo-prices"
            elif name in FUNDAMENTAL_METRICS:
                observed, known, sid = "2026-06-30T10:00:00Z", fundamental_at, "demo-fundamentals"
            elif name == "news_sentiment":
                observed, known, sid = news_at, news_at, "demo-news"
            else:
                observed, known, sid = event_at, event_at, "demo-announcements"
            metrics[name] = {
                "value": value, "observed_at": observed, "available_at": known,
                "source_ids": [sid] if value is not None else [],
            }
        assets.append({"symbol": symbol, "exchange": "NSE", "sector": sector,
                       "session": "2026-10-09", "metrics": metrics})
    return {
        "schema_version": 1, "dataset_id": "oraculum-fictional-v1", "mode": "synthetic",
        "as_of": "2026-10-09T12:00:00Z", "last_session": "2026-10-09",
        "session_close_at": close_at, "sources": sources, "assets": assets,
    }
