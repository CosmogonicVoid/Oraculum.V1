"""Offline integration example: fictional CSV research to a virtual next-open fill.

Run from the project root with: python -m oraculum.paper.demo
The three-share quantity and next-session raw bar are explicit demo inputs,
not an allocation policy or downloaded market observations. No files are written.
"""
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import sys

from ..contracts import IST, ValidationError
from ..interfaces import PaperOrder, PortfolioState, PriceBar
from ..pipeline import build_run
from ..providers.csv_provider import build_merged_bundle
from .simulator import BasicPaperSimulator


def run_demo() -> dict:
    fixtures = Path(__file__).resolve().parents[2] / "examples" / "qwen"
    bundle = build_merged_bundle(fixtures / "prices.csv", fixtures / "base.json", fixtures / "sessions.json")
    report = build_run(bundle)
    if not report["shortlist"]:
        raise ValidationError("The fictional fixture has no candidate to demonstrate execution")
    instrument = report["shortlist"][0]
    order = PaperOrder("DEMO-PAPER-001", instrument, "buy", 3, bundle.as_of, report["run_id"])
    # Explicit supplied session; the simulator does not infer exchange holidays.
    bar = PriceBar(
        instrument_id=instrument, session=date(2026, 10, 12),
        open_at=datetime(2026, 10, 12, 9, 15, tzinfo=IST),
        close_at=datetime(2026, 10, 12, 15, 30, tzinfo=IST),
        available_at=datetime(2026, 10, 12, 15, 35, tzinfo=IST),
        open=Decimal("130"), high=Decimal("132"), low=Decimal("128"), close=Decimal("131"),
        volume=100000, turnover_inr=Decimal("13000000"),
        source_id="fictional-paper-session", adjustment_version="raw",
    )
    initial = PortfolioState(Decimal("10000.00"), ())
    simulator = BasicPaperSimulator()
    result = simulator.execute_session(initial, [order], [bar],
                                       fee_bps=Decimal("10"), slippage_bps=Decimal("10"))
    repeat = simulator.execute_session(result.state, [order], [bar],
                                       fee_bps=Decimal("10"), slippage_bps=Decimal("10"))
    return {
        "mode": "fictional paper-only demonstration",
        "signal_run_id": report["run_id"], "signal_as_of": bundle.as_of,
        "starting_cash_inr": initial.cash_inr,
        "order": asdict(order), "result": asdict(result),
        "repeat_rejections": [asdict(item) for item in repeat.rejections],
        "repeat_state_unchanged": repeat.state == result.state,
    }


def _json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Unsupported JSON value: {type(value).__name__}")


def main() -> int:
    try:
        print(json.dumps(run_demo(), default=_json_value, indent=2, allow_nan=False))
        return 0
    except (ValidationError, OSError) as exc:
        print(f"Oraculum error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
