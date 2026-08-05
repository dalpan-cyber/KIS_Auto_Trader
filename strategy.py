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


class InfiniteBuyingStrategy(BaseStrategy):
    """
    라오어 무한매수법 v2.0 매매 전략 클래스
    - 매일 미국 장 개장 전/프리마켓에 당일 매수/매도 주문 제안 목록을 생성합니다.
    """

    def __init__(self, division_count: int = 40, target_roi: float = 0.10):
        super().__init__("InfiniteBuying")
        self.division_count = division_count
        self.target_roi = target_roi

    def generate_signal(
        self,
        symbol: str,
        current_price: float,
        daily_candles: pd.DataFrame,
        current_holding_qty: int = 0
    ) -> str:
        if current_holding_qty == 0:
            return Signal.BUY
        return Signal.HOLD

    def generate_daily_orders(
        self,
        symbol: str,
        current_price: float,
        state: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        무한매수법 당일 매수/매도 상세 주문 제안 리스트 생성
        :param symbol: 종목 코드 (예: TQQQ)
        :param current_price: 현재가 ($)
        :param state: InfiniteStateManager에서 가져온 종목 상태 dict
        :return: 생성할 주문 리스트 [{action: 'SELL'/'BUY', qty: int, price: float, ord_type: '00'/'34', desc: str}]
        """
        orders = []
        if current_price <= 0:
            self.logger.warning(f"[{symbol}] 현재가가 유효하지 않아 주문 생성을 보류합니다: ${current_price}")
            return orders

        curr_round = state.get("current_round", 0)
        division = state.get("division_count", self.division_count)
        total_budget = state.get("total_budget_usd", 10000.0)
        avg_price = state.get("avg_price", 0.0)
        total_qty = state.get("total_qty", 0)
        target_roi = state.get("target_roi", self.target_roi)

        # 1. 익절 매도 주문 제안 (보유 수량이 있는 경우)
        if total_qty > 0 and avg_price > 0:
            sell_target_price = round(avg_price * (1.0 + target_roi), 2)
            orders.append({
                "action": "SELL",
                "symbol": symbol,
                "qty": total_qty,
                "price": sell_target_price,
                "ord_type": "00",  # 지정가 매도
                "desc": f"전량 익절 매도 (목표가: ${sell_target_price:.2f}, +{target_roi*100:.1f}%)"
            })

        status = state.get("status", "IDLE")
        if status in ["STOPPED", "PAUSED"]:
            self.logger.info(f"[{symbol}] 무한매수 강제 중지 상태({status})입니다. 매수 주문 생성을 생략합니다.")
            return orders

        # 2. 매수 주문 제안 (회차 미소진 시)
        if curr_round < division:
            one_round_budget = total_budget / division
            half_budget = one_round_budget / 2.0

            base_price = avg_price if avg_price > 0 else current_price

            # 매수 수량 산정 (최소 1주 이상)
            loc1_price = round(base_price, 2)
            qty1 = max(1, int(half_budget / loc1_price))

            loc2_price = round(base_price * 1.05, 2)
            qty2 = max(1, int(half_budget / loc2_price))

            orders.append({
                "action": "BUY",
                "symbol": symbol,
                "qty": qty1,
                "price": loc1_price,
                "ord_type": "34",  # LOC 매수
                "round_inc": 0.5,
                "desc": f"0.5회차 평단가 LOC 매수 (${loc1_price:.2f}, {qty1}주)"
            })

            orders.append({
                "action": "BUY",
                "symbol": symbol,
                "qty": qty2,
                "price": loc2_price,
                "ord_type": "34",  # LOC 매수
                "round_inc": 0.5,
                "desc": f"0.5회차 상향 LOC 매수 (${loc2_price:.2f}, {qty2}주)"
            })
        else:
            self.logger.warning(f"[{symbol}] 무한매수 소진 ({curr_round}/{division}회차) - 추가 매수를 중단합니다.")

        return orders


class StrategyFactory:
    """전략 생성 팩토리 클래스"""

    @staticmethod
    def create_strategy(strategy_name: str, **kwargs) -> BaseStrategy:
        division = kwargs.get("division_count", 40)
        roi = kwargs.get("target_roi", 0.10)
        if strategy_name == "INFINITE_BUYING":
            return InfiniteBuyingStrategy(division_count=division, target_roi=roi)
        elif strategy_name == "MA_CROSS":
            short_p = kwargs.get("short_period", 5)
            long_p = kwargs.get("long_period", 20)
            return MACrossStrategy(short_period=short_p, long_period=long_p)
        elif strategy_name == "VOLATILITY_BREAKOUT":
            k_val = kwargs.get("k", 0.5)
            return VolatilityBreakoutStrategy(k=k_val)
        else:
            return InfiniteBuyingStrategy(division_count=division, target_roi=roi)

