# oraculum/features.py
"""Point-in-time price/volume features (Qwen assignment, Part A).

Pure numerical helpers plus BasicPriceFeatureBuilder, an implementation of the
PriceFeatureBuilder port declared in oraculum.interfaces.

Shared rules for every function in this module:

* Inputs are ordered oldest-first; only the most recent required window is used.
* Insufficient history returns None; malformed inputs raise ValidationError.
* Booleans, non-finite values, non-positive closes, negative volumes or
  turnover, and non-positive or non-integer window sizes are rejected.
* Volatility requires at least 2 return periods.
* Input sequences are never mutated and missing observations are never imputed.
* Prices carry whatever corporate-action treatment the provider supplied via
  PriceBar.adjustment_version; the builder requires one consistent version per
  instrument. See docs/QWEN_IMPLEMENTATION.md for the disclosure.
"""
from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from datetime import date, datetime
from decimal import Decimal

from .contracts import DAILY_METRICS, IST, ValidationError, iso
from .interfaces import PriceBar

_ANNUALIZATION = math.sqrt(252.0)


def _window_size(value: object, name: str, *, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValidationError(f"{name}: expected an integer >= {minimum}")
    return value


def _numeric(values: Sequence[object], name: str, *, kind: str, positive: bool = False) -> list[float]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValidationError(f"{name}: expected a sequence of numbers")
    result: list[float] = []
    for index, item in enumerate(values):
        if kind == "volume":
            if type(item) is not int or item < 0:
                raise ValidationError(f"{name}[{index}]: expected a non-negative integer volume")
        elif isinstance(item, bool) or not isinstance(item, (int, float)):
            raise ValidationError(f"{name}[{index}]: expected a finite number")
        try:
            value = float(item)
        except (ValueError, OverflowError) as exc:
            raise ValidationError(f"{name}[{index}]: number exceeds supported range") from exc
        if not math.isfinite(value):
            raise ValidationError(f"{name}[{index}]: expected a finite number")
        if positive and value <= 0:
            raise ValidationError(f"{name}[{index}]: must be positive")
        if not positive and value < 0:
            raise ValidationError(f"{name}[{index}]: must not be negative")
        result.append(value)
    return result


def _finite_result(value: float) -> float:
    if not math.isfinite(value):
        raise ValidationError("feature result exceeds supported numeric range")
    return value


def _aware(value: object, path: str) -> None:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{path}: a datetime with timezone is required")


def momentum(closes: Sequence[float], periods: int = 20) -> float | None:
    """closes[-1] / closes[-(periods + 1)] - 1 on the most recent window."""
    size = _window_size(periods, "periods")
    series = _numeric(closes, "closes", kind="close", positive=True)
    if len(series) < size + 1:
        return None
    return _finite_result(series[-1] / series[-(size + 1)] - 1.0)


def trend(closes: Sequence[float], window: int = 50) -> float | None:
    """closes[-1] / mean(closes[-window:]) - 1."""
    size = _window_size(window, "window")
    series = _numeric(closes, "closes", kind="close", positive=True)
    if len(series) < size:
        return None
    recent = series[-size:]
    return _finite_result(series[-1] / statistics.mean(recent) - 1.0)


def volume_ratio(volumes: Sequence[int], window: int = 20) -> float | None:
    """volumes[-1] / mean(volumes[-(window + 1):-1]); None if the mean is zero."""
    size = _window_size(window, "window")
    series = _numeric(volumes, "volumes", kind="volume")
    if len(series) < size + 1:
        return None
    denominator = statistics.mean(series[-(size + 1):-1])
    if denominator == 0:
        return None
    return _finite_result(series[-1] / denominator)


def annualized_volatility(closes: Sequence[float], periods: int = 20) -> float | None:
    """Sample standard deviation (ddof=1) of the last `periods` simple returns x sqrt(252).

    Needs periods + 1 closes. `periods` must be an integer >= 2.
    """
    size = _window_size(periods, "periods", minimum=2)
    series = _numeric(closes, "closes", kind="close", positive=True)
    if len(series) < size + 1:
        return None
    window = series[-(size + 1):]
    returns = [_finite_result(window[i] / window[i - 1] - 1.0) for i in range(1, size + 1)]
    try:
        return _finite_result(statistics.stdev(returns) * _ANNUALIZATION)
    except OverflowError as exc:
        raise ValidationError("volatility exceeds supported numeric range") from exc


def mean_turnover(turnovers: Sequence[float], window: int = 20) -> float | None:
    """Mean of the last `window` actual traded INR turnover values.

    Never approximates turnover by price times volume: the provider supplies
    actual traded turnover.
    """
    size = _window_size(window, "window")
    series = _numeric(turnovers, "turnovers", kind="turnover")
    if len(series) < size:
        return None
    return _finite_result(statistics.mean(series[-size:]))


class BasicPriceFeatureBuilder:
    """PriceFeatureBuilder implementation over point-in-time PriceBar history.

    The builder assumes the provider has already restricted `bars` to a
    contiguous run of exchange sessions for one instrument (the CSV provider
    checks this against its supplied calendar). Cutoff filtering, instrument
    and adjustment-version consistency, bar validity and duplicate-session
    detection are enforced here as well, so the builder is safe standalone.
    """

    def build_metrics(self, bars: Sequence[PriceBar], *, as_of: datetime) -> dict:
        _aware(as_of, "as_of")
        if not isinstance(bars, Sequence) or isinstance(bars, (str, bytes)):
            raise ValidationError("bars: expected a sequence of PriceBar objects")
        # Validate timestamp types before comparing them with the cutoff.
        for index, bar in enumerate(bars):
            if not isinstance(bar, PriceBar):
                raise ValidationError(f"bars[{index}]: expected a PriceBar")
            for label in ("open_at", "close_at", "available_at"):
                _aware(getattr(bar, label), f"bars[{index}].{label}")
        eligible = [bar for bar in bars if bar.available_at <= as_of and bar.close_at <= as_of]
        if not eligible:
            return {}
        self._validate(eligible)
        eligible.sort(key=lambda bar: bar.session)
        for earlier, later in zip(eligible, eligible[1:]):
            if earlier.session == later.session:
                raise ValidationError(f"bars: duplicate session {earlier.session.isoformat()}")

        closes = _numeric([float(bar.close) for bar in eligible], "closes", kind="close", positive=True)
        volumes = [bar.volume for bar in eligible]
        _numeric(volumes, "volumes", kind="volume")
        turnovers = _numeric([float(bar.turnover_inr) for bar in eligible], "turnovers", kind="turnover")
        latest = eligible[-1]
        observed_at = latest.close_at
        floor = max(observed_at, latest.available_at)

        plans = (
            ("close_inr", 1, lambda: closes[-1], (latest,)),
            ("turnover_20d_inr", 20, lambda: mean_turnover(turnovers, 20), tuple(eligible[-20:])),
            ("volatility_20d_annualized", 21, lambda: annualized_volatility(closes, 20), tuple(eligible[-21:])),
            ("momentum_20d", 21, lambda: momentum(closes, 20), tuple(eligible[-21:])),
            ("trend_50d", 50, lambda: trend(closes, 50), tuple(eligible[-50:])),
            ("volume_ratio_20d", 21, lambda: volume_ratio(volumes, 20), tuple(eligible[-21:])),
        )
        if {name for name, _, _, _ in plans} != set(DAILY_METRICS):
            raise AssertionError("feature plans drifted from contracts.DAILY_METRICS")

        metrics: dict = {}
        for name, required, compute, used in plans:
            if len(eligible) < required:
                value, source_ids = None, []
            else:
                value = compute()
                source_ids = sorted({bar.source_id for bar in used}) if value is not None else []
            available_at = max([floor] + [bar.available_at for bar in used])
            metrics[name] = {
                "value": value,
                "observed_at": iso(observed_at),
                "available_at": iso(available_at),
                "source_ids": source_ids,
            }
        return metrics

    @staticmethod
    def _validate(bars: list[PriceBar]) -> None:
        instrument = bars[0].instrument_id
        version = bars[0].adjustment_version
        for bar in bars:
            if type(bar.session) is not date:
                raise ValidationError("bar.session: expected an exchange session date")
            path = f"bar {bar.instrument_id} {bar.session.isoformat()}"
            for label in ("instrument_id", "source_id"):
                value = getattr(bar, label)
                if not isinstance(value, str) or not value.strip():
                    raise ValidationError(f"{path}.{label}: expected nonempty text")
            if bar.instrument_id != instrument:
                raise ValidationError("bars: all bars must reference one instrument")
            if bar.adjustment_version != version:
                raise ValidationError(
                    f"{path}: inconsistent adjustment_version {bar.adjustment_version!r}; expected {version!r}"
                )
            if not isinstance(bar.adjustment_version, str) or not bar.adjustment_version.strip():
                raise ValidationError(f"{path}: adjustment_version must be nonempty text")
            for label, stamp in (("open_at", bar.open_at), ("close_at", bar.close_at),
                                 ("available_at", bar.available_at)):
                if stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise ValidationError(f"{path}.{label}: timezone is required")
            if not bar.open_at < bar.close_at <= bar.available_at:
                raise ValidationError(f"{path}: require open_at < close_at <= available_at")
            if any(stamp.astimezone(IST).date() != bar.session for stamp in (bar.open_at, bar.close_at)):
                raise ValidationError(f"{path}: open_at/close_at must match the session date in India")
            if type(bar.volume) is not int or bar.volume < 0:
                raise ValidationError(f"{path}: volume must be a non-negative integer")
            for label, amount in (("open", bar.open), ("high", bar.high), ("low", bar.low),
                                  ("close", bar.close), ("turnover_inr", bar.turnover_inr)):
                if not isinstance(amount, Decimal) or not amount.is_finite():
                    raise ValidationError(f"{path}.{label}: expected a finite Decimal")
            if bar.open <= 0 or bar.high <= 0 or bar.low <= 0 or bar.close <= 0:
                raise ValidationError(f"{path}: OHLC prices must be positive")
            if bar.turnover_inr < 0:
                raise ValidationError(f"{path}: turnover_inr must not be negative")
            if (bar.high < bar.low or bar.high < bar.open or bar.high < bar.close
                    or bar.low > bar.open or bar.low > bar.close):
                raise ValidationError(f"{path}: OHLC geometry violated (require low <= open/close <= high)")
