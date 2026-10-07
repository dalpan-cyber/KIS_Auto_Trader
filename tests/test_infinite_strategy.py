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
        self.assertEqual(state["status"], "IDLE")
        # 전략 상태만 관리 (보유 수량/평단가는 API가 Source of Truth)
        self.assertNotIn("total_qty", state)
        self.assertNotIn("avg_price", state)
        self.assertNotIn("history", state)

        # 1차 매수 체결 시 회차 진행 (0.5회차)
        self.state_mgr.advance_round(symbol, round_inc=0.5)
        state = self.state_mgr.get_symbol_state(symbol)
        self.assertEqual(state["current_round"], 0.5)
        self.assertEqual(state["status"], "BUYING")

        # 2차 매수 체결 시 회차 진행 (0.5회차)
        self.state_mgr.advance_round(symbol, round_inc=0.5)
        state = self.state_mgr.get_symbol_state(symbol)
        self.assertEqual(state["current_round"], 1.0)

        # 익절 매도 시 회차 리셋 및 COMPLETED
        self.state_mgr.complete_round(symbol)
        state = self.state_mgr.get_symbol_state(symbol)
        self.assertEqual(state["current_round"], 0)
        self.assertEqual(state["status"], "COMPLETED")

    def test_strategy_order_generation(self):
        strategy = StrategyFactory.create_strategy("INFINITE_BUYING", division_count=40, target_roi=0.10)
        symbol = "TQQQ"
        
        # 1. 신규 시작 상태 (0회차, 미보유)
        state_0 = {
            "symbol": symbol,
            "total_budget_usd": 10000.0,
            "division_count": 40,
            "current_round": 0,
            "target_roi": 0.10
        }
        orders = strategy.generate_daily_orders(symbol, current_price=50.0, state=state_0)
        self.assertEqual(len(orders), 2)  # 매수 LOC 2건 (익절 매도 없음)
        self.assertEqual(orders[0]["action"], "BUY")
        self.assertEqual(orders[0]["ord_type"], "34")
        self.assertEqual(orders[0]["price"], 50.0)

        # 2. 보유 중 상태 (1회차, 평단가 50.0, 보유 10주) - API 실계좌 데이터를 별도 파라미터로 전달
        state_1 = {
            "symbol": symbol,
            "total_budget_usd": 10000.0,
            "division_count": 40,
            "current_round": 1.0,
            "target_roi": 0.10
        }
        orders = strategy.generate_daily_orders(
            symbol, current_price=52.0, state=state_1,
            avg_price=50.0, total_qty=10
        )
        self.assertEqual(len(orders), 3)  # 익절 매도 1건 + 매수 LOC 2건
        sell_order = [o for o in orders if o["action"] == "SELL"][0]
        self.assertEqual(sell_order["price"], 55.0)  # +10% 지정가 = 55.0

    def test_strategy_exhaust_modes(self):
        symbol = "TQQQ"
        state_40 = {
            "symbol": symbol,
            "total_budget_usd": 4000.0,
            "division_count": 40,
            "current_round": 40.0,
            "target_roi": 0.10
        }

        # 1. HOLD 모드 (무한 대기)
        strat_hold = InfiniteBuyingStrategy(division_count=40, target_roi=0.10, exhaust_action="HOLD")
        orders_hold = strat_hold.generate_daily_orders(symbol, current_price=50.0, state=state_40, avg_price=50.0, total_qty=40)
        self.assertEqual(len(orders_hold), 1)  # 매수 없이 익절 매도 1건만
        self.assertEqual(orders_hold[0]["action"], "SELL")
        self.assertEqual(orders_hold[0]["price"], 55.0)  # +10%

        # 2. LOWER_TARGET 모드 (목표가 하향 탈출)
        strat_lower = InfiniteBuyingStrategy(division_count=40, target_roi=0.10, exhaust_action="LOWER_TARGET", exhaust_target_roi=0.05)
        orders_lower = strat_lower.generate_daily_orders(symbol, current_price=50.0, state=state_40, avg_price=50.0, total_qty=40)
        self.assertEqual(len(orders_lower), 1)  # 매수 없이 익절 매도 1건만
        self.assertEqual(orders_lower[0]["action"], "SELL")
        self.assertEqual(orders_lower[0]["price"], 52.5)  # +5% (50.0 * 1.05)

        # 3. REBALANCE_QUARTER 모드 (쿼터 순환 매매)
        strat_reb = InfiniteBuyingStrategy(division_count=40, target_roi=0.10, exhaust_action="REBALANCE_QUARTER")
        orders_reb = strat_reb.generate_daily_orders(symbol, current_price=50.0, state=state_40, avg_price=50.0, total_qty=40)
        # 익절 매도 1건 + 순환 매도 1건 + 순환 LOC 재매수 1건 = 총 3건
        self.assertEqual(len(orders_reb), 3)
        sell_orders = [o for o in orders_reb if o["action"] == "SELL"]
        buy_orders = [o for o in orders_reb if o["action"] == "BUY"]
        self.assertEqual(len(sell_orders), 2)
        self.assertEqual(len(buy_orders), 1)

    def test_v21_first_and_second_half_orders(self):
        """라오어 무한매수법 v2.1 전반전(0.5회차x2) vs 후반전(1.0회차x1) 차등 매수 및 별% 공식 검증"""
        symbol = "TQQQ"
        strategy = InfiniteBuyingStrategy(division_count=40, target_roi=0.10)

        # 1. 전반전 (T=1.0회차): 0.5회차 평단가 LOC + 0.5회차 큰수(☆+9.5%) LOC
        # 예산 $4000, 40분할 -> 1회 예산 $100, 0.5회차 예산 $50
        # 평단가 $50.00
        # 별% = 10 - 1/2 = +9.5% -> 큰수 가격 = 50 * 1.095 = 54.75
        state_first_half = {
            "symbol": symbol,
            "total_budget_usd": 4000.0,
            "division_count": 40,
            "current_round": 1.0,
            "target_roi": 0.10
        }
        orders_1 = strategy.generate_daily_orders(
            symbol, current_price=52.0, state=state_first_half,
            avg_price=50.0, total_qty=10
        )
        self.assertEqual(len(orders_1), 3)  # 익절 매도 1건 + 매수 LOC 2건
        buy_orders_1 = [o for o in orders_1 if o["action"] == "BUY"]
        self.assertEqual(len(buy_orders_1), 2)
        self.assertEqual(buy_orders_1[0]["price"], 50.0)
        self.assertEqual(buy_orders_1[0]["qty"], 1)
        self.assertEqual(buy_orders_1[0]["round_inc"], 0.5)
        self.assertEqual(buy_orders_1[1]["price"], 54.75)
        self.assertEqual(buy_orders_1[1]["qty"], 1)
        self.assertEqual(buy_orders_1[1]["round_inc"], 0.5)
        self.assertIn("☆+9.5%", buy_orders_1[1]["desc"])

        # 2. 후반전 시작 (T=20.0회차): 1.0회차 후반전(☆0.0%) LOC 1건
        # 별% = 10 - 20/2 = 0.0% -> 가격 = 50 * 1.0 = 50.00
        # 1회 예산 $100 -> 수량 = int(100 / 50) = 2주
        state_second_half_20 = {
            "symbol": symbol,
            "total_budget_usd": 4000.0,
            "division_count": 40,
            "current_round": 20.0,
            "target_roi": 0.10
        }
        orders_20 = strategy.generate_daily_orders(
            symbol, current_price=48.0, state=state_second_half_20,
            avg_price=50.0, total_qty=40
        )
        self.assertEqual(len(orders_20), 2)  # 익절 매도 1건 + 후반전 매수 LOC 1건
        buy_orders_20 = [o for o in orders_20 if o["action"] == "BUY"]
        self.assertEqual(len(buy_orders_20), 1)
        self.assertEqual(buy_orders_20[0]["price"], 50.0)
        self.assertEqual(buy_orders_20[0]["qty"], 2)
        self.assertEqual(buy_orders_20[0]["round_inc"], 1.0)
        self.assertIn("1.0회차 후반전(☆+0.0%)", buy_orders_20[0]["desc"])

        # 3. 후반전 진행 중 (T=30.0회차): 1.0회차 후반전(☆-5.0%) LOC 1건
        # 별% = 10 - 30/2 = -5.0% -> 가격 = 50 * 0.95 = 47.50
        # 1회 예산 $100 -> 수량 = int(100 / 47.50) = 2주
        state_second_half_30 = {
            "symbol": symbol,
            "total_budget_usd": 4000.0,
            "division_count": 40,
            "current_round": 30.0,
            "target_roi": 0.10
        }
        orders_30 = strategy.generate_daily_orders(
            symbol, current_price=45.0, state=state_second_half_30,
            avg_price=50.0, total_qty=60
        )
        self.assertEqual(len(orders_30), 2)
        buy_orders_30 = [o for o in orders_30 if o["action"] == "BUY"]
        self.assertEqual(len(buy_orders_30), 1)
        self.assertEqual(buy_orders_30[0]["price"], 47.50)
        self.assertEqual(buy_orders_30[0]["qty"], 2)
        self.assertEqual(buy_orders_30[0]["round_inc"], 1.0)
        self.assertIn("1.0회차 후반전(☆-5.0%)", buy_orders_30[0]["desc"])


if __name__ == "__main__":
    unittest.main()
