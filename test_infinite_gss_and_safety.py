"""
무한매수법 Google Sheets 연동, 전략 상태 관리 및 전량매도 수량 맞춤 안전장치 단위 테스트 (test_infinite_gss_and_safety.py)
"""
import os
import json
import unittest
from unittest.mock import MagicMock, patch

import config
from google_sheet_manager import GoogleSheetManager
from infinite_state_manager import InfiniteStateManager
from trader import TraderBot
from kis_api import KISApiClient


class TestInfiniteGSSAndSafety(unittest.TestCase):
    def setUp(self):
        self.test_state_file = "test_infinite_trader_state.json"
        if os.path.exists(self.test_state_file):
            os.remove(self.test_state_file)

    def tearDown(self):
        if os.path.exists(self.test_state_file):
            os.remove(self.test_state_file)

    def test_google_sheet_manager_fallback(self):
        """인증 정보 미설정 시 GoogleSheetManager 안전 폴백 검증"""
        gss_mgr = GoogleSheetManager(enabled=False)
        self.assertFalse(gss_mgr.is_connected)
        # 메서드 호출 시 예외 없이 무반응 수행되는지 확인
        gss_mgr.sync_all_states({})

    def test_state_manager_round_advance_and_complete(self):
        """InfiniteStateManager 회차 진행/완료 및 전략 상태만 관리하는지 검증"""
        mgr = InfiniteStateManager(file_path=self.test_state_file)
        mgr.gss_mgr = GoogleSheetManager(enabled=False)

        # 1. 초기 상태 (전략 상태만 존재, 보유 수량/평단가/이력 없음)
        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["current_round"], 0)
        self.assertEqual(st["status"], "IDLE")
        self.assertNotIn("total_qty", st)
        self.assertNotIn("avg_price", st)
        self.assertNotIn("history", st)

        # 2. 매수 체결 시 회차 진행 (0.5회차)
        mgr.advance_round("TQQQ", round_inc=0.5)
        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["current_round"], 0.5)
        self.assertEqual(st["status"], "BUYING")

        # 3. 추가 매수 체결 시 회차 진행 (1.0회차)
        mgr.advance_round("TQQQ", round_inc=0.5)
        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["current_round"], 1.0)

        # 4. 익절 매도 시 회차 리셋 및 COMPLETED
        mgr.complete_round("TQQQ")
        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["current_round"], 0)
        self.assertEqual(st["status"], "COMPLETED")

    def test_trader_full_sell_qty_reconciliation(self):
        """+10% 전량 익절 매도 시 계좌 수량과 제안 수량이 다를 때 계좌 수량으로 자동 수정되는 안전 로직 검증"""
        api_mock = MagicMock(spec=KISApiClient)
        api_mock.mock = True
        api_mock.app_key = "test"
        api_mock.app_secret = "test"
        api_mock.cano = "12345678"
        api_mock.acnt_prdt_cd = "01"
        api_mock.is_overseas_symbol.return_value = True
        api_mock.get_stock_price.return_value = {"success": True, "price": 60.0}

        bot = TraderBot(api=api_mock)
        bot.infinite_state_mgr = InfiniteStateManager(file_path=self.test_state_file)
        bot.infinite_state_mgr.gss_mgr = GoogleSheetManager(enabled=False)

        # 전략 상태: 5회차 진행 중
        st = bot.infinite_state_mgr.get_symbol_state("TQQQ")
        st["current_round"] = 5.0
        st["status"] = "BUYING"
        bot.infinite_state_mgr.save_state()

        # 계좌 실제 보유: 5주 (KIS API가 Source of Truth)
        bot.holdings = {
            "TQQQ": {
                "name": "TQQQ",
                "qty": 5,  # 계좌 실제 수량: 5주
                "avg_price": 50.0,
                "current_price": 60.0,
                "pnl_rate": 20.0
            }
        }

        # 1. 제안 승인 매도 시 수량 보정 테스트
        proposal_id = "TQQQ_SELL"
        bot.pending_proposals[proposal_id] = {
            "id": proposal_id,
            "symbol": "TQQQ",
            "stock_name": "TQQQ (무한매수)",
            "action": "SELL",
            "action_kr": "익절 매도",
            "qty": 10,  # 제안 수량 10주 (상태에 기록된 수량과 불일치)
            "price": 55.0,
            "total_price": 550.0,
            "reason": "+10% 전량 익절",
            "timestamp": "12:00:00"
        }

        api_mock.order_overseas_cash.return_value = {"success": True, "msg": "주문 성공"}

        success = bot.approve_proposal(proposal_id)
        self.assertTrue(success)

        # KIS API order_overseas_cash에 계좌 수량인 5주로 매도 주문이 전송되었는지 확인!
        api_mock.order_overseas_cash.assert_called_with("TQQQ", 5, price=55.0, buy=False, ord_type="00")

    def test_run_infinite_buying_cycle_sell_qty_reconciliation(self):
        """자동 매매 사이클에서 전량 매도 수량 자동 보정 검증"""
        api_mock = MagicMock(spec=KISApiClient)
        api_mock.mock = True
        api_mock.app_key = "test"
        api_mock.app_secret = "test"
        api_mock.cano = "12345678"
        api_mock.acnt_prdt_cd = "01"
        api_mock.is_overseas_symbol.return_value = True
        api_mock.get_stock_price.return_value = {"success": True, "price": 60.0}

        bot = TraderBot(api=api_mock)
        bot.infinite_state_mgr = InfiniteStateManager(file_path=self.test_state_file)
        bot.infinite_state_mgr.gss_mgr = GoogleSheetManager(enabled=False)
        bot.require_approval = False
        bot.infinite_stocks = ["TQQQ"]

        # 전략 상태: 5회차 진행 중
        st = bot.infinite_state_mgr.get_symbol_state("TQQQ")
        st["current_round"] = 5.0
        st["status"] = "BUYING"
        bot.infinite_state_mgr.save_state()

        # 계좌 실제 보유: 4주 (KIS API가 Source of Truth)
        bot.holdings = {
            "TQQQ": {
                "name": "TQQQ",
                "qty": 4,  # 실제 계좌 보유수량 4주
                "avg_price": 50.0,
                "current_price": 60.0
            }
        }

        api_mock.order_overseas_cash.return_value = {"success": True, "msg": "주문 성공"}

        bot.run_infinite_buying_cycle()

        # 전량 익절 매도 주문이 4주로 자동 보정되어 제출되었는지 검증
        api_mock.order_overseas_cash.assert_any_call("TQQQ", 4, price=55.0, buy=False, ord_type="00")

    def test_stale_google_sheet_round_protection(self):
        """구글 시트에 오래된 회차가 남아있을 때 BUYING 상태인 JSON 회차(예: 3.0)가 1.0으로 다운그레이드되지 않도록 보호하는지 검증"""
        initial_data = {
            "TQQQ": {
                "symbol": "TQQQ",
                "start_date": "2026-08-07",
                "total_budget_usd": 5000.0,
                "division_count": 40,
                "current_round": 3.0,
                "target_roi": 0.1,
                "status": "BUYING"
            }
        }
        with open(self.test_state_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)

        mgr = InfiniteStateManager(file_path=self.test_state_file, enable_gss=False)
        mock_gss = MagicMock()
        mock_gss.is_connected = True
        mock_gss.read_states_from_sheet.return_value = {
            "TQQQ": {
                "symbol": "TQQQ",
                "division_count": 40,
                "start_date": "2026-08-07",
                "current_round": 1.0,
                "total_budget_usd": 5000.0,
                "target_roi": 0.1,
                "status": "BUYING"
            }
        }
        mgr.gss_mgr = mock_gss
        mgr.load_state()

        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["current_round"], 3.0)


if __name__ == "__main__":
    unittest.main()
