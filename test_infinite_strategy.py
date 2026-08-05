"""
무한매수법 상태 관리자 및 전략 엔진 단위 테스트 (test_infinite_strategy.py)
"""
import os
import unittest
from infinite_state_manager import InfiniteStateManager
from strategy import InfiniteBuyingStrategy, StrategyFactory

class TestInfiniteStrategy(unittest.TestCase):

    def setUp(self):
        self.test_file = "test_infinite_state.json"
        if os.path.exists(self.test_file):
            os.remove(self.test_file)
        self.state_mgr = InfiniteStateManager(self.test_file)

    def tearDown(self):
        if os.path.exists(self.test_file):
            os.remove(self.test_file)

    def test_state_manager_lifecycle(self):
        symbol = "TQQQ"
        state = self.state_mgr.get_symbol_state(symbol, default_budget_usd=10000.0, division_count=40)
        self.assertEqual(state["current_round"], 0)
        self.assertEqual(state["total_qty"], 0)

        # 1차 매수 체결 기록 (0.5회차, 5주 @ $50.0)
        self.state_mgr.record_buy_execution(symbol, qty=5, price=50.0, round_inc=0.5)
        state = self.state_mgr.get_symbol_state(symbol)
        self.assertEqual(state["current_round"], 0.5)
        self.assertEqual(state["total_qty"], 5)
        self.assertEqual(state["avg_price"], 50.0)

        # 2차 매수 체결 기록 (0.5회차, 5주 @ $60.0)
        self.state_mgr.record_buy_execution(symbol, qty=5, price=60.0, round_inc=0.5)
        state = self.state_mgr.get_symbol_state(symbol)
        self.assertEqual(state["current_round"], 1.0)
        self.assertEqual(state["total_qty"], 10)
        self.assertEqual(state["avg_price"], 55.0)

        # 익절 매도 체결 기록
        self.state_mgr.record_sell_execution(symbol, qty=10, price=60.5)
        state = self.state_mgr.get_symbol_state(symbol)
        self.assertEqual(state["current_round"], 0)
        self.assertEqual(state["total_qty"], 0)
        self.assertEqual(state["avg_price"], 0.0)
        self.assertEqual(state["status"], "COMPLETED")

    def test_strategy_order_generation(self):
        strategy = StrategyFactory.create_strategy("INFINITE_BUYING", division_count=40, target_roi=0.10)
        symbol = "TQQQ"
        
        # 1. 신규 시작 상태 (0회차)
        state_0 = {
            "symbol": symbol,
            "total_budget_usd": 10000.0,
            "division_count": 40,
            "current_round": 0,
            "avg_price": 0.0,
            "total_qty": 0,
            "target_roi": 0.10
        }
        orders = strategy.generate_daily_orders(symbol, current_price=50.0, state=state_0)
        self.assertEqual(len(orders), 2)  # 매수 LOC 2건 (익절 매도 없음)
        self.assertEqual(orders[0]["action"], "BUY")
        self.assertEqual(orders[0]["ord_type"], "34")
        self.assertEqual(orders[0]["price"], 50.0)

        # 2. 보유 중 상태 (1회차, 평단가 50.0, 보유 10주)
        state_1 = {
            "symbol": symbol,
            "total_budget_usd": 10000.0,
            "division_count": 40,
            "current_round": 1.0,
            "avg_price": 50.0,
            "total_qty": 10,
            "target_roi": 0.10
        }
        orders = strategy.generate_daily_orders(symbol, current_price=52.0, state=state_1)
        self.assertEqual(len(orders), 3)  # 익절 매도 1건 + 매수 LOC 2건
        sell_order = [o for o in orders if o["action"] == "SELL"][0]
        self.assertEqual(sell_order["price"], 55.0)  # +10% 지정가 = 55.0

if __name__ == "__main__":
    unittest.main()
