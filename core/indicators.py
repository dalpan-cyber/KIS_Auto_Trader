"""
KIS Auto Trading - Technical Indicators Module
주가 데이터프레임 기반 이동평균, 볼린저 밴드, RSI, ATR 및 15:10 거래량 보정치 계산
"""
from typing import List, Dict, Any, Optional, Union
import pandas as pd
import numpy as np

def calculate_technical_indicators(
    candles_or_df: Union[List[Dict[str, Any]], pd.DataFrame],
    is_intraday: bool = True,
    atr_period: int = 14
) -> Optional[pd.DataFrame]:
    """
    일봉 캔들 데이터를 바탕으로 기술적 보조지표 계산
    - 20영업일 이상 일봉 데이터 기준
    - 이동평균선: MA5, MA20, MA60
    - 거래량 이동평균: 전일까지 20일 거래량 단순 이동평균 (vol_ma20)
    - 장중 거래량 보정치: 15:10 누적 거래량 * (390분 / 370분) ≈ 누적 거래량 * 1.054
    - RSI(14)
    - 볼린저 밴드(20, 2): 20일 이평선 기준 ±2σ
    - ATR(14): 변동성 기반 손절 및 포지션 사이징용

    Args:
        candles_or_df: 캔들 리스트 또는 DataFrame
        is_intraday: 장중 평가 여부 (True 시 15:10 거래량 1.054배 보정 적용)
        atr_period: ATR 계산 기간 (기본: 14)

    Returns:
        보조지표가 추가된 pd.DataFrame 또는 데이터 부족 시 None
    """
    if candles_or_df is None:
        return None

    if isinstance(candles_or_df, pd.DataFrame):
        if candles_or_df.empty or len(candles_or_df) < 20:
            return None
        df = candles_or_df.copy()
    else:
        if not isinstance(candles_or_df, list) or len(candles_or_df) < 20:
            return None
        df = pd.DataFrame(candles_or_df).copy()

    # 컬럼 숫자형 변환
    for col in ["close", "open", "high", "low", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 결측치 보정
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    if len(df) < 20:
        return None

    if "open" not in df.columns or df["open"].isna().all():
        df["open"] = df["close"]
    if "high" not in df.columns or df["high"].isna().all():
        df["high"] = df["close"]
    if "low" not in df.columns or df["low"].isna().all():
        df["low"] = df["close"]
    if "volume" not in df.columns or df["volume"].isna().all():
        df["volume"] = 0

    # 1. 이동평균선 (MA5, MA20, MA60)
    df["ma5"] = df["close"].rolling(window=5, min_periods=1).mean()
    df["ma20"] = df["close"].rolling(window=20, min_periods=1).mean()
    df["ma60"] = df["close"].rolling(window=min(60, len(df)), min_periods=1).mean()

    # 2. 거래량 이동평균 (전일까지의 20일 거래량 단순 이동평균으로 산출하여 당일 봉 미완성 왜곡 방지)
    df["vol_ma20"] = df["volume"].shift(1).rolling(window=20, min_periods=1).mean()
    # 첫 행 등에 NaN이 남아있을 경우 현재 거래량으로 채움
    df["vol_ma20"] = df["vol_ma20"].fillna(df["volume"])

    # 3. 당일 거래량 보정치 계산 (15:10 장마감 직전 평가 시 1.054배 보정)
    df["adjusted_volume"] = df["volume"].astype(float).copy()
    if is_intraday and len(df) > 0:
        last_idx = df.index[-1]
        df.loc[last_idx, "adjusted_volume"] = float(df.loc[last_idx, "volume"]) * (390.0 / 370.0)

    # 4. RSI (14)
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=1).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=1).mean()
    rs = gain / (loss + 1e-9)
    df["rsi14"] = 100 - (100 / (1 + rs))
    df["rsi14"] = df["rsi14"].fillna(50.0)

    # 5. 볼린저 밴드 (20, 2)
    df["bb_mid"] = df["ma20"]
    df["bb_std"] = df["close"].rolling(window=20, min_periods=1).std().fillna(0.0)
    df["bb_upper"] = df["bb_mid"] + (df["bb_std"] * 2)
    df["bb_lower"] = df["bb_mid"] - (df["bb_std"] * 2)

    # 6. ATR (Average True Range) - 변동성 기반 손절/포지션 사이징용
    prev_close = df["close"].shift(1).fillna(df["open"])
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(window=atr_period, min_periods=1).mean().fillna(0.0)

    return df
