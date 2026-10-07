"""
Unit Tests for MonthlyTrendStrategy (KOSPI 100 월봉 10이평 GTAA 전략)
"""
import unittest
import pandas as pd
import numpy as np

from core.strategy import get_strategy, list_strategies
from core.strategy.monthly_trend import MonthlyTrendStrategy
from core.universe.kospi100 import get_kospi100_universe, KOSPI_100_STOCKS


class TestMonthlyTrendStrategy(unittest.TestCase):
    def setUp(self):
        self.strat = get_strategy("monthly_trend")

    def test_registry(self):
        """전략 레지스트리에 정상 등록되었는지 확인"""
        self.assertIsInstance(self.strat, MonthlyTrendStrategy)
        self.assertEqual(self.strat.name, "monthly_trend")
        strats = [s["name"] for s in list_strategies()]
        self.assertIn("monthly_trend", strats)

    def test_kospi100_universe(self):
        """KOSPI 100 유니버스 100개 종목 로드 확인"""
        u = get_kospi100_universe()
        self.assertEqual(len(u), 100)
        codes = [item["code"] for item in u]
        self.assertIn("005930", codes)  # 삼성전자
        self.assertIn("000660", codes)  # SK하이닉스
        self.assertIn("010130", codes)  # 고려아연

    def test_position_sizing_high_price(self):
        """100만 원 초과 고가주 1주 제한 로직 검증"""
        # 1. 일반 주식 (70,000원, 예산 100만 원) -> 14주
        qty_normal = self.strat.calculate_position_size(70000.0, 1000000.0)
        self.assertEqual(qty_normal, 14)

        # 2. 100만 원 초과 고가주 (1,200,000원, 예산 1,500,000원) -> 최대 1주로 제한
        qty_high = self.strat.calculate_position_size(1200000.0, 1500000.0)
        self.assertEqual(qty_high, 1)

        # 3. 100만 원 초과 고가주 (1,200,000원, 예산 500,000원 부족) -> 0주
        qty_insufficient = self.strat.calculate_position_size(1200000.0, 500000.0)
        self.assertEqual(qty_insufficient, 0)

    def test_evaluate_buy_golden_cross(self):
        """10개월 이동평균선 상향 돌파(골든크로스) 매수 신호 검증"""
        # 12개월 월봉 데이터 생성 (직전월까지 하락하다 당월 10이평을 상향 돌파)
        dates = pd.date_range(start="2024-01-01", periods=12, freq="MS").strftime("%Y%m%d").tolist()
        # 1~9월 100원, 10월 90원, 11월 85원 (직전월), 12월 105원 (당월 돌파)
        prices = [100.0] * 9 + [90.0, 85.0, 105.0]
        df = pd.DataFrame({
            "date": dates,
            "close": prices,
            "change_rate": [0.0] * 11 + [5.0]
        })

        res = self.strat.evaluate_buy(
            df=df,
            code="005930",
            name="삼성전자",
            budget=1000000
        )

        self.assertIsNotNone(res)
        self.assertTrue(res["is_golden_cross"])
        self.assertTrue(res["is_recommended"])
        self.assertGreaterEqual(res["score"], 60)
        self.assertIn("골든크로스", res["reasons"][0])
        self.assertEqual(res["strategy"], "monthly_trend")

    def test_evaluate_buy_downtrend_rejected(self):
        """10개월 이평선 하회 종목 탈락 검증"""
        dates = pd.date_range(start="2024-01-01", periods=12, freq="MS").strftime("%Y%m%d").tolist()
        prices = [100.0] * 10 + [90.0, 80.0]  # 80원으로 10이평 하회
        df = pd.DataFrame({"date": dates, "close": prices})

        res = self.strat.evaluate_buy(
            df=df,
            code="005930",
            name="삼성전자",
            return_raw_eval=True
        )

        self.assertIsNotNone(res)
        self.assertFalse(res["is_recommended"])
        self.assertIn("10개월 이평선 하회", res["disqualify_reason"])

    def test_evaluate_buy_overheat_rejected(self):
        """10이평 대비 +20% 초과 과열 종목 추격 매수 배제 검증"""
        dates = pd.date_range(start="2024-01-01", periods=12, freq="MS").strftime("%Y%m%d").tolist()
        prices = [100.0] * 10 + [98.0, 140.0]  # 140원으로 급등하여 이격도 +40% 초과
        df = pd.DataFrame({"date": dates, "close": prices})

        res = self.strat.evaluate_buy(
            df=df,
            code="005930",
            name="삼성전자",
            return_raw_eval=True
        )

        self.assertIsNotNone(res)
        self.assertFalse(res["is_recommended"])
        self.assertIn("이격 과열", res["disqualify_reason"])

    def test_evaluate_buy_continuation_rejected(self):
        """10이평 상회 지속 종목(골든크로스 첫 달이 아님) 배제 검증"""
        dates = pd.date_range(start="2024-01-01", periods=12, freq="MS").strftime("%Y%m%d").tolist()
        # 1~10월 100원, 11월 102원 (이미 10이평 위), 12월 105원 (지속 상승)
        prices = [100.0] * 10 + [102.0, 105.0]
        df = pd.DataFrame({"date": dates, "close": prices})

        # 기본 설정(monthly_allow_trend_continuation=False) 시 신규 골든크로스가 아니므로 탈락
        res = self.strat.evaluate_buy(
            df=df,
            code="005930",
            name="삼성전자",
            return_raw_eval=True
        )

        self.assertIsNotNone(res)
        self.assertFalse(res["is_recommended"])
        self.assertIn("신규 골든크로스", res["disqualify_reason"])

    def test_evaluate_sell_dead_cross(self):
        """10개월 이평선 하향 이탈 시 전량 매도 신호 검증"""
        dates = pd.date_range(start="2024-01-01", periods=12, freq="MS").strftime("%Y%m%d").tolist()
        # 평균 약 100원선, 당월 88원으로 이탈
        prices = [100.0] * 11 + [88.0]
        df = pd.DataFrame({"date": dates, "close": prices})

        holding = {
            "code": "005930",
            "name": "삼성전자",
            "current_price": 88.0,
            "avg_buy_price": 90.0,
            "holding_qty": 10,
            "highest_price": 100.0
        }

        sell_res = self.strat.evaluate_sell(holding, df=df)
        self.assertIsNotNone(sell_res)
        self.assertEqual(sell_res["sell_type"], "월봉 10이평 이탈 매도")
        self.assertEqual(sell_res["sell_qty"], 10)

    def test_evaluate_sell_emergency_stop_loss(self):
        """비상 손절(-7% 도달) 긴급 매도 신호 검증"""
        holding = {
            "code": "005930",
            "name": "삼성전자",
            "current_price": 90.0,
            "avg_buy_price": 100.0,  # -10% 손실
            "holding_qty": 5
        }

        sell_res = self.strat.evaluate_sell(holding, df=None, stop_loss_rate=-0.07)
        self.assertIsNotNone(sell_res)
        self.assertEqual(sell_res["sell_type"], "비상 손절")
        self.assertTrue(sell_res["is_urgent"])
        self.assertEqual(sell_res["sell_qty"], 5)


if __name__ == "__main__":
    unittest.main()
