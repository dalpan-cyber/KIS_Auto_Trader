"""
KIS Auto Trading - 52-Week High Rebound Strategy (rebound.py)
52주 최고가 대비 낙폭과대(-30% 이하) 바닥권에서
바닥 턴어라운드(5일선 돌파), 수급 폭발(거래량 130%+), RSI 과매도 탈출을 결합한 역발상 반등 매수 전략
"""
import logging
from typing import Dict, Any, Optional, Set
import pandas as pd

import app_config as config
from core.strategy.base import BaseStrategy
from core.strategy import register_strategy

logger = logging.getLogger("ReboundStrategy")


@register_strategy
class ReboundStrategy(BaseStrategy):
    """52주 낙폭과대 바닥반등 전략 - 떨어지는 칼날 방어 및 수급 반등 매매"""

    name = "rebound"
    display_name = "52주 낙폭과대 바닥반등"
    description = "52주 최고가 대비 -30% 이하 바닥권에서 5일선 상향 돌파(턴어라운드) 및 거래량 폭발, RSI 과매도 탈출 시 매수"

    settings_schema = [
        # --- 공통 설정 ---
        {"key": "target_profit_rate", "label": "목표 익절 수익률", "type": "number",
         "default": 0.07, "min": 0.01, "max": 1.00, "step": 0.01,
         "description": "1차 목표 익절 수익률 (예: 0.07 = +7%)", "category": "common"},
        {"key": "stop_loss_rate", "label": "손절 기준 수익률", "type": "number",
         "default": -0.045, "min": -0.50, "max": -0.01, "step": 0.005,
         "description": "손절 기준 수익률 (예: -0.045 = -4.5%)", "category": "common"},
        {"key": "trailing_stop_pct", "label": "트레일링 스탑 비율", "type": "number",
         "default": 0.05, "min": 0.01, "max": 0.20, "step": 0.005,
         "description": "1차 익절 후 최고가 대비 트레일링 스탑 비율 (예: 0.05 = 5.0%)", "category": "common"},
        {"key": "time_stop_enabled", "label": "타임컷 청산 활성화", "type": "toggle",
         "default": True, "description": "타임컷 청산 활성화 여부", "category": "common"},
        {"key": "time_stop_days", "label": "타임컷 보유 일수", "type": "number",
         "default": 8, "min": 1, "max": 30, "step": 1,
         "description": "바닥 반등 탄력 미발생 시 자금 회수 일수 (영업일 기준)", "category": "common"},
        {"key": "time_stop_min_profit", "label": "타임컷 기준 최소 수익률", "type": "number",
         "default": 0.015, "min": 0.0, "max": 0.20, "step": 0.005,
         "description": "타임컷 기준 최소 수익률 (예: 0.015 = +1.5%)", "category": "common"},
        {"key": "max_daily_buy_count", "label": "1일 최대 신규 매수 종목 수", "type": "number",
         "default": 2, "min": 1, "max": 10, "step": 1,
         "description": "1일 최대 신규 매수 종목 수", "category": "common"},
        {"key": "partial_sell_ratio", "label": "1차 익절 시 매도 비율", "type": "number",
         "default": 0.5, "min": 0.1, "max": 1.0, "step": 0.1,
         "description": "1차 익절 시 매도 비율 (0.5 = 50%)", "category": "common"},
        {"key": "cooldown_enabled", "label": "손절 쿨다운 활성화", "type": "toggle",
         "default": True, "description": "손절 종목 재매수 쿨다운 활성화", "category": "common"},
        {"key": "cooldown_days", "label": "손절 후 재매수 금지 기간", "type": "number",
         "default": 4, "min": 1, "max": 20, "step": 1,
         "description": "손절 후 재매수 금지 기간 (거래일 기준)", "category": "common"},
        {"key": "atr_stop_loss_enabled", "label": "ATR 동적 손절 활성화", "type": "toggle",
         "default": True, "description": "ATR 기반 동적 손절 활성화", "category": "common"},
        {"key": "atr_stop_loss_multiple", "label": "ATR 손절 배수", "type": "number",
         "default": 2.0, "min": 1.0, "max": 5.0, "step": 0.1,
         "description": "ATR 손절 배수 (진입가 - N×ATR)", "category": "common"},
        {"key": "buy_score_threshold", "label": "매수 추천 최소 종합 점수", "type": "number",
         "default": 50, "min": 0, "max": 100, "step": 1,
         "description": "매수 추천 최소 종합 점수 (50점 이상 추천)", "category": "common"},

        # --- 전략 고유 설정 (52주 바닥반등 특화) ---
        {"key": "rebound_w52_drop_threshold", "label": "52주 고가 대비 낙폭 기준", "type": "number",
         "default": -0.30, "min": -0.80, "max": -0.10, "step": 0.05,
         "description": "52주 최고가 대비 최소 하락률 (예: -0.30 = -30% 이하 낙폭과대)", "category": "strategy"},
        {"key": "rebound_volume_ratio_min", "label": "바닥 수급 최소 거래량 배수", "type": "number",
         "default": 1.3, "min": 1.0, "max": 3.0, "step": 0.1,
         "description": "손바꿈 수급 확인을 위한 20일 이평 대비 최소 거래량 배수 (1.3 = 130%)", "category": "strategy"},
        {"key": "rebound_volume_ratio_max", "label": "바닥 수급 최대 거래량 배수", "type": "number",
         "default": 4.5, "min": 2.0, "max": 10.0, "step": 0.5,
         "description": "이상 급변동 배제를 위한 거래량 상한 배수 (4.5 = 450%)", "category": "strategy"},
        {"key": "rebound_rsi_min", "label": "RSI 과매도 구간 하한", "type": "number",
         "default": 25, "min": 10, "max": 40, "step": 1,
         "description": "과매도 반등 탐지 RSI 하한", "category": "strategy"},
        {"key": "rebound_rsi_max", "label": "RSI 과매도 탈출 상한", "type": "number",
         "default": 48, "min": 35, "max": 65, "step": 1,
         "description": "과매도 탈출 반등 탐지 RSI 상한", "category": "strategy"},
        {"key": "rebound_high_chase_ma5_pct", "label": "5일선 이격 과열 기준", "type": "number",
         "default": 0.03, "min": 0.01, "max": 0.10, "step": 0.005,
         "description": "5일선 대비 이격도 3% 초과 시 고점 추격 배제", "category": "strategy"},
        {"key": "rebound_upper_shadow_ratio", "label": "윗꼬리 허용 비율", "type": "number",
         "default": 0.40, "min": 0.10, "max": 0.60, "step": 0.05,
         "description": "당일 윗꼬리 매물 출회 차단 비율", "category": "strategy"},
        {"key": "rebound_w52_score", "label": "52주 낙폭과대 배점", "type": "number",
         "default": 25, "min": 10, "max": 40, "step": 5,
         "description": "52주 고가 대비 낙폭 조건 만족 시 점수", "category": "strategy"},
        {"key": "rebound_turnaround_score", "label": "바닥 턴어라운드 배점", "type": "number",
         "default": 30, "min": 10, "max": 50, "step": 5,
         "description": "당일 5일선 상향 돌파 또는 양봉 지지 시 점수", "category": "strategy"},
        {"key": "rebound_volume_score", "label": "수급 거래량 폭발 배점", "type": "number",
         "default": 25, "min": 10, "max": 40, "step": 5,
         "description": "20일 평균 거래량 대비 130% 이상 수급 확인 시 점수", "category": "strategy"},
        {"key": "rebound_rsi_score", "label": "RSI 과매도 탈출 배점", "type": "number",
         "default": 20, "min": 5, "max": 30, "step": 5,
         "description": "RSI 과매도 구간 양봉 반등 시 점수", "category": "strategy"},
    ]

    def evaluate_buy(
        self,
        df: Optional[pd.DataFrame],
        code: str,
        name: str,
        held_codes: Optional[Set[str]] = None,
        budget: Optional[float] = None,
        market_regime: Optional[Dict[str, Any]] = None,
        settings: Optional[Dict[str, Any]] = None,
        is_in_cooldown: bool = False,
        futures_data: Optional[Dict[str, Any]] = None,
        return_raw_eval: bool = False,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        52주 낙폭과대 바닥 반등 매수 평가
        """
        if df is None or len(df) < 20:
            return None

        regime = (market_regime or {}).get("regime", "BULL")
        settings = config.get_effective_strategy_settings(self.name, settings or {})
        settings = config.get_effective_settings_for_regime(regime, settings)
        held_codes = held_codes or set()
        is_additional_buy = code in held_codes

        last = df.iloc[-1]
        prev = df.iloc[-2]
        current_price = float(last["close"])
        open_price = float(last.get("open", current_price))
        high_price = float(last.get("high", current_price))
        low_price = float(last.get("low", current_price))
        change_rate = float(last.get("change_rate", 0.0))

        reasons = []

        # -------------------------------------------------------------
        # [게이트 1] 손절 쿨다운 체크
        # -------------------------------------------------------------
        if is_in_cooldown:
            logger.info(f"[{name}({code})] 손절 쿨다운 기간 내 - 재매수 차단")
            return None

        # -------------------------------------------------------------
        # [게이트 2] 52주(250일) 최고가 대비 낙폭 조건 검증
        # -------------------------------------------------------------
        # 1) DataFrame 내 d250_hgpr 또는 high_52w 필드 확인
        # 2) 없으면 로드된 캔들의 전체 최고가를 기준선으로 활용
        w52_high = 0.0
        if "d250_hgpr" in last and not pd.isna(last["d250_hgpr"]) and float(last["d250_hgpr"]) > 0:
            w52_high = float(last["d250_hgpr"])
        elif "high_52w" in last and not pd.isna(last["high_52w"]) and float(last["high_52w"]) > 0:
            w52_high = float(last["high_52w"])
        else:
            w52_high = float(df["high"].max())

        if w52_high <= 0:
            return None

        w52_drop_rate = (current_price - w52_high) / w52_high  # 예: -0.34 (-34%)
        drop_threshold = float(settings.get("rebound_w52_drop_threshold", -0.30))

        # 고가 대비 낙폭이 기준치(기본 -30%) 미달(덜 빠짐)인 경우 제외
        if w52_drop_rate > drop_threshold:
            return None

        # -------------------------------------------------------------
        # [게이트 3] 고점 추격 매수 방지 & 윗꼬리 매물 출회 차단
        # -------------------------------------------------------------
        ma5_val = float(last["ma5"]) if not pd.isna(last["ma5"]) else current_price
        high_chase_pct = float(settings.get("rebound_high_chase_ma5_pct", 0.03))
        if ma5_val > 0 and (current_price / ma5_val) > (1 + high_chase_pct):
            return None

        # 윗꼬리 비율 차단 (윗꼬리 / 전체변동폭 >= 40% 제외)
        total_range = high_price - low_price
        if total_range > 0:
            upper_shadow = high_price - max(open_price, current_price)
            upper_ratio = float(settings.get("rebound_upper_shadow_ratio", 0.40))
            if (upper_shadow / total_range) >= upper_ratio:
                return None

        # -------------------------------------------------------------
        # [게이트 4] 바닥 턴어라운드 지지 확인 (떨어지는 칼날 방어)
        # 당일 양봉(종가 >= 시가)이거나, 5일선을 상향 돌파/안착해야 함
        # -------------------------------------------------------------
        is_bull_candle = current_price >= open_price
        is_ma5_rebound = current_price >= ma5_val or (prev["close"] <= prev["ma5"] and current_price > ma5_val)

        if not (is_bull_candle and is_ma5_rebound):
            # 바닥 지지 반등 없이 음봉으로 계속 밀리는 칼날은 제외
            return None

        # -------------------------------------------------------------
        # [게이트 5] 수급 필수 게이트 (손바꿈 대량 거래량)
        # -------------------------------------------------------------
        vol_ma20 = float(last["vol_ma20"]) if not pd.isna(last["vol_ma20"]) else 0.0
        adj_volume = float(last["adjusted_volume"]) if not pd.isna(last["adjusted_volume"]) else float(last["volume"])
        if vol_ma20 <= 0:
            return None

        vol_ratio = (adj_volume / vol_ma20) * 100
        vol_min = float(settings.get("rebound_volume_ratio_min", 1.3))
        vol_max = float(settings.get("rebound_volume_ratio_max", 4.5))

        if not (vol_min <= (adj_volume / vol_ma20) <= vol_max):
            return None

        # -------------------------------------------------------------
        # 점수 산출
        # -------------------------------------------------------------
        total_score = 0

        # 1. 52주 낙폭과대 점수
        w52_score = int(settings.get("rebound_w52_score", 25))
        total_score += w52_score
        reasons.append(f"📉 52주 최고가({w52_high:,.0f}원) 대비 {w52_drop_rate*100:.1f}% 낙폭과대 바닥권 (+{w52_score}점)")

        # 2. 바닥 턴어라운드 점수
        turnaround_score = int(settings.get("rebound_turnaround_score", 30))
        total_score += turnaround_score
        reasons.append(f"🔄 5일선 상향 돌파 및 양봉 턴어라운드 지지 확인 (+{turnaround_score}점)")

        # 3. 거래량 수급 점수
        vol_score = int(settings.get("rebound_volume_score", 25))
        total_score += vol_score
        reasons.append(f"🔥 바닥권 손바꿈 대량 수급 유입 (20일평균 대비 {vol_ratio:.0f}%) (+{vol_score}점)")

        # 4. RSI 과매도 탈출 점수
        rsi = float(last["rsi14"]) if not pd.isna(last["rsi14"]) else 50.0
        rsi_min = float(settings.get("rebound_rsi_min", 25))
        rsi_max = float(settings.get("rebound_rsi_max", 48))
        if rsi_min <= rsi <= rsi_max:
            rsi_score = int(settings.get("rebound_rsi_score", 20))
            total_score += rsi_score
            reasons.append(f"🎯 RSI({rsi:.1f}) 과매도권 탈출 반등 (+{rsi_score}점)")

        # 볼린저밴드 하단 지지 반등 보너스
        if "bb_lower" in last and not pd.isna(last["bb_lower"]):
            if current_price >= float(last["bb_lower"]) and low_price <= float(last["bb_lower"]) * 1.01:
                total_score += 10
                reasons.append("🛡️ 볼린저밴드 하단선 지지 반등 확인 (+10점)")

        # 종합 진입 점수 판별
        buy_threshold = float(settings.get("buy_score_threshold", 50))
        if total_score >= buy_threshold:
            default_budget = float(settings.get("max_buy_budget_per_stock", 500000.0))
            budget_val = budget if budget is not None else default_budget
            atr_val = float(last["atr"]) if "atr" in last and not pd.isna(last["atr"]) else 0.0

            qty = self.calculate_position_size(current_price, budget_val, atr_val=atr_val, settings=settings)
            total_est = qty * current_price

            result = {
                "code": code,
                "name": name,
                "current_price": current_price,
                "change_rate": change_rate,
                "score": total_score,
                "strategy": self.name,
                "strategy_name": self.name,
                "strategy_display_name": self.display_name,
                "w52_high": w52_high,
                "w52_drop_rate": round(w52_drop_rate * 100, 1),
                "vol_ratio": round(vol_ratio, 1),
                "reasons": reasons,
                "recommended_qty": qty,
                "estimated_amount": total_est,
                "rsi": round(float(rsi), 1) if not pd.isna(rsi) else None,
                "ma5": round(ma5_val, 0),
                "ma20": round(float(last.get("ma20", 0)), 0),
                "atr": round(atr_val, 0),
                "market_regime": regime,
                "buy_threshold": buy_threshold
            }

            if is_additional_buy:
                result["is_additional_buy"] = True
                result["buy_type"] = "추가매수"
                result["reasons"] = ["📌 보유 종목 바닥 반등 추가매수"] + reasons
            else:
                result["is_additional_buy"] = False
                result["buy_type"] = "신규매수"

            return result

        return None

    def evaluate_sell(
        self,
        holding: Dict[str, Any],
        df: Optional[pd.DataFrame] = None,
        is_recently_bought: bool = False,
        stop_loss_rate: Optional[float] = None,
        target_profit_rate: Optional[float] = None,
        settings: Optional[Dict[str, Any]] = None,
        is_partial_sold: bool = False,
        highest_price: Optional[float] = None,
        holding_days: int = 0,
        market_regime: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        바닥 반등 종목의 매도 판단 (빠른 1차 익절 및 손절 보호)
        """
        regime = (market_regime or {}).get("regime", "BULL")
        settings = config.get_effective_strategy_settings(self.name, settings or {})
        settings = config.get_effective_settings_for_regime(regime, settings)

        code = holding.get("code")
        name = holding.get("name", code)
        profit_rate = float(holding.get("profit_rate", 0.0))
        current_price = float(holding.get("current_price", 0.0))
        holding_qty = int(holding.get("quantity", holding.get("qty", 0)))
        avg_buy_price = float(holding.get("avg_buy_price", 0.0))
        profit_loss = float(holding.get("profit_loss", 0.0))

        # 1. 긴급 손절 (ATR 동적 손절 또는 고정 손절)
        base_sl_rate = (stop_loss_rate if stop_loss_rate is not None else float(settings.get("stop_loss_rate", -0.045))) * 100
        effective_sl = base_sl_rate

        if settings.get("atr_stop_loss_enabled", True) and df is not None and len(df) >= 20:
            last = df.iloc[-1]
            atr_val = float(last["atr"]) if "atr" in last and not pd.isna(last["atr"]) else 0.0
            if atr_val > 0 and avg_buy_price > 0:
                atr_mul = float(settings.get("atr_stop_loss_multiple", 2.0))
                calc_stop_price = avg_buy_price - (atr_mul * atr_val)
                calc_rate = ((calc_stop_price - avg_buy_price) / avg_buy_price) * 100
                effective_sl = max(-6.0, min(-3.0, calc_rate))

        if profit_rate <= effective_sl:
            return {
                "code": code,
                "name": name,
                "holding_qty": holding_qty,
                "sell_qty": holding_qty,
                "sell_ratio": 1.0,
                "sell_type": "전량 긴급손절",
                "avg_buy_price": avg_buy_price,
                "current_price": current_price,
                "profit_rate": profit_rate,
                "profit_loss": profit_loss,
                "reasons": [f"🚨 바닥 반등 실패 손절 도달 ({profit_rate:+.2f}% <= {effective_sl:.1f}%) - 전량 매도"],
                "is_urgent": True
            }

        # 2. 1차 분할 익절 (기본 +7%)
        tp_rate = (target_profit_rate if target_profit_rate is not None else float(settings.get("target_profit_rate", 0.07))) * 100
        if profit_rate >= tp_rate and not is_partial_sold:
            sell_qty = max(1, holding_qty // 2) if holding_qty > 1 else holding_qty
            sell_ratio = 0.5 if holding_qty > 1 else 1.0
            return {
                "code": code,
                "name": name,
                "holding_qty": holding_qty,
                "sell_qty": sell_qty,
                "sell_ratio": sell_ratio,
                "sell_type": "50% 1차익절" if sell_ratio == 0.5 else "전량익절",
                "avg_buy_price": avg_buy_price,
                "current_price": current_price,
                "profit_rate": profit_rate,
                "profit_loss": profit_loss,
                "reasons": [f"🎯 바닥 반등 1차 목표가 달성 (+{profit_rate:.2f}% >= +{tp_rate:.1f}%) - 50% 분할 익절"],
                "is_urgent": False,
                "is_partial_take": True
            }

        # 3. 1차 익절 후 잔여분 트레일링 스탑
        if is_partial_sold:
            high_bench = highest_price if highest_price is not None and highest_price > 0 else max(avg_buy_price, current_price)
            trailing_pct = float(settings.get("trailing_stop_pct", 0.05))
            trailing_price = high_bench * (1 - trailing_pct)
            if current_price <= trailing_price:
                return {
                    "code": code,
                    "name": name,
                    "holding_qty": holding_qty,
                    "sell_qty": holding_qty,
                    "sell_ratio": 1.0,
                    "sell_type": "트레일링 스탑 전량익절",
                    "avg_buy_price": avg_buy_price,
                    "current_price": current_price,
                    "profit_rate": profit_rate,
                    "profit_loss": profit_loss,
                    "reasons": [f"🏆 최고가({high_bench:,.0f}원) 대비 -{trailing_pct*100:.1f}% 트레일링 스탑 발동"],
                    "is_urgent": False
                }

        # 4. 2일 보유 유예
        if is_recently_bought:
            return None

        # 5. 타임컷 (기본 8영업일)
        time_days = int(settings.get("time_stop_days", 8))
        time_min_roi = float(settings.get("time_stop_min_profit", 0.015)) * 100
        if settings.get("time_stop_enabled", True) and holding_days >= time_days:
            if profit_rate < time_min_roi:
                return {
                    "code": code,
                    "name": name,
                    "holding_qty": holding_qty,
                    "sell_qty": holding_qty,
                    "sell_ratio": 1.0,
                    "sell_type": "타임컷 청산",
                    "avg_buy_price": avg_buy_price,
                    "current_price": current_price,
                    "profit_rate": profit_rate,
                    "profit_loss": profit_loss,
                    "reasons": [f"⏳ {holding_days}영업일 경과 및 반등 탄력 미발생({profit_rate:+.2f}% < +{time_min_roi:.1f}%) - 자금 회수"],
                    "is_urgent": False
                }

        return None
