"""Match prices against current pregame projections."""

from math import isfinite

from app.pick_journal import current_quote
from app.strategy import TOTAL_MARGIN_POINTS, total_selection

MIN_EXPECTED_RETURN = .05


def market_signals(rows, now, team, home, probability, projection, spread):
    signals = {}
    for market, book, line, first, second, captured in rows:
        quote = {"book": book, "captured_at": captured}
        if market in signals or not current_quote(quote, now):
            continue
        if not all(isinstance(price, (float, int)) and isfinite(price) and price > 1 for price in (first, second)):
            continue
        if market == "moneyline":
            price, opposite = (first, second) if team == home else (second, first)
            quote.update(selection=team, price=price, probability=probability)
            quote["favorite_side"] = "home" if first < second else "away" if second < first else None
        elif market == "total" and isinstance(line, (float, int)) and isfinite(line):
            selection = total_selection(projection, spread, line)
            price, opposite = (first, second) if selection["direction"] == "Over" else (second, first)
            quote.update(selection, price=price, edge=round(projection - line, 1))
            quote["margin_met"] = abs(projection - line) >= TOTAL_MARGIN_POINTS
        else:
            continue
        quote["fair_market_probability"] = (1 / price) / (1 / price + 1 / opposite)
        quote["expected_return"] = quote["probability"] * price + quote.get("push_probability", 0) - 1
        signals[market] = quote
    return signals
