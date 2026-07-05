from core.execution.paper_trader import PaperTrader
from core.market_data.yahoo_data import download_price_data


def refresh_paper_position_prices(starting_balance):
    trader = PaperTrader(starting_balance=starting_balance)

    positions = trader.get_positions()

    if positions.empty:
        return False, "No open positions to refresh."

    price_map = {}

    for symbol in positions["Symbol"].tolist():
        data = download_price_data(
            symbol=symbol,
            period="5d",
            interval="1d",
            auto_adjust=True
        )

        if not data.empty:
            latest_price = float(data["Close"].iloc[-1])
            price_map[symbol] = latest_price

    if not price_map:
        return False, "Could not fetch latest prices."

    trader.update_prices(price_map)

    return True, f"Updated prices for {len(price_map)} position(s)."