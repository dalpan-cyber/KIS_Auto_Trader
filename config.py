"""
한국투자증권 Open Trading API (KIS Developers) 라오어 무한매수법 전담 자동투자 설정 파일
"""
import os

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

# 하위 호환성 유지용 TARGET_STOCKS (해외 무한매수 대상 동기화)
TARGET_STOCKS = INFINITE_STOCKS

# --- Google Sheets 동기화 설정 ---
GOOGLE_SHEET_ENABLED = os.getenv("GOOGLE_SHEET_ENABLED", "true").lower() == "true"
GOOGLE_SHEET_NAME = os.getenv("GOOGLE_SHEET_NAME", "KIS_무한매수_매매일지")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY", "")  # 구글 시트 ID/Key
GCP_SERVICE_ACCOUNT_JSON = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")  # GCP Service Account JSON

# --- 리스크 및 시스템 제한 설정 ---
MAX_STOCKS_HOLDING = 5        # 최대 보유 가능 종목 수
API_CALL_DELAY = 0.2          # API 연속 호출 간 최소 딜레이 (초)
LOG_LEVEL = "INFO"            # DEBUG, INFO, WARNING, ERROR

