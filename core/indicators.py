# -*- coding: utf-8 -*-
"""
KIS Auto Trading - Technical Indicators Module
주가 데이터프레임 기반 이동평균, 볼린저 밴드, RSI, ATR 및 15:10 거래량 보정치 계산
"""
from typing import List, Dict, Any, Optional, Union
import datetime
import pandas as pd
import numpy as np
from time_utils import now as kst_now

def get_intraday_volume_scaling_factor(
    target_time: Optional[Union[datetime.time, datetime.datetime, str]] = None
) -> float:
    """
    정규장(09:00 ~ 15:30, 총 390분) 진행 시간에 맞춰
    15:30 종가 시점에 도달할 것으로 예상되는 거래량 비례 환산 배율 계산.

    - 09:00 이전: 장 시작 전이므로 1.0배
    - 09:00 ~ 15:30:
        경과 분수 M = max(10, (현재시간 - 09:00)) (장초 10분 클램핑으로 왜곡 방지)
        배율 = 390.0 / M
        예: 11:30 -> 390 / 150 = 2.60배, 15:10 -> 390 / 370 = 1.054배
    - 15:30 이후: 장 마감 후이므로 확정 종가 거래량(1.0배)
    """
    current_dt = kst_now()
    is_weekend = (current_dt.weekday() >= 5)
    # 주말(토/일) 실시간 조회 시 휴장일이므로 1.0배(확정 종가 데이터) 고정
    if is_weekend and (target_time == "now" or isinstance(target_time, datetime.time)):
        return 1.0

    if target_time is None or target_time == "15:10":
        t = datetime.time(15, 10)
    elif target_time == "now":
        t = current_dt.time()
    elif isinstance(target_time, datetime.datetime):
        t = target_time.time()
    elif isinstance(target_time, datetime.time):
        t = target_time
    elif isinstance(target_time, str):
        try:
            parts = [int(p) for p in target_time.strip().split(":")[:2]]
            t = datetime.time(parts[0], parts[1])
        except Exception:
            current_dt = kst_now()
            t = current_dt.time()
    else:
        current_dt = kst_now()
        t = current_dt.time()

    current_minutes = t.hour * 60 + t.minute
    market_open = 9 * 60        # 09:00 = 540
    market_close = 15 * 60 + 30  # 15:30 = 930
    total_market_minutes = market_close - market_open  # 390분

    if current_minutes < market_open:
        # 09:00 이전 장 시작 전
        return 1.0
    elif current_minutes >= market_close:
        # 15:30 이후 장 마감
        return 1.0
    else:
        # 장중: 09:00부터 경과 시간(분)
        elapsed = current_minutes - market_open
        # 장초반 과도한 왜곡 방지를 위해 최소 10분 클램핑
        elapsed = max(10, elapsed)
        scaling_factor = float(total_market_minutes) / float(elapsed)
        return scaling_factor


def calculate_technical_indicators(
    candles_or_df: Union[List[Dict[str, Any]], pd.DataFrame],
    is_intraday: bool = True,
    atr_period: int = 14,
    eval_time: Optional[Union[datetime.time, datetime.datetime, str]] = None
) -> Optional[pd.DataFrame]:
    """
    일봉 캔들 데이터를 바탕으로 기술적 보조지표 계산
    - 20영업일 이상 일봉 데이터 기준
    - 이동평균선: MA5, MA20, MA60
    - 거래량 이동평균: 전일까지 20일 거래량 단순 이동평균 (vol_ma20)
    - 장중 거래량 보정치: 검색/평가 시점 기준 15:30 종가 예상 거래량 환산
    - 볼린저 밴드(20, 2): 20일 이평선 기준 +- 2시그마
    - ATR(14): 변동성 기반 손절 및 포지션 사이징용

    Args:
        candles_or_df: 캔들 리스트 또는 DataFrame
        is_intraday: 장중 평가 여부 (True 시 검색 시점 비례 종가 예상 거래량 스케일링)
        atr_period: ATR 계산 기간 (기본: 14)
        eval_time: 평가 기준 시각 (None이면 현재 KST 시각 기준 자동 계산)

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

    # 날짜 기준 과거 -> 최신(오름차순) 정렬 보장
    if "date" in df.columns:
        df = df.sort_values(by="date", ascending=True).reset_index(drop=True)

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

    # 3. 당일 거래량 보정치 계산 (검색/평가 시점 기준 15:30 종가 예상 거래량 스케일링)
    df["adjusted_volume"] = df["volume"].astype(float).copy()
    if is_intraday and len(df) > 0:
        last_idx = df.index[-1]
        scaling_mult = get_intraday_volume_scaling_factor(eval_time)
        df.loc[last_idx, "adjusted_volume"] = float(df.loc[last_idx, "volume"]) * scaling_mult
        df.loc[last_idx, "volume_multiplier"] = scaling_mult

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


def detect_cup_and_handle(
    df: pd.DataFrame,
    min_cup_bars: int = 20,
    max_cup_bars: int = 80,
    min_handle_bars: int = 3,
    max_handle_bars: int = 25,
    min_cup_depth: float = 0.08,
    max_cup_depth: float = 0.40,
    max_rim_diff: float = 0.08,
    max_handle_depth_ratio: float = 0.50,
    vol_breakout_mult: float = 1.3,
) -> Optional[Dict[str, Any]]:
    """
    일봉 OHLCV 데이터를 바탕으로 컵앤핸들(Cup and Handle) 패턴을 탐지합니다.

    [패턴 탐지 기준]
    1. 사전 추세: 컵 좌측 고점(P1) 전 상승 추세 존재
    2. 컵(Cup):
       - 길이: min_cup_bars ~ max_cup_bars
       - 깊이: 좌측 고점 대비 바닥(Low) 하락폭 min_cup_depth ~ max_cup_depth
       - 대칭성: 우측 고점(P2)이 좌측 고점(P1)의 +/- max_rim_diff 이내
       - 바닥 형태: 둥근 U자형 (최저점 부근 체류 바 수가 충분한지 평가)
    3. 핸들(Handle):
       - 길이: min_handle_bars ~ max_handle_bars
       - 깊이: 우측 고점(P2) 대비 조정폭이 컵 깊이의 max_handle_depth_ratio 이하
       - 지지: 핸들 최저점이 컵의 상단 50% 구역 내 위치
       - 거래량 건조(Volume Dry-up): 핸들 구간 거래량이 컵 상승기 대비 축소
    4. 돌파(Breakout):
       - 피봇(우측 림 P2 또는 핸들 최고점) 상향 돌파
       - 거래량 급증(vol_ma20 대비 vol_breakout_mult 이상)

    Args:
        df: technical indicators가 계산되었거나 ohlcv가 포함된 DataFrame
        min_cup_bars: 컵 최소 봉 수 (기본: 20)
        max_cup_bars: 컵 최대 봉 수 (기본: 80)
        min_handle_bars: 핸들 최소 봉 수 (기본: 3)
        max_handle_bars: 핸들 최대 봉 수 (기본: 25)
        min_cup_depth: 컵 최소 하락 깊이 비율 (기본: 0.08 = -8%)
        max_cup_depth: 컵 최대 하락 깊이 비율 (기본: 0.40 = -40%)
        max_rim_diff: 좌우 림 고점 차이 허용률 (기본: 0.08 = 8%)
        max_handle_depth_ratio: 컵 깊이 대비 핸들 조정폭 최대 허용비율 (기본: 0.50 = 50%)
        vol_breakout_mult: 돌파 확인 거래량 배수 (기본: 1.3배)

    Returns:
        패턴 감지 결과 Dict 또는 미감지 시 None
    """
    min_required_len = min_cup_bars + min_handle_bars + 15
    if df is None or len(df) < min_required_len:
        return None

    # 필수 컬럼 검사
    cols = ["high", "low", "close", "volume"]
    if not all(col in df.columns for col in cols):
        return None

    close = df["close"].values
    high = df["high"].values
    low = df["low"].values
    vol = df["volume"].values
    n = len(df)

    curr_idx = n - 1
    curr_price = float(close[curr_idx])
    curr_vol = float(df["adjusted_volume"].values[curr_idx]) if "adjusted_volume" in df.columns else float(vol[curr_idx])
    vol_ma20 = float(df["vol_ma20"].values[curr_idx]) if "vol_ma20" in df.columns else float(np.mean(vol[max(0, curr_idx-20):curr_idx]))
    if vol_ma20 <= 0:
        vol_ma20 = 1.0

    best_pattern = None
    best_score = -1

    # 핸들 길이 h_len 탐색 (최근 min_handle_bars ~ max_handle_bars)
    # 우측 림(P2)의 위치는 curr_idx - h_len 부근
    for h_len in range(min_handle_bars, min_handle_bars + min(15, max_handle_bars - min_handle_bars + 1)):
        p2_idx = curr_idx - h_len
        if p2_idx < min_cup_bars + 10:
            continue

        # P2가 핸들 시작 시점 부근(p2_idx ± 2)에서 국소 고점인지 확인
        p2_window_start = max(0, p2_idx - 3)
        p2_window_end = min(curr_idx - 1, p2_idx + 3)
        local_max_p2_idx = p2_window_start + int(np.argmax(high[p2_window_start:p2_window_end + 1]))
        
        # P2 확정
        actual_p2_idx = local_max_p2_idx
        p2_price = float(high[actual_p2_idx])
        if p2_price <= 0:
            continue

        # 핸들 구간 데이터 분석 (금일 직전봉까지가 핸들 완성 구간)
        handle_highs = high[actual_p2_idx + 1:curr_idx]
        handle_lows = low[actual_p2_idx + 1:curr_idx]
        handle_vols = vol[actual_p2_idx + 1:curr_idx]

        if len(handle_lows) < min_handle_bars:
            continue

        handle_low = float(np.min(handle_lows))
        handle_high = float(np.max(handle_highs))
        handle_depth = (p2_price - handle_low) / p2_price

        # 컵 구간(Cup) 탐색: actual_p2_idx 이전 min_cup_bars ~ max_cup_bars
        for cup_len in range(min_cup_bars, min(max_cup_bars, actual_p2_idx - 5), 3):
            p1_search_start = max(5, actual_p2_idx - cup_len)
            p1_search_end = max(5, actual_p2_idx - min_cup_bars)
            if p1_search_start >= p1_search_end:
                continue

            # 좌측 림(P1) 후보: 컵 시작 부근 국소 고점
            p1_idx = p1_search_start + int(np.argmax(high[p1_search_start:p1_search_end]))
            p1_price = float(high[p1_idx])
            if p1_price <= 0:
                continue

            # P1과 P2 사이 최저점(Cup Low)
            cup_inner_lows = low[p1_idx + 1:actual_p2_idx]
            if len(cup_inner_lows) < 8:
                continue

            cup_low_rel_idx = int(np.argmin(cup_inner_lows))
            cup_low_idx = p1_idx + 1 + cup_low_rel_idx
            cup_low = float(cup_inner_lows[cup_low_rel_idx])

            # 1. 컵 깊이 검사
            cup_depth = (p1_price - cup_low) / p1_price
            if not (min_cup_depth <= cup_depth <= max_cup_depth):
                continue

            # 2. 좌우 림 대칭성 검사 (P2가 P1과 유사한 높이인지)
            rim_diff = abs(p2_price - p1_price) / p1_price
            if rim_diff > max_rim_diff:
                continue

            # 3. 컵 바닥 위치 (가운데 30%~70% 구역에 위치해야 자연스러운 대칭형)
            cup_total_bars = actual_p2_idx - p1_idx
            low_pos_ratio = (cup_low_idx - p1_idx) / max(1, cup_total_bars)
            if not (0.25 <= low_pos_ratio <= 0.75):
                continue

            # 4. 핸들 깊이 검사 (컵 깊이의 50% 이내이며 상단 절반에서 지지)
            max_allowed_handle_drop = cup_depth * max_handle_depth_ratio
            if handle_depth > max_allowed_handle_drop or handle_depth > 0.18:
                continue

            cup_midpoint = cup_low + (p1_price - cup_low) * (1.0 - max_handle_depth_ratio)
            if handle_low < cup_midpoint:
                continue

            # 5. 사전 상승 추세 (P1 이전 15~30봉 저점 대비 P1 상승률)
            pre_start = max(0, p1_idx - 25)
            if p1_idx > pre_start:
                pre_low = float(np.min(low[pre_start:p1_idx]))
                pre_gain = (p1_price - pre_low) / max(1e-5, pre_low)
                if pre_gain < 0.12:  # 최소 12% 이상 사전 상승 권장
                    continue
            else:
                continue

            # 6. 피봇 포인트 및 돌파 판단
            pivot_price = max(p2_price, handle_high)
            is_breakout = curr_price >= pivot_price
            is_near_pivot = (curr_price >= pivot_price * 0.98) and not is_breakout
            vol_ratio = curr_vol / max(1.0, vol_ma20)
            vol_confirmed = vol_ratio >= vol_breakout_mult

            # 7. 점수 산정 (Pattern Quality Score: 0 ~ 100)
            score = 60  # 기본 통과 점수
            
            # 대칭성 가산점 (좌우 림 높이가 거의 같을수록 우수)
            if rim_diff <= 0.03:
                score += 10
            elif rim_diff <= 0.05:
                score += 5

            # 핸들 건조도 가산점 (핸들 평균 거래량이 컵 상승기보다 낮을 때)
            cup_vol_mean = float(np.mean(vol[cup_low_idx:actual_p2_idx])) if cup_low_idx < actual_p2_idx else 1.0
            handle_vol_mean = float(np.mean(handle_vols)) if len(handle_vols) > 0 else 1.0
            if handle_vol_mean < cup_vol_mean * 0.75:
                score += 10

            # 돌파 거래량 가산점
            if is_breakout and vol_confirmed:
                score += 15
            elif is_breakout:
                score += 5
            elif is_near_pivot:
                score += 5

            # 바닥 체류 형태 (둥근 바닥 보너스)
            near_bottom_threshold = cup_low + (p1_price - cup_low) * 0.20
            bottom_bars = np.sum(cup_inner_lows <= near_bottom_threshold)
            if bottom_bars >= 4:
                score += 5

            if score > best_score:
                best_score = score
                target_price = pivot_price + (p2_price - cup_low)
                stop_loss_price = max(handle_low, pivot_price * 0.93)

                best_pattern = {
                    "is_pattern": True,
                    "status": "breakout" if is_breakout else ("near_pivot" if is_near_pivot else "forming_handle"),
                    "p1_idx": int(p1_idx),
                    "p1_price": round(p1_price, 2),
                    "cup_low_idx": int(cup_low_idx),
                    "cup_low_price": round(cup_low, 2),
                    "cup_depth_pct": round(cup_depth * 100, 2),
                    "p2_idx": int(actual_p2_idx),
                    "p2_price": round(p2_price, 2),
                    "handle_low_price": round(handle_low, 2),
                    "handle_depth_pct": round(handle_depth * 100, 2),
                    "pivot_price": round(pivot_price, 2),
                    "target_price": round(target_price, 2),
                    "stop_loss_price": round(stop_loss_price, 2),
                    "expected_return_pct": round(((target_price - curr_price) / curr_price) * 100, 2),
                    "risk_reward_ratio": round((target_price - curr_price) / max(1.0, curr_price - stop_loss_price), 2),
                    "is_breakout": bool(is_breakout),
                    "vol_ratio": round(vol_ratio, 2),
                    "vol_confirmed": bool(vol_confirmed),
                    "score": min(100, score),
                    "description": f"컵 깊이 -{round(cup_depth*100,1)}%, 핸들 조정 -{round(handle_depth*100,1)}%, 피봇({round(pivot_price, 0):,}원) {'돌파 완료' if is_breakout else '접근 중'}"
                }

    return best_pattern
