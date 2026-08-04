"""
리스크 및 자금 관리자 단위 테스트 (test_risk_manager.py)
"""
import unittest
from risk_manager import RiskManager

class TestRiskManager(unittest.TestCase):

    def setUp(self):
        self.risk_mgr = RiskManager(
            stop_loss_ratio=0.03,      # -3% 손절
            take_profit_ratio=0.07,    # +7% 익절
            trailing_stop_ratio=0.02,  # 고점 대비 -2% 트레일링스탑
            invest_ratio_per_stock=0.2, # 20%
            max_stocks_holding=5
        )

    def test_stop_loss_trigger(self):
        # 평단가 10,000원 -> 현재가 9,600원 (-4% 하락)
        should_sell, reason = self.risk_mgr.evaluate_holding_risk("005930", current_price=9600, avg_buy_price=10000)
        self.assertTrue(should_sell)
        self.assertIn("손절매", reason)

    def test_take_profit_trigger(self):
        # 평단가 10,000원 -> 현재가 10,800원 (+8% 상승)
        should_sell, reason = self.risk_mgr.evaluate_holding_risk("005930", current_price=10800, avg_buy_price=10000)
        self.assertTrue(should_sell)
        self.assertIn("목표 수익 달성", reason)

    def test_trailing_stop_trigger(self):
        # 1차 평가: 평단가 10,000원 -> 10,500원 (+5% 상승, 최고가 10,500원 저장)
        should_sell, _ = self.risk_mgr.evaluate_holding_risk("005930", current_price=10500, avg_buy_price=10000)
        self.assertFalse(should_sell)

        # 2차 평가: 최고가 10,500원 -> 현재가 10,250원 (최고가 대비 -2.38% 하락)
        should_sell, reason = self.risk_mgr.evaluate_holding_risk("005930", current_price=10250, avg_buy_price=10000)
        self.assertTrue(should_sell)
        self.assertIn("트레일링 스탑", reason)

    def test_calculate_buy_quantity(self):
        # 총 평가금액 1,000만원, 종목당 20% = 200만원 예산
        # 현재가 50,000원 -> 40주 계산
        qty = self.risk_mgr.calculate_buy_quantity(
            symbol="005930",
            current_price=50000,
            total_account_eval=10000000,
            available_cash=5000000,
            current_holding_count=2
        )
        self.assertEqual(qty, 40)

    def test_max_stocks_holding_limit(self):
        # 보유 종목 수 5개로 최대치 달성 -> 매수 불가 (0주)
        qty = self.risk_mgr.calculate_buy_quantity(
            symbol="005930",
            current_price=50000,
            total_account_eval=10000000,
            available_cash=5000000,
            current_holding_count=5
        )
        self.assertEqual(qty, 0)


if __name__ == "__main__":
    unittest.main()
