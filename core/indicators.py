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

    # 7. MACD (12, 26, 9) - 후지모토 시게루 1:2:6 2단계(모멘텀) 지표
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd_line"] = ema12 - ema26
    df["macd_signal"] = df["macd_line"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd_line"] - df["macd_signal"]

    # 8. 일목균형표 (Ichimoku Cloud, 9-26-52) - 후지모토 시게루 1:2:6 3단계(구름대 추세) 지표
    high_9 = df["high"].rolling(window=9, min_periods=1).max()
    low_9 = df["low"].rolling(window=9, min_periods=1).min()
    df["tenkan_sen"] = (high_9 + low_9) / 2.0  # 전환선 (9일)

    high_26 = df["high"].rolling(window=26, min_periods=1).max()
    low_26 = df["low"].rolling(window=26, min_periods=1).min()
    df["kijun_sen"] = (high_26 + low_26) / 2.0  # 기준선 (26일)

    # 선행스팬 A, B (원시값 및 현재 캔들 위치에 선행 배치된 구름대 값)
    span_a_raw = (df["tenkan_sen"] + df["kijun_sen"]) / 2.0
    high_52 = df["high"].rolling(window=52, min_periods=1).max()
    low_52 = df["low"].rolling(window=52, min_periods=1).min()
    span_b_raw = (high_52 + low_52) / 2.0

    # 표준 일목균형표: 26일 전 계산된 선행스팬이 오늘의 구름대를 형성 (데이터 초반 결측은 원시값으로 보정)
    df["senkou_span_a"] = span_a_raw.shift(26).fillna(span_a_raw)
    df["senkou_span_b"] = span_b_raw.shift(26).fillna(span_b_raw)
    df["cloud_top"] = df[["senkou_span_a", "senkou_span_b"]].max(axis=1)
    df["cloud_bottom"] = df[["senkou_span_a", "senkou_span_b"]].min(axis=1)

    return df


def evaluate_fujimoto_126_exit(
    df: pd.DataFrame,
    avg_buy_price: float,
    holding_qty: int = 9,
    buy_date: Optional[str] = None,
    current_exit_stage: int = 0,
    stop_loss_rate: float = -0.05
) -> Dict[str, Any]:
    """
    후지모토 시게루 1:2:6 매매법 기반 보유 종목 구간 진단 및 분할청산 추천 계산

    [청산 3단계 기준 (역방향 1:2:6)]
    - 1차 청산 (1/9, 약 11.1%):
      매수일 이후(또는 최근 5영업일 내) RSI(14) >= 70 과열 도달 후 현재 RSI < 70으로 하향 이탈 시
      (보조: 수익률 +3% 이상에서 RSI >= 65 후 꺾이며 전환선(9일) 하향 이탈 시에도 1차 경계 발동)
    - 2차 청산 (2/9, 약 22.2%, 누적 3/9):
      MACD 데드크로스 발생 (MACD 선 < 시그널 선으로 전환되었거나, 매수일 이후 골든 상태였다가 음전환 유지)
    - 3차 청산 (6/9, 약 66.7%, 잔여 전량):
      일목균형표 구름대 하향 이탈 (현재가 < 구름대 하단 cloud_bottom)
      또는 비상 손절선 침범 (현재 수익률 <= stop_loss_rate)

    Args:
        df: calculate_technical_indicators()를 거친 일봉 DataFrame
        avg_buy_price: 평균 매수가
        holding_qty: 현재 보유 수량 (기본: 9주)
        buy_date: 매수일자 (YYYYMMDD 또는 YYYY-MM-DD, 선택)
        current_exit_stage: 이미 완료한 청산 단계 (0=미진행, 1=1차완료, 2=2차완료, 3=청산완료)
        stop_loss_rate: 비상 손절 기준 수익률 (기본: -0.05 = -5%)
    """
    if df is None or df.empty:
        return {
            "status_code": "NO_DATA",
            "phase_badge": "⚪ 데이터 부족",
            "recommended_stage": 0,
            "recommended_qty": 0,
            "recommended_ratio_str": "0%",
            "is_action_needed": False,
            "reasons": ["일봉 데이터가 부족하여 지표를 산출할 수 없습니다."]
        }

    # 필수 지표 컬럼이 없으면 계산 수행
    if "macd_line" not in df.columns or "cloud_bottom" not in df.columns:
        df = calculate_technical_indicators(df, is_intraday=False)
        if df is None or df.empty:
            return {
                "status_code": "NO_DATA",
                "phase_badge": "⚪ 데이터 부족",
                "recommended_stage": 0,
                "recommended_qty": 0,
                "recommended_ratio_str": "0%",
                "is_action_needed": False,
                "reasons": ["일봉 데이터가 최소 기준(20봉) 미만입니다."]
            }

    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) >= 2 else last

    curr_price = float(last["close"])
    avg_p = float(avg_buy_price) if avg_buy_price and avg_buy_price > 0 else curr_price
    qty = max(0, int(holding_qty))
    profit_rate = ((curr_price - avg_p) / avg_p) * 100.0 if avg_p > 0 else 0.0
    profit_loss = (curr_price - avg_p) * qty

    # 매수일 정규화 (YYYYMMDD) 및 매수일 이후 슬라이스 추출
    norm_buy_date = ""
    if buy_date:
        norm_buy_date = str(buy_date).strip().replace("-", "").replace(".", "").replace("/", "")[:8]

    if norm_buy_date and "date" in df.columns:
        df_dates = df["date"].astype(str).str.replace("-", "").str.slice(0, 8)
        post_buy_df = df[df_dates >= norm_buy_date]
        if post_buy_df.empty:
            post_buy_df = df.tail(5)
    else:
        post_buy_df = df.tail(10)

    highest_since_buy = float(post_buy_df["high"].max()) if not post_buy_df.empty else max(curr_price, avg_p)
    max_rsi_since_buy = float(post_buy_df["rsi14"].max()) if not post_buy_df.empty else float(last["rsi14"])
    recent_5_max_rsi = float(df["rsi14"].tail(6).iloc[:-1].max()) if len(df) >= 2 else float(last["rsi14"])

    # 현재 지표 값
    curr_rsi = float(last.get("rsi14", 50.0))
    prev_rsi = float(prev.get("rsi14", 50.0))
    macd_line = float(last.get("macd_line", 0.0))
    macd_sig = float(last.get("macd_signal", 0.0))
    macd_hist = float(last.get("macd_hist", 0.0))
    prev_macd_hist = float(prev.get("macd_hist", 0.0))

    tenkan = float(last.get("tenkan_sen", curr_price))
    kijun = float(last.get("kijun_sen", curr_price))
    span_a = float(last.get("senkou_span_a", curr_price))
    span_b = float(last.get("senkou_span_b", curr_price))
    cloud_top = float(last.get("cloud_top", max(span_a, span_b)))
    cloud_bottom = float(last.get("cloud_bottom", min(span_a, span_b)))

    # 구름대 위치 판정
    if curr_price > cloud_top:
        cloud_pos = "ABOVE"
        cloud_pos_label = "구름대 위 (강세 지지)"
    elif curr_price >= cloud_bottom:
        cloud_pos = "INSIDE"
        cloud_pos_label = "구름대 내부 (혼조/지지시험)"
    else:
        cloud_pos = "BELOW"
        cloud_pos_label = "구름대 아래 (추세 이탈)"

    # -------------------------------------------------------------------------
    # 단계별 청산 시그널 판정
    # -------------------------------------------------------------------------
    reasons: List[str] = []

    # [1차 청산 시그널 (비중 1/9)]: RSI 70 과열 찍고 70 하향 이탈 (또는 수익구간 RSI 65+ 찍고 전환선 이탈)
    rsi_overbought_cooldown = (max(max_rsi_since_buy, recent_5_max_rsi) >= 70.0) and (curr_rsi < 70.0)
    rsi_early_turn = (profit_rate >= 3.0) and (max(max_rsi_since_buy, recent_5_max_rsi) >= 65.0) and (curr_rsi < prev_rsi) and (curr_price < tenkan)
    stage1_triggered = bool(rsi_overbought_cooldown or rsi_early_turn)
    stage1_reason = ""
    if rsi_overbought_cooldown:
        stage1_reason = f"[1차 시그널 (비중 1/9)] RSI 과열(최고 {max(max_rsi_since_buy, recent_5_max_rsi):.1f}) 도달 후 70 하향 이탈 (현재 RSI {curr_rsi:.1f})"
    elif rsi_early_turn:
        stage1_reason = f"[1차 시그널 (비중 1/9)] RSI 고점({max(max_rsi_since_buy, recent_5_max_rsi):.1f}→{curr_rsi:.1f}) 꺾임 및 일목 전환선({tenkan:,.0f}원) 하향 이탈"

    # [2차 청산 시그널 (비중 2/9)]: MACD 데드크로스 (macd_line < macd_signal)
    macd_dead_cross_today = (prev_macd_hist >= 0) and (macd_hist < 0)
    had_positive_macd = bool((post_buy_df["macd_hist"] > 0).any()) if "macd_hist" in post_buy_df.columns else True
    stage2_triggered = bool(macd_dead_cross_today or (macd_hist < 0 and had_positive_macd))
    stage2_reason = ""
    if macd_dead_cross_today:
        stage2_reason = f"[2차 시그널 (비중 2/9)] 당일 MACD 데드크로스 발생 (MACD {macd_line:,.1f} < Signal {macd_sig:,.1f})"
    elif stage2_triggered:
        stage2_reason = f"[2차 시그널 (비중 2/9)] MACD 시그널 하향 이탈 유지 (Hist {macd_hist:,.1f} 음수 모멘텀 약화)"

    # [3차 청산 시그널 (비중 6/9 전량)]: 일목 구름대 하단 이탈 또는 비상 손절선 침범
    sl_pct = stop_loss_rate * 100.0 if stop_loss_rate < 0 else -abs(stop_loss_rate) * 100.0
    is_cloud_breakdown = curr_price < cloud_bottom
    is_stop_loss_hit = (avg_p > 0) and (profit_rate <= sl_pct)
    stage3_triggered = bool(is_cloud_breakdown or is_stop_loss_hit)
    stage3_reason = ""
    if is_cloud_breakdown and is_stop_loss_hit:
        stage3_reason = f"[3차 시그널 (전량 6/9)] 일목 구름대 하단({cloud_bottom:,.0f}원) 이탈 및 비상 손절선({sl_pct:.1f}%) 도달"
    elif is_cloud_breakdown:
        stage3_reason = f"[3차 시그널 (전량 6/9)] 현재가({curr_price:,.0f}원)가 일목 구름대 하단({cloud_bottom:,.0f}원) 하향 이탈 (추세 종료)"
    elif is_stop_loss_hit:
        stage3_reason = f"[3차 시그널 (전량 6/9)] 매수가 대비 수익률({profit_rate:+.2f}%)이 손절 기준({sl_pct:.1f}%) 침범 (리스크 컷)"

    # -------------------------------------------------------------------------
    # 현재 보유 종목의 기완료 단계(current_exit_stage)를 고려한 최종 추천 단계 및 수량 산출
    # -------------------------------------------------------------------------
    target_stage = 0
    if stage3_triggered:
        target_stage = 3
        reasons.append(stage3_reason)
    elif stage2_triggered:
        target_stage = 2
        reasons.append(stage2_reason)
        if stage1_triggered:
            reasons.append(stage1_reason)
    elif stage1_triggered:
        target_stage = 1
        reasons.append(stage1_reason)

    # 아직 실행하지 않은 상위 단계 시그널인지 판별
    is_action_needed = (target_stage > current_exit_stage) and (qty > 0)
    recommended_qty = 0
    recommended_ratio_str = "0%"
    action_label = "홀딩 유지"

    if is_action_needed:
        if target_stage == 3:
            recommended_qty = qty
            recommended_ratio_str = "잔여 전량 (6/9, 100%)"
            action_label = "🚨 3차 전량 청산 (비중 6)"
        elif target_stage == 2:
            if current_exit_stage == 0:
                recommended_qty = max(1, int(round(qty * (3.0 / 9.0))))
                recommended_ratio_str = "3/9 (약 33.3%, 1+2차 합산)"
                action_label = "🟠 1·2차 통합 분할청산 (비중 1+2)"
            else:
                recommended_qty = max(1, int(round(qty * (2.0 / 8.0))))
                recommended_ratio_str = "2/9 (잔여의 25%)"
                action_label = "🟠 2차 분할청산 (비중 2)"
        elif target_stage == 1:
            recommended_qty = max(1, int(round(qty * (1.0 / 9.0))))
            recommended_ratio_str = "1/9 (약 11.1%)"
            action_label = "🟡 1차 분할청산 (비중 1)"
        recommended_qty = min(qty, recommended_qty)

    # 구간(Phase) 상태 배지 결정
    if target_stage == 3 and current_exit_stage < 3:
        status_code = "EXIT_STAGE_3"
        phase_badge = "🔴 3차 청산 구간 (구름대 이탈/손절)"
    elif target_stage == 2 and current_exit_stage < 2:
        status_code = "EXIT_STAGE_2"
        phase_badge = "🟠 2차 청산 구간 (MACD 데드크로스)"
    elif target_stage == 1 and current_exit_stage < 1:
        status_code = "EXIT_STAGE_1"
        phase_badge = "🟡 1차 청산 구간 (RSI 과열이탈)"
    elif curr_rsi >= 70.0:
        status_code = "OVERBOUGHT_WATCH"
        phase_badge = "🔥 과열 경계 구간 (RSI 70+ 대기)"
        reasons.append(f"현재 RSI({curr_rsi:.1f})가 70 이상 과열권입니다. 70 아래로 꺾일 때 1차(1/9) 분할익절을 준비하세요.")
    else:
        status_code = "HOLD_CRUISE"
        if cloud_pos == "ABOVE" and macd_hist >= 0:
            phase_badge = "🟢 순항 홀딩 (구름대 위 & MACD 강세)"
            reasons.append(f"현재가({curr_price:,.0f}원)가 구름대 상단({cloud_top:,.0f}원) 위에서 순항 중이며 MACD 모멘텀이 양호합니다.")
        else:
            phase_badge = "🔵 일반 홀딩 (추세 관찰)"
            reasons.append(f"구름대 하단({cloud_bottom:,.0f}원) 지지 여부를 관찰하며 보유를 유지합니다.")

    buy_stage1_ok = curr_rsi >= 30.0
    buy_stage2_ok = macd_hist > 0
    buy_stage3_ok = curr_price > cloud_top

    return {
        "status_code": status_code,
        "phase_badge": phase_badge,
        "action_label": action_label,
        "is_action_needed": bool(is_action_needed),
        "target_stage": int(target_stage),
        "current_exit_stage": int(current_exit_stage),
        "recommended_qty": int(recommended_qty),
        "recommended_amount": int(round(recommended_qty * curr_price)),
        "recommended_ratio_str": recommended_ratio_str,
        "current_price": curr_price,
        "avg_buy_price": avg_p,
        "holding_qty": qty,
        "profit_rate": round(profit_rate, 2),
        "profit_loss": int(round(profit_loss)),
        "highest_since_buy": highest_since_buy,
        "rsi14": round(curr_rsi, 1),
        "max_rsi_since_buy": round(max(max_rsi_since_buy, recent_5_max_rsi), 1),
        "macd_line": round(macd_line, 2),
        "macd_signal": round(macd_sig, 2),
        "macd_hist": round(macd_hist, 2),
        "macd_status": "골든(양수)" if macd_hist >= 0 else "데드(음수)",
        "tenkan_sen": round(tenkan, 0),
        "kijun_sen": round(kijun, 0),
        "cloud_top": round(cloud_top, 0),
        "cloud_bottom": round(cloud_bottom, 0),
        "cloud_pos": cloud_pos,
        "cloud_pos_label": cloud_pos_label,
        "stage1_triggered": stage1_triggered,
        "stage2_triggered": stage2_triggered,
        "stage3_triggered": stage3_triggered,
        "buy_signals": {
            "stage1_rsi30": buy_stage1_ok,
            "stage2_macd_golden": buy_stage2_ok,
            "stage3_cloud_breakout": buy_stage3_ok
        },
        "reasons": reasons
    }


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
