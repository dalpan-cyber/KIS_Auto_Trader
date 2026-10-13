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

        # 4. 익절 매도 시 회차 리셋 및 COMPLETED, 구글 시트 완료일지 연동 검증
        mock_gss = MagicMock()
        mgr.gss_mgr = mock_gss
        mgr.complete_round("TQQQ", avg_price=50.0, sell_price=55.0, qty=10)
        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["current_round"], 0)
        self.assertEqual(st["status"], "COMPLETED")
        mock_gss.record_completed_cycle.assert_called_once()

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
        """구글 시트 연동 여부와 무관하게 로컬 JSON 회차(Single Source of Truth)가 보존되는지 검증"""
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
        mgr.gss_mgr = mock_gss
        mgr.load_state()

        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["current_round"], 3.0)

    def test_sync_holdings_to_state_case_a_with_execution_history_sell_price(self):
        """케이스 A(전량 매도 후 잔고 0) 시 KIS 체결 이력의 실제 매도 체결단가와 last_avg_price가 complete_round에 정확히 전달되는지 검증"""
        api_mock = MagicMock(spec=KISApiClient)
        api_mock.mock = True
        api_mock.get_overseas_account_balance.return_value = {"success": True, "output": {}}
        api_mock.get_overseas_stock_balance.return_value = {"success": True, "holdings": []}
        api_mock.get_overseas_execution_balance.return_value = {"success": True, "holdings": []}

        # KIS 체결 이력 모의 데이터 (실제 체결된 매도 건: 10주 @ $55.0)
        api_mock.get_overseas_execution_history.return_value = [
            {
                "order_time": "2026-09-18 23:30:00",
                "symbol": "TQQQ",
                "order_type": "매도",
                "qty": 10,
                "executed_qty": 10,
                "price": 55.0,
                "executed_price": 55.0,
                "status": "체결",
                "order_no": "ORD12345"
            }
        ]

        bot = TraderBot(api=api_mock)
        bot.infinite_state_mgr = InfiniteStateManager(file_path=self.test_state_file, enable_gss=False)
        mock_gss = MagicMock()
        mock_gss.is_connected = True
        bot.infinite_state_mgr.gss_mgr = mock_gss
        bot.infinite_stocks = ["TQQQ"]

        # 종목 상태 설정: 3회차 진행 중, peak_qty=10, last_avg_price=50.0
        st = bot.infinite_state_mgr.get_symbol_state("TQQQ")
        st["current_round"] = 3.0
        st["status"] = "BUYING"
        st["peak_qty"] = 10
        st["last_avg_price"] = 50.0
        bot.infinite_state_mgr.save_state()

        # 잔고 0주인 상태에서 동기화 호출
        bot.holdings = {}
        bot.sync_holdings_to_state()

        # 검증: complete_round가 실제 매도 체결가 $55.0, 평단가 $50.0, 수량 10주로 완료 처리되었는지 확인
        mock_gss.record_completed_cycle.assert_called_once()
        call_kwargs = mock_gss.record_completed_cycle.call_args.kwargs
        self.assertEqual(call_kwargs["symbol"], "TQQQ")
        self.assertEqual(call_kwargs["avg_price"], 50.0)
        self.assertEqual(call_kwargs["sell_price"], 55.0)
        self.assertEqual(call_kwargs["qty"], 10)

        # 상태가 COMPLETED로 전환되고 peak_qty가 0으로 리셋되었는지 확인
        final_st = bot.infinite_state_mgr.get_symbol_state("TQQQ")
        self.assertEqual(final_st["status"], "COMPLETED")
        self.assertEqual(final_st["current_round"], 0)
        self.assertEqual(final_st["peak_qty"], 0)

    def test_sync_execution_history_to_sheets(self):
        """sync_execution_history_to_sheets가 체결 이력을 조회해 gss_mgr에 정상 전달하는지 검증"""
        api_mock = MagicMock(spec=KISApiClient)
        mock_history = [
            {"symbol": "TQQQ", "order_type": "매도", "executed_qty": 5, "executed_price": 60.0}
        ]
        api_mock.get_overseas_execution_history.return_value = mock_history

        bot = TraderBot(api=api_mock)
        bot.infinite_state_mgr = InfiniteStateManager(file_path=self.test_state_file, enable_gss=False)
        mock_gss = MagicMock()
        mock_gss.is_connected = True
        bot.infinite_state_mgr.gss_mgr = mock_gss
        bot.infinite_stocks = ["TQQQ"]

        bot.sync_execution_history_to_sheets(days_back=7)

        # 구글 시트 sync_execution_history가 호출되었는지 확인
        mock_gss.sync_execution_history.assert_called_once_with(mock_history)

    def test_pause_resume_sync_with_google_sheets(self):
        """웹 UI에서 일시중지(PAUSED) 및 지정매도가 설정 시 Google Sheets를 통해 GitHub Actions(로컬 BUYING 상태)에 동기화되는지 검증"""
        # 1. Git 저장소에 커밋된 기존 상태 가정 (status=BUYING, paused_sell_price=0.0)
        initial_data = {
            "TQQQ": {
                "symbol": "TQQQ",
                "start_date": "2026-09-22",
                "total_budget_usd": 5000.0,
                "division_count": 40,
                "current_round": 8.0,
                "target_roi": 0.1,
                "status": "BUYING",
                "paused_sell_price": 0.0,
            }
        }
        with open(self.test_state_file, "w", encoding="utf-8") as f:
            json.dump(initial_data, f)

        # 2. Google Sheets 'State' 워크시트에서 PAUSED 및 지정매도가($88.50)를 반환하도록 모킹
        mock_gss = MagicMock()
        mock_gss.is_connected = True
        mock_gss.read_settings_from_sheet.return_value = {}
        mock_gss.read_states_from_sheet.return_value = {
            "TQQQ": {
                "symbol": "TQQQ",
                "division_count": 40,
                "start_date": "2026-09-22",
                "current_round": 8.0,
                "total_budget_usd": 5000.0,
                "target_roi": 0.1,
                "status": "PAUSED",
                "paused_sell_price": 88.5,
            }
        }

        with patch("infinite_state_manager.GoogleSheetManager", return_value=mock_gss):
            mgr = InfiniteStateManager(file_path=self.test_state_file, enable_gss=True)

        st = mgr.get_symbol_state("TQQQ")
        self.assertEqual(st["status"], "PAUSED")
        self.assertEqual(st["paused_sell_price"], 88.5)

        # 3. 이후 웹 UI에서 투자 재개(BUYING, paused_sell_price=0.0)했을 때 다시 BUYING으로 복원되는지 검증
        mock_gss.read_states_from_sheet.return_value = {
            "TQQQ": {
                "symbol": "TQQQ",
                "division_count": 40,
                "start_date": "2026-09-22",
                "current_round": 8.0,
                "total_budget_usd": 5000.0,
                "target_roi": 0.1,
                "status": "BUYING",
                "paused_sell_price": 0.0,
            }
        }

        with patch("infinite_state_manager.GoogleSheetManager", return_value=mock_gss):
            mgr_resumed = InfiniteStateManager(file_path=self.test_state_file, enable_gss=True)

        st_resumed = mgr_resumed.get_symbol_state("TQQQ")
        self.assertEqual(st_resumed["status"], "BUYING")
        self.assertEqual(st_resumed["paused_sell_price"], 0.0)

    def test_pause_cancels_unexecuted_buy_orders(self):
        """일시중지 시 미체결 LOC 매수 주문만 선별하여 취소하고 당일 매수 원장(order_ledger)을 초기화하는지 검증"""
        api_client = KISApiClient(app_key="test", app_secret="test", cano="12345678", acnt_prdt_cd="01", mock=True)
        api_client.access_token = "mock_token"
        api_client.token_issued_at = 9999999999

        # 미체결 LOC 매수 2건 + 미체결 매도 1건 + 이미 취소된 매수 1건 모킹
        api_client.get_overseas_order_ccnl = MagicMock(return_value=[
            {
                "order_no": "00101",
                "symbol": "TQQQ",
                "order_type": "매수",
                "sll_buy_dvsn_cd": "02",
                "qty": 3,
                "executed_qty": 0,
                "nccs_qty": "3",
                "price": 78.50,
                "status": "접수",
                "rvse_cncl_dvsn": "00",
                "rvse_cncl_dvsn_name": "",
                "ovrs_excg_cd": "NASD",
            },
            {
                "order_no": "00102",
                "symbol": "TQQQ",
                "order_type": "매수",
                "sll_buy_dvsn_cd": "02",
                "qty": 2,
                "executed_qty": 0,
                "nccs_qty": "2",
                "price": 82.00,
                "status": "전송",
                "rvse_cncl_dvsn": "00",
                "rvse_cncl_dvsn_name": "",
                "ovrs_excg_cd": "NASD",
            },
            {
                "order_no": "00103",
                "symbol": "TQQQ",
                "order_type": "매도",
                "sll_buy_dvsn_cd": "01",
                "qty": 16,
                "executed_qty": 0,
                "nccs_qty": "16",
                "price": 87.07,
                "status": "접수",
                "rvse_cncl_dvsn": "00",
                "rvse_cncl_dvsn_name": "",
                "ovrs_excg_cd": "NASD",
            },
            {
                "order_no": "00104",
                "symbol": "TQQQ",
                "order_type": "매수",
                "sll_buy_dvsn_cd": "02",
                "qty": 2,
                "executed_qty": 0,
                "nccs_qty": "0",
                "price": 75.00,
                "status": "취소",
                "rvse_cncl_dvsn": "02",
                "rvse_cncl_dvsn_name": "취소",
                "ovrs_excg_cd": "NASD",
            },
        ])
        api_client.cancel_overseas_order = MagicMock(return_value={"success": True, "msg": "취소 성공"})

        mgr = InfiniteStateManager(file_path=self.test_state_file, enable_gss=False)
        st = mgr.get_symbol_state("TQQQ")
        st["status"] = "BUYING"
        st["order_ledger"] = {"session": "2026-10-13", "keys": ["SELL_00_1", "BUY_34_1", "BUY_34_2"]}
        mgr.save_state()

        # pause_buying 호출 및 미체결 매수 취소 실행
        mgr.pause_buying("TQQQ", sell_price=88.0)
        res = api_client.cancel_unexecuted_overseas_buy_orders("TQQQ")

        self.assertTrue(res["success"])
        self.assertEqual(res["cancelled"], 2)
        self.assertEqual(api_client.cancel_overseas_order.call_count, 2)
        # 매도 주문(00103)이나 이미 취소된 주문(00104)은 건드리지 않고 미체결 매수(00101, 00102)만 취소
        called_odnos = [c.kwargs["order_no"] for c in api_client.cancel_overseas_order.call_args_list]
        self.assertEqual(called_odnos, ["00101", "00102"])
        # 당일 order_ledger에서 BUY_ 슬롯만 제거되고 SELL_00_1은 유지되는지 확인
        self.assertEqual(mgr.get_symbol_state("TQQQ")["order_ledger"]["keys"], ["SELL_00_1"])


if __name__ == "__main__":
    unittest.main()
