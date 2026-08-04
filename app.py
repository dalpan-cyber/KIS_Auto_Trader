"""
한국투자증권 Open Trading API (KIS Developers) Streamlit 자동 투자 대시보드 (app.py)
"""
import time
import logging
import pandas as pd
import numpy as np
import streamlit as st

import config
from kis_api import KISApiClient
from trader import TraderBot
from strategy import Signal, StrategyFactory

# -----------------------------------------------------------------------------
# 1. 페이지 기본 설정 및 디자인 테마 CSS
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="KIS Open API 투자 대시보드 & 매매 승인 시스템",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS 커스텀 다크 모드 및 카드 스타일링
st.markdown("""
<style>
    /* 배경 및 기본 폰트 설정 */
    .stApp {
        background-color: #0F172A;
        color: #F8FAFC;
        font-family: 'Malgun Gothic', 'Pretendard', sans-serif;
    }
    
    /* 카드 컨테이너 */
    .proposal-card {
        background-color: #1E293B;
        border-radius: 12px;
        padding: 20px;
        border: 2px solid #F59E0B;
        box-shadow: 0 4px 12px rgba(245, 158, 11, 0.2);
        margin-bottom: 15px;
    }
    
    /* 뱃지 스타일 */
    .badge-mock {
        background-color: #065F46;
        color: #34D399;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .badge-real {
        background-color: #991B1B;
        color: #F87171;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .badge-running {
        background-color: #1E40AF;
        color: #60A5FA;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .badge-stopped {
        background-color: #374151;
        color: #9CA3AF;
        padding: 4px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.85rem;
    }
    .badge-buy {
        background-color: #991B1B;
        color: #F87171;
        padding: 4px 12px;
        border-radius: 6px;
        font-weight: bold;
    }
    .badge-sell {
        background-color: #1E3A8A;
        color: #60A5FA;
        padding: 4px 12px;
        border-radius: 6px;
        font-weight: bold;
    }

    div[data-testid="stMetricValue"] {
        font-size: 1.8rem !important;
        font-weight: 700 !important;
    }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# 2. 로깅 핸들러 (Streamlit Session State 연동)
# -----------------------------------------------------------------------------
class StreamlitLogHandler(logging.Handler):
    """로깅 메시지를 Streamlit 세션 상태(st.session_state.logs)에 기록"""
    def __init__(self):
        super().__init__()
        self.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))

    def emit(self, record):
        try:
            msg = self.format(record)
            if "logs" in st.session_state:
                st.session_state.logs.append(msg)
                if len(st.session_state.logs) > 500:
                    st.session_state.logs.pop(0)
        except Exception:
            pass


def setup_logger():
    """글로벌 로거에 Streamlit 핸들러 연결"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    for handler in logger.handlers:
        if isinstance(handler, StreamlitLogHandler):
            return
            
    st_handler = StreamlitLogHandler()
    logger.addHandler(st_handler)


# -----------------------------------------------------------------------------
# 3. 세션 상태 초기화
# -----------------------------------------------------------------------------
if "logs" not in st.session_state:
    st.session_state.logs = []

setup_logger()

if "bot" not in st.session_state:
    api_client = KISApiClient()
    bot = TraderBot(api_client)
    bot.initialize_account()
    st.session_state.bot = bot

bot: TraderBot = st.session_state.bot


# -----------------------------------------------------------------------------
# 4. 사이드바 (제어 및 설정)
# -----------------------------------------------------------------------------
with st.sidebar:
    st.title("⚙️ 시스템 제어")
    
    # 시스템 접속 상태 정보
    is_mock = bot.api.mock
    env_badge = '<span class="badge-mock">🟢 모의투자(VTS)</span>' if is_mock else '<span class="badge-real">🔴 실전투자(LIVE)</span>'
    status_badge = '<span class="badge-running">▶ 감시 중</span>' if bot.is_running else '<span class="badge-stopped">⏹ 정지됨</span>'
    
    st.markdown(f"**접속 환경**: {env_badge}", unsafe_allow_html=True)
    st.markdown(f"**실행 상태**: {status_badge}", unsafe_allow_html=True)
    st.markdown(f"**계좌번호**: `{bot.api.cano}-{bot.api.acnt_prdt_cd}`")
    st.divider()

    # 주문 방식 모드 선택 (반자동 사용자 승인 vs 완전자동)
    st.subheader("🛡️ 주문 실행 방식")
    mode_option = st.radio(
        "모드 선택",
        ["🛡️ 반자동 (제안 후 승인시 주문)", "⚡ 완전 자동 (즉시 주문)"],
        index=0 if bot.require_approval else 1,
        help="반자동 모드는 전략 신호나 손절/익절 감시 시 승인 대기 카드를 생성하고, 사용자가 승인할 때 주문을 제출합니다."
    )
    bot.require_approval = (mode_option.startswith("🛡️"))

    st.divider()

    # 자동 감시 시작 / 정지 버튼
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        if st.button("▶ 감시 시작", use_container_width=True, disabled=bot.is_running, type="primary"):
            bot.is_running = True
            logging.info(f"===== 대시보드: 감시 루프 시작 (모드: {'반자동 승인' if bot.require_approval else '완전자동'}) =====")
            st.rerun()
            
    with col_btn2:
        if st.button("⏹ 감시 정지", use_container_width=True, disabled=not bot.is_running):
            bot.is_running = False
            logging.info("===== 대시보드: 감시 루프 정지 =====")
            st.rerun()

    if st.button("🔄 잔고/시세 즉시 갱신", use_container_width=True):
        bot.fetch_account_balance()
        bot.fetch_target_prices()
        st.success("계좌 잔고 및 종목 시세가 갱신되었습니다.")
        st.rerun()

    st.divider()
    
    # 자동 갱신 옵션
    st.subheader("⏱️ 자동 감시 주기")
    auto_refresh = st.checkbox("자동 감시 및 갱신 활성화", value=bot.is_running)
    refresh_interval = st.slider("감시 간격 (초)", min_value=3, max_value=60, value=5, step=1)
    
    st.divider()
    st.caption("한국투자증권 Open API Trader v1.2")


# -----------------------------------------------------------------------------
# 5. 메인 대시보드 헤더 & 감시 루프
# -----------------------------------------------------------------------------
st.title("📈 KIS Open Trading API 투자 대시보드")

# 감시 활성화 상태 시 트레이딩/감시 사이클 1회 실행
if bot.is_running:
    bot.run_trading_cycle()

# 핵심 자산 평가 KPI metrics
m1, m2, m3, m4 = st.columns(4)

total_eval = bot.total_eval_amount
cash = bot.available_cash
stock_eval = max(0.0, total_eval - cash)
holding_count = len(bot.holdings)

with m1:
    st.metric(label="총 자산 평가액", value=f"₩{total_eval:,.0f}")
with m2:
    st.metric(label="보유 예수금", value=f"₩{cash:,.0f}")
with m3:
    st.metric(label="주식 평가금액", value=f"₩{stock_eval:,.0f}")
with m4:
    st.metric(label="보유 종목 수", value=f"{holding_count}개 / {config.MAX_STOCKS_HOLDING}개")

st.divider()

# -----------------------------------------------------------------------------
# 6. 승인 대기 중인 매매 제안 상단 긴급 섹션
# -----------------------------------------------------------------------------
pending_count = len(bot.pending_proposals)
if pending_count > 0:
    st.warning(f"🔔 **승인 대기 중인 매매 제안이 {pending_count}건 있습니다!** 아래 카드에서 [승인 및 주문 제출]을 클릭하시면 실제 매매가 실행됩니다.")
    
    for prop_id, prop in list(bot.pending_proposals.items()):
        action_color = "#EF4444" if prop["action"] == "BUY" else "#3B82F6"  # 빨강(매수) / 파랑(매도)
        
        with st.container():
            st.markdown(f"""
            <div class="proposal-card">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                    <h3 style="margin:0; color:#F59E0B;">💡 {prop['stock_name']} ({prop['symbol']}) - <span style="color:{action_color};">{prop['action_kr']} 제안</span></h3>
                    <span style="color:#94A3B8; font-size:0.9rem;">제안시각: {prop['timestamp']}</span>
                </div>
                <hr style="border-color:#334155; margin:10px 0;">
                <p style="font-size:1.05rem; margin-bottom:5px;"><b>제안 사유</b>: <span style="color:#38BDF8;">{prop['reason']}</span></p>
                <p style="font-size:1rem; margin-bottom:15px;">
                    <b>주문 수량</b>: {prop['qty']:,}주 | 
                    <b>현재가(기준가)</b>: ₩{prop['price']:,.0f} | 
                    <b>총 예상 금액</b>: <b>₩{prop['total_price']:,.0f}</b>
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            btn_col1, btn_col2, btn_spacer = st.columns([3, 3, 6])
            with btn_col1:
                if st.button(f"✅ 승인 및 {prop['action_kr']} 주문 제출", key=f"approve_{prop_id}", type="primary", use_container_width=True):
                    success = bot.approve_proposal(prop_id)
                    if success:
                        st.success(f"🎉 {prop['stock_name']} {prop['action_kr']} 주문이 성공적으로 제출되었습니다!")
                    else:
                        st.error(f"❌ 주문 제출에 실패하였습니다. 로그를 확인하세요.")
                    st.rerun()
                    
            with btn_col2:
                if st.button(f"❌ {prop['action_kr']} 제안 거절", key=f"reject_{prop_id}", use_container_width=True):
                    bot.reject_proposal(prop_id)
                    st.info(f"{prop['stock_name']} {prop['action_kr']} 제안을 거절하였습니다.")
                    st.rerun()
                    
            st.divider()

# -----------------------------------------------------------------------------
# 7. 메인 탭 구성
# -----------------------------------------------------------------------------
tab_titles = [
    f"🔔 승인 대기 제안 ({pending_count})" if pending_count > 0 else "🔔 승인 대기 제안",
    "📊 보유 종목 현황",
    "🎯 매매 감시 및 신호",
    "📜 시스템 실행 로그",
    "⚙️ 전략 및 리스크 설정"
]

tab_prop, tab_holdings, tab_targets, tab_logs, tab_config = st.tabs(tab_titles)

# 탭 1: 승인 대기 제안 목록 상세
with tab_prop:
    st.subheader("🔔 승인 대기 중인 주문 제안 목록")
    if bot.pending_proposals:
        prop_table_data = []
        for pid, p in bot.pending_proposals.items():
            prop_table_data.append({
                "제안ID": p["id"],
                "종목코드": p["symbol"],
                "종목명": p["stock_name"],
                "구분": p["action_kr"],
                "수량": f"{p['qty']:,}주",
                "현재가": f"₩{p['price']:,.0f}",
                "예상총액": f"₩{p['total_price']:,.0f}",
                "제안 사유": p["reason"],
                "제안 시간": p["timestamp"]
            })
        st.dataframe(pd.DataFrame(prop_table_data), use_container_width=True, hide_index=True)
    else:
        st.info("현재 대기 중인 매매 제안이 없습니다. 감시를 시작하면 매수/매도 조건 충족 시 이곳에 제안이 생성됩니다.")


# 탭 2: 보유 종목 현황
with tab_holdings:
    st.subheader("💼 현재 계좌 보유 종목")
    
    if bot.holdings:
        holdings_data = []
        for symbol, h in bot.holdings.items():
            qty = h.get("qty", 0)
            avg_p = h.get("avg_price", 0.0)
            cur_p = h.get("current_price", 0.0)
            eval_amt = qty * cur_p
            pnl_rate = h.get("pnl_rate", 0.0)
            if pnl_rate == 0.0 and avg_p > 0 and cur_p > 0:
                pnl_rate = ((cur_p - avg_p) / avg_p) * 100
            
            pnl_amt = eval_amt - (qty * avg_p)
            
            holdings_data.append({
                "종목코드": symbol,
                "종목명": h.get("name", symbol),
                "보유수량": f"{qty:,}주",
                "평균단가": f"₩{avg_p:,.0f}",
                "현재가": f"₩{cur_p:,.0f}",
                "평가금액": f"₩{eval_amt:,.0f}",
                "평가손익": f"₩{pnl_amt:+,.0f}",
                "수익률": f"{pnl_rate:+.2f}%"
            })
        
        df_holdings = pd.DataFrame(holdings_data)
        st.dataframe(df_holdings, use_container_width=True, hide_index=True)
    else:
        st.info("현재 계좌에 보유 중인 주식이 없습니다.")


# 탭 3: 매매 감시 및 신호
with tab_targets:
    st.subheader("🔭 매매 감시 종목 & 기술적 분석 신호")
    
    # 현재가 데이터가 비어있을 경우 일괄 조회
    if not any(bot.current_prices.values()):
        bot.fetch_target_prices()

    target_data = []
    for code in config.TARGET_STOCKS:
        cur_p = bot.current_prices.get(code, 0.0)
        if cur_p == 0.0:
            p_res = bot.api.get_stock_price(code)
            if p_res.get("success"):
                cur_p = float(p_res["price"])
                bot.current_prices[code] = cur_p

        is_held = code in bot.holdings
        
        signal_str = "HOLD"
        try:
            daily = bot.api.get_daily_chart(code, count=25)
            if daily and len(daily) > 5:
                df_d = pd.DataFrame(daily)
                holding_qty = bot.holdings.get(code, {}).get("qty", 0)
                signal_str = bot.strategy.generate_signal(code, cur_p if cur_p > 0 else float(df_d.iloc[-1]['close']), df_d, holding_qty)
        except Exception:
            pass

        is_overseas = KISApiClient.is_overseas_symbol(code)
        market_str = "🇺🇸 미국해외" if is_overseas else "🇰🇷 국내주식"
        curr_symbol = "$" if is_overseas else "₩"
        
        if cur_p > 0:
            price_str = f"{curr_symbol}{cur_p:,.2f}" if is_overseas else f"{curr_symbol}{cur_p:,.0f}"
        else:
            price_str = "시세 수신 불가"

        status_str = "🔴 보유 중" if is_held else "🟢 감시 중"
        
        target_data.append({
            "시장": market_str,
            "종목코드/티커": code,
            "현재가": price_str,
            "계좌 상태": status_str,
            "전략 생성 신호": signal_str,
            "적용 전략": config.STRATEGY_NAME
        })
        
    df_targets = pd.DataFrame(target_data)
    st.dataframe(df_targets, use_container_width=True, hide_index=True)


# 탭 4: 실시간 로그
with tab_logs:
    st.subheader("📜 실시간 이벤트 및 매매 실행 로그")
    
    col_log1, col_log2 = st.columns([8, 2])
    with col_log2:
        if st.button("🗑️ 로그 지우기", use_container_width=True):
            st.session_state.logs = []
            st.rerun()

    log_text = "\n".join(reversed(st.session_state.logs))
    st.text_area("시스템 로그 (최신순)", value=log_text, height=450)


# 탭 5: 설정 변경 안내 및 조회
with tab_config:
    st.subheader("⚙️ 현재 적용 중인 매매 파라미터 ([config.py](file:///c:/KIS_Auto_Trader/config.py))")
    
    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        st.markdown("### 📊 주문 및 전략 설정")
        st.write(f"- **주문 실행 방식**: `{'🛡️ 반자동 (승인 후 주문)' if bot.require_approval else '⚡ 완전 자동 (즉시 주문)'}`")
        st.write(f"- **적용 전략**: `{config.STRATEGY_NAME}`")
        st.write(f"- **단기 이동평균(MA)**: `{config.SHORT_MA_PERIOD}`일")
        st.write(f"- **장기 이동평균(MA)**: `{config.LONG_MA_PERIOD}`일")
        st.write(f"- **변동성 돌파 K 계수**: `{config.K_VALUE}`")
        st.write(f"- **감시 대상 종목**: `{', '.join(config.TARGET_STOCKS)}`")

    with col_cfg2:
        st.markdown("### 🛡️ 리스크 관리 설정")
        st.write(f"- **손절매(Stop Loss)**: `-{config.STOP_LOSS_RATIO * 100:.1f}%`")
        st.write(f"- **익절매(Take Profit)**: `+{config.TAKE_PROFIT_RATIO * 100:.1f}%`")
        st.write(f"- **트레일링 스탑**: 고점 대비 `-{config.TRAILING_STOP_RATIO * 100:.1f}%`")
        st.write(f"- **종목당 최대 투자 비율**: 계좌의 `{config.INVEST_RATIO_PER_STOCK * 100:.0f}%`")
        st.write(f"- **최대 보유 종목 수**: `{config.MAX_STOCKS_HOLDING}`개")


# -----------------------------------------------------------------------------
# 8. 자동 리프레시 루프 (스케줄러)
# -----------------------------------------------------------------------------
if auto_refresh and bot.is_running:
    time.sleep(refresh_interval)
    st.rerun()
