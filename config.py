"""
한국투자증권 Open Trading API (KIS Developers) 라오어 무한매수법 전담 자동투자 설정 파일 (Facade)
기존 코드 및 GitHub Actions 워크플로우 100% 하위 호환성을 보장합니다.
실제 핵심 구현은 core.config 패키지에 모듈화되어 있습니다.
"""
from core.config.common import *
from core.config.infinite import *
import core.config.infinite as _infinite


def get_stock_config(symbol: str) -> dict:
    return _infinite.get_stock_config(symbol)


def load_settings_from_google_sheet(gss_instance=None) -> dict:
    return _infinite.load_settings_from_google_sheet(gss_instance)
