from dataclasses import dataclass
from enum import Enum
from typing import List, Optional

import pandas as pd


class ScanStrategyMode(str, Enum):
    SINGLE = "single"
    VOTING = "voting"


@dataclass
class TradingPipelineRequest:
    """Symbol-independent decision inputs required to evaluate one prepared
    market-data frame. Does not include period/interval/symbol-list/queue
    flags/database settings — those are scanner (or future backtest/paper/
    live service) orchestration concerns, not decision inputs."""

    symbol: str
    data: pd.DataFrame
    strategy_mode: ScanStrategyMode = ScanStrategyMode.SINGLE
    strategy_name: str = "EMA Trend"
    short_ema: int = 20
    long_ema: int = 50
    rsi_threshold: int = 55
    use_volume_filter: bool = True
    use_regime_filter: bool = True
    account_balance: float = 0.0
    risk_percent: float = 1.0
    atr_multiplier: float = 2.0
    reward_risk_ratio: float = 2.0
    minimum_alpha_score: int = 70

    def __post_init__(self):
        if not isinstance(self.strategy_mode, ScanStrategyMode):
            self.strategy_mode = ScanStrategyMode(self.strategy_mode)


@dataclass
class TradingDecision:
    """One symbol's reusable trading-decision result. Only ever returned on
    a successful evaluation — operational failures are raised as pipeline
    exceptions instead of being encoded here, so `status` is always "OK"."""

    symbol: str
    status: str = "OK"
    strategy_mode: ScanStrategyMode = ScanStrategyMode.SINGLE
    strategy_name: str = ""
    raw_signal: str = "NO TRADE"
    final_signal: str = "NO TRADE"
    confidence: int = 0
    signal_reason: str = ""
    regime: str = "Unknown"
    strategy_allowed: bool = False
    regime_reason: str = ""
    alpha_score: int = 0
    alpha_grade: str = "D"
    alpha_reasons: str = ""
    current_price: Optional[float] = None
    rsi: Optional[float] = None
    atr: Optional[float] = None
    trend: bool = False
    momentum: bool = False
    volume: bool = False
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    suggested_shares: int = 0
    dollar_risk: float = 0.0
    queue_eligible: bool = False
    # Voting-mode-only metadata. Left as None for single-strategy decisions.
    vote_score: Optional[float] = None
    buy_votes: Optional[int] = None
    total_votes: Optional[int] = None
    strategy_votes: Optional[List[dict]] = None
