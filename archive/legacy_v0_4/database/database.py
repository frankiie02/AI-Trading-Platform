import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///trading_platform.db")
engine = create_engine(DATABASE_URL)


def init_db():
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS bot_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT,
                message TEXT
            )
        """))


def log_bot_run(status: str, message: str):
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO bot_runs (status, message) VALUES (:status, :message)"),
            {"status": status, "message": message}
        )