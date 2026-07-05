from config.settings import settings

print("\nSettings")
print("=" * 40)
print("Starting Balance:", settings.STARTING_BALANCE)
print("Risk Percent:", settings.RISK_PERCENT)
print("Max Positions:", settings.MAX_OPEN_POSITIONS)
print("Symbols:", settings.SYMBOLS)
print("Strategy:", settings.STRATEGY_NAME)