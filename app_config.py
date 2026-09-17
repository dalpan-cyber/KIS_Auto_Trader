"""
KIS Auto Trading - Configuration Module (Facade)
기존 코드 및 UI 100% 하위 호환성을 보장합니다.
실제 핵심 구현은 core.config 패키지에 모듈화되어 있습니다.
"""
from typing import Any, Dict, Optional, List
from core.config.common import *
from core.config.domestic import *
import core.config.domestic as _domestic


def load_settings() -> Dict[str, Any]:
    return _domestic.load_settings()


def save_settings(new_settings: Dict[str, Any]) -> bool:
    return _domestic.save_settings(new_settings)


def get_effective_settings_for_regime(detected_regime: str, base_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _domestic.get_effective_settings_for_regime(detected_regime, base_settings)


def get_strategy_settings(strategy_name: Optional[str] = None) -> Dict[str, Any]:
    return _domestic.get_strategy_settings(strategy_name)


def get_effective_strategy_settings(
    strategy_name: Optional[str] = None,
    base_settings: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    return _domestic.get_effective_strategy_settings(strategy_name, base_settings)


def save_strategy_settings(
    strategy_name: str,
    strategy_settings: Dict[str, Any],
    global_settings: Optional[Dict[str, Any]] = None
) -> bool:
    return _domestic.save_strategy_settings(strategy_name, strategy_settings, global_settings)


def save_multiple_strategy_settings(
    active_strategies: List[str],
    strategies_settings_map: Dict[str, Dict[str, Any]],
    global_settings: Optional[Dict[str, Any]] = None
) -> bool:
    return _domestic.save_multiple_strategy_settings(active_strategies, strategies_settings_map, global_settings)


def get_setting(key: str, default: Any = None) -> Any:
    return _domestic.get_setting(key, default)


def get_url_base() -> str:
    return _domestic.get_url_base()


def sync_settings_from_google_sheet() -> bool:
    return _domestic.sync_settings_from_google_sheet()
