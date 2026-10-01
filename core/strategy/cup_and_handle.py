"""
KIS Auto Trading - Cup and Handle Strategy (cup_and_handle.py)
완만한 U자형 컵(Cup)과 얕은 핸들(Handle) 조정 후
거래량 폭발과 함께 피봇 저항선을 돌파하는 정통 상승 추세 패턴 매매 전략
"""
import logging
from typing import Dict, Any, Optional, Set
import pandas as pd

import app_config as config
from core.strategy.base import BaseStrategy
from core.strategy import register_strategy
from core.indicators import detect_cup_and_handle

logger = logging.getLogger("CupAndHandleStrategy")


@register_strategy
class CupAndHandleStrategy(BaseStrategy):
    """컵앤핸들(Cup & Handle) 돌파 전략 - 윌리엄 오닐 스타일 모멘텀 지속형 매매"""

    name = "cup_and_handle"
    display_name = "컵앤핸들 돌파 (Cup & Handle)"
    description = "U자형 바닥과 핸들 조정을 거친 후 대량 거래량으로 피봇 저항선을 돌파하는 정통 상승 추세 지속 패턴 전략"

    settings_schema = [
        # --- 공통 설정 ---
        {"key": "target_profit_rate", "label": "목표 익절 수익률", "type": "number",
         "default": 0.10, "min": 0.02, "max": 1.00, "step": 0.01,
         "description": "기본 1차 목표 익절 수익률 (0.10 = +10%)", "category": "common"},
        {"key": "stop_loss_rate", "label": "손절 기준 수익률", "type": "number",
         "default": -0.05, "min": -0.30, "max": -0.01, "step": 0.005,
         "description": "손절 기준 수익률 (-0.05 = -5%)", "category": "common"},
        {"key": "trailing_stop_pct", "label": "트레일링 스탑 비율", "type": "number",
         "default": 0.05, "min": 0.01, "max": 0.20, "step": 0.005,
         "description": "1차 익절 후 최고가 대비 트레일링 스탑 비율 (0.05 = 5.0%)", "category": "common"},
        {"key": "time_stop_enabled", "label": "타임컷 청산 활성화", "type": "toggle",
         "default": True, "description": "돌파 후 탄력 미발생 시 자금 회수 활성화 여부", "category": "common"},
        {"key": "time_stop_days", "label": "타임컷 보유 일수", "type": "number",
         "default": 10, "min": 1, "max": 30, "step": 1,
         "description": "돌파 후 횡보 시 자금 회수 일수 (영업일 기준)", "category": "common"},
        {"key": "time_stop_min_profit", "label": "타임컷 기준 최소 수익률", "type": "number",
         "default": 0.02, "min": 0.0, "max": 0.20, "step": 0.005,
         "description": "타임컷 적용 전 최소 수익률 (+2%)", "category": "common"},
        {"key": "max_daily_buy_count", "label": "1일 최대 신규 매수 종목 수", "type": "number",
         "default": 2, "min": 1, "max": 10, "step": 1,
         "description": "1일 최대 신규 매수 종목 수", "category": "common"},
        {"key": "partial_sell_ratio", "label": "1차 익절 시 매도 비율", "type": "number",
         "default": 0.5, "min": 0.1, "max": 1.0, "step": 0.1,
         "description": "1차 익절 시 매도 비율 (0.5 = 50%)", "category": "common"},
        {"key": "cooldown_enabled", "label": "손절 쿨다운 활성화", "type": "toggle",
         "default": True, "description": "손절 종목 재매수 쿨다운 활성화", "category": "common"},
        {"key": "cooldown_days", "label": "손절 후 재매수 금지 기간", "type": "number",
         "default": 5, "min": 1, "max": 20, "step": 1,
         "description": "손절 후 재매수 금지 기간 (거래일 기준)", "category": "common"},
        {"key": "atr_stop_loss_enabled", "label": "ATR 동적 손절 활성화", "type": "toggle",
         "default": True, "description": "ATR 기반 동적 손절 활성화", "category": "common"},
        {"key": "atr_stop_loss_multiple", "label": "ATR 손절 배수", "type": "number",
         "default": 2.0, "min": 1.0, "max": 5.0, "step": 0.1,
         "description": "ATR 손절 배수 (진입가 - N×ATR)", "category": "common"},
        {"key": "buy_score_threshold", "label": "매수 추천 최소 종합 점수", "type": "number",
         "default": 65, "min": 0, "max": 100, "step": 1,
         "description": "매수 추천 최소 종합 점수 (65점 이상 추천)", "category": "common"},

        # --- 전략 고유 설정 (컵앤핸들 특화) ---
        {"key": "cnh_min_cup_bars", "label": "컵 최소 형성 봉수", "type": "number",
         "default": 20, "min": 10, "max": 60, "step": 1,
         "description": "컵 패턴 최소 거래일수 (기본: 20일)", "category": "strategy"},
        {"key": "cnh_max_cup_bars", "label": "컵 최대 형성 봉수", "type": "number",
         "default": 80, "min": 30, "max": 150, "step": 5,
         "description": "컵 패턴 최대 탐색 거래일수 (기본: 80일)", "category": "strategy"},
        {"key": "cnh_min_handle_bars", "label": "핸들 최소 형성 봉수", "type": "number",
         "default": 3, "min": 2, "max": 10, "step": 1,
         "description": "핸들 구간 최소 거래일수 (기본: 3일)", "category": "strategy"},
        {"key": "cnh_max_handle_bars", "label": "핸들 최대 형성 봉수", "type": "number",
         "default": 20, "min": 5, "max": 30, "step": 1,
         "description": "핸들 구간 최대 거래일수 (기본: 20일)", "category": "strategy"},
        {"key": "cnh_min_cup_depth", "label": "컵 최소 하락 깊이", "type": "number",
         "default": 0.08, "min": 0.03, "max": 0.20, "step": 0.01,
         "description": "컵 좌측 고점 대비 바닥 최소 하락률 (0.08 = -8%)", "category": "strategy"},
        {"key": "cnh_max_cup_depth", "label": "컵 최대 하락 깊이", "type": "number",
         "default": 0.38, "min": 0.15, "max": 0.60, "step": 0.01,
         "description": "컵 좌측 고점 대비 바닥 최대 하락률 (0.38 = -38%)", "category": "strategy"},
        {"key": "cnh_max_rim_diff", "label": "좌우 림 고점 차이 허용치", "type": "number",
         "default": 0.08, "min": 0.02, "max": 0.15, "step": 0.01,
         "description": "좌우 림 높이 차이 허용 비율 (0.08 = 8% 이내)", "category": "strategy"},
        {"key": "cnh_max_handle_depth_ratio", "label": "컵 깊이 대비 핸들 조정비율 상한", "type": "number",
         "default": 0.50, "min": 0.20, "max": 0.70, "step": 0.05,
         "description": "핸들 조정폭이 컵 깊이에서 차지하는 최대 비율 (0.50 = 50% 이내)", "category": "strategy"},
        {"key": "cnh_vol_breakout_mult", "label": "돌파 확인 거래량 배수", "type": "number",
         "default": 1.3, "min": 1.0, "max": 4.0, "step": 0.1,
         "description": "20일 평균 거래량 대비 돌파 시 최소 거래량 배수 (1.3 = 130%)", "category": "strategy"},
        {"key": "cnh_allow_near_pivot", "label": "피봇 근접 선제 진입 허용", "type": "toggle",
         "default": False, "description": "돌파 완료 전 피봇선 -2% 이내 근접 시 조기 매수 허용 여부", "category": "strategy"},
        {"key": "cnh_use_measured_target", "label": "컵 깊이 기반 목표가(Measured Move) 사용", "type": "toggle",
         "default": True, "description": "고정 익절률 대신 컵의 깊이만큼 상승 목표가를 동적 산출", "category": "strategy"},
    ]

    def evaluate_buy(
        self,
        df: pd.DataFrame,
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
        일봉 데이터를 바탕으로 컵앤핸들 패턴 형성 및 돌파 매수 신호 평가
        """
        # [게이트 1] 보유 종목 및 쿨다운 종목 배제
        if held_codes and code in held_codes:
            return None
        if is_in_cooldown:
            logger.info(f"[{name}({code})] 손절 쿨다운 종목 매수 제외")
            return None

        # 유효 데이터 확인
        if df is None or len(df) < 35:
            return None

        regime = (market_regime or {}).get("regime", "BULL")
        settings = config.get_effective_strategy_settings(self.name, settings or {})
        settings = config.get_effective_settings_for_regime(regime, settings)

        # 시장 국면 약세 차단 확인
        if settings.get("market_regime_block_weak", False) and regime == "BEAR":
            logger.info(f"[{name}({code})] 약세장 신규 매수 차단")
            return None

        last = df.iloc[-1]
        current_price = float(last["close"])
        change_rate = float(last.get("change_rate", 0.0))
        vol_ma20 = float(last["vol_ma20"]) if "vol_ma20" in last and not pd.isna(last["vol_ma20"]) else 0.0
        adj_volume = float(last["adjusted_volume"]) if "adjusted_volume" in last and not pd.isna(last["adjusted_volume"]) else float(last["volume"])

        # 파라미터 추출
        min_cup_bars = int(settings.get("cnh_min_cup_bars", 20))
        max_cup_bars = int(settings.get("cnh_max_cup_bars", 80))
        min_handle_bars = int(settings.get("cnh_min_handle_bars", 3))
        max_handle_bars = int(settings.get("cnh_max_handle_bars", 20))
        min_cup_depth = float(settings.get("cnh_min_cup_depth", 0.08))
        max_cup_depth = float(settings.get("cnh_max_cup_depth", 0.38))
        max_rim_diff = float(settings.get("cnh_max_rim_diff", 0.08))
        max_handle_depth_ratio = float(settings.get("cnh_max_handle_depth_ratio", 0.50))
        vol_breakout_mult = float(settings.get("cnh_vol_breakout_mult", 1.3))
        allow_near_pivot = bool(settings.get("cnh_allow_near_pivot", False))

        # [게이트 2] 컵앤핸들 패턴 탐지
        pattern = detect_cup_and_handle(
            df=df,
            min_cup_bars=min_cup_bars,
            max_cup_bars=max_cup_bars,
            min_handle_bars=min_handle_bars,
            max_handle_bars=max_handle_bars,
            min_cup_depth=min_cup_depth,
            max_cup_depth=max_cup_depth,
            max_rim_diff=max_rim_diff,
            max_handle_depth_ratio=max_handle_depth_ratio,
            vol_breakout_mult=vol_breakout_mult,
        )

        if not pattern or not pattern.get("is_pattern", False):
            return None

        # [게이트 3] 진입 타이밍 확인 (돌파 완료 or 근접 허용)
        is_breakout = pattern.get("is_breakout", False)
        status = pattern.get("status", "")

        if not is_breakout:
            if not (allow_near_pivot and status == "near_pivot"):
                # 돌파하지 않았고 선제 진입 미허용 시 패스
                return None

        # [게이트 4] 거래량 확인 (돌파 시 필수 수급 확인)
        vol_confirmed = pattern.get("vol_confirmed", False)
        vol_ratio = pattern.get("vol_ratio", 1.0)
        if is_breakout and not vol_confirmed:
            # 거래량 없는 속임수 돌파 필터링 (최소 100% 이상은 되어야 함)
            if vol_ratio < 1.0:
                return None

        # -------------------------------------------------------------
        # 점수 산출
        # -------------------------------------------------------------
        base_score = int(pattern.get("score", 70))
        reasons = []

        status_text = "🚀 피봇 저항선 돌파 완료" if is_breakout else "🎯 피봇 저항선 근접 (선제 진입)"
        reasons.append(f"🏆 컵앤핸들 패턴 포착: {status_text} (패턴 점수 {base_score}점)")
        reasons.append(f"📊 {pattern.get('description', '')}")

        total_score = base_score

        # 거래량 폭발 가산점
        if vol_ratio >= 2.0:
            total_score += 10
            reasons.append(f"🔥 대량 수급 폭발 (20일 평균 대비 {vol_ratio*100:.0f}%, +10점)")
        elif vol_ratio >= 1.5:
            total_score += 5
            reasons.append(f"⚡ 견조한 돌파 수급 (20일 평균 대비 {vol_ratio*100:.0f}%, +5점)")

        # 시장 국면 가산점
        if regime == "BULL":
            total_score += 5
            reasons.append("📈 상승장 추세 모멘텀 시너지 (+5점)")

        # 이동평균선 정배열 보너스 (20 > 60)
        ma20_val = float(last["ma20"]) if "ma20" in last and not pd.isna(last["ma20"]) else 0.0
        ma60_val = float(last["ma60"]) if "ma60" in last and not pd.isna(last["ma60"]) else 0.0
        if ma20_val > ma60_val > 0:
            total_score += 5
            reasons.append("📐 20일선-60일선 중기 정배열 안착 (+5점)")

        # 외인/기관 수급 반영
        if kwargs.get("investor_data"):
            inv = kwargs["investor_data"]
            f_buy = inv.get("foreign_buy", False)
            i_buy = inv.get("inst_buy", False)
            if f_buy and i_buy:
                total_score += 10
                reasons.append("💎 외국인/기관 메이저 쌍끌이 순매수 유입 (+10점)")
            elif f_buy or i_buy:
                total_score += 5
                reasons.append("💼 기관/외국인 수급 유입 (+5점)")

        # 종합 진입 점수 판별
        buy_threshold = float(settings.get("buy_score_threshold", 65))
        if total_score >= buy_threshold:
            default_budget = float(settings.get("max_buy_budget_per_stock", 500000.0))
            budget_val = budget if budget is not None else default_budget
            atr_val = float(last["atr"]) if "atr" in last and not pd.isna(last["atr"]) else 0.0

            qty = self.calculate_position_size(current_price, budget_val, atr_val=atr_val, settings=settings)
            total_est = qty * current_price

            use_measured = bool(settings.get("cnh_use_measured_target", True))
            target_price = float(pattern.get("target_price", current_price * 1.10)) if use_measured else current_price * (1 + float(settings.get("target_profit_rate", 0.10)))
            stop_loss_price = float(pattern.get("stop_loss_price", current_price * 0.95))

            result = {
                "code": code,
                "name": name,
                "current_price": current_price,
                "change_rate": change_rate,
                "score": min(100, total_score),
                "strategy": self.name,
                "strategy_name": self.name,
                "trend_score": 35,
                "supply_score": 30,
                "momentum_score": 35,
                "supply_gate_passed": True,
                "adjusted_volume": adj_volume,
                "vol_ma20": vol_ma20,
                "vol_ratio": vol_ratio * 100,
                "reasons": reasons,
                "recommended_qty": qty,
                "estimated_amount": total_est,
                "rsi": float(last.get("rsi14", 50.0)),
                "ma5": float(last.get("ma5", current_price)),
                "ma20": ma20_val,
                "ma60": ma60_val,
                "atr": atr_val,
                "pattern_info": {
                    "pattern_name": "Cup and Handle",
                    "status": status,
                    "pivot_price": pattern.get("pivot_price"),
                    "cup_depth_pct": pattern.get("cup_depth_pct"),
                    "handle_depth_pct": pattern.get("handle_depth_pct"),
                    "target_price": target_price,
                    "stop_loss_price": stop_loss_price,
                    "risk_reward_ratio": pattern.get("risk_reward_ratio", 2.0),
                }
            }
            logger.info(f"[{name}({code})] 컵앤핸들 매수 추천 확정 (점수: {total_score}점, 피봇: {pattern.get('pivot_price')}원)")
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
        컵앤핸들 종목 매도 신호 평가
        - 1. 긴급 손절 (핸들 저점 이탈 or ATR 기반 동적 손절)
        - 2. Measured Move 목표가 도달 시 1차 분할 익절 (50%)
        - 3. 1차 익절 후 잔여분 트레일링 스탑 (추세 극대화)
        - 4. 타임컷 청산 (돌파 후 지지부진 시)
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

        # 1. 긴급 손절 (ATR 손절 또는 기본 손절률)
        base_sl_rate = (stop_loss_rate if stop_loss_rate is not None else float(settings.get("stop_loss_rate", -0.05))) * 100
        effective_sl = base_sl_rate

        if settings.get("atr_stop_loss_enabled", True) and df is not None and len(df) >= 20:
            last = df.iloc[-1]
            atr_val = float(last["atr"]) if "atr" in last and not pd.isna(last["atr"]) else 0.0
            if atr_val > 0 and avg_buy_price > 0:
                atr_mul = float(settings.get("atr_stop_loss_multiple", 2.0))
                calc_stop_price = avg_buy_price - (atr_mul * atr_val)
                calc_rate = ((calc_stop_price - avg_buy_price) / avg_buy_price) * 100
                effective_sl = max(-7.0, min(-3.5, calc_rate))

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
                "reasons": [f"🚨 컵앤핸들 돌파 실패 지지선 이탈 손절 ({profit_rate:+.2f}% <= {effective_sl:.1f}%) - 전량 매도"],
                "is_urgent": True
            }

        # 2. 1차 목표가 익절 (기본 +10% 또는 Measured Move)
        tp_rate = (target_profit_rate if target_profit_rate is not None else float(settings.get("target_profit_rate", 0.10))) * 100
        if profit_rate >= tp_rate and not is_partial_sold:
            partial_ratio = float(settings.get("partial_sell_ratio", 0.5))
            sell_qty = max(1, int(holding_qty * partial_ratio)) if holding_qty > 1 else holding_qty
            sell_ratio = partial_ratio if holding_qty > 1 else 1.0
            return {
                "code": code,
                "name": name,
                "holding_qty": holding_qty,
                "sell_qty": sell_qty,
                "sell_ratio": sell_ratio,
                "sell_type": f"{int(sell_ratio*100)}% 1차익절" if sell_ratio < 1.0 else "전량익절",
                "avg_buy_price": avg_buy_price,
                "current_price": current_price,
                "profit_rate": profit_rate,
                "profit_loss": profit_loss,
                "reasons": [f"🎯 컵앤핸들 돌파 1차 목표가 달성 (+{profit_rate:.2f}% >= +{tp_rate:.1f}%) - {int(sell_ratio*100)}% 분할 익절"],
                "is_urgent": False,
                "is_partial_take": True
            }

        # 3. 1차 익절 후 잔여분 트레일링 스탑
        if is_partial_sold:
            high_bench = highest_price if highest_price is not None and highest_price > 0 else max(avg_buy_price, current_price)
            trailing_pct = float(settings.get("trailing_stop_pct", 0.05))
            trailing_price = high_bench * (1 - trailing_pct)

            if current_price <= trailing_price and high_bench > avg_buy_price * 1.03:
                return {
                    "code": code,
                    "name": name,
                    "holding_qty": holding_qty,
                    "sell_qty": holding_qty,
                    "sell_ratio": 1.0,
                    "sell_type": "트레일링스탑 청산",
                    "avg_buy_price": avg_buy_price,
                    "current_price": current_price,
                    "profit_rate": profit_rate,
                    "profit_loss": profit_loss,
                    "reasons": [f"🛡️ 최고가({high_bench:,.0f}원) 대비 -{trailing_pct*100:.1f}% 하락 트레일링스탑 청산 (수익률 {profit_rate:+.2f}%)"],
                    "is_urgent": False
                }

        # 4. 타임컷 (Time-based Cut): 돌파 후 일정 기간 내 탄력 미발생 시
        time_stop_on = bool(settings.get("time_stop_enabled", True))
        max_days = int(settings.get("time_stop_days", 10))
        min_p = float(settings.get("time_stop_min_profit", 0.02)) * 100

        if time_stop_on and holding_days >= max_days and profit_rate < min_p:
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
                "reasons": [f"⏰ 보유 {holding_days}일 경과 돌파 모멘텀 둔화 (수익률 {profit_rate:+.2f}% < {min_p:.1f}%) - 자금 회수 매도"],
                "is_urgent": False
            }

        return None
