from risk.position_sizer import calculate_position_size

trade = calculate_position_size(
    account_balance=100000,
    risk_percent=1,
    entry_price=561.17,
    stop_loss=525.20
)

print("\nPosition Size")
print("=" * 40)

for key, value in trade.items():
    print(f"{key:<20} {value}")