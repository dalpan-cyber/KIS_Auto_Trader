"""
TraderBot 매매 제안 및 에러 처리 단위 테스트 (test_trader_proposals.py)
"""
import unittest
from unittest.mock import MagicMock
from trader import TraderBot


class TestTraderProposals(unittest.TestCase):

    def setUp(self):
        self.mock_api = MagicMock()
        self.mock_api.is_overseas_symbol.return_value = True
        self.bot = TraderBot(api=self.mock_api)
        self.bot.require_approval = True

    def test_approve_proposal_pops_on_failure(self):
        """주문 실패 시에도 proposal이 pending_proposals에서 제거되어 무한 재시도가 안 되도록 보장"""
        proposal_id = "INFINITE_TQQQ_BUY_34_50.00"
        self.bot.pending_proposals[proposal_id] = {
            "id": proposal_id,
            "symbol": "TQQQ",
            "action": "BUY",
            "action_kr": "LOC 매수",
            "qty": 1,
            "price": 50.0,
            "ord_type": "34"
        }

        # API 실패 응답 모킹 (APBK1681)
        self.mock_api.order_overseas_cash.return_value = {
            "success": False,
            "msg": "해당종목은 기본예탁금 충족한 계좌만 매수주문가능합니다 (코드: APBK1681)",
            "msg_cd": "APBK1681"
        }

        result = self.bot.approve_proposal(proposal_id)

        self.assertFalse(result)
        # pending_proposals에서 제거되었는지 확인
        self.assertNotIn(proposal_id, self.bot.pending_proposals)
        # 연속 에러 카운터가 1 증가했는지 확인
        self.assertEqual(self.bot.risk_mgr.consecutive_errors, 1)

    def test_approve_proposal_circuit_breaker(self):
        """서킷브레이커 발동 시 신규 승인이 차단되는지 검증"""
        self.bot.risk_mgr.consecutive_errors = 3  # 서킷브레이커 발동 상태

        proposal_id = "INFINITE_TQQQ_BUY_34_50.00"
        self.bot.pending_proposals[proposal_id] = {
            "id": proposal_id,
            "symbol": "TQQQ",
            "action": "BUY",
            "action_kr": "LOC 매수",
            "qty": 1,
            "price": 50.0,
            "ord_type": "34"
        }

        result = self.bot.approve_proposal(proposal_id)

        self.assertFalse(result)
        self.assertNotIn(proposal_id, self.bot.pending_proposals)
        self.mock_api.order_overseas_cash.assert_not_called()


if __name__ == "__main__":
    unittest.main()
