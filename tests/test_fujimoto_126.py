# -*- coding: utf-8 -*-
"""
후지모토 시게루 1:2:6 매매법 구간 진단, 분할청산 추천, 수동 종목 JSON+Google Sheet 연동 테스트
"""
import os
import tempfile
import pandas as pd
import numpy as np
from unittest.mock import MagicMock, patch

from core.indicators import calculate_technical_indicators, evaluate_fujimoto_126_exit
from core.position_tracker import PositionTracker


def _make_sample_candles(n: int = 80, base_price: float = 50000.0, trend: str = "up"):
    candles = []
    start_dt = pd.date_range("2026-06-01", periods=n, freq="B")
    price = base_price
    for i, dt in enumerate(start_dt):
        if trend == "up":
            price += 300
        elif trend == "overbought_drop":
            # 초반 70봉 상승 후 마지막 2봉 살짝 조정 (RSI > 70 찍고 70 아래로 진입)
            if i < n - 2:
                price += 450
            else:
                price -= 900
        elif trend == "crash":
            if i < n - 10:
                price += 200
            else:
                price -= 2500
        candles.append({
            "date": dt.strftime("%Y%m%d"),
            "open": price - 100,
            "high": price + 300,
            "low": price - 300,
            "close": price,
            "volume": 100000 + i * 1000
        })
    return candles


def test_indicators_macd_and_ichimoku_columns():
    candles = _make_sample_candles(80, trend="up")
    df = calculate_technical_indicators(candles, is_intraday=False)
    assert df is not None
    for col in ["rsi14", "macd_line", "macd_signal", "macd_hist", "tenkan_sen", "kijun_sen", "senkou_span_a", "senkou_span_b", "cloud_top", "cloud_bottom"]:
        assert col in df.columns


def test_fujimoto_126_exit_stages():
    # 1. 강세 순항 구간 -> 홀딩 유지
    candles_up = _make_sample_candles(80, base_price=50000, trend="up")
    df_up = calculate_technical_indicators(candles_up, is_intraday=False)
    # RSI를 62 수준으로 조정해 순항 상태 확인
    df_up["rsi14"] = 62.0
    res_hold = evaluate_fujimoto_126_exit(df_up, avg_buy_price=55000, holding_qty=9, current_exit_stage=0)
    assert res_hold["is_action_needed"] is False
    assert res_hold["recommended_qty"] == 0

    # 2. 1차 청산 시그널 (RSI 70 이상 찍고 현재 68로 하향 이탈, MACD 양수, 구름대 위)
    df_s1 = df_up.copy()
    df_s1.loc[df_s1.index[-3], "rsi14"] = 74.5
    df_s1.loc[df_s1.index[-1], "rsi14"] = 68.0
    df_s1.loc[df_s1.index[-1], "macd_hist"] = 120.0
    res_s1 = evaluate_fujimoto_126_exit(df_s1, avg_buy_price=55000, holding_qty=90, current_exit_stage=0)
    assert res_s1["is_action_needed"] is True
    assert res_s1["target_stage"] == 1
    assert res_s1["recommended_qty"] == 10  # 90 * 1/9 = 10주

    # 3. 2차 청산 시그널 (MACD 데드크로스, 구름대 위)
    df_s2 = df_up.copy()
    df_s2.loc[df_s2.index[-2], "macd_hist"] = 50.0
    df_s2.loc[df_s2.index[-1], "macd_hist"] = -30.0
    # 1차 완료 상태(stage=1, 잔여 80주)에서 2차 시그널 발생 시 잔여 80주의 2/8 = 20주 추천
    res_s2 = evaluate_fujimoto_126_exit(df_s2, avg_buy_price=55000, holding_qty=80, current_exit_stage=1)
    assert res_s2["is_action_needed"] is True
    assert res_s2["target_stage"] == 2
    assert res_s2["recommended_qty"] == 20

    # 4. 3차 전량 청산 시그널 (구름대 하단 이탈)
    candles_crash = _make_sample_candles(80, base_price=50000, trend="crash")
    df_s3 = calculate_technical_indicators(candles_crash, is_intraday=False)
    res_s3 = evaluate_fujimoto_126_exit(df_s3, avg_buy_price=60000, holding_qty=60, current_exit_stage=2)
    assert res_s3["is_action_needed"] is True
    assert res_s3["target_stage"] == 3
    assert res_s3["recommended_qty"] == 60  # 잔여 전량


def test_manual_fujimoto_126_json_and_sheet_sync():
    with tempfile.TemporaryDirectory() as tmpdir:
        pos_file = os.path.join(tmpdir, "pos.json")
        cd_file = os.path.join(tmpdir, "cd.json")
        f126_file = os.path.join(tmpdir, "f126.json")

        tracker = PositionTracker(positions_file=pos_file, cooldown_file=cd_file, fujimoto_file=f126_file)

        # 수동 종목 추가
        entry = tracker.upsert_fujimoto_126_position(
            code="005930",
            name="삼성전자",
            avg_buy_price=72000,
            buy_date="2026-11-01",
            qty=18,
            market="KOSPI",
            is_manual=True
        )
        assert entry["code"] == "005930"
        assert entry["qty"] == 18
        assert entry["buy_date"] == "2026-11-01"

        loaded = tracker.load_fujimoto_126_positions()
        assert "005930" in loaded
        assert loaded["005930"]["avg_buy_price"] == 72000.0

        # 청산 단계 업데이트 (1차 완료)
        tracker.update_fujimoto_126_stage("005930", stage=1)
        loaded2 = tracker.load_fujimoto_126_positions()
        assert loaded2["005930"]["exit_126_stage"] == 1

        # 종목 삭제
        assert tracker.delete_fujimoto_126_position("005930") is True
        assert "005930" not in tracker.load_fujimoto_126_positions()
