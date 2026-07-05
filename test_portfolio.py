from risk.portfolio import Portfolio

portfolio = Portfolio(starting_balance=100000, max_open_positions=5)

result = portfolio.open_position(
    symbol="AMD",
    shares=27,
    entry_price=561.17,
    stop_loss=525.20,
    take_profit=633.11
)

print("\nOpen Position Result")
print("=" * 40)
print(result)

print("\nPortfolio Summary")
print("=" * 40)
print(portfolio.summary())

close_result = portfolio.close_position("AMD", exit_price=633.11)

print("\nClose Position Result")
print("=" * 40)
print(close_result)

print("\nFinal Portfolio Summary")
print("=" * 40)
print(portfolio.summary())