"""
한국투자증권 Open Trading API (KIS Developers) Streamlit 자동 투자 대시보드 (app.py)
"""
import time
import logging
import pandas as pd
import numpy as np
import streamlit as st

PLOTLY_AVAILABLE = False
try:
    import plotly.graph_objects as go
    PLOTLY_AVAILABLE = True
except ImportError:
    pass

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
    """글로벌 로거에 Streamlit 핸들러 연결 (중복 등록 방지)"""
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    for handler in list(logger.handlers):
        if isinstance(handler, StreamlitLogHandler):
            logger.removeHandler(handler)
            
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
        if st.button("▶ 감시 시작", width="stretch", disabled=bot.is_running, type="primary"):
            bot.is_running = True
            logging.info(f"===== 대시보드: 감시 루프 시작 (모드: {'반자동 승인' if bot.require_approval else '완전자동'}) =====")
            st.rerun()
            
    with col_btn2:
        if st.button("⏹ 감시 정지", width="stretch", disabled=not bot.is_running):
            bot.is_running = False
            logging.info("===== 대시보드: 감시 루프 정지 =====")
            st.rerun()

    if st.button("🔄 잔고/시세 즉시 갱신", width="stretch"):
        bot.fetch_account_balance()
        bot.fetch_target_prices()
        bot.sync_holdings_to_state()
        st.success("계좌 잔고, 시세 및 구글 시트 동기화가 완료되었습니다.")
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
# -----------------------------------------------------------------------------
# 5. 메인 대시보드 헤더 & 감시 루프
# -----------------------------------------------------------------------------
st.title("🇺🇸 KIS 라오어 무한매수법 전담 자동투자 시스템")

# 감시 활성화 상태 시 트레이딩/감시 사이클 1회 실행
if bot.is_running:
    bot.run_trading_cycle()

# 해외 무한매수 종목별 주식 평가금액($) 및 외화 총자산 계산
infinite_stocks = getattr(config, "INFINITE_STOCKS", ["TQQQ"])
usd_stock_eval = 0.0
holding_stock_count = 0

for sym in infinite_stocks:
    hld = bot.holdings.get(sym, {})
    q = hld.get("qty", 0)
    cur_p = bot.current_prices.get(sym, 0.0)
    if cur_p == 0.0:
        p_res = bot.api.get_stock_price(sym)
        if p_res.get("success"):
            cur_p = float(p_res["price"])
            bot.current_prices[sym] = cur_p
    
    if q > 0:
        holding_stock_count += 1
        usd_stock_eval += q * cur_p

usd_cash = getattr(bot, "available_usd_cash", 5000.0)
usd_total_eval = usd_cash + usd_stock_eval
ex_rate = getattr(bot, "exchange_rate", 1428.20)
is_sim = getattr(bot, "is_usd_simulated", True)

usd_dep_sub = "테스트용 시뮬레이션 가상 잔고" if is_sim else "KIS Open API 실시간 조회"

m1, m2, m3, m4 = st.columns(4)

with m1:
    st.metric(
        label="🇺🇸 총 자산 평가액 ($)",
        value=f"${usd_total_eval:,.2f}",
        delta=f"약 ₩{usd_total_eval * ex_rate:,.0f}",
        delta_color="off"
    )
with m2:
    st.metric(
        label="💵 외화(USD) 예수금",
        value=f"${usd_cash:,.2f}",
        delta=usd_dep_sub,
        delta_color="off"
    )
with m3:
    st.metric(
        label="📈 주식 평가금액 ($)",
        value=f"${usd_stock_eval:,.2f}",
        delta=f"약 ₩{usd_stock_eval * ex_rate:,.0f}",
        delta_color="off"
    )
with m4:
    st.metric(
        label="💱 미국 USD 환율",
        value=f"₩{ex_rate:,.2f} / $",
        delta=f"운용: {len(infinite_stocks)}개종목 (보유 {holding_stock_count}개)",
        delta_color="off"
    )

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
                    <b>현재가(기준가)</b>: ${prop['price']:,.2f} | 
                    <b>총 예상 금액</b>: <b>${prop['total_price']:,.2f}</b>
                </p>
            </div>
            """, unsafe_allow_html=True)
            
            btn_col1, btn_col2, btn_spacer = st.columns([3, 3, 6])
            with btn_col1:
                if st.button(f"✅ 승인 및 {prop['action_kr']} 주문 제출", key=f"approve_{prop_id}", type="primary", width="stretch"):
                    success = bot.approve_proposal(prop_id)
                    if success:
                        st.success(f"🎉 {prop['stock_name']} {prop['action_kr']} 주문이 성공적으로 제출되었습니다!")
                    else:
                        st.error(f"❌ 주문 제출에 실패하였습니다. 로그를 확인하세요.")
                    st.rerun()
                    
            with btn_col2:
                if st.button(f"❌ {prop['action_kr']} 제안 거절", key=f"reject_{prop_id}", width="stretch"):
                    bot.reject_proposal(prop_id)
                    st.info(f"{prop['stock_name']} {prop['action_kr']} 제안을 거절하였습니다.")
                    st.rerun()
                    
            st.divider()

# -----------------------------------------------------------------------------
# 7. 메인 탭 구성
# -----------------------------------------------------------------------------
tab_titles = [
    "🇺🇸 무한매수 현황 & 당일 주문",
    f"🔔 승인 대기 제안 ({pending_count})" if pending_count > 0 else "🔔 승인 대기 제안",
    "📜 시스템 실행 로그",
    "⚙️ 무한매수 설정"
]

tab_infinite, tab_prop, tab_logs, tab_config = st.tabs(tab_titles)

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
                "현재가": f"₩{p['price']:,.0f}" if isinstance(p['price'], (int, float)) and not bot.api.is_overseas_symbol(p["symbol"]) else f"${p['price']:,.2f}",
                "예상총액": f"₩{p['total_price']:,.0f}" if not bot.api.is_overseas_symbol(p["symbol"]) else f"${p['total_price']:,.2f}",
                "제안 사유": p["reason"],
                "제안 시간": p["timestamp"]
            })
        st.dataframe(pd.DataFrame(prop_table_data), width="stretch", hide_index=True)
    else:
        st.info("현재 대기 중인 매매 제안이 없습니다. 감시를 시작하면 매수/매도 조건 충족 시 이곳에 제안이 생성됩니다.")


def render_stock_detail(symbol: str, bot: TraderBot):
    """특정 종목의 무한매수 현황, 제어, 당일주문, 일별 주가-이력 차트 및 매매이력 표시"""
    st_data = bot.infinite_state_mgr.get_symbol_state(
        symbol,
        default_budget_usd=getattr(config, "INFINITE_TOTAL_BUDGET_USD", 5000.0),
        division_count=getattr(config, "INFINITE_DIVISION_COUNT", 40),
        target_roi=getattr(config, "INFINITE_TARGET_ROI", 0.10)
    )
    curr_round = st_data.get("current_round", 0)
    div_count = st_data.get("division_count", 40)
    budget = st_data.get("total_budget_usd", 5000.0)
    # 보유 수량/평단가는 KIS API 실계좌가 Source of Truth
    hld = bot.holdings.get(symbol, {})
    avg_p = hld.get("avg_price", 0.0)
    total_qty = hld.get("qty", 0)
    raw_status = st_data.get("status", "IDLE")

    cur_p = bot.current_prices.get(symbol, 0.0)
    if cur_p == 0.0:
        p_res = bot.api.get_stock_price(symbol)
        if p_res.get("success"):
            cur_p = float(p_res["price"])
            bot.current_prices[symbol] = cur_p

    status_map = {
        "BUYING": "🟢 매수 진행 중 (BUYING)",
        "STOPPED": "🔴 강제 중지됨 (STOPPED)",
        "IDLE": "🟡 대기 중 (IDLE)",
        "COMPLETED": "🔵 익절 완료 (COMPLETED)"
    }
    status_display = status_map.get(raw_status, raw_status)

    # 1. 상단 메트릭 요약
    c_m1, c_m2, c_m3, c_m4, c_m5 = st.columns(5)
    with c_m1:
        st.metric("진행 회차", f"{curr_round} / {div_count} 회차")
    with c_m2:
        st.metric("보유 수량", f"{total_qty:,} 주")
    with c_m3:
        st.metric("매수 평단가", f"${avg_p:.2f}" if avg_p > 0 else "-")
    with c_m4:
        st.metric("현재가", f"${cur_p:.2f}" if cur_p > 0 else "-")
    with c_m5:
        eval_amt = total_qty * cur_p if cur_p > 0 else 0.0
        pnl = (eval_amt - (total_qty * avg_p)) if avg_p > 0 else 0.0
        pnl_rt = (pnl / (total_qty * avg_p) * 100) if (total_qty * avg_p) > 0 else 0.0
        st.metric("평가 손익", f"${pnl:+,.2f}", delta=f"{pnl_rt:+.2f}%")

    st.caption(f"**상태**: {status_display} | **총 예산**: ${budget:,.2f}")
    st.progress(min(1.0, max(0.0, float(curr_round) / float(div_count))))

    # 2. 수동 제어 버튼
    col_b1, col_b2, col_b3, col_sp = st.columns([2.5, 2.5, 2.5, 4.5])
    with col_b1:
        if st.button(f"▶ {symbol} 수동 시작", key=f"start_{symbol}", type="primary", width="stretch"):
            bot.start_infinite_buying(symbol)
            st.success(f"🚀 [{symbol}] 무한매수 매매 루틴이 수동 시작되었습니다.")
            st.rerun()
    with col_b2:
        if st.button(f"⏹ {symbol} 강제 중지", key=f"stop_{symbol}", width="stretch"):
            bot.stop_infinite_buying(symbol)
            st.warning(f"⏹ [{symbol}] 무한매수가 강제 중지되었습니다.")
            st.rerun()
    with col_b3:
        if st.button(f"🔄 {symbol} 회차 초기화", key=f"reset_{symbol}", width="stretch"):
            bot.infinite_state_mgr.reset_round(symbol)
            st.info(f"🔄 [{symbol}] 회차가 0회차로 초기화되었습니다.")
            st.rerun()

    st.markdown("---")

    # 3. 당일 매수/매도 주문 상세 수량
    calc_price = cur_p if cur_p > 0 else (avg_p if avg_p > 0 else 50.0)
    orders = bot.infinite_strategy.generate_daily_orders(
        symbol, calc_price, st_data,
        avg_price=avg_p, total_qty=total_qty
    )

    col_det1, col_det2 = st.columns(2)
    with col_det1:
        st.markdown("#### 🔴 당일 전량 익절 매도 주문 (지정가)")
        s_orders = [o for o in orders if o["action"] == "SELL"]
        if s_orders:
            for s_o in s_orders:
                st.write(f"- **주문 내용**: {s_o['desc']}")
                st.write(f"- **주문 수량**: `{s_o['qty']:,} 주`")
                st.write(f"- **목표 매도가**: `${s_o['price']:.2f}` (+10.0%)")
                st.write(f"- **예상 총 매도금액**: **`${s_o['qty'] * s_o['price']:,.2f}`**")
        else:
            st.info("현재 보유 주식이 없어 매도 주문이 없습니다.")

    with col_det2:
        st.markdown("#### 🟢 당일 40분할 매수 주문 (LOC 종가입찰)")
        b_orders = [o for o in orders if o["action"] == "BUY"]
        if b_orders:
            tot_b_qty = sum(b['qty'] for b in b_orders)
            tot_b_amt = sum(b['qty'] * b['price'] for b in b_orders)
            for idx, b_o in enumerate(b_orders, 1):
                st.write(f"**{idx}. {b_o['desc']}**")
                st.write(f"  • 수량: `{b_o['qty']:,}주` | LOC단가: `${b_o['price']:.2f}` | 주문금액: `${b_o['qty'] * b_o['price']:,.2f}`")
            st.markdown(f"**💰 당일 매수 총 예상금액**: **`${tot_b_amt:,.2f}`** (`{tot_b_qty:,}주`)")
        else:
            if raw_status in ["STOPPED", "PAUSED"]:
                st.warning("현재 무한매수가 강제 중지(STOPPED) 상태입니다.")
            elif curr_round >= div_count:
                st.warning("40회차가 모두 소진되었습니다.")
            else:
                st.info("당일 매수 주문 생성 대기 중입니다.")

    st.markdown("---")

    # 4. Plotly 주가 & 매수이력 그래프
    st.subheader(f"📈 [{symbol}] 일별 주가 & 매수/매도/실패 이력 대조 차트")
    chart_data = bot.api.get_daily_chart(symbol, count=60)

    if PLOTLY_AVAILABLE:
        fig = go.Figure()

        if chart_data:
            df_chart = pd.DataFrame(chart_data)
            df_chart['date_fmt'] = pd.to_datetime(df_chart['date'], format='%Y%m%d', errors='coerce').dt.strftime('%Y-%m-%d')
            df_chart = df_chart.sort_values('date_fmt').dropna(subset=['date_fmt'])

            fig.add_trace(go.Scatter(
                x=df_chart['date_fmt'],
                y=df_chart['close'],
                mode='lines+markers',
                name=f'{symbol} 종가',
                line=dict(color='#38BDF8', width=2),
                marker=dict(size=4)
            ))

        # 매매 이력은 KIS API 실계좌 체결내역이 Source of Truth
        history = bot.api.get_overseas_execution_history(symbol=symbol)
        if history:
            buy_dates, buy_prices, buy_texts = [], [], []
            sell_dates, sell_prices, sell_texts = [], [], []
            fail_dates, fail_prices, fail_texts = [], [], []

            for h in history:
                h_date = str(h.get("order_time", ""))[:10]
                h_type = h.get("order_type", "")
                h_qty = h.get("executed_qty", 0)
                h_price = h.get("executed_price", 0.0)

                if "매수" in h_type:
                    buy_dates.append(h_date)
                    buy_prices.append(h_price)
                    buy_texts.append(f"🟢 매수 체결: {h_qty}주 @ ${h_price:.2f} ({h.get('status', '')})")
                elif "매도" in h_type:
                    sell_dates.append(h_date)
                    sell_prices.append(h_price)
                    sell_texts.append(f"🎉 익절 매도: {h_qty}주 @ ${h_price:.2f} ({h.get('status', '')})")

            if buy_dates:
                fig.add_trace(go.Scatter(
                    x=buy_dates, y=buy_prices, mode='markers', name='🟢 매수 체결',
                    marker=dict(symbol='triangle-up', size=12, color='#22C55E'),
                    text=buy_texts, hoverinfo='text'
                ))
            if sell_dates:
                fig.add_trace(go.Scatter(
                    x=sell_dates, y=sell_prices, mode='markers', name='🎉 익절 매도',
                    marker=dict(symbol='star', size=14, color='#EC4899'),
                    text=sell_texts, hoverinfo='text'
                ))
            if fail_dates:
                fig.add_trace(go.Scatter(
                    x=fail_dates, y=fail_prices, mode='markers', name='❌ 매수 실패',
                    marker=dict(symbol='x', size=12, color='#F97316'),
                    text=fail_texts, hoverinfo='text'
                ))

        if avg_p > 0:
            fig.add_hline(
                y=avg_p, line_dash="dash", line_color="#F59E0B",
                annotation_text=f"현재 평단가 (${avg_p:.2f})", annotation_position="top left"
            )

        fig.update_layout(
            template="plotly_dark",
            margin=dict(l=20, r=20, t=30, b=20),
            height=380,
            xaxis_title="날짜",
            yaxis_title="주가 ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        st.plotly_chart(fig, use_container_width=True)
    else:
        if chart_data:
            df_c = pd.DataFrame(chart_data)
            df_c['date_fmt'] = pd.to_datetime(df_c['date'], format='%Y%m%d', errors='coerce').dt.strftime('%Y-%m-%d')
            st.line_chart(df_c.set_index('date_fmt')['close'])
        st.info("💡 `pip install plotly`를 가상환경(.venv)에 설치하시면 대화형 매수/매도 이력 마커 차트가 표출됩니다.")


    # 5. 종목 매매 및 체결/실패 히스토리 테이블 (KIS API 실계좌 체결내역)
    st.subheader(f"📜 [{symbol}] 매수/매도 & 체결/실패 이력 (KIS API 실계좌)")
    if history:
        h_rows = []
        for h in reversed(history):
            h_rows.append({
                "일시": h.get("order_time", "-"),
                "구분": h.get("order_type", "-"),
                "수량": f"{h.get('executed_qty', 0):,}주",
                "단가 ($)": f"${h.get('executed_price', 0.0):.2f}",
                "총금액 ($)": f"${h.get('executed_qty', 0) * h.get('executed_price', 0.0):,.2f}",
                "상태": h.get("status", "-"),
                "주문번호": h.get("order_no", "-")
            })
        st.dataframe(pd.DataFrame(h_rows), width="stretch", hide_index=True)
    else:
        st.info("아직 누적된 매매 이력이 없습니다.")


# 탭 2: 라오어 무한매수 현황
with tab_infinite:
    st.subheader("🇺🇸 라오어 무한매수법 v2.0 진행 현황")
    
    if getattr(config, "INFINITE_BUYING_ENABLED", False):
        infinite_stocks = getattr(config, "INFINITE_STOCKS", ["TQQQ"])

        if len(infinite_stocks) > 1:
            stock_sub_tabs = st.tabs([f"📌 {sym}" for sym in infinite_stocks] + ["📊 전체 종목 종합 요약"])
            for idx, sym in enumerate(infinite_stocks):
                with stock_sub_tabs[idx]:
                    render_stock_detail(sym, bot)

            with stock_sub_tabs[-1]:
                st.subheader("📊 전체 종목 무한매수 종합 요약")
                summary_data = []
                for sym in infinite_stocks:
                    st_d = bot.infinite_state_mgr.get_symbol_state(sym)
                    hld = bot.holdings.get(sym, {})
                    avg_p = hld.get("avg_price", 0.0)
                    total_qty = hld.get("qty", 0)
                    summary_data.append({
                        "티커": sym,
                        "진행 회차": f"{st_d.get('current_round', 0)} / {st_d.get('division_count', 40)} 회차",
                        "총 예산 ($)": f"${st_d.get('total_budget_usd', 0.0):,.2f}",
                        "평단가 ($)": f"${avg_p:.2f}" if avg_p > 0 else "-",
                        "보유 수량": f"{total_qty:,} 주",
                        "상태": st_d.get("status", "IDLE")
                    })
                st.dataframe(pd.DataFrame(summary_data), width="stretch", hide_index=True)
        else:
            render_stock_detail(infinite_stocks[0], bot)
    else:
        st.warning("현재 무한매수법이 비활성화되어 있습니다. config.py에서 `INFINITE_BUYING_ENABLED = True`로 설정하세요.")



# 탭 3: 실시간 로그
with tab_logs:
    st.subheader("📜 실시간 이벤트 및 매매 실행 로그")
    
    col_log1, col_log2 = st.columns([8, 2])
    with col_log2:
        if st.button("🗑️ 로그 지우기", width="stretch"):
            st.session_state.logs = []
            st.rerun()

    log_text = "\n".join(reversed(st.session_state.logs))
    st.text_area("시스템 로그 (최신순)", value=log_text, height=450)


# 탭 4: 무한매수 전담 설정 조회
with tab_config:
    st.subheader("⚙️ 현재 적용 중인 무한매수 파라미터 ([config.py](file:///c:/KIS_Auto_Trader/config.py))")
    
    col_cfg1, col_cfg2 = st.columns(2)
    with col_cfg1:
        st.markdown("### 🇺🇸 라오어 무한매수법 v2.0 파라미터")
        st.write(f"- **전담 매매 전략**: `라오어 무한매수법 v2.0 (INFINITE_BUYING)`")
        st.write(f"- **운용 대상 종목**: `{', '.join(getattr(config, 'INFINITE_STOCKS', ['TQQQ']))}`")
        st.write(f"- **종목당 총 예산 ($)**: `${getattr(config, 'INFINITE_TOTAL_BUDGET_USD', 5000):,.0f}`")
        st.write(f"- **총 분할 매수 횟수**: `{getattr(config, 'INFINITE_DIVISION_COUNT', 40)}` 회차")
        st.write(f"- **전량 익절 목표 수익률**: `+{getattr(config, 'INFINITE_TARGET_ROI', 0.10)*100:.1f}%`")

    with col_cfg2:
        st.markdown("### 🛡️ 시스템 주문 및 리스크 관리")
        st.write(f"- **주문 실행 방식**: `{'🛡️ 반자동 (승인 후 주문)' if bot.require_approval else '⚡ 완전 자동 (즉시 주문)'}`")
        st.write(f"- **주문 구문**: `LOC (Limit On Close - 종가입찰) & 지정가 익절 매도`")
        st.write(f"- **최대 보유 종목 수**: `{getattr(config, 'MAX_STOCKS_HOLDING', 5)}` 개")
        st.write(f"- **API 호출 안전 딜레이**: `{getattr(config, 'API_CALL_DELAY', 0.2)}` 초")


# -----------------------------------------------------------------------------
# 8. 자동 리프레시 루프 (스케줄러)
# -----------------------------------------------------------------------------
if auto_refresh and bot.is_running:
    time.sleep(refresh_interval)
    st.rerun()
