import sys

from core.runtime.application import TradingApplication
from core.runtime.exceptions import RuntimeConfigurationError


def main() -> int:
    app = TradingApplication()

    try:
        result = app.run()
    except RuntimeConfigurationError as error:
        print(f"Runtime configuration error: {error}")
        return 1

    print(result.message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
