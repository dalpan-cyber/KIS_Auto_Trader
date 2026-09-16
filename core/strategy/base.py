"""
KIS Auto Trading - Base Strategy Interface
모든 매수/매도 전략이 구현해야 하는 추상 인터페이스 정의
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Set, List
import pandas as pd


class BaseStrategy(ABC):
    """모든 매수/매도 전략이 구현해야 하는 인터페이스"""

    name: str = "base"
    display_name: str = "기본 전략"
    description: str = ""

    # =========================================================================
    # 전략별 설정 스키마 (Strategy-specific Settings Schema)
    # =========================================================================
    # 각 전략은 자신이 필요로 하는 설정 항목을 이 스키마로 선언합니다.
    # UI는 선택된 전략의 스키마에 따라 설정 폼을 동적으로 렌더링합니다.
    # 공통 설정(목표익절, 손절, 타임컷 등)은 'common' 카테고리로,
    # 전략 고유 설정은 'strategy' 카테고리로 구분합니다.
    #
    # 각 항목 형식:
    # {
    #     "key": "설정 키 (settings.json에 저장될 키)",
    #     "label": "UI에 표시될 라벨",
    #     "type": "number | toggle | text | select",
    #     "default": 기본값,
    #     "min": 최소값 (number 타입),
    #     "max": 최대값 (number 타입),
    #     "step": 증가 단위 (number 타입),
    #     "options": 선택 옵션 (select 타입, [(value, label), ...]),
    #     "description": "설명 (UI 캡션)",
    #     "category": "common | strategy" (기본: common)
    # }
    settings_schema: List[Dict[str, Any]] = []

    @classmethod
    def get_settings_schema(cls) -> List[Dict[str, Any]]:
        """전략별 설정 스키마 반환"""
        return list(cls.settings_schema)

    @classmethod
    def get_strategy_settings_keys(cls) -> Set[str]:
        """전략 고유(category='strategy') 설정 키 목록 반환"""
        return {
            item["key"] for item in cls.settings_schema
            if item.get("category", "common") == "strategy"
        }

    @classmethod
    def get_common_settings_keys(cls) -> Set[str]:
        """공통(category='common') 설정 키 목록 반환"""
        return {
            item["key"] for item in cls.settings_schema
            if item.get("category", "common") == "common"
        }

    @abstractmethod
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
        매수 신호 평가 → 매수 추천 dict 반환

        반환 포맷 (기존 호환 유지):
        {
            "code": str,
            "name": str,
            "current_price": float,
            "change_rate": float,
            "score": int,
            "trend_score": int,
            "supply_score": int,
            "momentum_score": int,
            "supply_gate_passed": bool,
            "adjusted_volume": float,
            "vol_ma20": float,
            "vol_ratio": float,
            "reasons": List[str],
            "recommended_qty": int,
            "estimated_amount": float,
            "rsi": float,
            "ma5": float,
            "ma20": float,
            "ma60": float,
            "atr": float,
            "market_regime": str,
            "buy_threshold": float,
            "is_additional_buy": bool,
            "buy_type": str
        }
        """
        ...

    @abstractmethod
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
        매도 신호 평가 → 매도 추천 dict 반환

        반환 포맷 (기존 호환 유지):
        {
            "code": str,
            "name": str,
            "holding_qty": int,
            "sell_qty": int,
            "sell_ratio": float,
            "sell_type": str,
            "avg_buy_price": float,
            "current_price": float,
            "profit_rate": float,
            "profit_loss": float,
            "reasons": List[str],
            "is_urgent": bool,
            "is_partial_take": bool (optional),
            "atr_stop_price": float (optional),
            "atr_stop_rate": float (optional)
        }
        """
        ...

    def get_market_regime(
        self,
        candles_or_df: Optional[pd.DataFrame],
        ma_period: int = 20
    ) -> Dict[str, Any]:
        """
        시장 국면 판단 (기본 구현 제공, 오버라이드 가능)
        - STRONG: 지수가 20일선 위 & 5일선 > 20일선 (대세 상승/강세장)
        - NORMAL: 20일선 위 횡보
        - WEAK: 지수가 20일선 아래 또는 데드크로스 (약세장)
        """
        if candles_or_df is None or len(candles_or_df) < 20:
            return {"regime": "NORMAL", "below_ma20": False, "downtrend": False, "ma20": 0.0, "current": 0.0}

        df = candles_or_df.copy()
        if isinstance(df, list):
            df = pd.DataFrame(df)

        if "Close" in df.columns and "close" not in df.columns:
            df["close"] = df["Close"]

        df["close"] = pd.to_numeric(df["close"], errors="coerce")
        df["ma20"] = df["close"].rolling(window=ma_period, min_periods=1).mean()
        df["ma5"] = df["close"].rolling(window=5, min_periods=1).mean()
        df["ma60"] = df["close"].rolling(window=60, min_periods=1).mean()

        last_close = float(df.iloc[-1]["close"])
        last_ma20 = float(df.iloc[-1]["ma20"]) if not pd.isna(df.iloc[-1]["ma20"]) else last_close
        last_ma5 = float(df.iloc[-1]["ma5"]) if not pd.isna(df.iloc[-1]["ma5"]) else last_close
        last_ma60 = float(df.iloc[-1]["ma60"]) if not pd.isna(df.iloc[-1]["ma60"]) else last_close

        below_ma20 = last_close < last_ma20

        downtrend = False
        if len(df) >= 2:
            prev_ma5 = float(df.iloc[-2]["ma5"]) if not pd.isna(df.iloc[-2]["ma5"]) else 0
            prev_ma20 = float(df.iloc[-2]["ma20"]) if not pd.isna(df.iloc[-2]["ma20"]) else 0
            if prev_ma5 >= prev_ma20 and last_ma5 < last_ma20:
                downtrend = True

        if below_ma20 or downtrend:
            regime = "BEAR"  # 하락장/약세 국면
        elif last_close >= last_ma20 and last_ma5 >= last_ma20 and last_close >= last_ma60:
            regime = "BULL"  # 대세 상승/강세 국면
        else:
            regime = "VOLATILE"  # 변동성/횡보 국면

        return {
            "regime": regime,
            "below_ma20": below_ma20,
            "downtrend": downtrend,
            "ma20": last_ma20,
            "ma60": last_ma60,
            "current": last_close
        }

    def calculate_position_size(
        self,
        current_price: float,
        budget_val: float,
        atr_val: float = 0.0,
        settings: Optional[Dict[str, Any]] = None
    ) -> int:
        """
        변동성 조절 포지션 사이징 (ATR 기반 리스크 균등 분할) 또는 예산 기반 수량 계산
        (기본 구현 제공, 오버라이드 가능)
        """
        if current_price <= 0:
            return 1

        settings = settings or {}
        volatility_sizing = settings.get("volatility_sizing_enabled", True)

        if volatility_sizing and atr_val > 0:
            risk_per_trade = float(settings.get("risk_per_trade", 0.01))
            atr_stop_multiple = float(settings.get("atr_stop_multiple", 2.0))
            max_holdings = int(settings.get("max_holding_stocks", 5))
            total_equity = budget_val * max_holdings
            risk_amt = total_equity * risk_per_trade
            stop_dist = atr_stop_multiple * atr_val
            if stop_dist > 0:
                vol_qty = int(risk_amt // stop_dist)
                max_cap_qty = int(budget_val // current_price)
                return max(1, min(max_cap_qty, vol_qty))

        return max(1, int(budget_val // current_price))