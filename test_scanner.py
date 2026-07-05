from engine.scanner import Scanner

symbols = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA", "AMD"]

scanner = Scanner(symbols)
signals = scanner.scan()

print("\nSignals Found")
print("=" * 50)

if not signals:
    print("No BUY signals found.")
else:
    for signal in signals:
        print(signal)