"""
KIS Auto Trading - Common Configuration Module (core/config/common.py)
공통 환경 변수, KIS API 기본 인증 정보, 텔레그램 및 로깅 설정
"""
import os
import logging
import datetime
from zoneinfo import ZoneInfo
from typing import Any, Optional

_KST = ZoneInfo("Asia/Seoul")

# 로깅 기본 설정 (KST 기준)
class KSTFormatter(logging.Formatter):
    """한국 표준시(KST) 기준으로 로그 타임스탬프를 출력하는 Formatter"""
    def formatTime(self, record, datefmt=None):
        dt = datetime.datetime.fromtimestamp(record.created, tz=_KST)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime('%Y-%m-%d %H:%M:%S')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] (%(name)s) %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
for handler in logging.getLogger().handlers:
    handler.setFormatter(KSTFormatter(fmt='%(asctime)s [%(levelname)s] (%(name)s) %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))

logger = logging.getLogger("Config")

# .env 로드 (루트 디렉토리 기준)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ENV_PATH = os.path.join(_PROJECT_ROOT, ".env")
if not os.path.exists(ENV_PATH):
    ENV_PATH = os.path.join(os.getcwd(), ".env")

if os.path.exists(ENV_PATH):
    try:
        with open(ENV_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
    except Exception as e:
        logger.warning(f".env 로드 실패: {e}")


def _get_env_or_secret(key: str, default: str = "") -> str:
    val = os.getenv(key, "")
    if val:
        return val
    try:
        import streamlit as st
        try:
            if hasattr(st, "secrets") and key in st.secrets:
                return str(st.secrets.get(key, default) if hasattr(st.secrets, "get") else st.secrets[key])
        except (KeyError, Exception):
            pass
    except Exception:
        pass
    return default


# KIS API 계정 정보
APP_KEY = _get_env_or_secret("KIS_APP_KEY", "")
APP_SECRET = _get_env_or_secret("KIS_APP_SECRET", "")
CANO = _get_env_or_secret("KIS_CANO", "")               # 계좌번호 앞 8자리
ACNT_PRDT_CD = _get_env_or_secret("KIS_ACNT_PRDT_CD", "01")  # 계좌상품코드 2자리 (주식 기본 01)
ACCOUNT_PWD = _get_env_or_secret("KIS_ACCOUNT_PWD", "") # 계좌 비밀번호 (4자리)

# 텔레그램 알림 설정
TELEGRAM_BOT_TOKEN = _get_env_or_secret("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = _get_env_or_secret("TELEGRAM_CHAT_ID", "")

# API 엔드포인트 URL
URL_BASE_MOCK = "https://openapivts.koreainvestment.com:29443"
URL_BASE_REAL = "https://openapi.koreainvestment.com:9443"

# Google Sheets 공통 설정
GOOGLE_SHEET_ENABLED = _get_env_or_secret("GOOGLE_SHEET_ENABLED", "true").lower() == "true"
GCP_SERVICE_ACCOUNT_JSON = _get_env_or_secret("GCP_SERVICE_ACCOUNT_JSON", "kis-auto-trader-1024280eca64.json")
