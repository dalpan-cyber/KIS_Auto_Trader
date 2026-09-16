"""
KIS Auto Trading - Momentum Strategy
모멘텀/추세추종 전략 (기존 core/strategy.py 로직 이전)
15:10 종가 매수 신호(안전 게이트/수급 게이트/점수 카테고리 캡/눌림목 가산점) 및
실시간 리스크 관리(동적 ATR 손절 / 50% 추세 분할 익절 / 20일선 트레일링 스탑 / 타임컷 12일) 평가 엔진
"""
import logging
from typing import Dict, Any, Optional, Set
import pandas as pd

import app_config as config
from core.strategy.base import BaseStrategy
from core.strategy import register_strategy

logger = logging.getLogger("MomentumStrategy")


@register_strategy
class MomentumStrategy(BaseStrategy):
    """모멘텀/추세추종 전략 - 기존 core/strategy.py 로직"""

    name = "momentum"
    display_name = "모멘텀 추세추종"
    description = "이동평균 정배열, 거래량 급증, RSI/볼린저 모멘텀 기반 매수 및 ATR 동적 손절/분할 익절 매도"

    # =========================================================================
    # 전략별 설정 스키마
    # - category='common': 모든 전략이 공유하는 공통 설정 (시장 국면 프리셋에서 관리)
    # - category='strategy': 이 전략만의 고유 설정 (전략별로 독립 저장)
    # =========================================================================
    settings_schema = [
        # --- 공통 설정 (시장 국면 프리셋에서 관리) ---
        {"key": "target_profit_rate", "label": "목표 익절 수익률", "type": "number",
         "default": 0.08, "min": 0.01, "max": 1.00, "step": 0.01,
         "description": "목표 익절 수익률 (예: 0.08 = +8%)", "category": "common"},
        {"key": "stop_loss_rate", "label": "손절 기준 수익률", "type": "number",
         "default": -0.05, "min": -0.50, "max": -0.01, "step": 0.01,
         "description": "손절 기준 수익률 (예: -0.05 = -5%)", "category": "common"},
        {"key": "trailing_stop_pct", "label": "트레일링 스탑 비율", "type": "number",
         "default": 0.06, "min": 0.01, "max": 0.20, "step": 0.005,
         "description": "1차 익절 후 최고가 대비 트레일링 스탑 비율 (예: 0.06 = 6.0%)", "category": "common"},
        {"key": "time_stop_enabled", "label": "타임컷 청산 활성화", "type": "toggle",
         "default": True, "description": "타임컷 청산 활성화 여부", "category": "common"},
        {"key": "time_stop_days", "label": "타임컷 보유 일수", "type": "number",
         "default": 12, "min": 1, "max": 30, "step": 1,
         "description": "타임컷 보유 일수 (영업일 기준)", "category": "common"},
        {"key": "time_stop_min_profit", "label": "타임컷 기준 최소 수익률", "type": "number",
         "default": 0.02, "min": 0.0, "max": 0.20, "step": 0.005,
         "description": "타임컷 기준 최소 수익률 (예: 0.02 = +2%)", "category": "common"},
        {"key": "max_daily_buy_count", "label": "1일 최대 신규 매수 종목 수", "type": "number",
         "default": 3, "min": 1, "max": 10, "step": 1,
         "description": "1일 최대 신규 매수 종목 수 (집단 갭하락 리스크 방어)", "category": "common"},
        {"key": "partial_sell_ratio", "label": "1차 익절 시 매도 비율", "type": "number",
         "default": 0.5, "min": 0.1, "max": 1.0, "step": 0.1,
         "description": "1차 익절 시 매도 비율 (0.5 = 50%)", "category": "common"},
        {"key": "rsi_overbought_sell", "label": "RSI 과열 시 전량 매도", "type": "toggle",
         "default": False, "description": "RSI 75 초과 시 전량 매도 (체크 해제 시 50% 분할 매도)", "category": "common"},
        {"key": "market_regime_filter_enabled", "label": "시장 국면 필터 활성화", "type": "toggle",
         "default": True, "description": "시장 국면 필터 활성화 여부", "category": "common"},
        {"key": "use_futures_filter", "label": "개별주식선물 수급 분석 활성화", "type": "toggle",
         "default": True, "description": "개별주식선물 베이시스 및 미결제약정 수급 4번째 점수군(최대 20점) 반영 여부", "category": "common"},
        {"key": "market_regime_cutoff_normal", "label": "정상 국면 매수 점수 컷오프", "type": "number",
         "default": 60, "min": 0, "max": 100, "step": 1,
         "description": "정상/상승 국면 매수 점수 컷오프 (100점 만점 기준)", "category": "common"},
        {"key": "market_regime_cutoff_weak", "label": "약세 국면 매수 점수 컷오프", "type": "number",
         "default": 75, "min": 0, "max": 100, "step": 1,
         "description": "약세/하락 국면 매수 점수 컷오프 (100점 만점 기준)", "category": "common"},
        {"key": "market_regime_block_weak", "label": "약세 국면 신규 진입 차단", "type": "toggle",
         "default": False, "description": "약세 국면 신규 진입 전면 차단 여부", "category": "common"},
        {"key": "cooldown_enabled", "label": "손절 쿨다운 활성화", "type": "toggle",
         "default": True, "description": "손절 종목 재매수 쿨다운 활성화", "category": "common"},
        {"key": "cooldown_days", "label": "손절 후 재매수 금지 기간", "type": "number",
         "default": 4, "min": 1, "max": 20, "step": 1,
         "description": "손절 후 재매수 금지 기간 (거래일 기준)", "category": "common"},
        {"key": "atr_stop_loss_enabled", "label": "ATR 동적 손절 활성화", "type": "toggle",
         "default": True, "description": "ATR 기반 동적 손절 활성화", "category": "common"},
        {"key": "atr_stop_loss_multiple", "label": "ATR 손절 배수", "type": "number",
         "default": 2.2, "min": 1.0, "max": 5.0, "step": 0.1,
         "description": "ATR 손절 배수 (진입가 - N×ATR)", "category": "common"},
        {"key": "atr_stop_loss_min_pct", "label": "ATR 손절 최소 허용 손실률", "type": "number",
         "default": -0.055, "min": -0.20, "max": -0.01, "step": 0.005,
         "description": "ATR 손절 최소 허용 손실률 (하한, 예: -0.055 = -5.5%)", "category": "common"},
        {"key": "atr_stop_loss_max_pct", "label": "ATR 손절 최대 허용 손실률", "type": "number",
         "default": -0.035, "min": -0.10, "max": -0.005, "step": 0.005,
         "description": "ATR 손절 최대 허용 손실률 (상한, 예: -0.035 = -3.5%)", "category": "common"},
        {"key": "atr_stop_loss_use_low_break", "label": "당일 저가 이탈 시 손절 적용", "type": "toggle",
         "default": True, "description": "당일 저가 이탈 시 손절 적용 여부", "category": "common"},
        {"key": "volatility_sizing_enabled", "label": "변동성 기반 포지션 사이징", "type": "toggle",
         "default": True, "description": "ATR 기반 변동성 조절 포지션 사이징 활성화", "category": "common"},
        {"key": "risk_per_trade", "label": "1회 거래당 리스크 비율", "type": "number",
         "default": 0.01, "min": 0.001, "max": 0.10, "step": 0.005,
         "description": "1회 거래당 리스크 비율 (계좌 대비)", "category": "common"},
        {"key": "atr_stop_multiple", "label": "포지션 사이징 ATR 손절 배수", "type": "number",
         "default": 2.2, "min": 1.0, "max": 5.0, "step": 0.5,
         "description": "포지션 사이징 ATR 손절 배수", "category": "common"},
        {"key": "max_position_ratio", "label": "1종목당 최대 포지션 비율", "type": "number",
         "default": 0.3, "min": 0.05, "max": 1.0, "step": 0.05,
         "description": "1종목당 최대 포지션 비율 (계좌 대비)", "category": "common"},
        {"key": "min_position_ratio", "label": "1종목당 최소 포지션 비율", "type": "number",
         "default": 0.05, "min": 0.01, "max": 0.5, "step": 0.01,
         "description": "1종목당 최소 포지션 비율 (계좌 대비)", "category": "common"},
        {"key": "score_cap_trend", "label": "추세군 최대 점수", "type": "number",
         "default": 40, "min": 10, "max": 60, "step": 5,
         "description": "추세군(이동평균) 최대 점수 상한", "category": "common"},
        {"key": "score_cap_momentum", "label": "모멘텀군 최대 점수", "type": "number",
         "default": 30, "min": 10, "max": 50, "step": 5,
         "description": "모멘텀군(RSI, 볼린저) 최대 점수 상한", "category": "common"},
        {"key": "score_cap_volume", "label": "거래량군 최대 점수", "type": "number",
         "default": 25, "min": 10, "max": 50, "step": 5,
         "description": "거래량군 최대 점수 상한", "category": "common"},
        {"key": "buy_score_threshold", "label": "매수 추천 최소 종합 점수", "type": "number",
         "default": 45, "min": 0, "max": 100, "step": 1,
         "description": "매수 추천 최소 종합 점수 (45점 이상 추천)", "category": "common"},
        {"key": "max_buy_budget_per_stock", "label": "1종목당 최대 매수 예산", "type": "number",
         "default": 500000, "min": 10000, "max": 100000000, "step": 50000,
         "description": "1종목당 최대 매수 예산 (원)", "category": "common"},
        {"key": "max_holding_stocks", "label": "최대 동시 보유 종목 수", "type": "number",
         "default": 5, "min": 1, "max": 30, "step": 1,
         "description": "최대 동시 보유 종목 수", "category": "common"},
        {"key": "use_realtime_candle", "label": "실시간 봉 반영", "type": "toggle",
         "default": False, "description": "실시간 현재가를 일봉에 반영 (True: 실시간 15:10 캔들 합성, False: 전일 완성봉)", "category": "common"},

        # --- 전략 고유 설정 (전략별로 독립 저장) ---
        {"key": "momentum_ma_fast", "label": "빠른 이동평균 기간", "type": "number",
         "default": 5, "min": 3, "max": 20, "step": 1,
         "description": "빠른 이동평균 기간 (골든크로스 판단용)", "category": "strategy"},
        {"key": "momentum_ma_slow", "label": "느린 이동평균 기간", "type": "number",
         "default": 20, "min": 10, "max": 60, "step": 1,
         "description": "느린 이동평균 기간 (골든크로스 판단용)", "category": "strategy"},
        {"key": "momentum_volume_ratio_min", "label": "거래량 급증 최소 배수", "type": "number",
         "default": 1.3, "min": 1.0, "max": 3.0, "step": 0.1,
         "description": "수급 게이트 통과를 위한 거래량 급증 최소 배수 (1.3 = 130%)", "category": "strategy"},
        {"key": "momentum_volume_ratio_max", "label": "거래량 급증 최대 배수", "type": "number",
         "default": 4.0, "min": 2.0, "max": 10.0, "step": 0.5,
         "description": "수급 게이트 통과를 위한 거래량 급증 최대 배수 (4.0 = 400%)", "category": "strategy"},
        {"key": "momentum_rsi_buy_low", "label": "RSI 저평가 매수 하한", "type": "number",
         "default": 30, "min": 10, "max": 50, "step": 1,
         "description": "RSI 저평가 반등 구간 하한", "category": "strategy"},
        {"key": "momentum_rsi_buy_high", "label": "RSI 저평가 매수 상한", "type": "number",
         "default": 45, "min": 20, "max": 60, "step": 1,
         "description": "RSI 저평가 반등 구간 상한", "category": "strategy"},
        {"key": "momentum_rsi_momentum_high", "label": "RSI 상승 탄력 상한", "type": "number",
         "default": 65, "min": 50, "max": 80, "step": 1,
         "description": "RSI 상승 탄력 유지 구간 상한", "category": "strategy"},
        {"key": "momentum_rsi_overheat", "label": "RSI 과열 매도 기준", "type": "number",
         "default": 78, "min": 70, "max": 95, "step": 1,
         "description": "RSI 과열 매도 기준 (이 값 초과 시 분할 익절)", "category": "strategy"},
        {"key": "momentum_high_chase_ma5_pct", "label": "5일선 이격 과열 기준", "type": "number",
         "default": 0.03, "min": 0.01, "max": 0.10, "step": 0.005,
         "description": "5일선 대비 이격도 과열 기준 (3% 초과 시 고점 추격 차단)", "category": "strategy"},
        {"key": "momentum_high_chase_ma20_pct", "label": "20일선 이격 과열 기준", "type": "number",
         "default": 0.06, "min": 0.02, "max": 0.15, "step": 0.005,
         "description": "20일선 대비 이격도 과열 기준 (6% 초과 시 고점 추격 차단)", "category": "strategy"},
        {"key": "momentum_upper_shadow_ratio", "label": "윗꼬리 허용 비율", "type": "number",
         "default": 0.40, "min": 0.10, "max": 0.60, "step": 0.05,
         "description": "윗꼬리 매물 출회 차단 기준 (윗꼬리/전체 범위 비율)", "category": "strategy"},
        {"key": "momentum_supply_score_base", "label": "수급 게이트 기본 점수", "type": "number",
         "default": 15, "min": 5, "max": 25, "step": 1,
         "description": "수급 게이트 통과 시 기본 점수", "category": "strategy"},
        {"key": "momentum_supply_score_bonus", "label": "대량 거래량 보너스 점수", "type": "number",
         "default": 10, "min": 0, "max": 20, "step": 1,
         "description": "거래량 200% 이상 시 추가 보너스 점수", "category": "strategy"},
        {"key": "momentum_trend_golden_cross_score", "label": "골든크로스 점수", "type": "number",
         "default": 20, "min": 5, "max": 30, "step": 1,
         "description": "5일선-20일선 골든크로스 발생 시 점수", "category": "strategy"},
        {"key": "momentum_trend_alignment_score", "label": "정배열 점수", "type": "number",
         "default": 15, "min": 5, "max": 25, "step": 1,
         "description": "이동평균 정배열(MA5 > MA20 > MA60) 시 점수", "category": "strategy"},
        {"key": "momentum_trend_above_ma20_score", "label": "20일선 상회 점수", "type": "number",
         "default": 10, "min": 5, "max": 20, "step": 1,
         "description": "종가가 20일선 상회 시 점수", "category": "strategy"},
        {"key": "momentum_pullback_support_score", "label": "눌림목 지지 반등 점수", "type": "number",
         "default": 10, "min": 0, "max": 20, "step": 1,
         "description": "5일/20일선 눌림목 지지 반등 시 가산점", "category": "strategy"},
        {"key": "momentum_bb_lower_rebound_score", "label": "볼린저 하단 반등 점수", "type": "number",
         "default": 15, "min": 5, "max": 25, "step": 1,
         "description": "볼린저 하단 밴드 터치 후 지지 반등 시 점수", "category": "strategy"},
        {"key": "momentum_rsi_low_rebound_score", "label": "RSI 저평가 반등 점수", "type": "number",
         "default": 15, "min": 5, "max": 25, "step": 1,
         "description": "RSI 저평가 반등 구간 시 점수", "category": "strategy"},
        {"key": "momentum_rsi_momentum_score", "label": "RSI 상승 탄력 점수", "type": "number",
         "default": 10, "min": 5, "max": 20, "step": 1,
         "description": "RSI 상승 탄력 유지 구간 시 점수", "category": "strategy"},
        {"key": "use_investor_filter", "label": "메이저 수급 반영 활성화", "type": "toggle",
         "default": True, "description": "외인·기관 순매수 가점 및 쌍끌이 순매도 탈락 필터", "category": "strategy"},
        {"key": "investor_double_buy_score", "label": "쌍끌이 순매수 가점", "type": "number",
         "default": 8, "min": 0, "max": 15, "step": 1,
         "description": "외인·기관 동반 순매수 시 가산점", "category": "strategy"},
        {"key": "investor_single_buy_score", "label": "단독 순매수 가점", "type": "number",
         "default": 4, "min": 0, "max": 10, "step": 1,
         "description": "외인 또는 기관 단독 순매수 시 가산점", "category": "strategy"},
        {"key": "use_volume_power_gate", "label": "체결강도 안전 게이트 활성화", "type": "toggle",
         "default": True, "description": "15:10 진입 시점 당일 실시간 체결강도 검증", "category": "strategy"},
        {"key": "min_volume_power", "label": "최소 체결강도 기준 (%)", "type": "number",
         "default": 110.0, "min": 50.0, "max": 200.0, "step": 5.0,
         "description": "매수 추천을 위한 최소 체결강도 (%)", "category": "strategy"},
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
        extra_data: Optional[Dict[str, Any]] = None,
        investor_data: Optional[Dict[str, Any]] = None,
        volume_power: Optional[float] = None,
        **kwargs
    ) -> Optional[Dict[str, Any]]:
        """
        계산된 기술적 보조지표 DataFrame을 바탕으로 매수 점수 및 안전/수급/눌림목 게이트 평가
        - return_raw_eval: True일 경우 게이트 탈락 시에도 탈락 사유와 종합 점수를 계산하여 반환
        """
        if df is None or len(df) < 20:
            return None

        # extra_data 내부 데이터 추출 호환성
        if isinstance(extra_data, dict):
            investor_data = investor_data or extra_data.get("investor_trend")
            if volume_power is None and "volume_power" in extra_data:
                volume_power = extra_data.get("volume_power")

        # Mock 및 비정상 타입 방어 변환
        if volume_power is not None and not isinstance(volume_power, (int, float)):
            try:
                volume_power = float(volume_power)
            except Exception:
                volume_power = None

        if investor_data is not None and not isinstance(investor_data, dict):
            investor_data = None

        regime = (market_regime or {}).get("regime", "BULL")
        # 전략별 고유 설정을 전역 설정에 병합한 후, 시장 국면 프리셋 적용
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
        disqualify_reason: Optional[str] = None

        # -------------------------------------------------------------
        # [시장 국면 필터] 약세/하락 국면 시 매수 점수 컷오프 상향 또는 전면 차단
        # -------------------------------------------------------------
        if settings.get("market_regime_filter_enabled", True) and regime == "BEAR":
            if settings.get("market_regime_block_weak", False):
                logger.info(f"[{name}({code})] 약세 시장 국면 - 신규 진입 전면 차단")
                disqualify_reason = "약세 시장 국면 - 신규 진입 차단"
                if not return_raw_eval:
                    return None
            reasons.append("⚠️ 약세/하락 시장 국면 - 방어적 매수 점수 컷오프 상향 적용")

        # -------------------------------------------------------------
        # [손절 쿨다운] 손절 청산 종목 재매수 금지
        # -------------------------------------------------------------
        if is_in_cooldown:
            logger.info(f"[{name}({code})] 손절 쿨다운 기간 내 - 재매수 차단")
            disqualify_reason = "손절 후 쿨다운 기간"
            if not return_raw_eval:
                return None

        # -------------------------------------------------------------
        # [개선 3: 고점 추격 매수 방지 & 안전 게이트 1] 이격도 과열 방지
        # -------------------------------------------------------------
        ma5_val = float(last["ma5"]) if not pd.isna(last["ma5"]) else current_price
        ma20_val = float(last["ma20"]) if not pd.isna(last["ma20"]) else current_price

        # 5일선 대비 3% 초과 또는 20일선 대비 6% 초과 시 고점 추격 매수로 판정하여 배제
        high_chase_ma5_pct = float(settings.get("momentum_high_chase_ma5_pct", 0.03))
        high_chase_ma20_pct = float(settings.get("momentum_high_chase_ma20_pct", 0.06))
        if ma5_val > 0 and (current_price / ma5_val) > (1 + high_chase_ma5_pct):
            disqualify_reason = "5일선 이격도 과열 (단기 고점 추격 방지)"
            if not return_raw_eval:
                return None
        if ma20_val > 0 and (current_price / ma20_val) > (1 + high_chase_ma20_pct):
            disqualify_reason = "20일선 이격도 과열 (단기 고점 추격 방지)"
            if not return_raw_eval:
                return None

        # 당일 급등(+4.5% 이상) 종목의 상투 추격 차단
        if change_rate >= 4.5 and ma5_val > 0 and (current_price / ma5_val) > 1.025:
            disqualify_reason = "당일 급등(+4.5% 이상) 상투 추격 차단"
            if not return_raw_eval:
                return None

        # -------------------------------------------------------------
        # [안전 게이트 2] 캔들 형태 필터 (윗꼬리 매물 출회 차단)
        # -------------------------------------------------------------
        total_range = high_price - low_price
        if total_range > 0:
            upper_shadow = high_price - max(open_price, current_price)
            upper_shadow_ratio = float(settings.get("momentum_upper_shadow_ratio", 0.40))
            if (upper_shadow / total_range) >= upper_shadow_ratio:
                disqualify_reason = "윗꼬리 매물 출회 (단기 차익 실현 압력)"
                if not return_raw_eval:
                    return None

        # -------------------------------------------------------------
        # [안전 게이트 3] 체결강도 필터 (Step 3: 당일 실시간 매수세 우위 검증)
        # -------------------------------------------------------------
        use_vp_gate = settings.get("use_volume_power_gate", True)
        min_vp = float(settings.get("min_volume_power", 110.0))
        if use_vp_gate and isinstance(volume_power, (int, float)) and volume_power > 0:
            if volume_power < min_vp:
                disqualify_reason = f"체결강도 미달 ({volume_power:.1f}% < {min_vp:.0f}%)"
                if not return_raw_eval:
                    return None
            else:
                reasons.append(f"💪 실시간 체결강도 우세 ({volume_power:.1f}% >= {min_vp:.0f}%)")

        # -------------------------------------------------------------
        # [안전 게이트 4] 메이저 수급 필터 (Step 1: 외인/기관 쌍끌이 순매도 종목 매수 배제)
        # -------------------------------------------------------------
        use_investor = settings.get("use_investor_filter", True)
        if use_investor and isinstance(investor_data, dict):
            try:
                frgn_qty = int(investor_data.get("foreign_net_buy_qty", 0) or 0)
                orgn_qty = int(investor_data.get("institution_net_buy_qty", 0) or 0)
                is_double_selling = investor_data.get("is_double_selling", (frgn_qty < 0 and orgn_qty < 0))
                if is_double_selling:
                    disqualify_reason = f"외인·기관 쌍끌이 순매도 종목 매수 배제 (외인 {frgn_qty:,}주, 기관 {orgn_qty:,}주)"
                    if not return_raw_eval:
                        return None
            except Exception:
                pass

        # -------------------------------------------------------------
        # 1. 추세군 점수 산출 (그룹 상한: 최대 30점)
        # -------------------------------------------------------------
        raw_trend_score = 0
        golden_cross_score = int(settings.get("momentum_trend_golden_cross_score", 20))
        alignment_score = int(settings.get("momentum_trend_alignment_score", 15))
        above_ma20_score = int(settings.get("momentum_trend_above_ma20_score", 10))
        pullback_score = int(settings.get("momentum_pullback_support_score", 10))

        if prev["ma5"] <= prev["ma20"] and last["ma5"] > last["ma20"]:
            raw_trend_score += golden_cross_score
            reasons.append(f"📈 5일선-20일선 골든크로스 발생 (+{golden_cross_score}점)")
        if last["ma5"] > last["ma20"] and last["ma20"] > last["ma60"]:
            raw_trend_score += alignment_score
            reasons.append(f"📊 이동평균 정배열 지속 (MA5 > MA20 > MA60) (+{alignment_score}점)")
        if last["close"] > last["ma20"]:
            raw_trend_score += above_ma20_score
            reasons.append(f"🟢 20일선 상회 유지 (종가 > MA20) (+{above_ma20_score}점)")

        # [개선 3: 눌림목 지지 반등 가산점] 5일선/20일선 지지 후 첫 반등
        if (low_price <= ma5_val * 1.008 and current_price > ma5_val) or (low_price <= ma20_val * 1.008 and current_price > ma20_val):
            raw_trend_score += pullback_score
            reasons.append(f"⚡ 5일/20일선 눌림목 지지 반등 확인 (+{pullback_score}점)")

        cap_trend = int(settings.get("score_cap_trend", 40))
        trend_score = min(min(30, cap_trend), raw_trend_score)

        # -------------------------------------------------------------
        # 2. 수급군 점수 및 필수 게이트 검증 (그룹 상한: 최대 25점, 필수 게이트)
        # -------------------------------------------------------------
        vol_ma20 = float(last["vol_ma20"]) if not pd.isna(last["vol_ma20"]) else 0.0
        adj_volume = float(last["adjusted_volume"]) if not pd.isna(last["adjusted_volume"]) else float(last["volume"])

        supply_gate_passed = False
        supply_score = 0
        vol_ratio = 0.0

        if vol_ma20 > 0:
            vol_ratio = (adj_volume / vol_ma20) * 100
            # 거래량이 1.3배 이상이면서 4배(400%) 이하 사이만 유효
            vol_ratio_min = float(settings.get("momentum_volume_ratio_min", 1.3))
            vol_ratio_max = float(settings.get("momentum_volume_ratio_max", 4.0))
            supply_base_score = int(settings.get("momentum_supply_score_base", 15))
            supply_bonus_score = int(settings.get("momentum_supply_score_bonus", 10))

            if vol_ratio_min <= (adj_volume / vol_ma20) <= vol_ratio_max:
                supply_gate_passed = True
                raw_supply_score = supply_base_score
                reasons.append(f"🔥 수급 필수 게이트 통과 (전일 20일평균 대비 {vol_ratio:.0f}% 급증) (+{supply_base_score}점)")

                if (adj_volume / vol_ma20) >= 2.0:
                    raw_supply_score += supply_bonus_score
                    reasons.append(f"⚡ 대량 거래량 폭발 (200% 이상) (+{supply_bonus_score}점)")

                # Step 1: 메이저 외인/기관 순매수 가산점
                if use_investor and investor_data:
                    frgn_qty = int(investor_data.get("foreign_net_buy_qty", 0) or 0)
                    orgn_qty = int(investor_data.get("institution_net_buy_qty", 0) or 0)
                    is_double_buying = investor_data.get("is_double_buying", (frgn_qty > 0 and orgn_qty > 0))
                    if is_double_buying:
                        bonus = int(settings.get("investor_double_buy_score", 8))
                        raw_supply_score += bonus
                        reasons.append(f"💎 외인·기관 쌍끌이 순매수 유입 (외인 {frgn_qty:+,}주, 기관 {orgn_qty:+,}주) (+{bonus}점)")
                    elif frgn_qty > 0 or orgn_qty > 0:
                        bonus = int(settings.get("investor_single_buy_score", 4))
                        raw_supply_score += bonus
                        buyer = "외국인" if frgn_qty > 0 else "기관"
                        reasons.append(f"💎 메이저 수급({buyer}) 순매수 유입 (외인 {frgn_qty:+,}주, 기관 {orgn_qty:+,}주) (+{bonus}점)")

                cap_vol = int(settings.get("score_cap_volume", 25))
                supply_score = min(min(25, cap_vol), raw_supply_score)
            else:
                if (adj_volume / vol_ma20) < vol_ratio_min:
                    disqualify_reason = f"거래량 부족 (20일평균 대비 {vol_ratio:.0f}% < {vol_ratio_min*100:.0f}%)"
                    if not return_raw_eval:
                        return None
                elif (adj_volume / vol_ma20) > vol_ratio_max:
                    disqualify_reason = f"거래량 과열 (20일평균 대비 {vol_ratio:.0f}% > {vol_ratio_max*100:.0f}%)"
                    if not return_raw_eval:
                        return None
        else:
            disqualify_reason = "20일 평균 거래량 부족"
            if not return_raw_eval:
                return None

        # -------------------------------------------------------------
        # 3. 모멘텀군 점수 산출 (그룹 상한: 최대 25점)
        # -------------------------------------------------------------
        raw_momentum_score = 0
        rsi = float(last["rsi14"]) if not pd.isna(last["rsi14"]) else 50.0

        rsi_buy_low = float(settings.get("momentum_rsi_buy_low", 30))
        rsi_buy_high = float(settings.get("momentum_rsi_buy_high", 45))
        rsi_momentum_high = float(settings.get("momentum_rsi_momentum_high", 65))
        rsi_low_rebound_score = int(settings.get("momentum_rsi_low_rebound_score", 15))
        rsi_momentum_score = int(settings.get("momentum_rsi_momentum_score", 10))
        bb_rebound_score = int(settings.get("momentum_bb_lower_rebound_score", 15))

        if rsi_buy_low <= rsi <= rsi_buy_high and last["close"] >= last["open"]:
            raw_momentum_score += rsi_low_rebound_score
            reasons.append(f"🎯 RSI({rsi:.1f}) 저평가 반등 구간 (+{rsi_low_rebound_score}점)")
        elif rsi_buy_high < rsi <= rsi_momentum_high:
            raw_momentum_score += rsi_momentum_score
            reasons.append(f"🚀 RSI({rsi:.1f}) 상승 탄력 유지 (+{rsi_momentum_score}점)")

        if prev["close"] <= prev["bb_lower"] and last["close"] > last["bb_lower"]:
            raw_momentum_score += bb_rebound_score
            reasons.append(f"🛡️ 볼린저 하단 밴드 터치 후 지지 반등 (+{bb_rebound_score}점)")

        cap_mom = int(settings.get("score_cap_momentum", 30))
        momentum_score = min(min(25, cap_mom), raw_momentum_score)

        # -------------------------------------------------------------
        # 4. 선행 파생수급군 점수 산출 (그룹 상한: 최대 20점 / 총점 100점 척도)
        # -------------------------------------------------------------
        futures_score = 0
        use_futures = settings.get("use_futures_filter", True)
        has_futures = bool(futures_data and futures_data.get("has_futures"))
        market_basis = 0.0
        oi_change = 0
        is_contango = False
        futures_warning = False

        if use_futures and has_futures:
            market_basis = float(futures_data.get("market_basis", 0.0))
            oi_change = int(futures_data.get("oi_change", 0))
            is_contango = bool(futures_data.get("is_contango", False))
            oi_total = int(futures_data.get("open_interest", 0))

            # 1) 시장 베이시스 (Market Basis = 선물가격 - 현물가격) 평가
            basis_pct = (market_basis / current_price) * 100.0 if current_price > 0 else 0.0
            if market_basis > 0:
                if basis_pct >= 0.2:  # 강력한 콘탱고 (+0.2% 이상)
                    futures_score += 10
                    reasons.append(f"📈 [선물] 강력한 콘탱고(베이시스 +{market_basis:,.0f}원, +{basis_pct:.2f}%) - 선물 프리미엄 현물 견인 (+10점)")
                else:
                    futures_score += 8
                    reasons.append(f"📈 [선물] 콘탱고(베이시스 +{market_basis:,.0f}원) - 매수 우세 (+8점)")
            elif basis_pct <= -0.5:  # 심각한 백워데이션 (-0.5% 이하)
                futures_score -= 5
                reasons.append(f"📉 [선물] 심각한 백워데이션(베이시스 {market_basis:,.0f}원, {basis_pct:.2f}%) - 단기 하락 압력 (-5점)")

            # 2) 미결제약정 증감 (OI Change) 평가
            if change_rate > 0 and oi_change > 0:
                futures_score += 10
                reasons.append(f"🔥 [선물] 주가 상승 동반 미결제약정 증가(+{oi_change:,}계약) - 신규 롱포지션 진입 확인 (+10점)")
            elif change_rate > 0 and oi_change < 0:
                reasons.append(f"⚠️ [선물] 주가 상승 중 미결제약정 감소({oi_change:,}계약) - 단순 숏커버링 반등 가능성 (+0점)")
            elif change_rate < 0 and oi_change > 0:
                reasons.append(f"⚠️ [선물] 주가 하락 중 미결제약정 증가(+{oi_change:,}계약) - 신규 숏포지션 공세 (+0점)")

            # 3) 킬스위치 / 선물 역행 필터 (Kill-switch)
            if change_rate >= 2.0 and (basis_pct <= -0.4 or (oi_change < -5000 and oi_total > 0 and (abs(oi_change) / oi_total) >= 0.05)):
                futures_warning = True
                futures_score -= 10
                reasons.append("🚨 [선물 역행 경고] 현물 급등 대비 선물 시장 역행/수급 이탈 감지 (가짜 상승 주의, -10점)")

            # 그룹 상한 캡 (0점 ~ 20점)
            futures_score = max(0, min(20, futures_score))
            total_score = trend_score + supply_score + momentum_score + futures_score
        else:
            # 개별주식선물이 미상장된 종목 (중소형주 등) 또는 데이터 미조회 시
            # 기존 3개 카테고리 합계(최대 80점 만점 기준)를 100점 만점으로 비례 환산
            raw_score = trend_score + supply_score + momentum_score
            total_score = round(min(100.0, raw_score * (100.0 / 80.0)), 1)
            reasons.append("ℹ️ 개별주식선물 미상장 종목 (기본 80점 척도를 100점 만점으로 비례 환산)")

        # -------------------------------------------------------------
        # 5. 종합 진입 조건 판별 (시장 국면별 컷오프 적용, 100점 만점 척도)
        # -------------------------------------------------------------
        if settings.get("market_regime_filter_enabled", True) and regime == "WEAK":
            buy_threshold = float(settings.get("market_regime_cutoff_weak", 75))
        else:
            buy_threshold = float(settings.get("market_regime_cutoff_normal", settings.get("buy_score_threshold", 60)))

        is_recommended = bool(
            total_score >= buy_threshold
            and supply_gate_passed
            and not disqualify_reason
        )

        if not is_recommended and not return_raw_eval:
            return None

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
            "trend_score": trend_score,
            "supply_score": supply_score,
            "momentum_score": momentum_score,
            "futures_score": futures_score if (use_futures and has_futures) else None,
            "has_futures": has_futures,
            "market_basis": market_basis if (use_futures and has_futures) else None,
            "oi_change": oi_change if (use_futures and has_futures) else None,
            "is_contango": is_contango if (use_futures and has_futures) else None,
            "futures_warning": futures_warning,
            "supply_gate_passed": supply_gate_passed,
            "adjusted_volume": adj_volume,
            "vol_ma20": vol_ma20,
            "vol_ratio": round(vol_ratio, 1),
            "reasons": reasons,
            "recommended_qty": qty,
            "estimated_amount": total_est,
            "rsi": round(float(rsi), 1) if not pd.isna(rsi) else None,
            "ma5": round(ma5_val, 0),
            "ma20": round(ma20_val, 0),
            "ma60": round(float(last["ma60"]), 0) if not pd.isna(last["ma60"]) else 0.0,
            "atr": round(atr_val, 0),
            "market_regime": regime,
            "buy_threshold": buy_threshold,
            "volume_power": round(float(volume_power), 1) if volume_power is not None else None,
            "investor_trend": investor_data,
            "is_recommended": is_recommended,
            "disqualify_reason": disqualify_reason or (f"매수 점수 기준 미달 ({total_score}점 < {buy_threshold}점)" if not is_recommended else None)
        }

        if is_additional_buy:
            result["is_additional_buy"] = True
            result["buy_type"] = "추가매수"
            result["reasons"] = ["📌 현재 보유 종목 추가매수 추천"] + reasons
        else:
            result["is_additional_buy"] = False
            result["buy_type"] = "신규매수"

        return result

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
        보유 종목의 수익률 및 지표 기반 매도 판단
        [개선 1: 대세상승장 추세추종 익절 +8~10% 및 20일선 트레일링 스탑]
        [개선 2: 동적 ATR 기반 손절선 유연화 (-4.5~-5.5% 휩쏘 방지)]
        [개선 4: 타임컷 12거래일 연장]
        """
        regime = (market_regime or {}).get("regime", "BULL")
        # 전략별 고유 설정을 전역 설정에 병합한 후, 시장 국면 프리셋 적용
        settings = config.get_effective_strategy_settings(self.name, settings or {})
        settings = config.get_effective_settings_for_regime(regime, settings)

        code = holding.get("code")
        name = holding.get("name", code)
        profit_rate = float(holding.get("profit_rate", 0.0))
        current_price = float(holding.get("current_price", 0.0))
        holding_qty = int(holding.get("quantity", holding.get("qty", 0)))
        avg_buy_price = float(holding.get("avg_buy_price", 0.0))
        profit_loss = float(holding.get("profit_loss", 0.0))

        # -------------------------------------------------------------
        # [개선 1: 목표 익절 수익률 대세상승장 확장 (+8.0%)]
        # -------------------------------------------------------------
        if target_profit_rate is not None:
            tp_rate = target_profit_rate * 100
        else:
            default_tp = float(settings.get("target_profit_rate", 0.08))
            if regime == "STRONG":
                tp_rate = max(8.0, default_tp * 100)
            else:
                tp_rate = default_tp * 100

        # -------------------------------------------------------------
        # [개선 2: 동적 ATR 기반 손절선 유연화 (-4.5% ~ -5.5% 휩쏘 필터링)]
        # -------------------------------------------------------------
        base_sl_rate = (stop_loss_rate if stop_loss_rate is not None else float(settings.get("stop_loss_rate", -0.05))) * 100

        atr_stop_price = None
        atr_stop_rate = None
        if settings.get("atr_stop_loss_enabled", True) and df is not None and len(df) >= 20:
            last = df.iloc[-1]
            atr_val = float(last["atr"]) if "atr" in last and not pd.isna(last["atr"]) else 0.0
            if atr_val > 0 and avg_buy_price > 0:
                atr_multiple = float(settings.get("atr_stop_loss_multiple", 2.2))
                calc_stop_price = avg_buy_price - (atr_multiple * atr_val)
                calc_rate = ((calc_stop_price - avg_buy_price) / avg_buy_price) * 100

                min_pct = float(settings.get("atr_stop_loss_min_pct", -0.055)) * 100
                max_pct = float(settings.get("atr_stop_loss_max_pct", -0.035)) * 100
                atr_stop_rate = max(min_pct, min(max_pct, calc_rate))
                atr_stop_price = avg_buy_price * (1 + atr_stop_rate / 100)

                if settings.get("atr_stop_loss_use_low_break", True):
                    low_price = float(last.get("low", current_price))
                    if low_price < atr_stop_price:
                        atr_stop_price = low_price
                        atr_stop_rate = ((low_price - avg_buy_price) / avg_buy_price) * 100

        effective_sl_rate = atr_stop_rate if atr_stop_rate is not None else base_sl_rate

        # 1. 긴급 손절 (2일 유예 무시, 100% 매도)
        if profit_rate <= effective_sl_rate:
            sl_reason = f"🚨 손절 기준 도달 ({profit_rate:+.2f}% <= {effective_sl_rate:.1f}%)"
            if atr_stop_rate is not None:
                sl_reason += f" [ATR 변동성 동적 손절: 진입가-{settings.get('atr_stop_loss_multiple', 2.2):.1f}×ATR]"
            else:
                sl_reason += " - 자본 보호 즉시 전량 매도"

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
                "reasons": [sl_reason],
                "is_urgent": True,
                "atr_stop_price": atr_stop_price,
                "atr_stop_rate": atr_stop_rate
            }

        # -------------------------------------------------------------
        # [개선 1: 1차 익절 후 잔여분 20일선 추세 추종 트레일링 스탑]
        # -------------------------------------------------------------
        if is_partial_sold:
            high_benchmark = highest_price if highest_price is not None and highest_price > 0 else max(avg_buy_price, current_price)
            trailing_pct = float(settings.get("trailing_stop_pct", 0.06))  # 6% 유연 트레일링 스탑

            is_ma20_broken = False
            if df is not None and len(df) >= 20:
                last = df.iloc[-1]
                ma20_val = float(last["ma20"]) if not pd.isna(last["ma20"]) else 0.0
                if ma20_val > 0 and current_price < ma20_val:
                    is_ma20_broken = True

            trailing_stop_price = high_benchmark * (1 - trailing_pct)
            if current_price <= trailing_stop_price or is_ma20_broken:
                trigger_reason = f"📉 20일 이동평균선 이탈" if is_ma20_broken else f"🏆 최고가({high_benchmark:,.0f}원) 대비 -{trailing_pct*100:.1f}% 트레일링 스탑"
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
                    "reasons": [f"{trigger_reason} - 잔여 수량 전량 추세 익절 (+{profit_rate:.2f}%)"],
                    "is_urgent": False
                }
            return None

        # 3. 1차 목표 익절 (2일 유예 무시, 50% 분할 익절)
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
                "reasons": [f"🎯 목표 익절 수익률 달성 (+{profit_rate:.2f}% >= +{tp_rate:.1f}%) - 50% 1차 익절 및 잔여분 추세 추종"],
                "is_urgent": False,
                "is_partial_take": True
            }

        # 4. 2일 보유 유예 원칙
        if is_recently_bought:
            return None

        # -------------------------------------------------------------
        # [개선 4: 타임컷 12거래일(약 2.5주)로 연장]
        # -------------------------------------------------------------
        time_stop_days = int(settings.get("time_stop_days", 12))
        time_stop_min_profit = float(settings.get("time_stop_min_profit", 0.02)) * 100
        if settings.get("time_stop_enabled", True) and holding_days >= time_stop_days:
            if profit_rate < time_stop_min_profit:
                return {
                    "code": code,
                    "name": name,
                    "holding_qty": holding_qty,
                    "sell_qty": holding_qty,
                    "sell_ratio": 1.0,
                    "sell_type": "타임컷 청산 (기간 만료)",
                    "avg_buy_price": avg_buy_price,
                    "current_price": current_price,
                    "profit_rate": profit_rate,
                    "profit_loss": profit_loss,
                    "reasons": [f"⏳ {holding_days}영업일 경과 및 목표수익 미달({profit_rate:+.2f}% < {time_stop_min_profit:.1f}%) - 자금 회수 타임컷 청산"],
                    "is_urgent": False
                }

        # 6. 일반 기술적 매도 신호 분석
        if df is not None and len(df) >= 20:
            last = df.iloc[-1]
            prev = df.iloc[-2]

            sell_reasons = []
            is_deadcross = False
            is_rsi_overheat = False

            if prev["ma5"] >= prev["ma20"] and last["ma5"] < last["ma20"]:
                is_deadcross = True
                sell_reasons.append("📉 5일선이 20일선을 하향 이탈 (데드크로스 발생) - 전량 청산 권고")

            rsi_val = float(last["rsi14"]) if not pd.isna(last["rsi14"]) else 0.0
            rsi_overheat_threshold = float(settings.get("momentum_rsi_overheat", 78))
            if rsi_val > rsi_overheat_threshold:
                is_rsi_overheat = True
                sell_reasons.append(f"🔥 RSI 극과열권 도달 ({rsi_val:.1f} > {rsi_overheat_threshold:.0f}) - 50% 분할 차익실현 권고")

            if is_deadcross:
                return {
                    "code": code,
                    "name": name,
                    "holding_qty": holding_qty,
                    "sell_qty": holding_qty,
                    "sell_ratio": 1.0,
                    "sell_type": "전량 청산 (데드크로스)",
                    "avg_buy_price": avg_buy_price,
                    "current_price": current_price,
                    "profit_rate": profit_rate,
                    "profit_loss": profit_loss,
                    "reasons": sell_reasons,
                    "is_urgent": False
                }
            elif is_rsi_overheat and not is_partial_sold:
                sell_qty = max(1, holding_qty // 2) if holding_qty > 1 else holding_qty
                sell_ratio = 0.5 if holding_qty > 1 else 1.0
                return {
                    "code": code,
                    "name": name,
                    "holding_qty": holding_qty,
                    "sell_qty": sell_qty,
                    "sell_ratio": sell_ratio,
                    "sell_type": "50% 분할익절 (RSI 과열)" if sell_ratio == 0.5 else "전량익절",
                    "avg_buy_price": avg_buy_price,
                    "current_price": current_price,
                    "profit_rate": profit_rate,
                    "profit_loss": profit_loss,
                    "reasons": sell_reasons,
                    "is_urgent": False,
                    "is_partial_take": True
                }

        return None