"""
KIS Auto Trading - Domestic Quant Configuration Module (core/config/domestic.py)
국내 퀀트 트레이딩 설정, 시장 국면 프리셋(BULL/VOLATILE/BEAR/AUTO), settings.json 및 구글 시트 동기화
"""
import os
import json
import logging
import threading
from typing import Any, Dict, Optional, List
from core.storage import safe_load_json, atomic_save_json
from .common import (
    APP_KEY, APP_SECRET, CANO, ACNT_PRDT_CD, ACCOUNT_PWD,
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID,
    URL_BASE_MOCK, URL_BASE_REAL,
    GOOGLE_SHEET_ENABLED, GCP_SERVICE_ACCOUNT_JSON,
    _get_env_or_secret, logger
)

# 설정 파일 경로
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SETTINGS_FILE = os.path.join(_PROJECT_ROOT, "settings.json")
if not os.path.exists(SETTINGS_FILE) and os.path.exists("settings.json"):
    SETTINGS_FILE = "settings.json"

# Google Sheets 국내 퀀트 시트 설정
DOMESTIC_GOOGLE_SHEET_NAME = _get_env_or_secret("DOMESTIC_GOOGLE_SHEET_NAME", _get_env_or_secret("GOOGLE_SHEET_NAME", "KIS_Auto2_매매일지"))
DOMESTIC_GOOGLE_SHEET_KEY = _get_env_or_secret("DOMESTIC_GOOGLE_SHEET_KEY", _get_env_or_secret("GOOGLE_SHEET_KEY", ""))
GOOGLE_SHEET_NAME = DOMESTIC_GOOGLE_SHEET_NAME
GOOGLE_SHEET_KEY = DOMESTIC_GOOGLE_SHEET_KEY

# ==============================================================================
# 시장 국면별 3대 프리셋 정의 (Market Regime Presets)
# ==============================================================================
MARKET_REGIME_PRESETS: Dict[str, Dict[str, Any]] = {
    "BULL": {
        "name": "🔥 상승장 모드 (Bull Trend)",
        "description": "추세 추종 및 이익 극대화 (목표익절 +8%~+10%, 20일선 트레일링, ATR 2.2배 손절 -5.0%, 타임컷 12일)",
        "target_profit_rate": 0.08,
        "stop_loss_rate": -0.05,
        "trailing_stop_pct": 0.06,
        "time_stop_days": 12,
        "time_stop_min_profit": 0.02,
        "buy_score_threshold": 60,
        "market_regime_cutoff_normal": 60,
        "market_regime_cutoff_weak": 75,
        "max_daily_buy_count": 3,
        "atr_stop_loss_multiple": 2.2,
        "atr_stop_loss_min_pct": -0.055,
        "atr_stop_loss_max_pct": -0.035
    },
    "VOLATILE": {
        "name": "⚡ 변동성/횡보장 모드 (Volatile)",
        "description": "박스권 순환매 & 빠른 차익 실현 (목표익절 +5%, 트레일링 3.5%, 손절 -3.5%, 타임컷 6일)",
        "target_profit_rate": 0.05,
        "stop_loss_rate": -0.035,
        "trailing_stop_pct": 0.035,
        "time_stop_days": 6,
        "time_stop_min_profit": 0.02,
        "buy_score_threshold": 65,
        "market_regime_cutoff_normal": 65,
        "market_regime_cutoff_weak": 75,
        "max_daily_buy_count": 2,
        "atr_stop_loss_multiple": 2.0,
        "atr_stop_loss_min_pct": -0.045,
        "atr_stop_loss_max_pct": -0.025
    },
    "BEAR": {
        "name": "🛡️ 하락장/방어 모드 (Bear Defense)",
        "description": "원금 보존 & 타이트한 초긴급 방어 (목표익절 +3%, 트레일링 2.0%, 칼손절 -2.5%, 컷오프 75점, 타임컷 3일)",
        "target_profit_rate": 0.03,
        "stop_loss_rate": -0.025,
        "trailing_stop_pct": 0.02,
        "time_stop_days": 3,
        "time_stop_min_profit": 0.01,
        "buy_score_threshold": 75,
        "market_regime_cutoff_normal": 75,
        "market_regime_cutoff_weak": 80,
        "max_daily_buy_count": 1,
        "atr_stop_loss_multiple": 1.5,
        "atr_stop_loss_min_pct": -0.035,
        "atr_stop_loss_max_pct": -0.020
    }
}

# 기본 전략 및 시스템 파라미터
DEFAULT_SETTINGS: Dict[str, Any] = {
    "mock_trading": True,                    # 모의투자 여부 (True: 모의, False: 실전)
    "regime_preset_mode": "AUTO",            # 국면 모드: 'AUTO'(지수 자동감지), 'BULL', 'VOLATILE', 'BEAR', 'CUSTOM'
    "active_strategies": ["momentum"],       # 활성화된 전략 목록 (다중 선택 지원)
    "strategy_name": "momentum",             # 단일 전략 이름 (하위 호환 유지)
    "strategy_settings": {},                 # 전략별 고유 설정 (예: {"momentum": {...}, "rebound": {...}})
    "monthly_allow_trend_continuation": False, # 월봉 10이평 상회 지속 종목 진입 허용 (False: 신규 골든크로스 종목만 진입)
    "target_profit_rate": 0.08,             # 목표 익절 수익률 (+8.0%)
    "stop_loss_rate": -0.05,                # 손절 수익률 (-5.0%)
    "max_buy_budget_per_stock": 500000,     # 1종목당 최대 매수 한도 (원)
    "max_holding_stocks": 5,                # 최대 보유 종목 수
    "premarket_time": "15:10",              # 종가 매수 스크리닝 시각 (KST)
    "auto_execute_orders": False,           # 주문 완전 자동화 여부 (False: UI 원클릭 승인)
    "telegram_enabled": False,              # 텔레그램 알림 활성화 여부 (기본: OFF)

    # --- 스크리닝 점수 카테고리별 상한 (Cap) 및 파생 수급 ---
    "use_futures_filter": True,             # 개별주식선물 수급 분석 활성화 여부 (베이시스/미결제약정 4번째 군 최대 20점)
    "score_cap_trend": 40,                  # 추세군(이동평균) 최대 점수 상한
    "score_cap_momentum": 30,               # 모멘텀군(RSI, 볼린저) 최대 점수 상한
    "score_cap_volume": 25,                 # 거래량군 최대 점수 상한
    "score_cap_futures": 20,                # 선행 파생수급군 최대 점수 상한
    "buy_score_threshold": 60,              # 매수 추천 최소 종합 점수 (100점 만점 기준 60점 이상 추천)

    # --- 고도화 1~3단계 설정 (메이저 수급, 동적 유니버스, 체결강도) ---
    "use_investor_filter": True,             # 외인/기관 메이저 수급 반영 및 쌍끌이 순매도 필터
    "investor_double_buy_score": 8,          # 외인·기관 쌍끌이 순매수 가점 (+8점)
    "investor_single_buy_score": 4,          # 외인 또는 기관 단독 순매수 가점 (+4점)
    "dynamic_universe_enabled": True,        # 당일 거래대금 상위 주도주 동적 유니버스 확장
    "dynamic_universe_top_n": 30,            # 거래대금 상위 N개 탐색
    "use_volume_power_gate": True,           # 15:10 체결강도 안전 게이트 활성화 여부
    "min_volume_power": 110.0,               # 최소 체결강도 기준 (110.0%)

    # --- 실시간 봉 반영 설정 ---
    "use_realtime_candle": False,           # 실시간 현재가를 일봉에 반영할지 여부 (False: 완성봉만 사용)

    # --- 분할 매도 및 트레일링 스탑 설정 ---
    "partial_sell_ratio": 0.5,              # 1차 익절 시 매도 비율 (50%)
    "trailing_stop_pct": 0.06,              # 1차 익절 후 최고가 대비 트레일링 스탑 비율 (6.0%)
    "rsi_overbought_sell": False,           # RSI 과열 시 전량 매도 여부 (False: 분할 매도만)

    # --- 타임컷 (Time-based Exit / 기간 청산) ---
    "time_stop_enabled": True,              # 타임컷 청산 활성화
    "time_stop_days": 12,                   # 타임컷 보유 일수 (12영업일)
    "time_stop_min_profit": 0.02,           # 타임컷 기준 최소 수익률 (+2%)

    # --- 1일 최대 신규 매수 제한 ---
    "max_daily_buy_count": 2,               # 1일 최대 신규 매수 종목 수 (집단 갭하락 리스크 방어)

    # --- 변동성 조절 포지션 사이징 ---
    "volatility_sizing_enabled": True,      # ATR 기반 변동성 조절 포지션 사이징 활성화
    "atr_period": 14,                       # ATR 계산 기간
    "risk_per_trade": 0.01,                 # 1회 거래당 리스크 비율 (계좌 대비 1%)
    "atr_stop_multiple": 2.2,               # ATR 기반 손절 배수 (2.2배 ATR)
    "max_position_ratio": 0.3,              # 1종목당 최대 포지션 비율 (계좌 대비 30%)
    "min_position_ratio": 0.05,             # 1종목당 최소 포지션 비율 (계좌 대비 5%)

    # --- 시장 국면 필터 (Market Regime Filter) ---
    "market_regime_filter_enabled": True,   # 시장 국면 필터 활성화
    "market_regime_ma_period": 20,          # 시장 국면 판단 이동평균 기간 (20일)
    "market_regime_cutoff_normal": 60,      # 정상 국면 매수 점수 컷오프 (100점 만점 기준)
    "market_regime_cutoff_weak": 75,        # 약세 국면 매수 점수 컷오프 (상향)
    "market_regime_block_weak": False,       # 약세 국면 신규 진입 전면 차단 여부

    # --- 손절 종목 쿨다운 (Cool-down) ---
    "cooldown_enabled": True,               # 손절 종목 쿨다운 활성화
    "cooldown_days": 4,                     # 손절 후 재매수 금지 기간 (거래일 기준 4일)

    # --- ATR 동적 손절 (변동성 기반 손절가) ---
    "atr_stop_loss_enabled": True,          # ATR 기반 동적 손절 활성화
    "atr_stop_loss_multiple": 2.2,          # ATR 손절 배수 (진입가 - 2.2×ATR)
    "atr_stop_loss_min_pct": -0.055,        # ATR 손절 최소 허용 손실률 (-5.5% 하한)
    "atr_stop_loss_max_pct": -0.035,        # ATR 손절 최대 허용 손실률 (-3.5% 상한)
    "atr_stop_loss_use_low_break": True,    # 당일 저가 이탈 시 손절 적용 여부
    "watchlist": [
        {"code": "005930", "name": "삼성전자", "market": "KOSPI"},
        {"code": "000660", "name": "SK하이닉스", "market": "KOSPI"},
        {"code": "373220", "name": "LG에너지솔루션", "market": "KOSPI"},
        {"code": "207940", "name": "삼성바이오로직스", "market": "KOSPI"},
        {"code": "005380", "name": "현대차", "market": "KOSPI"},
        {"code": "000270", "name": "기아", "market": "KOSPI"},
        {"code": "068270", "name": "셀트리온", "market": "KOSPI"},
        {"code": "035420", "name": "NAVER", "market": "KOSPI"},
        {"code": "105560", "name": "KB금융", "market": "KOSPI"},
        {"code": "055550", "name": "신한지주", "market": "KOSPI"},
        {"code": "005490", "name": "POSCO홀딩스", "market": "KOSPI"},
        {"code": "012330", "name": "현대모비스", "market": "KOSPI"},
        {"code": "006400", "name": "삼성SDI", "market": "KOSPI"},
        {"code": "051910", "name": "LG화학", "market": "KOSPI"},
        {"code": "028260", "name": "삼성물산", "market": "KOSPI"},
        {"code": "086790", "name": "하나금융지주", "market": "KOSPI"},
        {"code": "035720", "name": "카카오", "market": "KOSPI"},
        {"code": "010130", "name": "고려아연", "market": "KOSPI"},
        {"code": "003670", "name": "포스코퓨처엠", "market": "KOSPI"},
        {"code": "032830", "name": "삼성생명", "market": "KOSPI"},
        {"code": "012450", "name": "한화에어로스페이스", "market": "KOSPI"},
        {"code": "011200", "name": "HMM", "market": "KOSPI"},
        {"code": "066570", "name": "LG전자", "market": "KOSPI"},
        {"code": "009150", "name": "삼성전기", "market": "KOSPI"},
        {"code": "010950", "name": "S-Oil", "market": "KOSPI"},
        {"code": "034020", "name": "두산에너빌리티", "market": "KOSPI"},
        {"code": "018260", "name": "삼성에스디에스", "market": "KOSPI"},
        {"code": "003550", "name": "LG", "market": "KOSPI"},
        {"code": "033780", "name": "KT&G", "market": "KOSPI"},
        {"code": "000810", "name": "삼성화재", "market": "KOSPI"},
        {"code": "017670", "name": "SK텔레콤", "market": "KOSPI"},
        {"code": "030200", "name": "KT", "market": "KOSPI"},
        {"code": "090430", "name": "아모레퍼시픽", "market": "KOSPI"},
        {"code": "015760", "name": "한국전력", "market": "KOSPI"},
        {"code": "024110", "name": "기업은행", "market": "KOSPI"},
        {"code": "316140", "name": "우리금융지주", "market": "KOSPI"},
        {"code": "000100", "name": "유한양행", "market": "KOSPI"},
        {"code": "071050", "name": "한국금융지주", "market": "KOSPI"},
        {"code": "003490", "name": "대한항공", "market": "KOSPI"},
        {"code": "034730", "name": "SK", "market": "KOSPI"},
        {"code": "096770", "name": "SK이노베이션", "market": "KOSPI"},
        {"code": "326030", "name": "SK바이오팜", "market": "KOSPI"},
        {"code": "329180", "name": "HD현대중공업", "market": "KOSPI"},
        {"code": "042660", "name": "한화오션", "market": "KOSPI"},
        {"code": "010140", "name": "삼성중공업", "market": "KOSPI"},
        {"code": "047810", "name": "한국항공우주", "market": "KOSPI"},
        {"code": "086280", "name": "현대글로비스", "market": "KOSPI"},
        {"code": "042700", "name": "한미반도체", "market": "KOSPI"},
        {"code": "259960", "name": "크래프톤", "market": "KOSPI"},
        {"code": "352820", "name": "하이브", "market": "KOSPI"},
        {"code": "247540", "name": "에코프로비엠", "market": "KOSDAQ"},
        {"code": "086520", "name": "에코프로", "market": "KOSDAQ"},
        {"code": "028300", "name": "HLB", "market": "KOSDAQ"},
        {"code": "058470", "name": "리노공업", "market": "KOSDAQ"},
        {"code": "277810", "name": "레인보우로보틱스", "market": "KOSDAQ"},
        {"code": "196170", "name": "알테오젠", "market": "KOSDAQ"},
        {"code": "068760", "name": "셀트리온제약", "market": "KOSDAQ"},
        {"code": "214150", "name": "클래시스", "market": "KOSDAQ"},
        {"code": "293490", "name": "카카오게임즈", "market": "KOSDAQ"},
        {"code": "035900", "name": "JYP Ent.", "market": "KOSDAQ"},
        {"code": "041510", "name": "에스엠", "market": "KOSDAQ"},
        {"code": "263750", "name": "펄어비스", "market": "KOSDAQ"},
        {"code": "039030", "name": "이오테크닉스", "market": "KOSDAQ"},
        {"code": "036540", "name": "SFA반도체", "market": "KOSDAQ"},
        {"code": "241560", "name": "두산밥캣", "market": "KOSPI"},
        {"code": "131970", "name": "두산테스나", "market": "KOSDAQ"},
        {"code": "095610", "name": "테스", "market": "KOSDAQ"},
        {"code": "000080", "name": "하이트진로", "market": "KOSPI"},
        {"code": "000250", "name": "삼천당제약", "market": "KOSDAQ"},
        {"code": "000990", "name": "DB하이텍", "market": "KOSPI"},
        {"code": "004020", "name": "현대제철", "market": "KOSPI"},
        {"code": "005420", "name": "코스모화학", "market": "KOSPI"},
        {"code": "006800", "name": "미래에셋증권", "market": "KOSPI"},
        {"code": "011070", "name": "LG이노텍", "market": "KOSPI"},
        {"code": "034220", "name": "LG디스플레이", "market": "KOSPI"},
        {"code": "036570", "name": "엔씨소프트", "market": "KOSPI"},
        {"code": "039490", "name": "키움증권", "market": "KOSPI"},
        {"code": "047050", "name": "포스코인터내셔널", "market": "KOSPI"},
        {"code": "051900", "name": "LG생활건강", "market": "KOSPI"},
        {"code": "064350", "name": "현대로템", "market": "KOSPI"},
        {"code": "066970", "name": "엘앤에프", "market": "KOSDAQ"},
        {"code": "067310", "name": "하나마이크론", "market": "KOSDAQ"},
        {"code": "086900", "name": "메디톡스", "market": "KOSDAQ"},
        {"code": "097950", "name": "CJ제일제당", "market": "KOSPI"},
        {"code": "122870", "name": "와이지엔터테인먼트", "market": "KOSDAQ"},
        {"code": "128940", "name": "한미약품", "market": "KOSPI"},
        {"code": "138040", "name": "메리츠금융지주", "market": "KOSPI"},
        {"code": "141080", "name": "레고켐바이오", "market": "KOSDAQ"},
        {"code": "145020", "name": "휴젤", "market": "KOSDAQ"},
        {"code": "237690", "name": "에스티팜", "market": "KOSDAQ"},
        {"code": "251270", "name": "넷마블", "market": "KOSPI"},
        {"code": "267260", "name": "HD현대일렉트릭", "market": "KOSPI"},
        {"code": "302440", "name": "SK바이오사이언스", "market": "KOSPI"},
        {"code": "348370", "name": "엔켐", "market": "KOSDAQ"},
        {"code": "403870", "name": "HPSP", "market": "KOSDAQ"},
        {"code": "450080", "name": "에코프로머티", "market": "KOSPI"},
        {"code": "454910", "name": "두산로보틱스", "market": "KOSPI"},
        {"code": "069500", "name": "KODEX 200", "market": "ETF"},
        {"code": "122630", "name": "KODEX 레버리지", "market": "ETF"},
        {"code": "233740", "name": "KODEX 코스닥150레버리지", "market": "ETF"},
        {"code": "114800", "name": "KODEX 인버스", "market": "ETF"},
        {"code": "009540", "name": "HD한국조선해양", "market": "KOSPI"},
        {"code": "298040", "name": "효성중공업", "market": "KOSPI"},
        {"code": "402340", "name": "SK스퀘어", "market": "KOSPI"},
        {"code": "009830", "name": "한화솔루션", "market": "KOSPI"},
        {"code": "021240", "name": "코웨이", "market": "KOSPI"},
        {"code": "000120", "name": "CJ대한통운", "market": "KOSPI"},
        {"code": "001040", "name": "CJ", "market": "KOSPI"},
        {"code": "078930", "name": "GS", "market": "KOSPI"},
        {"code": "011170", "name": "롯데케미칼", "market": "KOSPI"},
        {"code": "004170", "name": "신세계", "market": "KOSPI"},
        {"code": "000720", "name": "현대건설", "market": "KOSPI"},
        {"code": "005830", "name": "DB손해보험", "market": "KOSPI"},
        {"code": "001450", "name": "현대해상", "market": "KOSPI"},
        {"code": "004990", "name": "롯데지주", "market": "KOSPI"},
        {"code": "029780", "name": "삼성카드", "market": "KOSPI"},
        {"code": "036460", "name": "한국가스공사", "market": "KOSPI"},
        {"code": "079550", "name": "LIG넥스원", "market": "KOSPI"},
        {"code": "011780", "name": "금호석유", "market": "KOSPI"},
        {"code": "012750", "name": "에스원", "market": "KOSPI"},
        {"code": "004370", "name": "농심", "market": "KOSPI"},
        {"code": "271560", "name": "오리온", "market": "KOSPI"},
        {"code": "008770", "name": "호텔신라", "market": "KOSPI"},
        {"code": "030000", "name": "제일기획", "market": "KOSPI"},
        {"code": "005940", "name": "NH투자증권", "market": "KOSPI"},
        {"code": "014680", "name": "한솔케미칼", "market": "KOSPI"},
        {"code": "007070", "name": "GS리테일", "market": "KOSPI"},
        {"code": "002790", "name": "아모레G", "market": "KOSPI"},
        {"code": "006260", "name": "LS", "market": "KOSPI"},
        {"code": "000150", "name": "두산", "market": "KOSPI"}
    ]
}

_settings_lock = threading.Lock()
_cached_settings: Optional[Dict[str, Any]] = None


def load_settings() -> Dict[str, Any]:
    global _cached_settings
    with _settings_lock:
        if _cached_settings is not None:
            return _cached_settings

        loaded = safe_load_json(SETTINGS_FILE, default=None)
        if loaded is None or not isinstance(loaded, dict) or not loaded:
            _cached_settings = DEFAULT_SETTINGS.copy()
            atomic_save_json(SETTINGS_FILE, _cached_settings)
            return _cached_settings

        merged = DEFAULT_SETTINGS.copy()
        merged.update(loaded)

        if "active_strategies" not in merged or not merged["active_strategies"]:
            single = merged.get("strategy_name", "momentum")
            merged["active_strategies"] = [single] if single else ["momentum"]

        # Google Sheets 'Settings' 탭에서 최신 설정값 오버라이드
        try:
            from core.sheets.domestic_sheet_manager import get_domestic_sheet_manager
            sheet_mgr = get_domestic_sheet_manager()
            if sheet_mgr.is_connected:
                sheet_settings = sheet_mgr.read_settings_from_sheet()
                if sheet_settings:
                    merged.update(sheet_settings)
        except Exception as e:
            logger.debug(f"Google Sheet 설정값 로드 생략: {e}")

        _cached_settings = merged
        return _cached_settings


def save_settings(new_settings: Dict[str, Any]) -> bool:
    global _cached_settings
    with _settings_lock:
        merged = DEFAULT_SETTINGS.copy()
        merged.update(new_settings)
        ok = atomic_save_json(SETTINGS_FILE, merged)
        if ok:
            # 기존 CURRENT_SETTINGS dict를 in-place로 갱신
            CURRENT_SETTINGS.clear()
            CURRENT_SETTINGS.update(merged)
            _cached_settings = CURRENT_SETTINGS

            # Google Sheets 'Settings' 탭에 동기화
            try:
                from core.sheets.domestic_sheet_manager import get_domestic_sheet_manager
                sheet_mgr = get_domestic_sheet_manager()
                if sheet_mgr.is_connected:
                    sheet_mgr.sync_settings_to_sheet(merged)
            except Exception as e:
                logger.debug(f"Google Sheet 설정값 저장 동기화 생략: {e}")

        return ok


def get_effective_settings_for_regime(detected_regime: str, base_settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    현재 설정 모드에 따른 최종 유효 전략 파라미터 반환:
    - regime_preset_mode == 'AUTO': 감지된 국면(BULL/VOLATILE/BEAR)의 프리셋을 로드 후 사용자 오버라이드 적용
    - regime_preset_mode in ('BULL', 'VOLATILE', 'BEAR'): 해당 고정 프리셋 적용 후 오버라이드 적용
    - regime_preset_mode == 'CUSTOM': 사용자 설정 우선
    """
    current = load_settings().copy()
    user_settings = (base_settings or {}).copy()
    mode = user_settings.get("regime_preset_mode", current.get("regime_preset_mode", "AUTO"))

    resolved = current.copy()
    target_preset_key = None
    if mode == "AUTO":
        target_preset_key = detected_regime.upper()
    elif mode in MARKET_REGIME_PRESETS:
        target_preset_key = mode

    if target_preset_key and target_preset_key in MARKET_REGIME_PRESETS:
        preset_values = MARKET_REGIME_PRESETS[target_preset_key]
        for k, v in preset_values.items():
            if k not in ["name", "description"]:
                resolved[k] = v
        resolved["_active_regime_name"] = preset_values.get("name", target_preset_key)

    resolved.update(user_settings)
    return resolved


def get_strategy_settings(strategy_name: Optional[str] = None) -> Dict[str, Any]:
    """특정 전략의 고유 설정 dict 반환"""
    name = strategy_name or CURRENT_SETTINGS.get("strategy_name", "momentum")
    strategy_settings = CURRENT_SETTINGS.get("strategy_settings", {}) or {}
    return dict(strategy_settings.get(name, {}))


def get_effective_strategy_settings(
    strategy_name: Optional[str] = None,
    base_settings: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """전략별 고유 설정을 전역 설정에 병합한 최종 유효 설정 반환"""
    name = strategy_name or CURRENT_SETTINGS.get("strategy_name", "momentum")
    base = base_settings.copy() if base_settings is not None else CURRENT_SETTINGS.copy()
    base.pop("strategy_settings", None)

    # 1. 전략 클래스의 스키마 기본값(defaults) 우선 병합 (각 전략마다 고유 기본값이 다를 수 있음)
    try:
        from core.strategy import get_strategy_settings_defaults
        defaults = get_strategy_settings_defaults(name)
        if defaults:
            base.update(defaults)
    except Exception as e:
        logger.debug(f"전략 기본값 스키마 로드 생략: {e}")

    # 2. 사용자가 해당 전략에 개별 설정/저장한 고유 값 병합
    strategy_specific = get_strategy_settings(name)
    base.update(strategy_specific)

    return base


def save_strategy_settings(
    strategy_name: str,
    strategy_settings: Dict[str, Any],
    global_settings: Optional[Dict[str, Any]] = None
) -> bool:
    """특정 전략의 고유 설정을 저장"""
    current = load_settings().copy()
    strategy_map = dict(current.get("strategy_settings", {}) or {})
    strategy_map[strategy_name] = dict(strategy_settings)

    if global_settings is not None:
        merged = current.copy()
        merged.update(global_settings)
        merged["strategy_settings"] = strategy_map
        return save_settings(merged)

    current["strategy_settings"] = strategy_map
    return save_settings(current)


def save_multiple_strategy_settings(
    active_strategies: List[str],
    strategies_settings_map: Dict[str, Dict[str, Any]],
    global_settings: Optional[Dict[str, Any]] = None
) -> bool:
    """여러 활성 전략 목록과 각 전략별 고유 설정 및 전역 설정을 일괄 저장"""
    current = load_settings().copy()
    strategy_map = dict(current.get("strategy_settings", {}) or {})
    for s_name, s_cfg in strategies_settings_map.items():
        if s_name not in strategy_map:
            strategy_map[s_name] = {}
        strategy_map[s_name].update(s_cfg)

    merged = current.copy()
    if global_settings is not None:
        merged.update(global_settings)
    merged["active_strategies"] = list(active_strategies)
    if active_strategies:
        merged["strategy_name"] = active_strategies[0]
    merged["strategy_settings"] = strategy_map
    return save_settings(merged)


CURRENT_SETTINGS = load_settings()


def get_setting(key: str, default: Any = None) -> Any:
    return CURRENT_SETTINGS.get(key, default)


def get_url_base() -> str:
    return URL_BASE_MOCK if CURRENT_SETTINGS.get("mock_trading", True) else URL_BASE_REAL


def sync_settings_from_google_sheet() -> bool:
    """구글 시트 'Settings' 탭의 최신 설정을 읽어와 로컬 캐시 및 CURRENT_SETTINGS에 최우선 반영"""
    try:
        from core.sheets.domestic_sheet_manager import get_domestic_sheet_manager
        sheet_mgr = get_domestic_sheet_manager()
        if sheet_mgr.is_connected:
            sheet_settings = sheet_mgr.read_settings_from_sheet()
            if sheet_settings:
                with _settings_lock:
                    CURRENT_SETTINGS.update(sheet_settings)
                    if _cached_settings is not None:
                        _cached_settings.update(sheet_settings)
                logger.info(f"📊 구글 시트 'Settings'에서 최신 설정값 {len(sheet_settings)}건 반영 완료 (Sheet 최우선 적용)")
                return True
    except Exception as e:
        logger.debug(f"구글 시트 설정 동기화 생략: {e}")
    return False
