import os
from ib_insync import IB
from dotenv import load_dotenv

load_dotenv()


class IBKRClient:
    def __init__(self):
        self.host = os.getenv("IBKR_HOST", "127.0.0.1")
        self.port = int(os.getenv("IBKR_PORT", "7497"))
        self.client_id = int(os.getenv("IBKR_CLIENT_ID", "1"))
        self.ib = IB()

    def connect(self):
        self.ib.connect(
            host=self.host,
            port=self.port,
            clientId=self.client_id,
            readonly=True
        )
        return self.ib.isConnected()

    def disconnect(self):
        if self.ib.isConnected():
            self.ib.disconnect()

    def account_summary(self):
        return self.ib.accountSummary()

    def positions(self):
        return self.ib.positions()