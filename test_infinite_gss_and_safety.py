"""
무한매수법 Google Sheets 연동, 매수실패 기록 및 전량매도 수량 맞춤 안전장치 단위 테스트 (test_infinite_gss_and_safety.py)
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
        gss_mgr.append_history_entry("TQQQ", "BUY", 10, 50.0)

    def test_state_manager_record_buy_and_failure(self):
        """InfiniteStateManager 매수 체결, 매수 실패, LOC 접수 기록 검증"""
        mgr = InfiniteStateManager(file_path=self.test_state_file)
        mgr.gss_mgr = GoogleSheetManager(enabled=False)

        # 1. 매수 체결 기록
        mgr.record_buy_execution("TQQQ", qty=5, price=50.0, round_inc=0.5)
        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["total_qty"], 5)
        self.assertEqual(st["avg_price"], 50.0)
        self.assertEqual(st["current_round"], 0.5)
        self.assertEqual(len(st["history"]), 1)
        self.assertEqual(st["history"][0]["type"], "BUY")

        # 2. 매수 실패 기록
        mgr.record_buy_failure("TQQQ", qty=5, price=52.0, reason="APBK1681 기본예탁금 미등록")
        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(len(st["history"]), 2)
        self.assertEqual(st["history"][1]["type"], "BUY_FAILED")
        self.assertIn("APBK1681", st["history"][1]["note"])

        # 3. LOC 주문 접수 기록
        mgr.record_order_sent("TQQQ", qty=5, price=50.0, ord_type="34", desc="0.5회차 LOC 매수")
        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(len(st["history"]), 3)
        self.assertEqual(st["history"][2]["type"], "ORDER_SENT")

    def test_trader_full_sell_qty_reconciliation(self):
        """+10% 전량 익절 매도 시 계좌 수량과 상태 수량이 다를 때 계좌 수량으로 자동 수정되는 안전 로직 검증"""
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

        # 상태에는 10주 보유 중으로 기록되어 있으나 계좌 실제 수량은 5주라고 가정 (수량 불일치)
        st = bot.infinite_state_mgr.get_symbol_state("TQQQ")
        st["total_qty"] = 10
        st["avg_price"] = 50.0
        st["current_round"] = 5.0
        bot.infinite_state_mgr.save_state()

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
            "qty": 10,  # 제안 수량 10주
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

        st = bot.infinite_state_mgr.get_symbol_state("TQQQ")
        st["total_qty"] = 10
        st["avg_price"] = 50.0
        st["current_round"] = 5.0
        st["status"] = "BUYING"
        bot.infinite_state_mgr.save_state()

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


if __name__ == "__main__":
    unittest.main()
