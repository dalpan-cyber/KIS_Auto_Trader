"""
매매 전략 엔진 모듈 (strategy.py)
자동 투자 알고리즘 (이동평균 교차, 변동성 돌파, RSI/볼린저밴드 등)
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np
import logging

class Signal:
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class BaseStrategy(ABC):
    """모든 매매 전략의 기본 추상 클래스"""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(f"Strategy.{name}")

    @abstractmethod
    def generate_signal(
        self,
        symbol: str,
        current_price: float,
        daily_candles: pd.DataFrame,
        current_holding_qty: int = 0
    ) -> str:
        """
        매매 신호 생성 메서드
        :param symbol: 종목 코드
        :param current_price: 현재가
        :param daily_candles: 일봉 DataFrame ['date', 'open', 'high', 'low', 'close', 'volume']
        :param current_holding_qty: 현재 보유 수량
        :return: Signal.BUY, Signal.SELL, Signal.HOLD
        """
        pass


class MACrossStrategy(BaseStrategy):
    """
    이동평균선 교차 전략 (Moving Average Crossover)
    - 단기 이평선이 장기 이평선을 상향 돌파(골든 크로스) 시 매수
    - 단기 이평선이 장기 이평선을 하향 돌파(데드 크로스) 시 매도
    """

    def __init__(self, short_period: int = 5, long_period: int = 20):
        super().__init__("MACross")
        self.short_period = short_period
        self.long_period = long_period

    def generate_signal(
        self,
        symbol: str,
        current_price: float,
        daily_candles: pd.DataFrame,
        current_holding_qty: int = 0
    ) -> str:
        if daily_candles is None or len(daily_candles) < self.long_period + 1:
            self.logger.debug(f"[{symbol}] 데이터 부족으로 신호 보류 ({len(daily_candles) if daily_candles is not None else 0}/{self.long_period+1})")
            return Signal.HOLD

        df = daily_candles.copy()
        # 종가 컬럼을 숫자로 변환
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        
        # 현재가를 최신 종가로 업데이트/추가
        closes = df['close'].tolist()
        closes.append(current_price)
        
        closes_s = pd.Series(closes)
        short_ma = closes_s.rolling(window=self.short_period).mean()
        long_ma = closes_s.rolling(window=self.long_period).mean()

        prev_short = short_ma.iloc[-2]
        prev_long = long_ma.iloc[-2]
        curr_short = short_ma.iloc[-1]
        curr_long = long_ma.iloc[-1]

        self.logger.debug(f"[{symbol}] 이평선: 이전({prev_short:.1f}/{prev_long:.1f}) -> 현재({curr_short:.1f}/{curr_long:.1f})")

        # 골든 크로스 (매수)
        if prev_short <= prev_long and curr_short > curr_long and current_holding_qty == 0:
            self.logger.info(f"★ [{symbol}] 골든크로스 발생 -> 매수 신호! (단기:{curr_short:.1f} > 장기:{curr_long:.1f})")
            return Signal.BUY

        # 데드 크로스 (매도)
        if prev_short >= prev_long and curr_short < curr_long and current_holding_qty > 0:
            self.logger.info(f"★ [{symbol}] 데드크로스 발생 -> 매도 신호! (단기:{curr_short:.1f} < 장기:{curr_long:.1f})")
            return Signal.SELL

        return Signal.HOLD


class VolatilityBreakoutStrategy(BaseStrategy):
    """
    변동성 돌파 전략 (Larry Williams Volatility Breakout)
    - 당일 매수 목표가 = 당일 시가 + (전일 고가 - 전일 저가) * K
    - 현재가가 목표가를 상향 돌파할 때 매수
    """

    def __init__(self, k: float = 0.5):
        super().__init__("VolatilityBreakout")
        self.k = k

    def generate_signal(
        self,
        symbol: str,
        current_price: float,
        daily_candles: pd.DataFrame,
        current_holding_qty: int = 0
    ) -> str:
        if daily_candles is None or len(daily_candles) < 2:
            return Signal.HOLD

        df = daily_candles.copy()
        for col in ['open', 'high', 'low', 'close']:
            df[col] = pd.to_numeric(df[col], errors='coerce')

        yesterday = df.iloc[-1]  # 가장 최근 완료 일봉 (전일)
        target_range = (yesterday['high'] - yesterday['low']) * self.k
        
        # 오늘 시가 (만약 당일 일봉 데이터가 있다면 당일 시가, 없으면 전일 종가 기반 추정)
        today_open = yesterday['close']
        target_price = today_open + target_range

        self.logger.debug(f"[{symbol}] 돌파 목표가: {target_price:.0f} (현재가: {current_price:.0f})")

        if current_price >= target_price and current_holding_qty == 0:
            self.logger.info(f"★ [{symbol}] 변동성 돌파 발생! 현재가({current_price}) >= 목표가({target_price:.0f}) -> 매수 신호")
            return Signal.BUY

        return Signal.HOLD


class StrategyFactory:
    """전략 생성 팩토리 클래스"""

    @staticmethod
    def create_strategy(strategy_name: str, **kwargs) -> BaseStrategy:
        if strategy_name == "MA_CROSS":
            short_p = kwargs.get("short_period", 5)
            long_p = kwargs.get("long_period", 20)
            return MACrossStrategy(short_period=short_p, long_period=long_p)
        elif strategy_name == "VOLATILITY_BREAKOUT":
            k_val = kwargs.get("k", 0.5)
            return VolatilityBreakoutStrategy(k=k_val)
        else:
            raise ValueError(f"지원하지 않는 전략 이름입니다: {strategy_name}")
