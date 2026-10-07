import unittest
import pandas as pd
from unittest.mock import MagicMock
from core.futures_manager import futures_manager
from core.strategy.momentum import MomentumStrategy


class TestFuturesScoring(unittest.TestCase):
    def setUp(self):
        self.strategy = MomentumStrategy()
        # 65봉 더미 일봉 데이터 생성 (골든크로스 + 정배열 + 거래량 급증)
        candles = []
        base_price = 100000.0
        for i in range(65):
            p = base_price + (i * 200.0)
            vol = 100000 if i < 64 else 200000
            candles.append({
                "date": f"202601{i+1:02d}" if i < 30 else f"202602{i-29:02d}",
                "open": p - 100,
                "high": p,
                "low": p - 200,
                "close": p,
                "volume": vol,
                "change_rate": 1.5
            })
        from core.indicators import calculate_technical_indicators
        self.df = calculate_technical_indicators(candles, is_intraday=True)

    def test_futures_manager_mapping(self):
        """삼성전자 등 주요 종목의 선물 코드 매핑 확인"""
        samsung_fut = futures_manager.get_futures_code("005930")
        self.assertIsNotNone(samsung_fut)
        self.assertTrue(samsung_fut.startswith("A") or samsung_fut.startswith("1"))

        # 미상장 가상 종목
        non_existent = futures_manager.get_futures_code("999999")
        self.assertIsNone(non_existent)
        self.assertFalse(futures_manager.has_futures("999999"))

    def test_momentum_buy_with_strong_contango_and_oi_increase(self):
        """콘탱고 + 미결제약정 증가 시 선물 점수 20점 만점 획득 및 100점 스케일링 검증"""
        futures_data = {
            "has_futures": True,
            "stock_code": "005930",
            "futures_code": "A11609",
            "price": 130000.0,
            "market_basis": 500.0,   # 콘탱고 (+0.38%)
            "basis": 200.0,
            "open_interest": 100000,
            "oi_change": 5000,       # 미결제약정 증가 (+5,000)
            "is_contango": True
        }
        settings = {
            "use_futures_filter": True,
            "buy_score_threshold": 60,
            "market_regime_cutoff_normal": 60
        }
        res = self.strategy.evaluate_buy(
            df=self.df,
            code="005930",
            name="삼성전자",
            settings=settings,
            futures_data=futures_data
        )
        self.assertIsNotNone(res)
        self.assertIn("futures_score", res)
        self.assertEqual(res["futures_score"], 20)  # 콘탱고(+10) + 미결제 증가(+10) = 20점
        self.assertTrue(res["is_contango"])
        self.assertEqual(res["market_basis"], 500.0)
        self.assertEqual(res["oi_change"], 5000)
        self.assertFalse(res["futures_warning"])
        self.assertGreaterEqual(res["score"], 60)

    def test_momentum_buy_with_backwardation(self):
        """심각한 백워데이션 시 감점 및 선물 점수 하락 검증"""
        futures_data = {
            "has_futures": True,
            "stock_code": "005930",
            "futures_code": "A11609",
            "price": 128000.0,
            "market_basis": -1000.0,  # 백워데이션 (-0.77%)
            "basis": -500.0,
            "open_interest": 100000,
            "oi_change": -3000,       # 미결제약정 감소 (단순 숏커버)
            "is_contango": False
        }
        settings = {
            "use_futures_filter": True,
            "buy_score_threshold": 50,
            "market_regime_cutoff_normal": 50
        }
        res = self.strategy.evaluate_buy(
            df=self.df,
            code="005930",
            name="삼성전자",
            settings=settings,
            futures_data=futures_data
        )
        self.assertIsNotNone(res)
        self.assertEqual(res["futures_score"], 0)  # 백워데이션 감점(-5) -> 0점 캡
        self.assertFalse(res["is_contango"])

    def test_futures_kill_switch_warning(self):
        """현물 급등(+2% 이상) 대비 선물 OI 급감 및 백워데이션 시 선물역행경고 발동"""
        # 마지막 봉의 change_rate를 +2.5%로 설정
        df_spike = self.df.copy()
        df_spike.loc[df_spike.index[-1], "change_rate"] = 2.5

        futures_data = {
            "has_futures": True,
            "stock_code": "005930",
            "futures_code": "A11609",
            "price": 128000.0,
            "market_basis": -800.0,   # 백워데이션 (-0.6%)
            "open_interest": 50000,
            "oi_change": -10000,      # 미결제약정 대량 이탈 (-20%)
            "is_contango": False
        }
        settings = {
            "use_futures_filter": True,
            "buy_score_threshold": 40,
            "market_regime_cutoff_normal": 40
        }
        res = self.strategy.evaluate_buy(
            df=df_spike,
            code="005930",
            name="삼성전자",
            settings=settings,
            futures_data=futures_data
        )
        self.assertIsNotNone(res)
        self.assertTrue(res["futures_warning"])
        self.assertTrue(any("선물 역행 경고" in r for r in res["reasons"]))

    def test_non_futures_stock_proportional_scaling(self):
        """개별주식선물 미상장 종목의 100점 만점 비례 환산 검증"""
        settings = {
            "use_futures_filter": True,
            "buy_score_threshold": 60,
            "market_regime_cutoff_normal": 60
        }
        res = self.strategy.evaluate_buy(
            df=self.df,
            code="999999",
            name="미상장중소형주",
            settings=settings,
            futures_data={"has_futures": False, "stock_code": "999999"}
        )
        self.assertIsNotNone(res)
        self.assertIsNone(res["futures_score"])
        self.assertFalse(res["has_futures"])
        # 비례 환산 (80점 척도 -> 100점 만점) 확인
        raw = res["trend_score"] + res["supply_score"] + res["momentum_score"]
        expected = round(min(100.0, raw * (100.0 / 80.0)), 1)
        self.assertEqual(res["score"], expected)
        self.assertTrue(any("미상장 종목" in r for r in res["reasons"]))

    def test_return_raw_eval_when_not_recommended(self):
        """매수 기준 미달 시 return_raw_eval=True로 점수 및 탈락 사유 확인 검증"""
        settings = {
            "use_futures_filter": True,
            "buy_score_threshold": 95,  # 도달 불가능한 높은 컷오프
            "market_regime_cutoff_normal": 95
        }
        # 1) 일반 호출 -> None 반환
        res_normal = self.strategy.evaluate_buy(
            df=self.df,
            code="005930",
            name="삼성전자",
            settings=settings,
            return_raw_eval=False
        )
        self.assertIsNone(res_normal)

        # 2) return_raw_eval=True -> 점수와 탈락 사유가 포함된 dict 반환
        res_raw = self.strategy.evaluate_buy(
            df=self.df,
            code="005930",
            name="삼성전자",
            settings=settings,
            return_raw_eval=True
        )
        self.assertIsNotNone(res_raw)
        self.assertFalse(res_raw["is_recommended"])
        self.assertIn("disqualify_reason", res_raw)
        self.assertGreater(res_raw["score"], 0)
        self.assertIn("기준 미달", res_raw["disqualify_reason"])


if __name__ == "__main__":
    unittest.main()
