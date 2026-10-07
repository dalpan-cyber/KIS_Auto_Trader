
import unittest
from unittest.mock import MagicMock
from infinite_state_manager import InfiniteStateManager
from core.sheets.infinite_sheet_manager import InfiniteSheetManager

class TestCompletedTrades(unittest.TestCase):
    def test_get_completed_trades_fallback_to_local(self):
        mgr = InfiniteStateManager(enable_gss=False, completed_file='test_completed.json')
        sample = {
            '완료일시': '2026-09-22 10:00:00',
            '티커': 'TQQQ',
            '시작일자': '2026-08-01',
            '매도일자': '2026-09-22',
            '완료회차': 20,
            '매도수량': 30,
            '매수평단가($)': 70.0,
            '매도단가($)': 77.0,
            '총매수금액($)': 2100.0,
            '총매도금액($)': 2310.0,
            '실현손익($)': 210.0,
            '수익률(%)': 10.0,
            '상태': 'COMPLETED'
        }
        mgr._save_completed_trade_local(sample)
        trades = mgr.get_completed_trades()
        self.assertTrue(len(trades) >= 1)
        self.assertEqual(trades[-1]['티커'], 'TQQQ')
        import os
        if os.path.exists('test_completed.json'):
            os.remove('test_completed.json')

    def test_infinite_sheet_manager_get_completed_trades_unconnected(self):
        sheet_mgr = InfiniteSheetManager(enabled=False)
        self.assertEqual(sheet_mgr.get_completed_trades(), [])

if __name__ == '__main__':
    unittest.main()
