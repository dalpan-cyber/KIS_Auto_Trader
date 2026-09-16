"""
KIS Auto Trading - Monthly Trend Strategy (monthly_trend.py)
KOSPI 100 대형 우량주 대상 월봉 10개월 단순이동평균(SMA 10) 추세추종 (GTAA) 전략
- 매수: 월봉 종가가 10개월 이평선을 상향 돌파(Golden Cross) 또는 10이평 위 안정적 상승 추세 시
- 매도: 월봉 종가가 10개월 이평선을 하향 이탈(Dead Cross) 시 전량 현금화(원금 보존)
- 자금 관리: 100만 원 초과 고가주(고려아연 등) 1주 제한 규칙 적용
"""
import logging
from typing import Dict, Any, Optional, Set, List
import pandas as pd
import numpy as np

import app_config as config
from core.strategy.base import BaseStrategy
from core.strategy import register_strategy

logger = logging.getLogger("MonthlyTrendStrategy")


@register_strategy
class MonthlyTrendStrategy(BaseStrategy):
    """월봉 10개월 이동평균선 추세추종 (GTAA) 전략"""

    name = "monthly_trend"
    display_name = "월봉 10이평 추세추종 (GTAA)"
    description = "KOSPI 100 대형주 대상, 월봉 종가가 10개월 이동평균선(SMA 10)을 상향 돌파 시 매수하고 하향 이탈 시 전량 현금화하는 중장기 전술적 자산배분 전략"

    settings_schema = [
        # --- 공통 설정 ---
        {"key": "target_profit_rate", "label": "목표 익절 수익률", "type": "number",
         "default": 0.20, "min": 0.05, "max": 1.00, "step": 0.05,
         "description": "추세 추종 중 목표 익절 수익률 (0.20 = +20%)", "category": "common"},
        {"key": "stop_loss_rate", "label": "비상 손절 기준 수익률", "type": "number",
         "default": -0.07, "min": -0.20, "max": -0.02, "step": 0.005,
         "description": "월봉 이탈 전 일봉 기준 비상 손절 수익률 (-0.07 = -7.0%)", "category": "common"},
        {"key": "trailing_stop_pct", "label": "트레일링 스탑 비율", "type": "number",
         "default": 0.08, "min": 0.02, "max": 0.20, "step": 0.01,
         "description": "고점 대비 트레일링 스탑 비율 (0.08 = 8.0%)", "category": "common"},
        {"key": "max_holding_stocks", "label": "최대 동시 보유 종목 수", "type": "number",
         "default": 10, "min": 1, "max": 30, "step": 1,
         "description": "포트폴리오 분산 최대 보유 종목 수", "category": "common"},
        {"key": "max_daily_buy_count", "label": "1일 최대 신규 매수 종목 수", "type": "number",
         "default": 3, "min": 1, "max": 10, "step": 1,
         "description": "1일 최대 신규 매수 가능 종목 수", "category": "common"},
        {"key": "buy_score_threshold", "label": "매수 추천 최소 종합 점수", "type": "number",
         "default": 60, "min": 0, "max": 100, "step": 1,
         "description": "매수 추천 최소 종합 점수 (60점 이상 추천)", "category": "common"},
        {"key": "max_buy_budget_per_stock", "label": "1종목당 기본 배정 예산", "type": "number",
         "default": 1000000, "min": 100000, "max": 10000000, "step": 100000,
         "description": "1종목당 기본 배정 예산 (원)", "category": "common"},
        {"key": "cooldown_enabled", "label": "손절 쿨다운 활성화", "type": "toggle",
         "default": True, "description": "손절 종목 재매수 쿨다운 활성화", "category": "common"},
        {"key": "cooldown_days", "label": "손절 후 재매수 금지 기간", "type": "number",
         "default": 5, "min": 1, "max": 20, "step": 1,
         "description": "손절 후 재매수 금지 기간 (영업일 기준)", "category": "common"},

        # --- 월봉 전략 고유 설정 ---
        {"key": "monthly_sma_period", "label": "월봉 이동평균 기간", "type": "number",
         "default": 10, "min": 3, "max": 24, "step": 1,
         "description": "추세 판별 월봉 단순이동평균 기간 (기본: 10개월)", "category": "strategy"},
        {"key": "monthly_allow_trend_continuation", "label": "10이평 상회 지속 종목 진입 허용", "type": "toggle",
         "default": False, "description": "골든크로스 첫 달뿐만 아니라 10이평 위에서 우상향 지속 중인 우량주도 진입 허용 (False: 신규 골든크로스 종목만 진입)", "category": "strategy"},
        {"key": "monthly_high_price_limit_enabled", "label": "100만 원 초과 고가주 1주 제한", "type": "toggle",
         "default": True, "description": "주가가 100만 원을 초과하는 황제주(고려아연 등)는 최대 1주만 매수하도록 제한", "category": "strategy"},
        {"key": "monthly_max_high_chase_pct", "label": "10이평 이격도 과열 차단 기준", "type": "number",
         "default": 0.20, "min": 0.05, "max": 0.50, "step": 0.01,
         "description": "10개월 이평선 대비 이격도가 너무 큰 종목 고점 추격 매수 배제 (0.20 = +20%)", "category": "strategy"}
    ]

    def calculate_position_size(
        self,
        current_price: float,
        budget_val: float,
        atr_val: float = 0.0,
        settings: Optional[Dict[str, Any]] = None
    ) -> int:
        """자금 관리: 100만 원 초과 고가주는 1주 제한, 일반 주식은 예산 내 최대 정수 수량"""
        if current_price <= 0 or budget_val <= 0:
            return 0

        sett = settings or config.CURRENT_SETTINGS
        high_price_limit = sett.get("monthly_high_price_limit_enabled", True)

        # 💡 [핵심 조건] 주가가 1,000,000원을 초과하는 고가주인 경우
        if high_price_limit and current_price > 1000000:
            # 예산이 허용하면 1주, 아니면 0주
            return 1 if budget_val >= current_price else 0

        # 일반 주식: 배정 예산 한도 내 정수 수량 매수
        shares = int(budget_val // current_price)
        return max(1, shares) if budget_val >= current_price else 0

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
        investor_data: Optional[Dict[str, Any]] = None,
        volume_power: Optional[float] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """월봉 데이터(최소 10개월 이상)를 바탕으로 10이평 골든크로스 / 지속 상승 추세 평가"""
        # extra_data에서 monthly_df 우선 사용, 없으면 df 사용
        target_df = None
        if extra_data and isinstance(extra_data.get("monthly_df"), pd.DataFrame):
            target_df = extra_data["monthly_df"]
        elif df is not None:
            target_df = df

        if target_df is None or len(target_df) < 10:
            return None

        sett = settings or config.CURRENT_SETTINGS
        sma_period = int(sett.get("monthly_sma_period", 10))
        if len(target_df) < sma_period + 1:
            return None

        # 월봉 종가 및 SMA10 연산
        work_df = target_df.copy()
        if "close" not in work_df.columns:
            return None

        work_df["close"] = pd.to_numeric(work_df["close"], errors="coerce")
        work_df = work_df.dropna(subset=["close"]).reset_index(drop=True)
        if len(work_df) < sma_period + 1:
            return None

        work_df[f"sma_{sma_period}"] = work_df["close"].rolling(window=sma_period).mean()

        last_idx = work_df.index[-1]
        prev_idx = work_df.index[-2]

        curr_close = float(work_df.loc[last_idx, "close"])
        curr_sma = float(work_df.loc[last_idx, f"sma_{sma_period}"])
        prev_close = float(work_df.loc[prev_idx, "close"])
        prev_sma = float(work_df.loc[prev_idx, f"sma_{sma_period}"])

        change_rate = float(work_df.loc[last_idx].get("change_rate", 0.0))

        reasons = []
        disqualify_reason: Optional[str] = None

        # 1. 손절 쿨다운 확인
        if is_in_cooldown:
            disqualify_reason = "손절 후 쿨다운 기간 (재매수 대기)"
            if not return_raw_eval:
                return None

        # 2. [핵심 매수 시그널] 월봉 10이평 골든크로스 vs 지속 상승 추세
        is_golden_cross = (prev_close <= prev_sma) and (curr_close > curr_sma)
        is_continuation = (prev_close > prev_sma) and (curr_close > curr_sma)
        allow_continuation = sett.get("monthly_allow_trend_continuation", False)

        if not is_golden_cross and not is_continuation:
            disqualify_reason = f"월봉 종가가 {sma_period}개월 이평선 하회 (역배열/하락추세)"
            if not return_raw_eval:
                return None
        elif not is_golden_cross and not allow_continuation:
            disqualify_reason = f"{sma_period}개월 이평선 상향 돌파(신규 골든크로스) 첫 달 아님 (추세 지속 종목 배제)"
            if not return_raw_eval:
                return None

        # 3. 고점 이격도 과열 방지
        distance_pct = (curr_close - curr_sma) / curr_sma if curr_sma > 0 else 0.0
        max_chase_pct = float(sett.get("monthly_max_high_chase_pct", 0.20))
        if distance_pct > max_chase_pct:
            disqualify_reason = f"{sma_period}개월선 대비 이격 과열 (+{distance_pct*100:.1f}% > +{max_chase_pct*100:.0f}%)"
            if not return_raw_eval:
                return None

        # 4. 점수 산출 (100점 만점 척도)
        total_score = 0

        # (1) 추세 돌파 / 지속 점수 (최대 50점)
        if is_golden_cross:
            total_score += 50
            reasons.append(f"🌟 [골든크로스] 월봉 종가가 {sma_period}개월 이동평균선을 상향 돌파 (+50점)")
        else:
            total_score += 40
            reasons.append(f"📈 [추세 지속] 월봉 종가가 {sma_period}개월 이동평균선 상회 유지 (+40점)")

        # (2) 이격도 안정성 점수 (최대 25점)
        if 0.01 <= distance_pct <= 0.08:
            total_score += 25
            reasons.append(f"🎯 {sma_period}개월선 근접 눌림목 지지 반등 (이격도 +{distance_pct*100:.1f}%) (+25점)")
        elif 0.08 < distance_pct <= 0.15:
            total_score += 20
            reasons.append(f"🟢 {sma_period}개월선 대비 건전한 상승 추세 (이격도 +{distance_pct*100:.1f}%) (+20점)")
        else:
            total_score += 10
            reasons.append(f"⚡ {sma_period}개월선 상회 (이격도 +{distance_pct*100:.1f}%) (+10점)")

        # (3) 최근 월봉 모멘텀 (최대 15점)
        # 최근 2~3개월 연속 양봉 여부
        if len(work_df) >= 3:
            p2_close = float(work_df.loc[work_df.index[-3], "close"])
            if curr_close > prev_close > p2_close:
                total_score += 15
                reasons.append("🔥 최근 3개월 연속 우상향 모멘텀 지속 (+15점)")
            elif curr_close > prev_close:
                total_score += 10
                reasons.append("📊 전월 대비 상승 마감 모멘텀 (+10점)")

        # (4) 메이저 수급 가산점 (외인/기관) (최대 10점)
        if isinstance(investor_data, dict):
            if investor_data.get("is_double_buying"):
                total_score += 10
                reasons.append("💎 메이저 외인·기관 쌍끌이 순매수 (+10점)")
            elif investor_data.get("foreign_net_buy_qty", 0) > 0 or investor_data.get("institution_net_buy_qty", 0) > 0:
                total_score += 5
                reasons.append("👍 외인 또는 기관 순매수 유입 (+5점)")

        total_score = min(100, total_score)
        buy_threshold = float(sett.get("buy_score_threshold", 60))
        is_recommended = (total_score >= buy_threshold) and (disqualify_reason is None)

        # 5. 수량 계산
        budget_val = budget or float(sett.get("max_buy_budget_per_stock", 1000000))
        rec_qty = self.calculate_position_size(curr_close, budget_val, settings=sett)

        return {
            "code": code,
            "name": name,
            "current_price": curr_close,
            "change_rate": change_rate,
            "score": total_score,
            "trend_score": 50 if is_golden_cross else 40,
            "supply_score": 10 if (investor_data and investor_data.get("is_double_buying")) else 5,
            "momentum_score": 25 if (0.01 <= distance_pct <= 0.08) else 15,
            "is_recommended": is_recommended,
            "disqualify_reason": disqualify_reason,
            "recommended_qty": rec_qty,
            "estimated_amount": rec_qty * curr_close,
            "reasons": reasons,
            "strategy": self.name,
            "strategy_name": self.name,
            "strategy_display_name": self.display_name,
            "monthly_sma": curr_sma,
            "distance_from_sma": round(distance_pct * 100, 2),
            "is_golden_cross": is_golden_cross
        }

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
        매도 신호 평가:
        1. 비상 손절: 진입가 대비 급락 시 (예: -7%) 조기 손절
        2. 월봉 10이평 하향 이탈(Dead Cross): 월봉 종가가 10개월 이평선 하회 시 전량 현금화
        3. 목표 익절: +20% 이상 달성 후 트레일링 스탑
        """
        sett = settings or config.CURRENT_SETTINGS
        current_price = float(holding.get("current_price", 0.0))
        avg_buy_price = float(holding.get("avg_buy_price", current_price))
        holding_qty = int(holding.get("holding_qty", 0))

        if current_price <= 0 or avg_buy_price <= 0 or holding_qty <= 0:
            return None

        profit_rate = (current_price - avg_buy_price) / avg_buy_price
        profit_loss = (current_price - avg_buy_price) * holding_qty

        # 1. 비상 손절 체크 (일봉 급락 방어)
        emergency_stop = float(stop_loss_rate or sett.get("stop_loss_rate", -0.07))
        if profit_rate <= emergency_stop:
            return {
                "code": holding.get("code"),
                "name": holding.get("name"),
                "sell_type": "비상 손절",
                "sell_qty": holding_qty,
                "current_price": current_price,
                "avg_buy_price": avg_buy_price,
                "profit_rate": round(profit_rate * 100, 2),
                "profit_loss": profit_loss,
                "reasons": [f"🚨 비상 손절 기준 도달 ({profit_rate*100:.2f}% <= {emergency_stop*100:.1f}%) - 원금 보호 전량 매도"],
                "is_urgent": True
            }

        # 2. 월봉 10이평선 하향 이탈(Dead Cross) 체크
        if df is not None and len(df) >= 10:
            sma_period = int(sett.get("monthly_sma_period", 10))
            work_df = df.copy()
            work_df["close"] = pd.to_numeric(work_df["close"], errors="coerce")
            work_df = work_df.dropna(subset=["close"]).reset_index(drop=True)
            if len(work_df) >= sma_period:
                work_df[f"sma_{sma_period}"] = work_df["close"].rolling(window=sma_period).mean()
                curr_sma = float(work_df.loc[work_df.index[-1], f"sma_{sma_period}"])
                
                # 월봉 종가가 10이평선을 하향 이탈한 경우
                if current_price < curr_sma:
                    return {
                        "code": holding.get("code"),
                        "name": holding.get("name"),
                        "sell_type": "월봉 10이평 이탈 매도",
                        "sell_qty": holding_qty,
                        "current_price": current_price,
                        "avg_buy_price": avg_buy_price,
                        "profit_rate": round(profit_rate * 100, 2),
                        "profit_loss": profit_loss,
                        "reasons": [
                            f"📉 월봉 종가({current_price:,.0f}원)가 {sma_period}개월 이동평균선({curr_sma:,.0f}원)을 하향 이탈하여 전량 현금화"
                        ],
                        "is_urgent": False
                    }

        # 3. 목표 익절 및 트레일링 스탑
        target_profit = float(target_profit_rate or sett.get("target_profit_rate", 0.20))
        trailing_pct = float(sett.get("trailing_stop_pct", 0.08))
        high_p = float(highest_price or holding.get("highest_price", current_price))

        if high_p >= avg_buy_price * (1 + target_profit):
            drawdown_from_high = (high_p - current_price) / high_p if high_p > 0 else 0.0
            if drawdown_from_high >= trailing_pct:
                return {
                    "code": holding.get("code"),
                    "name": holding.get("name"),
                    "sell_type": "트레일링 스탑 익절",
                    "sell_qty": holding_qty,
                    "current_price": current_price,
                    "avg_buy_price": avg_buy_price,
                    "profit_rate": round(profit_rate * 100, 2),
                    "profit_loss": profit_loss,
                    "reasons": [
                        f"🎯 최고가({high_p:,.0f}원) 대비 -{drawdown_from_high*100:.1f}% 하락하여 트레일링 익절 ({profit_rate*100:+.2f}%)"
                    ],
                    "is_urgent": False
                }

        return None
