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

# --- 라오어 무한매수법 전담 설정 ---
STRATEGY_NAME = "INFINITE_BUYING"     # 전담 매매 전략: 무한매수법 v2.0
INFINITE_BUYING_ENABLED = True        # 무한매수법 자동화 모드 활성화 여부
INFINITE_STOCKS = ["TQQQ"]            # 무한매수 대상 미국 3배 레버리지 ETF 리스트 (예: TQQQ, SOXL)
INFINITE_TOTAL_BUDGET_USD = 5000.0    # 종목당 총 분할 매수 예산 ($)
INFINITE_DIVISION_COUNT = 40          # 총 분할 횟수 (40회차)
INFINITE_TARGET_ROI = 0.10            # 전량 익절 목표 수익률 (+10%)
INFINITE_EXHAUST_ACTION = "HOLD"      # 40회차 소진 시 대응 모드: HOLD(무한대기), REBALANCE_QUARTER(쿼터순환), LOWER_TARGET(목표가하향)
INFINITE_EXHAUST_TARGET_ROI = 0.05    # LOWER_TARGET 선택 시 탈출 목표 수익률 (+5%)

# 하위 호환성 유지용 TARGET_STOCKS (해외 무한매수 대상 동기화)
TARGET_STOCKS = INFINITE_STOCKS

# --- 영속 설정 파일 (infinite_settings.json) 로드 ---
# UI에서 변경한 무한매수 설정값을 저장/로드하여,
# 앱 재시작 및 GitHub Actions 자동 실행 시에도 동일한 설정이 유지되도록 한다.
SETTINGS_FILE = "infinite_settings.json"

def _apply_settings(_settings: dict):
    """설정 dict를 config 모듈 변수에 반영"""
    if not isinstance(_settings, dict):
        return

    # 무한매수 설정값 반영
    if "infinite_stocks" in _settings and isinstance(_settings["infinite_stocks"], list):
        global INFINITE_STOCKS, TARGET_STOCKS
        INFINITE_STOCKS = [s.strip().upper() for s in _settings["infinite_stocks"] if s.strip()]
        TARGET_STOCKS = INFINITE_STOCKS
    if "infinite_total_budget_usd" in _settings:
        global INFINITE_TOTAL_BUDGET_USD
        INFINITE_TOTAL_BUDGET_USD = float(_settings["infinite_total_budget_usd"])
    if "infinite_division_count" in _settings:
        global INFINITE_DIVISION_COUNT
        INFINITE_DIVISION_COUNT = int(_settings["infinite_division_count"])
    if "infinite_target_roi" in _settings:
        global INFINITE_TARGET_ROI
        INFINITE_TARGET_ROI = float(_settings["infinite_target_roi"])
    if "infinite_exhaust_action" in _settings:
        global INFINITE_EXHAUST_ACTION
        INFINITE_EXHAUST_ACTION = str(_settings["infinite_exhaust_action"]).strip().upper()
    if "infinite_exhaust_target_roi" in _settings:
        global INFINITE_EXHAUST_TARGET_ROI
        INFINITE_EXHAUST_TARGET_ROI = float(_settings["infinite_exhaust_target_roi"])

    # 리스크/시스템 설정값 반영
    if "max_stocks_holding" in _settings:
        global MAX_STOCKS_HOLDING
        MAX_STOCKS_HOLDING = int(_settings["max_stocks_holding"])
    if "api_call_delay" in _settings:
        global API_CALL_DELAY
        API_CALL_DELAY = float(_settings["api_call_delay"])


def _load_persistent_settings():
    """infinite_settings.json 파일 및 Google Sheet에서 영속 설정값을 로드하여 config 모듈 변수에 반영"""
    _settings = {}

    # 1. 로컬 JSON 파일에서 로드
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as _f:
                _file_settings = json.load(_f)
            if isinstance(_file_settings, dict):
                _settings.update(_file_settings)
        except Exception as e:
            logging.getLogger("Config").warning(f"영속 설정 파일({SETTINGS_FILE}) 로드 실패: {e}")

    # 2. Google Sheet 'Settings' 워크시트에서 로드 (로컬 JSON보다 우선)
    #    - 순환 import 방지: google_sheet_manager가 이미 import되고 있는 중이면 건너뜀
    try:
        import sys
        if "google_sheet_manager" in sys.modules and "GoogleSheetManager" in dir(sys.modules["google_sheet_manager"]):
            from google_sheet_manager import GoogleSheetManager
            _gss = GoogleSheetManager(enabled=True)
            if _gss.is_connected:
                _sheet_settings = _gss.read_settings_from_sheet()
                if _sheet_settings:
                    _settings.update(_sheet_settings)
                    logging.getLogger("Config").info(f"📊 Google Sheet 'Settings'에서 설정값 로드 완료: {list(_sheet_settings.keys())}")
    except Exception as e:
        logging.getLogger("Config").warning(f"Google Sheet 설정값 로드 실패: {e}")

    # 3. 설정값 반영
    if _settings:
        _apply_settings(_settings)
        logging.getLogger("Config").info(f"⚙️ 영속 설정 적용 완료: 종목={INFINITE_STOCKS}, 예산=${INFINITE_TOTAL_BUDGET_USD:,.0f}, 분할={INFINITE_DIVISION_COUNT}회, 목표수익률=+{INFINITE_TARGET_ROI*100:.1f}%")

# 리스크 및 시스템 제한 설정 (영속 설정 로드 전에 정의)
MAX_STOCKS_HOLDING = 5        # 최대 보유 가능 종목 수
API_CALL_DELAY = 0.2          # API 연속 호출 간 최소 딜레이 (초)

# 영속 설정 파일 로드 (기본값을 영속 설정으로 오버라이드)
_load_persistent_settings()

# --- Google Sheets 동기화 설정 ---
GOOGLE_SHEET_ENABLED = os.getenv("GOOGLE_SHEET_ENABLED", "true").lower() == "true"
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "KIS_무한매수_매매일지")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY", "")  # 구글 시트 ID/Key
GCP_SERVICE_ACCOUNT_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")  # GCP Service Account JSON

# --- 리스크 및 시스템 제한 설정 ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")  # DEBUG, INFO, WARNING, ERROR

