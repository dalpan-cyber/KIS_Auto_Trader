"""
한국투자증권 Open Trading API (KIS Developers) Streamlit 자동 투자 대시보드 (app.py)
"""
import time
import datetime
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

logger = logging.getLogger("Dashboard")


# -----------------------------------------------------------------------------
# 1. 페이지 기본 설정
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="KIS Open API 투자 대시보드 & 매매 승인 시스템",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS 커스텀 다크 모드 및 카드 스타일링
CUSTOM_CSS = """
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
"""


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
    
    # 기존 핸들러를 모두 제거하여 중복 로그 방지
    for handler in list(logger.handlers):
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
# 4. 공통 렌더링 함수 (CSS + 사이드바)
# -----------------------------------------------------------------------------
def render_css():
    """전역 CSS 적용"""
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def render_sidebar():
    """사이드바 (제어 및 설정)"""
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

        # 자동 감시 시작 / 정지 버튼
        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("▶ 감시 시작", width="stretch", disabled=bot.is_running, type="primary"):
                bot.is_running = True
                logging.info("===== 대시보드: 감시 루프 시작 =====")
                st.rerun()
                
        with col_btn2:
            if st.button("⏹ 감시 정지", width="stretch", disabled=not bot.is_running):
                bot.is_running = False
                logging.info("===== 대시보드: 감시 루프 정지 =====")
                st.rerun()

        if st.button("🔄 잔고/시세/구글시트 즉시 갱신", width="stretch"):
            bot.fetch_account_balance()
            bot.fetch_target_prices()
            bot.sync_holdings_to_state()
            st.success("계좌 잔고, 시세 및 구글 시트(State/Holdings/ExecutionHistory) 동기화 완료.")
            st.rerun()

        st.divider()
        st.caption("한국투자증권 Open API Trader v1.2")


# -----------------------------------------------------------------------------
# 5. 페이지 함수 정의
# -----------------------------------------------------------------------------
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

    st.caption(f"**상태**: {status_display} | **전략 시작일**: {st_data.get('start_date', '-')} | **총 예산**: ${budget:,.2f}")
    st.progress(min(1.0, max(0.0, float(curr_round) / float(div_count))))

    # 2. 당일 주문 상세
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
            for s in s_orders:
                st.info(f"**익절 매도**: ${s['price']:.2f} (수량: {s['qty']:,}주 / +10% 익절)")
        else:
            st.write("보유 수량이 없거나 익절 조건 미충족")

    with col_det2:
        st.markdown("#### 🟢 당일 분할 매수 주문 (LOC)")
        b_orders = [o for o in orders if o["action"] == "BUY"]
        if b_orders:
            for b in b_orders:
                st.success(f"**LOC 매수**: ${b['price']:.2f} 이하 (수량: {b['qty']:,}주)")
        else:
            st.write("매수 조건 미충족 또는 최대 회차 도달")

    st.markdown("---")

    # 3. 당일 주문 즉시 실행 버튼
    st.markdown("#### ⚡ 당일 주문 즉시 실행")
    col_exec1, col_exec2, col_exec3 = st.columns([3, 3, 6])
    with col_exec1:
        if st.button(f"🔴 {symbol} 전량 익절 매도 즉시 실행", key=f"exec_sell_{symbol}", type="primary", width="stretch"):
            result = bot.execute_daily_orders(symbol, action_filter="SELL")
            if result["success"] and result["executed"] > 0:
                st.success(f"🎉 [{symbol}] 익절 매도 주문이 즉시 실행되었습니다! ({result['executed']}건)")
            elif result["failed"] > 0:
                st.error(f"❌ [{symbol}] 익절 매도 주문 실행 중 오류 발생! (성공: {result['executed']}건, 실패: {result['failed']}건)")
            else:
                st.info(f"ℹ️ [{symbol}] 실행할 익절 매도 주문이 없습니다.")
            for msg in result["messages"]:
                st.caption(msg)
            st.rerun()

    with col_exec2:
        if st.button(f"🟢 {symbol} 분할 매수 즉시 실행", key=f"exec_buy_{symbol}", width="stretch"):
            result = bot.execute_daily_orders(symbol, action_filter="BUY")
            if result["success"] and result["executed"] > 0:
                st.success(f"🎉 [{symbol}] 분할 매수 주문이 즉시 실행되었습니다! ({result['executed']}건)")
            elif result["failed"] > 0:
                st.error(f"❌ [{symbol}] 분할 매수 주문 실행 중 오류 발생! (성공: {result['executed']}건, 실패: {result['failed']}건)")
            else:
                st.info(f"ℹ️ [{symbol}] 실행할 분할 매수 주문이 없습니다.")
            for msg in result["messages"]:
                st.caption(msg)
            st.rerun()

    with col_exec3:
        with st.popover("⚙️ 전략 시작일 변경"):
            curr_sd_str = st_data.get("start_date", datetime.date.today().strftime("%Y-%m-%d"))
            try:
                curr_sd_obj = datetime.datetime.strptime(curr_sd_str, "%Y-%m-%d").date()
            except Exception:
                curr_sd_obj = datetime.date.today()
            new_sd = st.date_input("전략 시작일 지정", value=curr_sd_obj, key=f"sd_input_{symbol}")
            if st.button("시작일 저장", key=f"sd_save_{symbol}"):
                new_sd_str = new_sd.strftime("%Y-%m-%d")
                bot.infinite_state_mgr.update_start_date(symbol, new_sd_str)
                st.success(f"전략 시작일이 {new_sd_str}로 변경되었습니다.")
                st.rerun()

    st.markdown("---")

    # 4. 차트 및 매매 이력
    st.subheader(f"📈 [{symbol}] 주가 차트 및 매매 체결 이력")
    chart_data = bot.api.get_daily_chart(symbol, count=90)

    today_dt = datetime.date.today()
    hist_start = st_data.get("start_date", "")
    clean_sd = hist_start.replace("-", "") if hist_start else ""
    # NOTE: 상태의 start_date가 없거나 오늘 날짜면, 최소 30일 전부터 조회하여 과거 이력 누락을 방지한다.
    default_start = (today_dt - datetime.timedelta(days=30)).strftime("%Y%m%d")
    if clean_sd and clean_sd.isdigit():
        query_start_fmt = clean_sd  # JSON의 start_date 사용
    else:
        query_start_fmt = default_start
    logger.info(f"[대시보드] 체결이력 조회 기간 결정: state_start={hist_start or '없음'}, query_start={query_start_fmt}, end={today_dt.strftime('%Y%m%d')}")

    end_date_fmt = today_dt.strftime("%Y%m%d")
    logger.info(f"[대시보드] 체결이력 조회 시작: symbol={symbol}, start_date={query_start_fmt}, end_date={end_date_fmt}")
    history_api = bot.api.get_overseas_execution_history(symbol=symbol, start_date=query_start_fmt, end_date=end_date_fmt)
    logger.info(f"[대시보드] 체결이력 조회 완료: {len(history_api)}건 (symbol={symbol})")

    # KIS API 단일 소스로 매매 이력 구성 (Google Sheets 읽기 참조 제거)
    merged_history = []
    seen_keys = set()

    for h in list(history_api):
        ord_no = str(h.get("order_no", "")).strip()
        ord_time = str(h.get("order_time", "")).strip()
        sym = str(h.get("symbol", "")).strip().upper()
        if symbol and sym and sym != symbol.upper():
            continue

        ord_type = str(h.get("order_type", "")).strip()
        qty = int(h.get("qty", 0) or 0)
        exec_qty = int(h.get("executed_qty", 0) or 0)
        price = float(h.get("price", 0.0) or 0.0)
        exec_price = float(h.get("executed_price", 0.0) or 0.0)
        status = str(h.get("status", "")).strip()

        # 중복 식별 키 생성
        if ord_no and not ord_no.startswith("EXEC_"):
            key = f"{sym}|{ord_no}|{ord_type}|{qty}|{exec_qty}|{status}"
        else:
            key = f"{sym}|{ord_time}|{ord_type}|{qty}|{exec_qty}|{price}|{exec_price}|{status}"

        if key in seen_keys:
            continue
        seen_keys.add(key)

        # start_date 필터링 (start_date 이전 레코드는 제외)
        rec_dt = ord_time.replace("-", "").replace(":", "").replace(" ", "")[:8]
        if clean_sd and rec_dt and rec_dt.isdigit() and rec_dt < clean_sd:
            continue

        merged_history.append(h)

    history = merged_history
    history.sort(key=lambda x: str(x.get("order_time", "")))

    # 신규 KIS API 이력을 구글 시트에 백업용으로만 누적 동기화
    if history_api and hasattr(bot, "infinite_state_mgr") and bot.infinite_state_mgr and bot.infinite_state_mgr.gss_mgr:
        try:
            bot.infinite_state_mgr.gss_mgr.sync_execution_history(history_api)
        except Exception as e:
            logger.warning(f"[대시보드] Google Sheets 백업 동기화 예외: {e}")

    if PLOTLY_AVAILABLE and chart_data:
        df_chart = pd.DataFrame(chart_data)
        fig = go.Figure()

        if 'date' in df_chart.columns and 'close' in df_chart.columns:
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

        if history:
            buy_dates, buy_prices, buy_texts = [], [], []
            sell_dates, sell_prices, sell_texts = [], [], []
            fail_dates, fail_prices, fail_texts = [], [], []

            for h in history:
                raw_ot = str(h.get("order_time", "")).strip()
                clean_ot = raw_ot.replace("-", "").replace(":", "").replace(" ", "")
                if len(clean_ot) >= 8 and clean_ot[:8].isdigit():
                    h_date = f"{clean_ot[:4]}-{clean_ot[4:6]}-{clean_ot[6:8]}"
                else:
                    h_date = raw_ot[:10]
                h_type = h.get("order_type", "")
                h_qty = h.get("executed_qty", 0) or h.get("qty", 0)
                h_price = h.get("executed_price", 0.0) or h.get("price", 0.0)
                h_status = h.get("status", "")

                # 실패/미체결 상태는 별도 마커로 표시
                is_failed = ("실패" in h_status or "미체결" in h_status or "취소" in h_status)

                if "매수" in h_type:
                    if is_failed:
                        fail_dates.append(h_date)
                        fail_prices.append(h_price)
                        fail_texts.append(f"❌ 매수 실패: {h_qty}주 @ ${h_price:.2f} ({h_status})")
                    else:
                        buy_dates.append(h_date)
                        buy_prices.append(h_price)
                        buy_texts.append(f"🟢 매수 주문/체결: {h_qty}주 @ ${h_price:.2f} ({h_status})")
                elif "매도" in h_type:
                    if is_failed:
                        fail_dates.append(h_date)
                        fail_prices.append(h_price)
                        fail_texts.append(f"❌ 매도 실패: {h_qty}주 @ ${h_price:.2f} ({h_status})")
                    else:
                        sell_dates.append(h_date)
                        sell_prices.append(h_price)
                        sell_texts.append(f"🎉 익절 매도: {h_qty}주 @ ${h_price:.2f} ({h_status})")

            if buy_dates:
                fig.add_trace(go.Scatter(
                    x=buy_dates, y=buy_prices, mode='markers', name='🟢 매수 주문/체결',
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


    # 5. 종목 매매 및 체결/실패 히스토리 테이블 (KIS API 실계좌 단일 소스)
    st.subheader(f"📜 [{symbol}] 매수/매도 & 체결/실패 이력 (KIS API 실계좌)")
    if history:
        h_rows = []
        for h in reversed(history):
            rvse_cncl_name = str(h.get("rvse_cncl_dvsn_name", "")).strip()
            rvse_cncl_cd = str(h.get("rvse_cncl_dvsn", "")).strip()
            status = str(h.get("status", "")).strip()

            # "취소" 항목 제외 (정정/취소구분 또는 상태에 '취소'가 포함된 경우 테이블에서 제외)
            if "취소" in rvse_cncl_name or rvse_cncl_cd == "02" or "취소" in status:
                continue

            h_qty = h.get("qty", 0)
            h_exec_qty = h.get("executed_qty", 0)
            h_price = h.get("price", 0.0)
            h_exec_price = h.get("executed_price", 0.0)
            h_type = h.get("order_type", "-")

            disp_ord_price = f"${h_price:.2f}" if h_price > 0 else "-"
            disp_exec_price = f"${h_exec_price:.2f}" if h_exec_qty > 0 else "-"
            disp_exec_amt = f"${h_exec_qty * h_exec_price:,.2f}" if h_exec_qty > 0 else "-"

            # API 응답의 추가 필드 (없으면 "-" 표시)
            def _disp(v):
                v = str(v or "").strip()
                return v if v else "-"

            h_rows.append({
                "일시": h.get("order_time", "-"),
                "구분": h_type,
                "주문수량": f"{h_qty:,}주",
                "체결수량": f"{h_exec_qty:,}주",
                "미체결수량": _disp(h.get("nccs_qty")),
                "주문단가 ($)": disp_ord_price,
                "체결단가 ($)": disp_exec_price,
                "총 체결금액 ($)": disp_exec_amt,
                "상태": status,
                "주문번호": h.get("order_no", "-"),
                "원주문번호": _disp(h.get("orgn_odno")),
                "주문지점": _disp(h.get("ord_gno_brno")),
                "주문일자": _disp(h.get("ord_dt")),
                "주문시각": _disp(h.get("ord_tmd")),
                "상품명": _disp(h.get("prdt_name")),
                "매도/매수코드": _disp(h.get("sll_buy_dvsn_cd")),
                "정정/취소구분": _disp(h.get("rvse_cncl_dvsn_name")),
                "거절사유": _disp(h.get("rjct_rson_name")),
                "거래시장": _disp(h.get("tr_mket_name")),
                "거래국가": _disp(h.get("tr_natn_name")),
                "거래소": _disp(h.get("ovrs_excg_cd")),
                "통화": _disp(h.get("tr_crcy_cd")),
                "국내주문일자": _disp(h.get("dmst_ord_dt")),
                "당사주문시각": _disp(h.get("thco_ord_tmd")),
                "대출유형": _disp(h.get("loan_type_cd")),
                "대출일자": _disp(h.get("loan_dt")),
                "매체구분": _disp(h.get("mdia_dvsn_name")),
                "장외연장요청": _disp(h.get("usa_amk_exts_rqst_yn"))
            })
        st.dataframe(pd.DataFrame(h_rows), width="stretch", hide_index=True)
    else:
        st.info("아직 누적된 매매 이력이 없습니다.")


def page_main_dashboard():
    """메인 대시보드: 무한매수 현황 & 당일 주문"""
    render_css()
    render_sidebar()

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

    # 무한매수 현황
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


def page_logs():
    """시스템 실행 로그 페이지"""
    render_css()
    render_sidebar()

    st.title("📜 시스템 실행 로그")
    
    col_log1, col_log2 = st.columns([8, 2])
    with col_log2:
        if st.button("🗑️ 로그 지우기", width="stretch"):
            st.session_state.logs = []
            st.rerun()

    log_text = "\n".join(reversed(st.session_state.logs))
    st.text_area("시스템 로그 (최신순)", value=log_text, height=600)


def page_config():
    """무한매수 설정 페이지"""
    render_css()
    render_sidebar()

    st.title("⚙️ 무한매수 설정")
    st.subheader("현재 적용 중인 무한매수 파라미터 ([config.py](file:///c:/KIS_Auto_Trader/config.py))")
    
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
        st.write(f"- **주문 실행 방식**: `⚡ 완전 자동 (GitHub Actions Cron 1일 2회)`")
        st.write(f"- **주문 구문**: `LOC (Limit On Close - 종가입찰) & 지정가 익절 매도`")
        st.write(f"- **최대 보유 종목 수**: `{getattr(config, 'MAX_STOCKS_HOLDING', 5)}` 개")
        st.write(f"- **API 호출 안전 딜레이**: `{getattr(config, 'API_CALL_DELAY', 0.2)}` 초")


# -----------------------------------------------------------------------------
# 6. 페이지 네비게이션 (왼쪽 nav)
# -----------------------------------------------------------------------------
pages = {
    "📊 대시보드": [
        st.Page(page_main_dashboard, title="무한매수 현황 & 당일 주문", icon="📈", default=True),
    ],
    "🛠️ 시스템": [
        st.Page(page_logs, title="시스템 실행 로그", icon="📜"),
        st.Page(page_config, title="무한매수 설정", icon="⚙️"),
    ],
}

pg = st.navigation(pages, position="sidebar")
pg.run()
