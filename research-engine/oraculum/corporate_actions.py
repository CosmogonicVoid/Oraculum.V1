"""Explicit split/bonus/cash-dividend adjustments; raw execution prices stay intact."""
from collections import defaultdict
from decimal import Decimal, localcontext
import json
import re

from .contracts import ValidationError, day
from .nse_evidence import SYMBOL, csv_rows, exchange_date
from .serialization import digest


def parse_renames(raw):
    rows = csv_rows(raw, {"OLD SYMBOL", "NEW SYMBOL", "EFFECTIVE DATE"})
    result, seen = [], set()
    for r in rows:
        old, new = r["OLD SYMBOL"], r["NEW SYMBOL"]
        if not SYMBOL.fullmatch(old) or not SYMBOL.fullmatch(new) or old == new:
            continue
        effective = str(exchange_date(r["EFFECTIVE DATE"]))
        key = old, new, effective
        if key not in seen:
            result.append({"old": old, "new": new, "effective": effective})
            seen.add(key)
    return result


def action_terms(subject):
    """Parse only explicit supported exchange wording. Ambiguity is a blocker."""
    clean = re.sub(r"\s+", " ", subject.strip())
    bonus = re.fullmatch(r"Bonus\s+(\d+)\s*:\s*(\d+)", clean, re.I)
    if bonus:
        new, old = map(int, bonus.groups())
        if new <= 0 or old <= 0:
            return {"kind": "unsupported", "reason": "Invalid bonus ratio"}
        return {"kind": "bonus", "numerator": old, "denominator": old + new}
    split = re.fullmatch(r"(?:Face Value )?(?:Split \(Sub-Division\)|Split|Consolidation)(?:\s*-)?\s*From\s*(?:Rs\.?|Re\.?)\s*(\d+(?:\.\d+)?)(?:/-)?\s*Per Share\s*To\s*(?:Rs\.?|Re\.?)\s*(\d+(?:\.\d+)?)(?:/-)?\s*Per Share", clean, re.I)
    if split:
        old, new = map(Decimal, split.groups())
        if not old.is_finite() or not new.is_finite() or min(old, new) <= 0:
            return {"kind": "unsupported", "reason": "Invalid split face values"}
        return {"kind": "split", "numerator": str(new), "denominator": str(old)}
    # Multiple cash dividends explicitly stated in the same entry can be added.
    dividend_pattern = r"(?:(?:Interim|Final|Special) )?Dividend\s*-\s*(?:(?:Rs\.?|Re\.?)\s*)?([\d,]+(?:\.\d+)?)(?:/-)?\s*Per Share"
    dividends = re.findall(dividend_pattern, clean, re.I)
    remainder = re.sub(dividend_pattern, "", clean, flags=re.I)
    remainder = re.sub(r"Annual General Meeting|AGM|[ /&+;,-]", "", remainder, flags=re.I)
    if dividends and not remainder:
        amount = sum(Decimal(x.replace(",", "")) for x in dividends)
        if 0 < amount < Decimal("1000000"):
            return {"kind": "dividend", "cash_inr": str(amount)}
    if re.fullmatch(r"(?:Annual General Meeting|AGM|Extra Ordinary General Meeting)", clean, re.I):
        return {"kind": "meeting"}
    return {"kind": "unsupported", "reason": "Action requires manual economic/ratio review"}


def parse_actions(raw, start, end):
    try:
        rows = json.loads(raw)
    except (UnicodeError, ValueError) as exc:
        raise ValidationError("Corporate-action source did not return JSON") from exc
    if not isinstance(rows, list) or len(rows) > 100_000:
        raise ValidationError("Corporate-action response schema changed")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict) or not {"symbol", "series", "exDate", "subject"}.issubset(row):
            raise ValidationError("Corporate-action row missing required fields")
        symbol = row["symbol"]
        if row["series"] != "EQ" or not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol):
            continue
        ex_date = exchange_date(row["exDate"])
        if not start <= ex_date <= end:
            raise ValidationError("Exchange returned an action outside the requested window")
        subject = row["subject"]
        if not isinstance(subject, str) or not subject.strip() or len(subject) > 3000:
            raise ValidationError("Invalid corporate-action subject")
        terms = action_terms(subject)
        action = {"symbol": symbol, "ex_date": str(ex_date), "subject": subject,
                  "isin": row.get("isin") or "", **terms}
        identity = digest(action)
        if identity not in seen:
            result.append({**action, "action_id": identity})
            seen.add(identity)
    return {"coverage_start": str(start), "coverage_end": str(end), "actions": result}


def symbol_at(symbol, session, latest, renames):
    current, upper, seen = symbol, latest, set()
    for _ in range(30):
        candidates = [r for r in renames if r["new"] == current
                      and str(session) < r["effective"] <= str(upper)]
        if not candidates:
            return current
        nearest = max(r["effective"] for r in candidates)
        choices = {r["old"] for r in candidates if r["effective"] == nearest}
        if len(choices) != 1 or current in seen:
            raise ValidationError("Ambiguous/cyclic symbol-change history")
        seen.add(current)
        current, upper = choices.pop(), day(nearest, "rename date")
    raise ValidationError("Too many chained symbol changes")


def rename_chain(symbol, latest, by_new):
    """Restrict joins to the dated backwards chain, using a pre-indexed master."""
    result, current, upper, seen = [], symbol, str(latest), set()
    for _ in range(30):
        candidates = [r for r in by_new.get(current, []) if r["effective"] <= upper]
        if not candidates:
            return result
        nearest = max(r["effective"] for r in candidates)
        choices = [r for r in candidates if r["effective"] == nearest]
        if len({r["old"] for r in choices}) != 1 or current in seen:
            raise ValidationError("Ambiguous/cyclic symbol-change chain")
        row = choices[0]
        result.append(row)
        seen.add(current)
        current, upper = row["old"], row["effective"]
    raise ValidationError("Too many chained symbol changes")


def linked_tail(symbol, snapshots, window, renames, actions):
    """Join dated official aliases; never join unrelated securities by name."""
    rows, warnings, blockers = [], [], []
    for session in reversed(window):
        alias = symbol_at(symbol, session, window[-1], renames)
        row = snapshots[session].get(alias)
        if row is None:
            break
        if rows:
            later_session, later = rows[-1]
            if row.get("isin") and later.get("isin") and row["isin"] != later["isin"]:
                authorized = any(a["ex_date"] == str(later_session) and a["kind"] in ("split", "bonus")
                                 and a["symbol"] in (alias, later["symbol"], symbol) for a in actions)
                if not authorized:
                    blockers.append("ISIN changed without a supported corporate action; history needs review")
                    break
        rows.append((session, row))
    rows.reverse()
    if any(row["symbol"] != symbol for _, row in rows):
        warnings.append("History includes a dated exchange-confirmed symbol change")
    return rows, blockers, warnings


def adjusted_series(symbol, tail, window, actions, renames):
    """Backward price factors; split/bonus volume factors; dividends do not alter volume.

    Dividend factor is (previous raw close - cash dividend) / previous raw close.
    This is a price-history adjustment convention, not an exact reinvested-return index.
    Unknown events block eligibility instead of guessing an adjustment.
    """
    prices = [Decimal(row["close"]) for _, row in tail]
    volumes = [Decimal(row["volume"]) for _, row in tail]
    blockers, applied = [], []
    if not tail:
        return prices, volumes, blockers, applied
    session_index = {s: i for i, (s, _) in enumerate(tail)}
    groups = defaultdict(list)
    for a in actions:
        ex = day(a["ex_date"], "ex_date")
        if not tail[0][0] < ex <= tail[-1][0]:
            continue
        # Feed can use either side of a same-day ticker change.
        names = {symbol_at(symbol, ex, window[-1], renames), symbol}
        names.update(row["symbol"] for s, row in tail if s == ex)
        index = session_index.get(ex)
        if index:
            names.add(tail[index - 1][1]["symbol"])
        if a["symbol"] in names and a["kind"] != "meeting":
            groups[ex].append(a)
    with localcontext() as context:
        context.prec = 40
        for ex, events in sorted(groups.items(), reverse=True):
            index = session_index.get(ex)
            if index is None or index == 0:
                blockers.append(f"Missing ex-date/previous price for action on {ex}")
                continue
            known_isins = {tail[i][1].get("isin") for i in (index - 1, index)} - {None, ""}
            if known_isins and any(a.get("isin") not in (None, "", "-") and a["isin"] not in known_isins for a in events):
                blockers.append(f"Corporate-action ISIN differs from adjacent price identities on {ex}")
                continue
            if any(a["kind"] == "unsupported" for a in events):
                blockers.append(f"Unresolved corporate action on {ex}: " + "; ".join(a["subject"] for a in events))
                continue
            kinds = {a["kind"] for a in events}
            if len(events) > 1:
                blockers.append(f"Multiple same-day action records on {ex}; possible revision or duplicate needs review")
                continue
            if kinds == {"dividend"}:
                dividend = sum(Decimal(a["cash_inr"]) for a in events)
                prev = Decimal(tail[index - 1][1]["close"])
                if dividend >= prev:
                    blockers.append(f"Dividend is not below previous close on {ex}")
                    continue
                factor, volume_factor = (prev - dividend) / prev, Decimal(1)
            else:
                factor = Decimal(events[0]["numerator"]) / Decimal(events[0]["denominator"])
                volume_factor = 1 / factor
            for i in range(index):
                prices[i] *= factor
                volumes[i] *= volume_factor
            applied.append({"ex_date": str(ex), "price_factor": str(factor),
                            "volume_factor": str(volume_factor), "actions": events})
    return prices, volumes, blockers, sorted(applied, key=lambda x: x["ex_date"])
