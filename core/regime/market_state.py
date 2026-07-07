from enum import Enum


class MarketState(str, Enum):
    BULL = "Bull"
    BEAR = "Bear"
    SIDEWAYS = "Sideways"
    UNKNOWN = "Unknown"