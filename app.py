"""
KIS Auto Trader - Unified Control Center
한국투자증권 Open Trading API 기반 알고리즘 주식 자동매매 & 퀀트 관제 터미널
- 🇰🇷 국내 퀀트 트레이딩 (15:10 종가 스크리닝 / 모멘텀 / 볼린저 반등 / 지수선물 헤지)
- 🇺🇸 미국 라오어 무한매수법 v2.0 (LOC 매수 / 분할 적립 / 목표 익절)
"""
import time
import streamlit as st
from ui.flash import flash, render_flash

import app_config as config
from kis_api import KISApiClient, resolve_mock_mode
from screener import StockScreener
from scheduler import start_scheduler, is_scheduler_active
from time_utils import now_str
from ui import (
    apply_custom_styles,
    render_dashboard,
    render_screener,
    render_stock_checker,
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

# 직전 실행에서 st.rerun() 전에 등록한 결과 메시지 표시
render_flash()

# 기본 네비게이션 상태 초기화
if "nav_page" not in st.session_state or st.session_state["nav_page"] not in ["dashboard", "infinite", "screener", "stock_checker", "backtest", "settings"]:
    st.session_state["nav_page"] = "dashboard"

# 백그라운드 스케줄러 초기화 (앱 실행 중 1회만 등록)
@st.cache_resource
def get_system_scheduler():
    config.sync_settings_from_google_sheet()
    try:
        from core.config.infinite import load_settings_from_google_sheet as load_infinite_sheet_settings
        load_infinite_sheet_settings()
    except Exception as e_inf:
        config.logger.debug(f"무한매수 구글 시트 설정 동기화 생략: {e_inf}")
    return start_scheduler()

try:
    scheduler = get_system_scheduler()
except Exception as e:
    scheduler = None

# 공용 KIS API 클라이언트 싱글톤 인스턴스
# 모의/실전 모드가 바뀌면 기존 클라이언트·스크리너를 폐기하고 새 모드로 재생성
if "kis_api" not in st.session_state or st.session_state["kis_api"].mock != resolve_mock_mode():
    st.session_state["kis_api"] = KISApiClient()
    st.session_state.pop("screener", None)
api: KISApiClient = st.session_state["kis_api"]

token_ok = api.get_access_token()
if not token_ok:
    st.warning("⚠️ KIS API 토큰 발급에 실패했습니다. 네트워크 및 API 키 설정을 확인하세요.")

# 국내 퀀트 스크리너 인스턴스 (모듈 갱신 시 자동 재할당)
if "screener" not in st.session_state or type(st.session_state.get("screener")) is not StockScreener:
    st.session_state["screener"] = StockScreener(api)
screener = st.session_state["screener"]

# 실시간 매도 신호 감지 fragment (5분 주기 - 고속 리스크 감시)
@st.fragment(run_every=60)
def realtime_detection_fragment():
    last_check = st.session_state.get("last_realtime_check", 0.0)
    now_ts = time.time()
    if now_ts - last_check >= 300:
        st.session_state["last_realtime_check"] = now_ts
        # 장중(09:05~15:05)에는 백그라운드 스케줄러가 5분 감시를 수행하므로 결과 화면 갱신만 수행
        hm = int(now_str("%H%M"))
        if is_scheduler_active() and 905 <= hm <= 1505:
            st.session_state["last_check_time"] = StockScreener.load_proposals(force_sheet_sync=False).get("sell_checked_at", "-")
            st.rerun()
        with st.spinner("⚡ 5분 주기 고속 리스크 감시 중 (손익·트레일링스탑)..."):
            active_screener = st.session_state.get("screener")
            if active_screener is None or type(active_screener) is not StockScreener:
                active_screener = StockScreener(api)
                st.session_state["screener"] = active_screener
            updated = active_screener.check_sell_signals_now(fast_mode=True)

            st.session_state["last_check_time"] = now_str("%H:%M:%S")
            flash(f"고속 감시 완료: {len(updated.get('sell_proposals', []))}건의 리스크 신호 감지", icon="⚡")
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
    
    # 실제 주문이 나가는 API 클라이언트의 모드를 그대로 표시
    is_mock = api.mock
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

    # 6대 핵심 통합 네비게이션 메뉴
    st.markdown("<div class='nav-header'>🧭 NAVIGATION • 메인 메뉴</div>", unsafe_allow_html=True)
    main_menu = [
        ("dashboard", "📊 국내 자산 & 포트폴리오"),
        ("screener", "🎯 15:10 종가 스크리닝"),
        ("stock_checker", "🔍 개별 종목 매수 진단"),
        ("infinite", "🇺🇸 미국 라오어 무한매수법"),
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
    if st.button("🔄 데이터 즉시 새로고침", key="sidebar_force_refresh", width="stretch", help="캐시를 무효화하고 한국투자증권 실시간 잔고 및 데이터를 즉시 다시 불러옵니다."):
        st.session_state["force_refresh_balance"] = True
        st.rerun()
    st.caption("KIS Auto Trading Engine • Unified Terminal v3.0")

# ==============================================================================
# 캐시 기반 계좌 및 제안서 데이터 로더 (반응성 최적화)
# ==============================================================================
def get_cached_account_balance(api_client: KISApiClient, ttl_seconds: float = 30.0, force: bool = False):
    """30초 TTL 세션 캐시 기반 잔고 조회 (무조건적인 KIS API 동기 호출 방지)"""
    now_ts = time.time()
    last_fetch = st.session_state.get("last_balance_fetch_ts", 0.0)
    cached_bal = st.session_state.get("cached_balance_data")

    if not force and cached_bal and (now_ts - last_fetch < ttl_seconds):
        return cached_bal

    # API 호출
    balance_data = api_client.get_account_balance()
    summary = balance_data.get("summary", {})
    holdings = balance_data.get("holdings", [])

    is_zero = (
        balance_data.get("rt_cd") != "0" or
        (summary.get("tot_asset", 0) == 0 and summary.get("cash_balance", 0) == 0)
    )
    if is_zero:
        time.sleep(0.2)
        retry_bal = api_client.get_account_balance()
        if retry_bal.get("rt_cd") == "0" and (
            retry_bal.get("summary", {}).get("tot_asset", 0) > 0 or
            retry_bal.get("summary", {}).get("cash_balance", 0) > 0
        ):
            balance_data = retry_bal

    # 정상 데이터 수신 시 캐시 저장, 실패 시 이전 캐시 유지
    new_summary = balance_data.get("summary", {})
    if new_summary.get("tot_asset", 0) > 0 or new_summary.get("cash_balance", 0) > 0 or len(balance_data.get("holdings", [])) > 0:
        st.session_state["cached_balance_data"] = balance_data
        st.session_state["last_balance_fetch_ts"] = now_ts
        return balance_data
    elif cached_bal:
        return cached_bal

    st.session_state["cached_balance_data"] = balance_data
    st.session_state["last_balance_fetch_ts"] = now_ts
    return balance_data

def get_cached_proposals(screener_inst: StockScreener, ttl_seconds: float = 15.0, force: bool = False):
    """15초 TTL 세션 캐시 기반 제안서 파일 로더 (불필요한 반복 디스크 I/O 방지)"""
    now_ts = time.time()
    last_fetch = st.session_state.get("last_proposals_fetch_ts", 0.0)
    cached_props = st.session_state.get("cached_proposals_data")

    if not force and cached_props and (now_ts - last_fetch < ttl_seconds):
        return cached_props

    props = screener_inst.load_proposals()
    st.session_state["cached_proposals_data"] = props
    st.session_state["last_proposals_fetch_ts"] = now_ts
    return props

# 메인 뷰 라우팅 결정
current_page = st.session_state["nav_page"]

# dashboard, screener, stock_checker 페이지에서만 국내 잔고 및 제안서 로드
force_refresh = st.session_state.pop("force_refresh_balance", False)
if current_page in ["dashboard", "screener", "stock_checker"]:
    balance_data = get_cached_account_balance(api, ttl_seconds=30.0, force=force_refresh)
    summary = balance_data.get("summary", {})
    holdings = balance_data.get("holdings", [])
    proposals = get_cached_proposals(screener, ttl_seconds=15.0, force=force_refresh)

    holding_codes = {h.get("code") for h in holdings if isinstance(h, dict) and h.get("code")}
    if proposals.get("sell_proposals"):
        proposals["sell_proposals"] = [
            s for s in proposals["sell_proposals"]
            if isinstance(s, dict) and s.get("code") in holding_codes
        ]
else:
    summary = {}
    holdings = []
    proposals = {}
    holding_codes = set()

# ==============================================================================
# 메인 뷰 라우팅
# ==============================================================================
current_page = st.session_state["nav_page"]

if current_page == "dashboard":
    render_dashboard(api, screener, summary, holdings, proposals, holding_codes, realtime_detection_fragment)
elif current_page == "screener":
    render_screener(api, screener, proposals, holding_codes)
elif current_page == "stock_checker":
    render_stock_checker(api, screener, holding_codes)
elif current_page == "infinite":
    render_infinite()
elif current_page == "backtest":
    render_backtest()
elif current_page == "settings":
    render_settings()

