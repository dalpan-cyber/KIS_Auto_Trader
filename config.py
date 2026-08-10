"""
한국투자증권 Open Trading API (KIS Developers) 자동 투자 프로그램 설정 파일
"""
import os

# --- KIS Developers Open API 인증 및 계좌 설정 ---
# KIS Developers 포털(https://apiportal.koreainvestment.com/)에서 발급받은 키 설정
APP_KEY = os.getenv("KIS_APP_KEY", "YOUR_APP_KEY")               # AppKey (환경변수 또는 직입력)
APP_SECRET = os.getenv("KIS_APP_SECRET", "YOUR_APP_SECRET")         # AppSecret (환경변수 또는 직입력)

CANO = os.getenv("KIS_CANO", "YOUR_CANO_8_DIGITS")                # 계좌번호 앞 8자리
ACNT_PRDT_CD = os.getenv("KIS_ACNT_PRDT_CD", "01")              # 계좌상품코드 2자리 (주식 기본 01)
ACCOUNT_PWD = os.getenv("KIS_ACCOUNT_PWD", "YOUR_ACCOUNT_PWD")  # 계좌 비밀번호 (4자리)

# 모의투자 / 실전투자 모드 설정
MOCK_TRADING_ONLY = False  # True: 모의투자(VTS), False: 실전투자

# 매매 주문 방식 설정 (True: 매매 제안 후 사용자 승인 시 주문, False: 완전 자동 주문)
REQUIRE_USER_APPROVAL = True

# API 서버 Base URL (MOCK_TRADING_ONLY 값에 따라 자동 설정)
URL_BASE_MOCK = "https://openapivts.koreainvestment.com:29443"
URL_BASE_REAL = "https://openapi.koreainvestment.com:9443"
URL_BASE = URL_BASE_MOCK if MOCK_TRADING_ONLY else URL_BASE_REAL

# --- 매매 대상 및 종목 설정 ---
# 자동 매매할 종목 코드 리스트 (국내: 6자리 숫자, 해외: 미국 주식 알파벳 티커)
TARGET_STOCKS = [
    "005930",  # 삼성전자 (국내)
    "000660",  # SK하이닉스 (국내)
    "GOOGL",   # 알파벳/구글 (미국)
    "PFE",     # 화이자 (미국)
    "PLTR",    # 팔란티어 (미국)
]

# --- 매매 전략 설정 ---
STRATEGY_NAME = "MA_CROSS"  # MA_CROSS (이동평균 교차) 또는 VOLATILITY_BREAKOUT (변동성 돌파)

# 이동평균 교차 전략 파라미터
SHORT_MA_PERIOD = 5    # 단기 이동평균선 기간
LONG_MA_PERIOD = 20    # 장기 이동평균선 기간

# 변동성 돌파 전략 파라미터
K_VALUE = 0.5          # 변동성 K 계수 (0.4 ~ 0.6 권장)

# --- 리스크 및 자금 관리 설정 ---
INVEST_RATIO_PER_STOCK = 0.2  # 종목당 계좌 총 평가금액 대비 최대 투자 비율 (20%)
MAX_STOCKS_HOLDING = 5        # 최대 보유 가능 종목 수
STOP_LOSS_RATIO = 0.03        # 손절 비율 (3% 하락 시 매도)
TAKE_PROFIT_RATIO = 0.07      # 익절 비율 (7% 상승 시 매도)
TRAILING_STOP_RATIO = 0.02    # 트레일링 스탑 비율 (고점 대비 2% 하락 시 매도)

# --- API 안전성 및 속도 제한 설정 ---
API_CALL_DELAY = 0.2          # API 연속 호출 간 최소 딜레이 (초)
LOG_LEVEL = "INFO"            # DEBUG, INFO, WARNING, ERROR

INFINITE_BUYING_ENABLED = True
