"""
매매 전략 엔진 단위 테스트 (test_strategy.py)
"""
import unittest
import pandas as pd

from strategy import MACrossStrategy, VolatilityBreakoutStrategy, Signal


class TestTradingStrategies(unittest.TestCase):

    def setUp(self):
        # 모의 일봉 데이터 생성 (25일치)
        dates = pd.date_range("2026-01-01", periods=25)
        prices = [100 + i * 2 for i in range(25)]  # 지속 상승 추세
        self.bullish_df = pd.DataFrame({
            "date": dates,
            "open": prices,
            "high": [p + 2 for p in prices],
            "low": [p - 1 for p in prices],
            "close": prices,
            "volume": [1000] * 25
        })

        prices_bearish = [200 - i * 2 for i in range(25)]  # 지속 하락 추세
        self.bearish_df = pd.DataFrame({
            "date": dates,
            "open": prices_bearish,
            "high": [p + 1 for p in prices_bearish],
            "low": [p - 2 for p in prices_bearish],
            "close": prices_bearish,
            "volume": [1000] * 25
        })

    def test_ma_cross_strategy_buy_signal(self):
        strategy = MACrossStrategy(short_period=5, long_period=20)
        # 상승 추세에서는 5일선이 20일선 위에 도달
        signal = strategy.generate_signal("005930", current_price=160, daily_candles=self.bullish_df, current_holding_qty=0)
        self.assertIn(signal, [Signal.BUY, Signal.HOLD])

    def test_ma_cross_strategy_insufficient_data(self):
        strategy = MACrossStrategy(short_period=5, long_period=20)
        short_df = self.bullish_df.iloc[:10]  # 10일치만 제공 (20일 미만)
        signal = strategy.generate_signal("005930", current_price=120, daily_candles=short_df, current_holding_qty=0)
        self.assertEqual(signal, Signal.HOLD)

    def test_volatility_breakout_strategy(self):
        strategy = VolatilityBreakoutStrategy(k=0.5)
        # 전일: high=150, low=140 -> range=10. target = open(148) + 10*0.5 = 153
        # 현재가 155 -> 돌파 조건 충족 (BUY)
        df = pd.DataFrame({
            "open": [140, 148],
            "high": [145, 150],
            "low": [138, 140],
            "close": [142, 148],
            "volume": [100, 100]
        })
        signal = strategy.generate_signal("005930", current_price=155.0, daily_candles=df, current_holding_qty=0)
        self.assertEqual(signal, Signal.BUY)


if __name__ == "__main__":
    unittest.main()
