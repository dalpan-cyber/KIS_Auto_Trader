"""
KIS Auto Trader - Unified Control Center
한국투자증권 Open Trading API 기반 알고리즘 주식 자동매매 & 퀀트 관제 터미널
- 🇰🇷 국내 퀀트 트레이딩 (15:10 종가 스크리닝 / 모멘텀 / 볼린저 반등 / 지수선물 헤지)
- 🇺🇸 미국 라오어 무한매수법 v2.0 (LOC 매수 / 분할 적립 / 목표 익절)
"""
import time
import streamlit as st

import app_config as config
from kis_api import KISApiClient
from screener import StockScreener
from scheduler import start_scheduler
from time_utils import now_str
from ui import (
    apply_custom_styles,
    render_dashboard,
    render_screener,
    render_backtest,
    render_settings,
    render_infinite
)

# 기본 페이지 레이아웃 설정
st.set_page_config(
    page_title="KIS Unified Auto Trader",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 커스텀 테마 및 스타일 적용
apply_custom_styles()

# 기본 네비게이션 상태 초기화
if "nav_page" not in st.session_state or st.session_state["nav_page"] not in ["dashboard", "infinite", "screener", "backtest", "settings"]:
    st.session_state["nav_page"] = "dashboard"

# 백그라운드 스케줄러 초기화 (앱 실행 중 1회만 등록)
@st.cache_resource
def get_system_scheduler():
    config.sync_settings_from_google_sheet()
    return start_scheduler()

try:
    scheduler = get_system_scheduler()
except Exception as e:
    scheduler = None

# 공용 KIS API 클라이언트 싱글톤 인스턴스
if "kis_api" not in st.session_state:
    st.session_state["kis_api"] = KISApiClient()
api: KISApiClient = st.session_state["kis_api"]

token_ok = api.get_access_token()
if not token_ok:
    st.warning("⚠️ KIS API 토큰 발급에 실패했습니다. 네트워크 및 API 키 설정을 확인하세요.")

# 국내 퀀트 스크리너 인스턴스
if "screener" not in st.session_state:
    st.session_state["screener"] = StockScreener(api)
screener = st.session_state["screener"]

# 실시간 매도 신호 감지 fragment (5분 주기 - 고속 리스크 감시)
@st.fragment(run_every=60)
def realtime_detection_fragment():
    last_check = st.session_state.get("last_realtime_check", 0.0)
    now_ts = time.time()
    if now_ts - last_check >= 300:
        st.session_state["last_realtime_check"] = now_ts
        with st.spinner("⚡ 5분 주기 고속 리스크 감시 중 (손익·트레일링스탑)..."):
            updated = screener.check_sell_signals_now(fast_mode=True)
            st.session_state["last_check_time"] = now_str("%H:%M:%S")
            st.success(f"⚡ 고속 감시 완료: {len(updated.get('sell_proposals', []))}건의 리스크 신호 감지")
            time.sleep(1)
            st.rerun()
    else:
        st.caption("⏳ 5분 주기로 고속 리스크 감시가 실행됩니다. (손절·목표익절·트레일링스탑 즉시 체크)")

# ==============================================================================
# 통합 사이드바 (Unified Navigation)
# ==============================================================================
with st.sidebar:
    st.markdown("""
        <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 8px;">
            <div style="background: linear-gradient(135deg, #0284c7, #6366f1); padding: 8px; border-radius: 10px; display: flex; align-items: center; justify-content: center;">
                <span style="font-size: 1.3rem;">⚡</span>
            </div>
            <div>
                <div style="font-size: 1.15rem; font-weight: 800; color: #f8fafc; letter-spacing: -0.02em;">KIS AUTO TERMINAL</div>
                <div style="font-size: 0.7rem; color: #64748b; font-weight: 600; letter-spacing: 0.05em;">DOMESTIC & OVERSEAS UNIFIED</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    is_mock = config.CURRENT_SETTINGS.get("mock_trading", True)
    if is_mock:
        st.markdown("<div class='badge-mock'><span class='status-dot dot-mock'></span>VTS SIMULATION ACTIVE</div>", unsafe_allow_html=True)
    else:
        st.markdown("<div class='badge-real'><span class='status-dot dot-real'></span>LIVE TRADING ACTIVE</div>", unsafe_allow_html=True)
        
    st.markdown(f"""
        <div class="sidebar-account-box">
            <div style="font-size: 0.72rem; color: #64748b; font-weight: 600;">ACTIVE ACCOUNT</div>
            <div style="font-size: 0.88rem; font-weight: 700; color: #e2e8f0; font-family: monospace;">{config.CANO}-{config.ACNT_PRDT_CD}</div>
            <div style="font-size: 0.72rem; color: #94a3b8; margin-top: 4px;">🇰🇷 국내 종가 15:10 | 🇺🇸 미국 개장 22:30</div>
        </div>
    """, unsafe_allow_html=True)

    # 5대 핵심 통합 네비게이션 메뉴
    st.markdown("<div class='nav-header'>🧭 NAVIGATION • 메인 메뉴</div>", unsafe_allow_html=True)
    main_menu = [
        ("dashboard", "📊 국내 자산 & 포트폴리오"),
        ("infinite", "🇺🇸 미국 라오어 무한매수법"),
        ("screener", "🎯 15:10 종가 스크리닝"),
        ("backtest", "🧪 퀀트 백테스터"),
        ("settings", "⚙️ 시스템 환경설정")
    ]

    for key, label in main_menu:
        is_active = (st.session_state["nav_page"] == key)
        if st.button(
            label,
            key=f"nav_btn_{key}",
            type="primary" if is_active else "secondary",
            width="stretch"
        ):
            st.session_state["nav_page"] = key
            st.rerun()

    st.divider()
    st.caption("KIS Auto Trading Engine • Unified Terminal v3.0")

# 계좌 및 제안서 데이터 조회
balance_data = api.get_account_balance()
summary = balance_data.get("summary", {})
holdings = balance_data.get("holdings", [])

is_zero_balance = (
    balance_data.get("rt_cd") != "0" or
    (summary.get("tot_asset", 0) == 0 and summary.get("cash_balance", 0) == 0)
)
if is_zero_balance:
    time.sleep(0.3)
    retry_balance = api.get_account_balance()
    if retry_balance.get("rt_cd") == "0" and (
        retry_balance.get("summary", {}).get("tot_asset", 0) > 0 or
        retry_balance.get("summary", {}).get("cash_balance", 0) > 0
    ):
        balance_data = retry_balance
        summary = balance_data.get("summary", {})
        holdings = balance_data.get("holdings", [])

# 정상 수신된 잔고 데이터는 세션에 캐싱 (이후 일시적 API 지연 시 0원 노출 방지 fallback)
if summary.get("tot_asset", 0) > 0 or summary.get("cash_balance", 0) > 0 or len(holdings) > 0:
    st.session_state["cached_summary"] = summary
    st.session_state["cached_holdings"] = holdings
elif "cached_summary" in st.session_state:
    summary = st.session_state["cached_summary"]
    holdings = st.session_state.get("cached_holdings", holdings)

proposals = screener.load_proposals()

# 매도 추천에서 이미 매도 완료된 종목 제외
holding_codes = {h.get("code") for h in holdings if isinstance(h, dict) and h.get("code")}
if proposals.get("sell_proposals"):
    proposals["sell_proposals"] = [
        s for s in proposals["sell_proposals"]
        if isinstance(s, dict) and s.get("code") in holding_codes
    ]

# ==============================================================================
# 메인 뷰 라우팅
# ==============================================================================
current_page = st.session_state["nav_page"]

if current_page == "dashboard":
    render_dashboard(api, screener, summary, holdings, proposals, holding_codes, realtime_detection_fragment)
elif current_page == "infinite":
    render_infinite()
elif current_page == "screener":
    render_screener(api, screener, proposals, holding_codes)
elif current_page == "backtest":
    render_backtest()
elif current_page == "settings":
    render_settings()

