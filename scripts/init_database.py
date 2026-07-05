from config.settings import settings
from core.database.database import (
    initialise_account,
    initialise_database
)


def main():
    initialise_database()
    initialise_account(settings.STARTING_BALANCE)
    print("Database initialised successfully.")


if __name__ == "__main__":
    main()