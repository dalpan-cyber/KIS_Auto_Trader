"""
pytest 공통 설정: 테스트가 실제 계좌/구글 시트/텔레그램/로컬 상태 파일을 건드리지 않도록 격리

- 모듈 import 전에 환경변수를 설정해야 하므로 이 파일 최상단에서 처리합니다.
  (core.config.common이 import 시점에 환경변수/.env를 읽음. 이미 설정된 키는 .env가 덮어쓰지 않음)
- 모든 상태 JSON 경로를 임시 디렉터리로 돌리고, 작업 디렉터리도 임시 디렉터리로 바꿉니다.
"""
import copy
import os
import shutil
import sys
import tempfile

import pytest

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 1. 외부 연동 차단 (빈 값 = 미설정 -> 시뮬레이션 모드)
os.environ.update({
    "GOOGLE_SHEET_ENABLED": "false",
    "GCP_SERVICE_ACCOUNT_JSON": "",
    "KIS_APP_KEY": "",
    "KIS_APP_SECRET": "",
    "KIS_CANO": "",
    "KIS_ACCOUNT_PWD": "",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "MOCK_TRADING_ONLY": "true",
    "LOG_TO_FILE": "false",
})

# 2. 임시 작업 디렉터리 (상대경로로 쓰는 상태 파일: completed_trades.json, infinite_trader_state.json 등)
TEST_DATA_DIR = tempfile.mkdtemp(prefix="kis_tests_")
for _name in ("settings.json", "infinite_settings.json", "infinite_trader_state.json", "completed_trades.json",
              "proposals.json", "proposals_fallback.json"):
    _src = os.path.join(ROOT_DIR, _name)
    if os.path.exists(_src):
        shutil.copy2(_src, os.path.join(TEST_DATA_DIR, _name))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 3. 절대경로로 고정된 상태 파일 경로를 임시 디렉터리로 교체
import core.config.domestic as _domestic  # noqa: E402
import core.config.infinite as _infinite  # noqa: E402
import core.position_tracker as _position_tracker  # noqa: E402
import screener as _screener  # noqa: E402
import telegram_notifier as _telegram_notifier  # noqa: E402


def _tmp(name: str) -> str:
    return os.path.join(TEST_DATA_DIR, name)


_domestic.SETTINGS_FILE = _tmp("settings.json")
_infinite.SETTINGS_FILE = _tmp("infinite_settings.json")
_position_tracker.POSITIONS_STATE_FILE = _tmp("positions_state.json")
_position_tracker.COOLDOWN_FILE = _tmp("cooldown.json")
_position_tracker.PositionTracker.__init__.__defaults__ = (_tmp("positions_state.json"), _tmp("cooldown.json"))
_screener.POSITIONS_STATE_FILE = _tmp("positions_state.json")
_screener.COOLDOWN_FILE = _tmp("cooldown.json")
_screener.PROPOSALS_FILE = _tmp("proposals.json")
_screener.PROPOSALS_FALLBACK_FILE = _tmp("proposals_fallback.json")
_screener.EXECUTED_BUY_ORDERS_FILE = _tmp("executed_buy_orders.json")
_telegram_notifier.SELL_NOTIFY_HISTORY_FILE = _tmp("sell_notify_history.json")


@pytest.fixture(autouse=True)
def _restore_global_settings():
    """테스트가 전역 설정(CURRENT_SETTINGS)을 변경해도 다음 테스트로 누수되지 않도록 복원"""
    snapshot = copy.deepcopy(_domestic.CURRENT_SETTINGS)
    yield
    _domestic.CURRENT_SETTINGS.clear()
    _domestic.CURRENT_SETTINGS.update(snapshot)


def pytest_sessionstart(session):
    os.chdir(TEST_DATA_DIR)


def pytest_sessionfinish(session, exitstatus):
    os.chdir(ROOT_DIR)
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
