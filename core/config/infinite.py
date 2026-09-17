"""
KIS Auto Trading - Infinite Buying Configuration Module (core/config/infinite.py)
라오어 무한매수법 v2.0 전담 설정 및 infinite_settings.json / Google Sheets 동기화
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
from .common import (
    APP_KEY, APP_SECRET, CANO, ACNT_PRDT_CD, ACCOUNT_PWD,
    URL_BASE_MOCK, URL_BASE_REAL, GOOGLE_SHEET_ENABLED, GCP_SERVICE_ACCOUNT_JSON,
    _get_env_or_secret
)

logger = logging.getLogger("Config.Infinite")

# 모의투자 / 실전투자 모드 설정
MOCK_TRADING_ONLY = os.getenv("MOCK_TRADING_ONLY", "false").lower() == "true"

# 매매 주문 방식 설정 (True: 매매 제안 후 사용자 승인 시 주문, False: 완전 자동 주문)
REQUIRE_USER_APPROVAL = os.getenv("REQUIRE_USER_APPROVAL", "true").lower() == "true"

# API 서버 Base URL
URL_BASE = URL_BASE_MOCK if MOCK_TRADING_ONLY else URL_BASE_REAL

# 라오어 무한매수법 전담 설정 (기본값)
STRATEGY_NAME = "INFINITE_BUYING"
INFINITE_BUYING_ENABLED = True
INFINITE_STOCKS = ["TQQQ"]
INFINITE_TOTAL_BUDGET_USD = 5000.0
INFINITE_DIVISION_COUNT = 40
INFINITE_TARGET_ROI = 0.10
INFINITE_EXHAUST_ACTION = "HOLD"
INFINITE_EXHAUST_TARGET_ROI = 0.05

# 종목별 무한매수 설정
INFINITE_STOCK_CONFIGS: Dict[str, Dict[str, Any]] = {}

# 하위 호환성 유지용 TARGET_STOCKS
TARGET_STOCKS = INFINITE_STOCKS

# 영속 설정 파일 경로
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTINGS_FILE = os.path.join(_PROJECT_ROOT, "infinite_settings.json")
if not os.path.exists(SETTINGS_FILE) and os.path.exists("infinite_settings.json"):
    SETTINGS_FILE = "infinite_settings.json"

# Google Sheets 무한매수 시트 설정
INFINITE_GOOGLE_SHEET_NAME = _get_env_or_secret("INFINITE_GOOGLE_SHEET_NAME", _get_env_or_secret("GOOGLE_SHEET_NAME", "KIS_무한매수_매매일지"))
INFINITE_GOOGLE_SHEET_KEY = _get_env_or_secret("INFINITE_GOOGLE_SHEET_KEY", _get_env_or_secret("GOOGLE_SHEET_KEY", ""))
GOOGLE_SHEET_NAME = INFINITE_GOOGLE_SHEET_NAME
GOOGLE_SHEET_KEY = INFINITE_GOOGLE_SHEET_KEY

# 리스크 및 시스템 제한 설정
MAX_STOCKS_HOLDING = 5
API_CALL_DELAY = 0.2
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


def get_stock_config(symbol: str) -> dict:
    """
    특정 종목의 무한매수 설정값을 반환한다.
    종목별 설정이 없으면 전역 기본값을 사용한다.
    """
    sym_upper = str(symbol).strip().upper()
    cfg = INFINITE_STOCK_CONFIGS.get(sym_upper, {})
    return {
        "total_budget_usd": float(cfg.get("total_budget_usd", INFINITE_TOTAL_BUDGET_USD)),
        "division_count": int(cfg.get("division_count", INFINITE_DIVISION_COUNT)),
        "target_roi": float(cfg.get("target_roi", INFINITE_TARGET_ROI)),
        "exhaust_action": str(cfg.get("exhaust_action", INFINITE_EXHAUST_ACTION)).strip().upper(),
        "exhaust_target_roi": float(cfg.get("exhaust_target_roi", INFINITE_EXHAUST_TARGET_ROI)),
    }


def _apply_settings(_settings: dict):
    """설정 dict를 모듈 변수에 반영"""
    global INFINITE_STOCKS, TARGET_STOCKS, INFINITE_STOCK_CONFIGS
    global INFINITE_TOTAL_BUDGET_USD, INFINITE_DIVISION_COUNT, INFINITE_TARGET_ROI
    global INFINITE_EXHAUST_ACTION, INFINITE_EXHAUST_TARGET_ROI
    global MAX_STOCKS_HOLDING, API_CALL_DELAY

    if not isinstance(_settings, dict):
        return

    # 무한매수 설정값 반영
    if "infinite_stocks" in _settings and isinstance(_settings["infinite_stocks"], list):
        INFINITE_STOCKS = [s.strip().upper() for s in _settings["infinite_stocks"] if s.strip()]
        TARGET_STOCKS = INFINITE_STOCKS

    # 종목별 설정 반영 (infinite_stock_configs)
    if "infinite_stock_configs" in _settings and isinstance(_settings["infinite_stock_configs"], dict):
        INFINITE_STOCK_CONFIGS = {}
        for sym, cfg in _settings["infinite_stock_configs"].items():
            if not isinstance(cfg, dict):
                continue
            sym_upper = str(sym).strip().upper()
            INFINITE_STOCK_CONFIGS[sym_upper] = {
                "total_budget_usd": float(cfg.get("total_budget_usd", INFINITE_TOTAL_BUDGET_USD)),
                "division_count": int(cfg.get("division_count", INFINITE_DIVISION_COUNT)),
                "target_roi": float(cfg.get("target_roi", INFINITE_TARGET_ROI)),
                "exhaust_action": str(cfg.get("exhaust_action", INFINITE_EXHAUST_ACTION)).strip().upper(),
                "exhaust_target_roi": float(cfg.get("exhaust_target_roi", INFINITE_EXHAUST_TARGET_ROI)),
            }

    # 전역 기본값 반영 (하위 호환성: 종목별 설정이 없는 경우 사용)
    if "infinite_total_budget_usd" in _settings:
        INFINITE_TOTAL_BUDGET_USD = float(_settings["infinite_total_budget_usd"])
    if "infinite_division_count" in _settings:
        INFINITE_DIVISION_COUNT = int(_settings["infinite_division_count"])
    if "infinite_target_roi" in _settings:
        INFINITE_TARGET_ROI = float(_settings["infinite_target_roi"])
    if "infinite_exhaust_action" in _settings:
        INFINITE_EXHAUST_ACTION = str(_settings["infinite_exhaust_action"]).strip().upper()
    if "infinite_exhaust_target_roi" in _settings:
        INFINITE_EXHAUST_TARGET_ROI = float(_settings["infinite_exhaust_target_roi"])

    # 리스크/시스템 설정값 반영
    if "max_stocks_holding" in _settings:
        MAX_STOCKS_HOLDING = int(_settings["max_stocks_holding"])
    if "api_call_delay" in _settings:
        API_CALL_DELAY = float(_settings["api_call_delay"])


def load_settings_from_google_sheet(gss_instance=None) -> dict:
    """
    Google Sheet 'Settings' 워크시트에서 최신 설정값을 로드하여 config에 최우선 반영
    """
    sheet_settings = {}
    try:
        if gss_instance is not None:
            gss = gss_instance
        else:
            from core.sheets.infinite_sheet_manager import get_infinite_sheet_manager
            gss = get_infinite_sheet_manager()

        if gss and gss.is_connected:
            sheet_settings = gss.read_settings_from_sheet()
            if sheet_settings:
                _apply_settings(sheet_settings)
                # 로컬 백업 파일도 최신 구글 시트 값으로 동기화
                try:
                    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                        json.dump(sheet_settings, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass

                stock_cfg_summary = ", ".join(
                    [f"{s}(예산=${get_stock_config(s)['total_budget_usd']:,.0f}, 분할={get_stock_config(s)['division_count']}회, 목표=+{get_stock_config(s)['target_roi']*100:.1f}%)"
                     for s in INFINITE_STOCKS]
                )
                logger.info(f"📊 [Google Sheets 우선 로딩] 설정 동기화 완료: {stock_cfg_summary}")
    except Exception as e:
        logger.warning(f"Google Sheet 설정 우선 로딩 건너뜀 (로컬 설정 유지): {e}")

    return sheet_settings


def _load_persistent_settings():
    """infinite_settings.json 파일 및 Google Sheet에서 영속 설정값을 로드"""
    _settings = {}

    # 1. 로컬 JSON 파일에서 로드
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as _f:
                _file_settings = json.load(_f)
            if isinstance(_file_settings, dict):
                _settings.update(_file_settings)
        except Exception as e:
            logger.warning(f"영속 설정 파일({SETTINGS_FILE}) 로드 실패: {e}")

    if _settings:
        _apply_settings(_settings)

    # 2. Google Sheet 'Settings' 워크시트에서 우선 로드
    load_settings_from_google_sheet()


# 모듈 로드 시 영속 설정 반영
_load_persistent_settings()
