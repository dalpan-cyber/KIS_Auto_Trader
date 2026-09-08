"""
한국투자증권 Open Trading API (KIS Developers) 라오어 무한매수법 전담 자동투자 설정 파일
"""
import os
import json
import logging

# --- 로컬 .env 파일 자동 로드 (.env 파일이 존재하는 경우 환경변수로 등록) ---
if os.path.exists(".env"):
    try:
        with open(".env", "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if _line and not _line.startswith("#") and "=" in _line:
                    _k, _v = _line.split("=", 1)
                    _k = _k.strip()
                    _v = _v.strip().strip('"').strip("'")
                    if _k and _k not in os.environ:
                        os.environ[_k] = _v
    except Exception:
        pass

# --- KIS Developers Open API 인증 및 계좌 설정 ---
# GitHub Secrets 또는 환경변수를 우선 참조하며, 보안을 위해 키는 로컬 .env 파일이나 서버 환경변수로 관리합니다.
APP_KEY = os.getenv("KIS_APP_KEY", "")
APP_SECRET = os.getenv("KIS_APP_SECRET", "")

CANO = os.getenv("KIS_CANO", "")               # 계좌번호 앞 8자리
ACNT_PRDT_CD = os.getenv("KIS_ACNT_PRDT_CD", "01")  # 계좌상품코드 2자리 (주식 기본 01)
ACCOUNT_PWD = os.getenv("KIS_ACCOUNT_PWD", "") # 계좌 비밀번호 (4자리)


# 모의투자 / 실전투자 모드 설정
MOCK_TRADING_ONLY = os.getenv("MOCK_TRADING_ONLY", "false").lower() == "true"

# 매매 주문 방식 설정 (True: 매매 제안 후 사용자 승인 시 주문, False: 완전 자동 주문)
REQUIRE_USER_APPROVAL = os.getenv("REQUIRE_USER_APPROVAL", "true").lower() == "true"

# API 서버 Base URL (MOCK_TRADING_ONLY 값에 따라 자동 설정)
URL_BASE_MOCK = "https://openapivts.koreainvestment.com:29443"
URL_BASE_REAL = "https://openapi.koreainvestment.com:9443"
URL_BASE = URL_BASE_MOCK if MOCK_TRADING_ONLY else URL_BASE_REAL

# --- 라오어 무한매수법 전담 설정 (기본값 - 종목별 설정이 없을 때 사용) ---
STRATEGY_NAME = "INFINITE_BUYING"     # 전담 매매 전략: 무한매수법 v2.0
INFINITE_BUYING_ENABLED = True        # 무한매수법 자동화 모드 활성화 여부
INFINITE_STOCKS = ["TQQQ"]            # 무한매수 대상 미국 3배 레버리지 ETF 리스트 (예: TQQQ, SOXL)
INFINITE_TOTAL_BUDGET_USD = 5000.0    # 종목당 총 분할 매수 예산 ($) - 기본값
INFINITE_DIVISION_COUNT = 40          # 총 분할 횟수 (40회차) - 기본값
INFINITE_TARGET_ROI = 0.10            # 전량 익절 목표 수익률 (+10%) - 기본값
INFINITE_EXHAUST_ACTION = "HOLD"      # 40회차 소진 시 대응 모드: HOLD(무한대기), REBALANCE_QUARTER(쿼터순환), LOWER_TARGET(목표가하향) - 기본값
INFINITE_EXHAUST_TARGET_ROI = 0.05    # LOWER_TARGET 선택 시 탈출 목표 수익률 (+5%) - 기본값

# 종목별 무한매수 설정 (infinite_settings.json의 infinite_stock_configs에서 로드)
# 구조: { "TQQQ": {"total_budget_usd": 5000.0, "division_count": 40, "target_roi": 0.10,
#                  "exhaust_action": "HOLD", "exhaust_target_roi": 0.05} }
INFINITE_STOCK_CONFIGS: dict = {}

# 하위 호환성 유지용 TARGET_STOCKS (해외 무한매수 대상 동기화)
TARGET_STOCKS = INFINITE_STOCKS

# --- 영속 설정 파일 (infinite_settings.json) 로드 ---
# UI에서 변경한 무한매수 설정값을 저장/로드하여,
# 앱 재시작 및 GitHub Actions 자동 실행 시에도 동일한 설정이 유지되도록 한다.
SETTINGS_FILE = "infinite_settings.json"


def get_stock_config(symbol: str) -> dict:
    """
    특정 종목의 무한매수 설정값을 반환한다.
    종목별 설정이 없으면 전역 기본값을 사용한다.
    :param symbol: 종목 코드 (예: TQQQ)
    :return: {"total_budget_usd": float, "division_count": int, "target_roi": float,
              "exhaust_action": str, "exhaust_target_roi": float}
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
    """설정 dict를 config 모듈 변수에 반영"""
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


# --- Google Sheets 동기화 설정 (영속 설정 로드 전에 선언) ---
GOOGLE_SHEET_ENABLED = os.getenv("GOOGLE_SHEET_ENABLED", "true").lower() == "true"
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "KIS_무한매수_매매일지")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY", "")  # 구글 시트 ID/Key
GCP_SERVICE_ACCOUNT_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")  # GCP Service Account JSON

# 리스크 및 시스템 제한 설정 (영속 설정 로드 전에 정의)
MAX_STOCKS_HOLDING = 5        # 최대 보유 가능 종목 수
API_CALL_DELAY = 0.2          # API 연속 호출 간 최소 딜레이 (초)
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR


def load_settings_from_google_sheet(gss_instance=None) -> dict:
    """
    Google Sheet 'Settings' 워크시트에서 최신 설정값을 로드하여 config에 최우선 반영
    - Streamlit Cloud(streamlit.io) 환경 대응: 로컬 파일보다 구글 시트 설정을 최우선 로딩
    :param gss_instance: 기존 생성된 GoogleSheetManager 인스턴스 (없으면 새로 생성 시도)
    :return: 불러온 설정 dict (실패 시 빈 dict)
    """
    sheet_settings = {}
    try:
        if gss_instance is not None:
            gss = gss_instance
        else:
            from google_sheet_manager import GoogleSheetManager
            gss = GoogleSheetManager(enabled=True)

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
                logging.getLogger("Config").info(f"📊 [Google Sheets 우선 로딩] 설정 동기화 완료: {stock_cfg_summary}")
    except Exception as e:
        logging.getLogger("Config").warning(f"Google Sheet 설정 우선 로딩 건너뜀 (로컬 설정 유지): {e}")

    return sheet_settings


def _load_persistent_settings():
    """infinite_settings.json 파일 및 Google Sheet에서 영속 설정값을 로드하여 config 모듈 변수에 반영"""
    _settings = {}

    # 1. 로컬 JSON 파일에서 로드 (기본값)
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as _f:
                _file_settings = json.load(_f)
            if isinstance(_file_settings, dict):
                _settings.update(_file_settings)
        except Exception as e:
            logging.getLogger("Config").warning(f"영속 설정 파일({SETTINGS_FILE}) 로드 실패: {e}")

    # 로컬 설정 1차 적용
    if _settings:
        _apply_settings(_settings)

    # 2. Google Sheet 'Settings' 워크시트에서 우선 로드 (구글 시트가 Single Source of Truth)
    load_settings_from_google_sheet()


# 영속 설정 파일 로드 (기본값을 영속 설정으로 오버라이드)
_load_persistent_settings()
