import os
import requests
from dotenv import load_dotenv

load_dotenv()


class TelegramBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def send(self, message: str):
        if not self.token or not self.chat_id:
            print("Telegram not configured:")
            print(message)
            return

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        response = requests.post(
            url,
            data={
                "chat_id": self.chat_id,
                "text": message
            },
            timeout=10
        )

        response.raise_for_status()