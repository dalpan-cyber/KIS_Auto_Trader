"""
매매 전략 엔진 모듈 (strategy.py)
자동 투자 알고리즘 (이동평균 교차, 변동성 돌파, RSI/볼린저밴드 등)
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional, Tuple
import pandas as pd
import numpy as np
import logging

import config

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
    라오어 무한매수법 v2.1 매매 전략 클래스
    - 전반전(T < division/2): 0.5회차 평단가 LOC + 0.5회차 큰수(☆%) LOC 2건 분할 매수
    - 후반전(division/2 <= T < division): 1.0회차 후반전(☆%) LOC 1건 통합 매수
    - 소진(T >= division): HOLD, LOWER_TARGET, REBALANCE_QUARTER 등 소진 대응
    - 매일 미국 장 개장 전/프리마켓에 당일 매수/매도 주문 제안 목록을 생성합니다.
    """

    def __init__(
        self,
        division_count: int = 40,
        target_roi: float = 0.10,
        exhaust_action: str = "HOLD",
        exhaust_target_roi: float = 0.05
    ):
        super().__init__("InfiniteBuying")
        self.division_count = division_count
        self.target_roi = target_roi
        self.exhaust_action = exhaust_action
        self.exhaust_target_roi = exhaust_target_roi

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

    def determine_exhaust_action_auto(
        self,
        symbol: str,
        current_price: float,
        avg_price: float,
        daily_candles: Optional[pd.DataFrame] = None
    ) -> Tuple[str, str]:
        """
        40회차 소진 시 현재 손실률 및 일봉 차트(이동평균선)를 기반으로
        가장 적합한 대응 모드(HOLD, LOWER_TARGET, REBALANCE_QUARTER)를 자동 선택
        :return: (선택된_액션: str, 사유_설명: str)
        """
        if avg_price <= 0:
            return "HOLD", "평단가 미확인으로 안전 대기(HOLD) 선택"

        pnl_rate = (current_price - avg_price) / avg_price

        # 일봉 데이터 기반 단기/중기 이동평균선 산출
        ma5 = None
        ma20 = None
        if daily_candles is not None and isinstance(daily_candles, pd.DataFrame) and len(daily_candles) >= 5:
            try:
                df = daily_candles.copy()
                close_col = None
                for c in ["close", "stck_clpr", "stck_prpr", "Close"]:
                    if c in df.columns:
                        close_col = c
                        break
                if close_col is None:
                    close_col = df.columns[-1]

                df["c_num"] = pd.to_numeric(df[close_col], errors="coerce")
                df_valid = df.dropna(subset=["c_num"])
                if len(df_valid) >= 5:
                    ma5 = float(df_valid["c_num"].tail(5).mean())
                if len(df_valid) >= 20:
                    ma20 = float(df_valid["c_num"].tail(20).mean())
            except Exception as e:
                self.logger.debug(f"이동평균선 계산 중 예외: {e}")

        # 1. HOLD (무한 대기 / +10% 목표 익절 완주)
        # 조건: 손실률이 -5% 이내이거나, 단기 반등 추세(골든크로스 & 현재가 >= 5일선)
        is_rebounding = (ma5 is not None and ma20 is not None and ma5 > ma20 and current_price >= ma5)
        if pnl_rate >= -0.05:
            return "HOLD", f"손실률 경미({pnl_rate*100:+.1f}%)로 원금 회복 근접 -> HOLD(기존 목표가 완주) 선택"
        if is_rebounding:
            return "HOLD", f"단기 골든크로스 반등세(MA5: ${ma5:.2f} > MA20: ${ma20:.2f}) 감지 -> HOLD(기존 목표가 완주) 선택"

        # 2. LOWER_TARGET (목표가 하향 탈출)
        # 조건: 손실률 -5% ~ -15% 박스권 횡보/조정 구간
        if pnl_rate >= -0.15:
            return "LOWER_TARGET", f"박스권 횡보/조정 구간(손실률: {pnl_rate*100:+.1f}%) -> LOWER_TARGET(빠른 원금 회수) 선택"

        # 3. REBALANCE_QUARTER (쿼터 순환 매매)
        # 조건: 손실률 -15% 초과 심한 침체/하락세
        return "REBALANCE_QUARTER", f"깊은 하락/침체 추세(손실률: {pnl_rate*100:+.1f}%) -> REBALANCE_QUARTER(평단가 적극 인하) 선택"

    def generate_daily_orders(
        self,
        symbol: str,
        current_price: float,
        state: Dict[str, Any],
        avg_price: float = 0.0,
        total_qty: int = 0,
        daily_candles: Optional[pd.DataFrame] = None
    ) -> List[Dict[str, Any]]:
        """
        무한매수법 당일 매수/매도 상세 주문 제안 리스트 생성
        :param symbol: 종목 코드 (예: TQQQ)
        :param current_price: 현재가 ($)
        :param state: InfiniteStateManager에서 가져온 종목 상태 dict (전략 상태만)
        :param avg_price: 보유 평단가 ($) - KIS API 실계좌에서 조회 (Source of Truth = API)
        :param total_qty: 보유 수량 (주) - KIS API 실계좌에서 조회 (Source of Truth = API)
        :param daily_candles: 일봉 캔들 데이터 (선택, AUTO 모드 시 이평선 분석용)
        :return: 생성할 주문 리스트 [{action: 'SELL'/'BUY', qty: int, price: float, ord_type: '00'/'34', desc: str}]
        """
        orders = []
        if current_price <= 0:
            self.logger.warning(f"[{symbol}] 현재가가 유효하지 않아 주문 생성을 보류합니다: ${current_price}")
            return orders

        curr_round = state.get("current_round", 0)
        division = state.get("division_count", self.division_count)
        total_budget = state.get("total_budget_usd", 10000.0)
        target_roi = state.get("target_roi", self.target_roi)
        exhaust_action = str(state.get("exhaust_action", getattr(self, "exhaust_action", getattr(config, "INFINITE_EXHAUST_ACTION", "HOLD")))).upper()
        exhaust_target_roi = float(state.get("exhaust_target_roi", getattr(self, "exhaust_target_roi", getattr(config, "INFINITE_EXHAUST_TARGET_ROI", 0.05))))

        is_exhausted = (curr_round >= division)

        status = state.get("status", "IDLE")
        paused_sell_price = float(state.get("paused_sell_price", 0.0) or 0.0)

        # 40회차 소진 시 유효 대응 모드 판별 (AUTO 모드 동적 선택 지원)
        effective_exhaust_action = exhaust_action
        auto_desc_tag = ""
        if is_exhausted and exhaust_action == "AUTO":
            effective_exhaust_action, auto_reason = self.determine_exhaust_action_auto(
                symbol, current_price, avg_price, daily_candles=daily_candles
            )
            auto_desc_tag = f"[AUTO: {effective_exhaust_action}] "
            self.logger.info(f"🤖 [{symbol} 40회차 소진] {auto_reason}")

        # 1. 익절/지정 매도 주문 제안 (보유 수량이 있는 경우)
        if total_qty > 0 and avg_price > 0:
            if status == "PAUSED" and paused_sell_price > 0:
                sell_target_price = round(paused_sell_price, 2)
                orders.append({
                    "action": "SELL",
                    "symbol": symbol,
                    "qty": total_qty,
                    "price": sell_target_price,
                    "ord_type": "00",  # 지정가 매도
                    "desc": f"전량 매도 (투자 일시중지 지정가: ${sell_target_price:.2f})"
                })
            elif is_exhausted and effective_exhaust_action == "LOWER_TARGET":
                eff_roi = exhaust_target_roi
                sell_target_price = round(avg_price * (1.0 + eff_roi), 2)
                orders.append({
                    "action": "SELL",
                    "symbol": symbol,
                    "qty": total_qty,
                    "price": sell_target_price,
                    "ord_type": "00",  # 지정가 매도
                    "desc": f"{auto_desc_tag}전량 익절 매도 (40회차 소진 - 목표가 하향: ${sell_target_price:.2f}, +{eff_roi*100:.1f}%)"
                })
            elif is_exhausted and effective_exhaust_action == "REBALANCE_QUARTER":
                # 쿼터 순환 매매: 1회차 분량은 하단에서 현재가 순환 매도하므로, 잔여 수량만 목표가 익절 매도로 발주 (수량 초과 방지)
                rebalance_qty = max(1, int(total_qty / division)) if total_qty > 0 else 0
                main_sell_qty = total_qty - rebalance_qty
                sell_target_price = round(avg_price * (1.0 + target_roi), 2)
                if main_sell_qty > 0:
                    orders.append({
                        "action": "SELL",
                        "symbol": symbol,
                        "qty": main_sell_qty,
                        "price": sell_target_price,
                        "ord_type": "00",
                        "desc": f"{auto_desc_tag}잔여 익절 매도 (쿼터순환 제외 {main_sell_qty}주, 목표가: ${sell_target_price:.2f}, +{target_roi*100:.1f}%)"
                    })
            else:
                sell_target_price = round(avg_price * (1.0 + target_roi), 2)
                orders.append({
                    "action": "SELL",
                    "symbol": symbol,
                    "qty": total_qty,
                    "price": sell_target_price,
                    "ord_type": "00",  # 지정가 매도
                    "desc": f"{auto_desc_tag}전량 익절 매도 (목표가: ${sell_target_price:.2f}, +{target_roi*100:.1f}%)"
                })

        if status in ["STOPPED", "PAUSED"]:
            self.logger.info(f"[{symbol}] 무한매수 일시/강제 중지 상태({status})입니다. 매수 주문 생성을 생략합니다.")
            return orders

        # 2. 매수 및 40회차 소진 대응 주문 제안 (라오어 무한매수법 v2.1)
        if not is_exhausted:
            one_round_budget = total_budget / division
            half_budget = one_round_budget / 2.0
            half_division = division / 2.0

            base_price = avg_price if avg_price > 0 else current_price

            # 별퍼센트(☆%) 공식: 10.0 - (T * (10.0 / half_division))
            # 40분할 기준: 10.0 - (T / 2.0)
            star_percent = 10.0 - (float(curr_round) * (10.0 / float(half_division)))

            # 현재가 대비 과도한 괴리율 방지 (브로커/거래소 Limit Price too aggressive / 6008 거부 방어)
            max_loc_premium_ratio = float(
                state.get(
                    "max_loc_premium_ratio",
                    getattr(config, "INFINITE_MAX_LOC_PREMIUM_RATIO", 0.10)
                )
            )
            max_allowed_loc_price = round(current_price * (1.0 + max_loc_premium_ratio), 2)

            if curr_round < half_division:
                # [전반전] (0 <= T < half_division): 적극적 물량 확보 구간
                # 1) 0.5회차 평단가 LOC 매수
                raw_loc1 = round(base_price, 2)
                loc1_price = round(min(raw_loc1, max_allowed_loc_price), 2)

                # 2) 0.5회차 큰수(☆%) LOC 매수
                # 평단가가 없는 최초 매수(0회차)인 경우 현재가 기반 진입 보장
                if avg_price <= 0:
                    raw_loc2 = round(base_price * 1.05, 2)
                else:
                    raw_loc2 = round(base_price * (1.0 + star_percent / 100.0), 2)
                    if raw_loc2 <= raw_loc1:
                        raw_loc2 = round(raw_loc1 + 0.01, 2)

                loc2_price = round(min(raw_loc2, max_allowed_loc_price), 2)

                # 상한 캡 적용 시 두 가격이 같아지거나 역전되지 않도록 분리 (loc1을 0.01 낮춤)
                if loc2_price <= loc1_price and loc1_price > 0.01:
                    loc1_price = round(max(0.01, loc2_price - 0.01), 2)

                qty1 = max(1, int(half_budget / loc1_price))
                qty2 = max(1, int(half_budget / loc2_price))

                capped1_str = " (상한캡)" if loc1_price < raw_loc1 else ""
                capped2_str = " (상한캡)" if loc2_price < raw_loc2 else ""

                if loc1_price < raw_loc1 or loc2_price < raw_loc2:
                    self.logger.info(
                        f"🛡️ [{symbol}] LOC 매수가가 현재가(${current_price:.2f}) 대비 과도(Limit price too aggressive 방지)하여 상한 캡(+{max_loc_premium_ratio*100:.0f}%) 적용: "
                        f"평단LOC ${raw_loc1:.2f}->${loc1_price:.2f}, 큰수LOC ${raw_loc2:.2f}->${loc2_price:.2f}"
                    )

                orders.append({
                    "action": "BUY",
                    "symbol": symbol,
                    "qty": qty1,
                    "price": loc1_price,
                    "ord_type": "34",  # LOC 매수
                    "round_inc": 0.5,
                    "desc": f"0.5회차 평단가 LOC 매수 (${loc1_price:.2f}, {qty1}주){capped1_str}"
                })

                orders.append({
                    "action": "BUY",
                    "symbol": symbol,
                    "qty": qty2,
                    "price": loc2_price,
                    "ord_type": "34",  # LOC 매수
                    "round_inc": 0.5,
                    "desc": f"0.5회차 큰수(☆{star_percent:+.1f}%) LOC 매수 (${loc2_price:.2f}, {qty2}주){capped2_str}"
                })
            else:
                # [후반전] (half_division <= T < division): 평단가 방어 및 리스크 통제 구간
                # 하루 1회차 전체 예산을 1건의 보수적 별%(☆%) LOC 매수로 집행
                raw_loc = round(base_price * (1.0 + star_percent / 100.0), 2)
                loc_price = round(min(raw_loc, max_allowed_loc_price), 2)
                capped_str = ""
                if loc_price < raw_loc:
                    capped_str = " (상한캡)"
                    self.logger.info(
                        f"🛡️ [{symbol}] 후반전 LOC 매수가가 현재가(${current_price:.2f}) 대비 과도하여 상한 캡(+{max_loc_premium_ratio*100:.0f}%) 적용: "
                        f"${raw_loc:.2f} -> ${loc_price:.2f}"
                    )
                qty = max(1, int(one_round_budget / loc_price))

                orders.append({
                    "action": "BUY",
                    "symbol": symbol,
                    "qty": qty,
                    "price": loc_price,
                    "ord_type": "34",  # LOC 매수
                    "round_inc": 1.0,
                    "desc": f"1.0회차 후반전(☆{star_percent:+.1f}%) LOC 매수 (${loc_price:.2f}, {qty}주){capped_str}"
                })
        else:
            # 40회차 소진 시 3가지 대응 모드 분기 (effective_exhaust_action 기준)
            if effective_exhaust_action == "REBALANCE_QUARTER":
                # 옵션 2: 쿼터 순환 매매 (1회차 분량 매도 후 당일 LOC 재매수로 평단가 인하)
                one_round_budget = total_budget / division
                rebalance_qty = max(1, int(total_qty / division)) if total_qty > 0 else max(1, int(one_round_budget / current_price))
                loc_price = round(current_price * 1.02, 2)
                buy_qty = max(1, int(one_round_budget / loc_price))

                self.logger.info(
                    f"[{symbol}] 무한매수 {division}회차 소진 {auto_desc_tag}-> 쿼터 순환 모드 (1회차 분량 {rebalance_qty}주 매도 + LOC {buy_qty}주 재매수)"
                )
                orders.append({
                    "action": "SELL",
                    "symbol": symbol,
                    "qty": rebalance_qty,
                    "price": round(current_price, 2),
                    "ord_type": "00",
                    "round_inc": 0.0,
                    "desc": f"{auto_desc_tag}순환 매도 ({division}회차 소진 - 평단가 인하용 {rebalance_qty}주 매도)"
                })
                orders.append({
                    "action": "BUY",
                    "symbol": symbol,
                    "qty": buy_qty,
                    "price": loc_price,
                    "ord_type": "34",
                    "round_inc": 0.0,
                    "desc": f"{auto_desc_tag}순환 LOC 재매수 ({division}회차 소진 - 평단가 인하용 ${loc_price:.2f}, {buy_qty}주)"
                })
            elif effective_exhaust_action == "LOWER_TARGET":
                eff_roi = exhaust_target_roi
                self.logger.warning(
                    f"[{symbol}] 무한매수 소진 ({curr_round}/{division}회차) {auto_desc_tag}- 목표수익률 하향(+{eff_roi*100:.1f}%) 빠른 탈출 대기 중"
                )
            else:
                # 옵션 1: HOLD (무한 대기)
                self.logger.warning(
                    f"[{symbol}] 무한매수 소진 ({curr_round}/{division}회차) {auto_desc_tag}- 무한 대기 모드 (추가 매수 중단, +{target_roi*100:.1f}% 익절 매도 대기)"
                )

        return orders


class StrategyFactory:
    """전략 생성 팩토리 클래스"""

    @staticmethod
    def create_strategy(strategy_name: str, **kwargs) -> BaseStrategy:
        division = kwargs.get("division_count", 40)
        roi = kwargs.get("target_roi", 0.10)
        exhaust_act = kwargs.get("exhaust_action", getattr(config, "INFINITE_EXHAUST_ACTION", "HOLD"))
        exhaust_roi = kwargs.get("exhaust_target_roi", getattr(config, "INFINITE_EXHAUST_TARGET_ROI", 0.05))
        if strategy_name == "INFINITE_BUYING":
            return InfiniteBuyingStrategy(
                division_count=division,
                target_roi=roi,
                exhaust_action=exhaust_act,
                exhaust_target_roi=exhaust_roi
            )
        elif strategy_name == "MA_CROSS":
            short_p = kwargs.get("short_period", 5)
            long_p = kwargs.get("long_period", 20)
            return MACrossStrategy(short_period=short_p, long_period=long_p)
        elif strategy_name == "VOLATILITY_BREAKOUT":
            k_val = kwargs.get("k", 0.5)
            return VolatilityBreakoutStrategy(k=k_val)
        else:
            return BaseStrategy(strategy_name)

