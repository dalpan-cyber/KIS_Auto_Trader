"""
KIS Auto Trader Configuration Package (core/config)
공통(common), 무한매수(infinite), 국내 퀀트(domestic) 설정 통합
"""
from .common import *
from .infinite import (
    STRATEGY_NAME as INFINITE_STRATEGY_NAME,
    INFINITE_BUYING_ENABLED,
    INFINITE_STOCKS,
    INFINITE_TOTAL_BUDGET_USD,
    INFINITE_DIVISION_COUNT,
    INFINITE_TARGET_ROI,
    INFINITE_EXHAUST_ACTION,
    INFINITE_EXHAUST_TARGET_ROI,
    INFINITE_STOCK_CONFIGS,
    get_stock_config,
    load_settings_from_google_sheet as load_infinite_settings_from_google_sheet,
)
from .domestic import (
    MARKET_REGIME_PRESETS,
    DEFAULT_SETTINGS,
    load_settings as load_domestic_settings,
    save_settings as save_domestic_settings,
    get_effective_settings_for_regime,
    get_strategy_settings,
    get_effective_strategy_settings,
    save_strategy_settings,
    save_multiple_strategy_settings,
    get_setting,
    get_url_base,
    sync_settings_from_google_sheet as sync_domestic_settings_from_google_sheet,
    CURRENT_SETTINGS,
)
