"""
Comprehensive Unit Tests for KIS Auto 2 Refactored Core Architecture
- Storage Atomic I/O & Thread Safety
- Technical Indicators & ATR
- Safety Gates (Disparity, Upper Shadow, Supply Gate)
- Market Regime Filters & Stop-loss Cooldown
- Trailing Stop & Time-based Exit
- Position Tracker
"""
import unittest
import os
import tempfile
import threading
import pandas as pd
import numpy as np

from core.storage import atomic_save_json, safe_load_json
from core.indicators import calculate_technical_indicators
from core.position_tracker import PositionTracker
from core.strategy import (
    get_market_regime,
    calculate_position_size,
    evaluate_buy_signals_from_df,
    evaluate_sell_signals_from_df
)

class TestStorageModule(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_file = os.path.join(self.test_dir, "test_state.json")

    def tearDown(self):
        if os.path.exists(self.test_file):
            try:
                os.remove(self.test_file)
            except Exception:
                pass
        try:
            os.rmdir(self.test_dir)
        except Exception:
            pass

    def test_atomic_save_and_safe_load(self):
        data = {"key": "value", "count": 42, "items": [1, 2, 3]}
        ok = atomic_save_json(self.test_file, data)
        self.assertTrue(ok)
        self.assertTrue(os.path.exists(self.test_file))

        loaded = safe_load_json(self.test_file)
        self.assertEqual(loaded, data)

    def test_safe_load_nonexistent_and_corrupted(self):
        # Non-existent
        res = safe_load_json("non_existent_file.json", default={"default": True})
        self.assertEqual(res, {"default": True})

        # Corrupted JSON
        with open(self.test_file, "w", encoding="utf-8") as f:
            f.write("{invalid_json: 123,")
        res_corrupt = safe_load_json(self.test_file, default={"recovered": True})
        self.assertEqual(res_corrupt, {"recovered": True})

    def test_concurrent_atomic_writes(self):
        threads = []
        errors = []

        def worker(idx):
            try:
                for i in range(20):
                    atomic_save_json(self.test_file, {"worker": idx, "iteration": i})
            except Exception as e:
                errors.append(e)

        for i in range(5):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        final_data = safe_load_json(self.test_file)
        self.assertIn("worker", final_data)

class TestIndicatorsModule(unittest.TestCase):
    def generate_candles(self, n=65, base_price=10000):
        candles = []
        for i in range(n):
            p = base_price + i * 10
            candles.append({
                "date": f"202601{i+1:02d}",
                "open": p - 5,
                "high": p + 20,
                "low": p - 20,
                "close": p,
                "volume": 10000 + i * 100
            })
        return candles

    def test_indicator_columns_and_calculations(self):
        candles = self.generate_candles(65)
        df = calculate_technical_indicators(candles, is_intraday=True)
        self.assertIsNotNone(df)
        self.assertEqual(len(df), 65)

        for col in ["ma5", "ma20", "ma60", "vol_ma20", "adjusted_volume", "rsi14", "bb_upper", "bb_lower", "atr"]:
            self.assertIn(col, df.columns)

        # 15:10 intraday volume adjustment
        last_vol = candles[-1]["volume"]
        expected_adj = last_vol * (390.0 / 370.0)
        self.assertAlmostEqual(df.iloc[-1]["adjusted_volume"], expected_adj, places=1)

class TestStrategyModule(unittest.TestCase):
    def test_disparity_safety_gate(self):
        """이격도 과열 방지 필터: 5일선 대비 3% 초과 또는 20일선 대비 6% 초과 시 배제"""
        df = pd.DataFrame({
            "close": [10000] * 20 + [10400],  # 5일선 10080 대비 3.17% 초과
            "open": [10000] * 20 + [10100],
            "high": [10000] * 20 + [10450],
            "low": [10000] * 20 + [10050],
            "volume": [10000] * 20 + [20000],
            "vol_ma20": [10000] * 21,
            "adjusted_volume": [10000] * 20 + [20000],
            "ma5": [10000] * 20 + [10080],
            "ma20": [10000] * 20 + [10020],
            "ma60": [10000] * 21,
            "rsi14": [50.0] * 21,
            "bb_lower": [9500] * 21,
            "atr": [100.0] * 21
        })

        res = evaluate_buy_signals_from_df(
            df=df,
            code="005930",
            name="삼성전자",
            settings={"market_regime_filter_enabled": False}
        )
        self.assertIsNone(res, "5일선 대비 3% 초과 과열 시 매수 배제되어야 합니다.")

    def test_upper_shadow_safety_gate(self):
        """캔들 형태 필터: 윗꼬리 40% 이상 시 매물 출회 차단"""
        # high 11000, close 10200, open 10000, low 9900 -> range 1100, upper shadow = 11000 - 10200 = 800 (72.7%)
        df = pd.DataFrame({
            "close": [10000] * 20 + [10200],
            "open": [10000] * 20 + [10000],
            "high": [10000] * 20 + [11000],
            "low": [10000] * 20 + [9900],
            "volume": [10000] * 20 + [20000],
            "vol_ma20": [10000] * 21,
            "adjusted_volume": [10000] * 20 + [20000],
            "ma5": [10000] * 20 + [10040],
            "ma20": [10000] * 20 + [10010],
            "ma60": [10000] * 21,
            "rsi14": [50.0] * 21,
            "bb_lower": [9500] * 21,
            "atr": [100.0] * 21
        })

        res = evaluate_buy_signals_from_df(
            df=df,
            code="005930",
            name="삼성전자",
            settings={"market_regime_filter_enabled": False}
        )
        self.assertIsNone(res, "윗꼬리 40% 이상 매물 출회 시 매수 배제되어야 합니다.")

    def test_trailing_stop_after_partial_profit(self):
        """1차 익절 완료 후 최고가 대비 트레일링 스탑 (3.5% 하락)"""
        holding = {
            "code": "005930",
            "name": "삼성전자",
            "quantity": 5,
            "avg_buy_price": 70000,
            "current_price": 72000, # 최고가 75000 대비 -4.0% 하락
            "profit_rate": +2.85,
            "profit_loss": 10000
        }
        res = evaluate_sell_signals_from_df(
            holding=holding,
            is_partial_sold=True,
            highest_price=75000,
            settings={"trailing_stop_pct": 0.035}
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["sell_type"], "트레일링 스탑 전량익절")
        self.assertEqual(res["sell_ratio"], 1.0)

    def test_time_stop_exit(self):
        """타임컷 청산: 6영업일 경과 및 최소수익(+2%) 미달 시 청산"""
        holding = {
            "code": "005930",
            "name": "삼성전자",
            "quantity": 10,
            "avg_buy_price": 70000,
            "current_price": 70500,
            "profit_rate": +0.71, # +2% 미달
            "profit_loss": 5000
        }
        res = evaluate_sell_signals_from_df(
            holding=holding,
            holding_days=6,
            settings={
                "time_stop_enabled": True,
                "time_stop_days": 6,
                "time_stop_min_profit": 0.02
            }
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["sell_type"], "타임컷 청산 (기간 만료)")
        self.assertEqual(res["sell_ratio"], 1.0)

class TestPositionTracker(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.pos_file = os.path.join(self.temp_dir, "positions.json")
        self.cd_file = os.path.join(self.temp_dir, "cooldown.json")
        self.tracker = PositionTracker(self.pos_file, self.cd_file)

    def tearDown(self):
        for f in [self.pos_file, self.cd_file]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass
        try:
            os.rmdir(self.temp_dir)
        except Exception:
            pass

    def test_position_tracking_lifecycle(self):
        # 1. Update initial price
        pos = self.tracker.update_position_state("005930", current_price=70000, avg_buy_price=70000)
        self.assertEqual(pos["highest_price"], 70000)
        self.assertFalse(pos["is_partial_sold"])

        # 2. Update higher price
        pos = self.tracker.update_position_state("005930", current_price=75000, avg_buy_price=70000)
        self.assertEqual(pos["highest_price"], 75000)

        # 3. Partial take profit
        pos = self.tracker.update_position_state("005930", current_price=74000, avg_buy_price=70000, is_partial_take=True)
        self.assertEqual(pos["highest_price"], 75000)
        self.assertTrue(pos["is_partial_sold"])

        # 4. Clear on full exit
        self.tracker.clear_position_state("005930")
        state = self.tracker.load_positions_state()
        self.assertNotIn("005930", state)

if __name__ == "__main__":
    unittest.main()
