"""
KIS Auto Trading - Strategy Registry
매수/매도 전략 플러그인 등록 및 조회
"""
import logging
from typing import Dict, Type, List, Any, Optional, Set
import pandas as pd

from core.strategy.base import BaseStrategy

logger = logging.getLogger("StrategyRegistry")

_registry: Dict[str, Type[BaseStrategy]] = {}


def register_strategy(cls: Type[BaseStrategy]) -> Type[BaseStrategy]:
    """전략 클래스를 레지스트리에 등록 (데코레이터)"""
    if not hasattr(cls, "name") or not cls.name:
        raise ValueError(f"Strategy class {cls.__name__} must define a 'name' attribute")
    _registry[cls.name] = cls
    logger.info(f"전략 등록: {cls.name} ({cls.display_name})")
    return cls


def get_strategy(name: str) -> BaseStrategy:
    """설정된 전략 이름으로 인스턴스 생성"""
    if name not in _registry:
        available = ", ".join(list(_registry.keys())) or "none"
        raise ValueError(f"Unknown strategy: {name}. Available strategies: {available}")
    return _registry[name]()


def get_strategy_class(name: str) -> Type[BaseStrategy]:
    """설정된 전략 이름으로 클래스 반환 (인스턴스 없이 스키마 조회용)"""
    if name not in _registry:
        available = ", ".join(list(_registry.keys())) or "none"
        raise ValueError(f"Unknown strategy: {name}. Available strategies: {available}")
    return _registry[name]


def list_strategies() -> List[Dict[str, str]]:
    """등록된 전략 목록 반환"""
    return [
        {"name": cls.name, "display_name": cls.display_name, "description": getattr(cls, "description", "")}
        for cls in _registry.values()
    ]


def get_default_strategy_name() -> str:
    """기본 전략 이름 반환 (첫 번째 등록된 전략)"""
    if not _registry:
        return "momentum"
    return next(iter(_registry.keys()))


def get_strategy_settings_schema(name: str) -> List[Dict[str, Any]]:
    """특정 전략의 설정 스키마 반환"""
    cls = get_strategy_class(name)
    return cls.get_settings_schema()


def get_strategy_settings_defaults(name: str) -> Dict[str, Any]:
    """특정 전략의 설정 스키마에서 기본값 dict 생성"""
    cls = get_strategy_class(name)
    return {
        item["key"]: item.get("default")
        for item in cls.settings_schema
    }


def get_strategy_settings_keys(name: str) -> Set[str]:
    """특정 전략의 모든 설정 키 목록 반환"""
    cls = get_strategy_class(name)
    return {item["key"] for item in cls.settings_schema}


def get_strategy_specific_settings_keys(name: str) -> Set[str]:
    """특정 전략의 고유(category='strategy') 설정 키 목록 반환"""
    cls = get_strategy_class(name)
    return cls.get_strategy_settings_keys()


def get_active_strategies(names: Optional[List[str]] = None) -> List[BaseStrategy]:
    """활성화된 전략 인스턴스 목록 반환 (다중 전략 지원)"""
    import app_config as config
    if names is None:
        names = config.CURRENT_SETTINGS.get("active_strategies")
        if not names:
            single = config.CURRENT_SETTINGS.get("strategy_name", get_default_strategy_name())
            names = [single] if single else [get_default_strategy_name()]

    strategies = []
    for n in names:
        if n in _registry:
            strategies.append(_registry[n]())
        else:
            logger.warning(f"등록되지 않은 전략 '{n}' 건너뜀")

    if not strategies:
        strategies = [_registry[get_default_strategy_name()]()]
    return strategies


# 전략 모듈 자동 로드 (등록을 위해 import)
from core.strategy import momentum        # noqa: E402,F401
from core.strategy import rebound         # noqa: E402,F401
from core.strategy import monthly_trend   # noqa: E402,F401
from core.strategy import cup_and_handle  # noqa: E402,F401

# =============================================================================
# 하위 호환성을 위한 래퍼 함수 (기존 core.strategy 모듈 함수 시그니처 유지)
# =============================================================================

_default_strategy = get_strategy(get_default_strategy_name())


def get_market_regime(
    candles_or_df: Optional[pd.DataFrame],
    ma_period: int = 20
) -> Dict[str, Any]:
    """시장 국면 판단 (기본 전략 위임)"""
    return _default_strategy.get_market_regime(candles_or_df, ma_period=ma_period)


def calculate_position_size(
    current_price: float,
    budget_val: float,
    atr_val: float = 0.0,
    settings: Optional[Dict[str, Any]] = None
) -> int:
    """변동성 조절 포지션 사이징 (기본 전략 위임)"""
    return _default_strategy.calculate_position_size(
        current_price, budget_val, atr_val=atr_val, settings=settings
    )


def evaluate_buy_signals_from_df(
    df: Optional[pd.DataFrame],
    code: str,
    name: str,
    held_codes: Optional[Set[str]] = None,
    budget: Optional[float] = None,
    market_regime: Optional[Dict[str, Any]] = None,
    settings: Optional[Dict[str, Any]] = None,
    is_in_cooldown: bool = False,
    futures_data: Optional[Dict[str, Any]] = None,
    return_raw_eval: bool = False
) -> Optional[Dict[str, Any]]:
    """매수 신호 평가 (기본 전략 위임)"""
    return _default_strategy.evaluate_buy(
        df=df,
        code=code,
        name=name,
        held_codes=held_codes,
        budget=budget,
        market_regime=market_regime,
        settings=settings,
        is_in_cooldown=is_in_cooldown,
        futures_data=futures_data,
        return_raw_eval=return_raw_eval
    )


def evaluate_sell_signals_from_df(
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
    """매도 신호 평가 (기본 전략 위임)"""
    return _default_strategy.evaluate_sell(
        holding=holding,
        df=df,
        is_recently_bought=is_recently_bought,
        stop_loss_rate=stop_loss_rate,
        target_profit_rate=target_profit_rate,
        settings=settings,
        is_partial_sold=is_partial_sold,
        highest_price=highest_price,
        holding_days=holding_days,
        market_regime=market_regime
    )