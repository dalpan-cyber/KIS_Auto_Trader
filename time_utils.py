"""
Timezone Utility Module
서버 시간대와 무관하게 한국 표준시(KST, UTC+9) 기준의 시간을 제공
"""
import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now() -> datetime.datetime:
    """현재 시각을 KST(Asia/Seoul) 기준으로 반환"""
    return datetime.datetime.now(KST)


def today() -> datetime.date:
    """오늘 날짜를 KST(Asia/Seoul) 기준으로 반환"""
    return now().date()


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """현재 시각을 KST 기준 문자열로 반환"""
    return now().strftime(fmt)