"""
한국투자증권 Open Trading API (KIS Developers) 라오어 무한매수법 전담 자동투자 설정 파일 (Facade)
기존 코드 및 GitHub Actions 워크플로우 100% 하위 호환성을 보장합니다.
실제 핵심 구현은 core.config 패키지에 모듈화되어 있습니다.
"""
import sys
import types
from core.config.common import *
from core.config.infinite import *
import core.config.infinite as _infinite
import core.config.common as _common


def get_stock_config(symbol: str) -> dict:
    return _infinite.get_stock_config(symbol)


def load_settings_from_google_sheet(gss_instance=None) -> dict:
    return _infinite.load_settings_from_google_sheet(gss_instance)


class _ConfigModule(types.ModuleType):
    """
    core.config.infinite 및 core.config.common과 실시간 양방향 속성 동기화를 제공하는 Facade 모듈 클래스
    """
    def __getattribute__(self, name: str):
        if name in (
            "_infinite", "_common", "__class__", "__dict__",
            "__name__", "__doc__", "__file__", "__package__",
            "__loader__", "__spec__", "__path__", "get_stock_config",
            "load_settings_from_google_sheet"
        ):
            return super().__getattribute__(name)
        _inf = super().__getattribute__("_infinite")
        if hasattr(_inf, name):
            return getattr(_inf, name)
        _com = super().__getattribute__("_common")
        if hasattr(_com, name):
            return getattr(_com, name)
        return super().__getattribute__(name)

    def __setattr__(self, name: str, value):
        if name in ("_infinite", "_common", "__class__"):
            super().__setattr__(name, value)
            return
        _inf = super().__getattribute__("_infinite")
        if hasattr(_inf, name):
            setattr(_inf, name, value)
        _com = super().__getattribute__("_common")
        if hasattr(_com, name):
            setattr(_com, name, value)
        super().__setattr__(name, value)


_current_mod = sys.modules[__name__]
_current_mod._infinite = _infinite
_current_mod._common = _common
_current_mod.__class__ = _ConfigModule

