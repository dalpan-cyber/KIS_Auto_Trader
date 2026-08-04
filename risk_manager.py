"""
리스크 및 자금 관리자 모듈 (risk_manager.py)
손절매(Stop-loss), 익절매(Take-profit), 트레일링 스탑, 포지션사이징 관리
"""
import logging
from typing import Dict, Any, Tuple

class RiskManager:
    """
    리스크 관리 및 포지션 크기 계산 클래스
    """

    def __init__(
        self,
        stop_loss_ratio: float = 0.03,
        take_profit_ratio: float = 0.07,
        trailing_stop_ratio: float = 0.02,
        invest_ratio_per_stock: float = 0.2,
        max_stocks_holding: int = 5,
        max_consecutive_errors: int = 3
    ):
        self.stop_loss_ratio = stop_loss_ratio
        self.take_profit_ratio = take_profit_ratio
        self.trailing_stop_ratio = trailing_stop_ratio
        self.invest_ratio_per_stock = invest_ratio_per_stock
        self.max_stocks_holding = max_stocks_holding
        self.max_consecutive_errors = max_consecutive_errors

        self.consecutive_errors = 0
        self.highest_prices: Dict[str, float] = {}  # 매수 이후 최고가 기록
        self.logger = logging.getLogger("RiskManager")

    def reset_highest_price(self, symbol: str):
        """종목 매도 시 최고가 기록 초기화"""
        if symbol in self.highest_prices:
            del self.highest_prices[symbol]

    def update_highest_price(self, symbol: str, current_price: float):
        """매수 보유 종목의 고점 갱신"""
        if symbol not in self.highest_prices or current_price > self.highest_prices[symbol]:
            self.highest_prices[symbol] = current_price

    def evaluate_holding_risk(
        self,
        symbol: str,
        current_price: float,
        avg_buy_price: float
    ) -> Tuple[bool, str]:
        """
        보유 종목 손절/익절/트레일링스탑 조건 검사
        :return: (매도필요여부, 매도사유)
        """
        if avg_buy_price <= 0 or current_price <= 0:
            return False, ""

        # Profit/Loss Ratio 계산
        pnl_ratio = (current_price - avg_buy_price) / avg_buy_price

        # 1. 손절매 (Stop Loss) 검사
        if pnl_ratio <= -self.stop_loss_ratio:
            reason = f"손절매 조건 충족 (수익률: {pnl_ratio*100:.2f}% <= -{self.stop_loss_ratio*100:.1f}%)"
            self.logger.warning(f"🚨 [{symbol}] {reason}")
            return True, reason

        # 2. 익절매 (Take Profit) 검사
        if pnl_ratio >= self.take_profit_ratio:
            reason = f"목표 수익 달성 (수익률: {pnl_ratio*100:.2f}% >= +{self.take_profit_ratio*100:.1f}%)"
            self.logger.info(f"🎉 [{symbol}] {reason}")
            return True, reason

        # 3. 트레일링 스탑 (Trailing Stop) 검사
        self.update_highest_price(symbol, current_price)
        peak_price = self.highest_prices.get(symbol, current_price)
        
        # 최고점 대비 일정 비율 이상 하락했는지 검사
        if peak_price > avg_buy_price:  # 이익 구간에 진입했던 경우에만 트레일링스탑 동작
            drawdown = (peak_price - current_price) / peak_price
            if drawdown >= self.trailing_stop_ratio:
                reason = f"트레일링 스탑 발동 (최고가:{peak_price:.0f} 대비 하락률:{drawdown*100:.2f}%)"
                self.logger.info(f"⚡ [{symbol}] {reason}")
                return True, reason

        return False, ""

    def calculate_buy_quantity(
        self,
        symbol: str,
        current_price: float,
        total_account_eval: float,
        available_cash: float,
        current_holding_count: int
    ) -> int:
        """
        신규 매수 수량 계산 (자금 관리)
        """
        if current_holding_count >= self.max_stocks_holding:
            self.logger.warning(f"최대 보유 종목 수 초과 ({current_holding_count}/{self.max_stocks_holding}). 매수 불가.")
            return 0

        if current_price <= 0 or available_cash <= 0:
            return 0

        # 종목당 최대 배정 가능 금액
        max_budget = min(total_account_eval * self.invest_ratio_per_stock, available_cash)
        qty = int(max_budget // current_price)

        if qty <= 0:
            self.logger.info(f"[{symbol}] 예산 부족으로 1주도 구매할 수 없습니다. (배정예산:{max_budget:.0f}, 현재가:{current_price:.0f})")
            return 0

        self.logger.info(f"[{symbol}] 매수 가능 수량 계산: {qty}주 (예산:{max_budget:.0f}원, 현재가:{current_price:.0f}원)")
        return qty

    def record_error(self):
        """연속 주문/API 에러 기록"""
        self.consecutive_errors += 1
        self.logger.error(f"연속 에러 발생 횟수: {self.consecutive_errors}/{self.max_consecutive_errors}")

    def reset_error(self):
        """에러 카운터 초기화"""
        self.consecutive_errors = 0

    def is_circuit_broken(self) -> bool:
        """연속 에러 초과로 인한 거래 정지 서킷브레이커 여부"""
        return self.consecutive_errors >= self.max_consecutive_errors
