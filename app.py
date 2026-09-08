"""
한국투자증권 Open Trading API (KIS Developers) Streamlit 자동 투자 대시보드 (app.py)
"""
import time
import datetime
import json
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

    /* 매도 실행 버튼 - 레드 계열 (key: exec_sell_*) */
    [class*="st-key-exec_sell"] button[kind="primary"] {
        background-color: #DC2626 !important;
        border-color: #DC2626 !important;
        color: #FFFFFF !important;
    }
    [class*="st-key-exec_sell"] button[kind="primary"]:hover {
        background-color: #B91C1C !important;
        border-color: #B91C1C !important;
    }

    /* 매수 실행 버튼 - 블루 계열 (key: exec_buy_*) */
    [class*="st-key-exec_buy"] button[kind="primary"] {
        background-color: #2563EB !important;
        border-color: #2563EB !important;
        color: #FFFFFF !important;
    }
    [class*="st-key-exec_buy"] button[kind="primary"]:hover {
        background-color: #1D4ED8 !important;
        border-color: #1D4ED8 !important;
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
    """사이드바 (시스템 정보 및 상태)"""
    with st.sidebar:
        st.title("⚙️ 시스템 정보")
        
        # 시스템 접속 상태 정보
        is_mock = bot.api.mock
        env_badge = '<span class="badge-mock">🟢 모의투자(VTS)</span>' if is_mock else '<span class="badge-real">🔴 실전투자(LIVE)</span>'
        auto_badge = '<span class="badge-running">🤖 무인 가동 중</span>'
        
        st.markdown(f"**접속 환경**: {env_badge}", unsafe_allow_html=True)
        st.markdown(f"**자동 매매**: {auto_badge}", unsafe_allow_html=True)
        st.caption("⚡ GitHub Actions (매일 21:59 KST 자동 발주)")
        st.markdown(f"**계좌번호**: `{bot.api.cano}-{bot.api.acnt_prdt_cd}`")
        st.divider()

        # 잔고 및 시세 새로고침 버튼
        if st.button("🔄 잔고 및 시세 새로고침", width="stretch"):
            bot.fetch_account_balance()
            bot.fetch_target_prices()
            bot.sync_holdings_to_state()
            st.success("실시간 계좌 잔고 및 종목 시세를 새로고침했습니다.")
            st.rerun()

        st.divider()
        st.caption("한국투자증권 Open API Trader v1.2")


# -----------------------------------------------------------------------------
# 5. 페이지 함수 정의
# -----------------------------------------------------------------------------
def render_stock_detail(symbol: str, bot: TraderBot):
    """특정 종목의 무한매수 현황, 제어, 당일주문, 일별 주가-이력 차트 및 매매이력 표시"""
    stock_cfg = config.get_stock_config(symbol)
    st_data = bot.infinite_state_mgr.get_symbol_state(
        symbol,
        default_budget_usd=stock_cfg["total_budget_usd"],
        division_count=stock_cfg["division_count"],
        target_roi=stock_cfg["target_roi"],
        exhaust_action=stock_cfg["exhaust_action"],
        exhaust_target_roi=stock_cfg["exhaust_target_roi"]
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
        "BUYING": f"🟢 무한매수 운용 중 (BUYING - {curr_round}/{div_count}회차)",
        "STOPPED": "🔴 운용 강제 중지됨 (STOPPED)",
        "IDLE": "🟡 시작 전 대기 (IDLE)",
        "COMPLETED": "🔵 전량 익절 완료 (COMPLETED - 사이클 종료)"
    }
    status_display = status_map.get(raw_status, raw_status)

    # 1. 상단 메트릭 요약
    c_m1, c_m2, c_m3, c_m4, c_m5, c_m6 = st.columns(6)
    with c_m1:
        st.metric("진행 회차", f"{curr_round} / {div_count} 회차")
    with c_m2:
        st.metric("보유 수량", f"{total_qty:,} 주")
    with c_m3:
        st.metric("매수 평단가", f"${avg_p:.2f}" if avg_p > 0 else "-")
    with c_m4:
        st.metric("현재가", f"${cur_p:.2f}" if cur_p > 0 else "-")
    with c_m5:
        total_exec_amt = (total_qty * avg_p) if avg_p > 0 else 0.0
        st.metric("총 체결금액", f"${total_exec_amt:,.2f}")
    with c_m6:
        eval_amt = total_qty * cur_p if cur_p > 0 else 0.0
        pnl = (eval_amt - (total_qty * avg_p)) if avg_p > 0 else 0.0
        pnl_rt = (pnl / (total_qty * avg_p) * 100) if (total_qty * avg_p) > 0 else 0.0
        st.metric("평가 손익", f"${pnl:+,.2f}", delta=f"{pnl_rt:+.2f}%")

    exhaust_act = str(st_data.get("exhaust_action", stock_cfg["exhaust_action"])).upper()
    exhaust_roi = float(st_data.get("exhaust_target_roi", stock_cfg["exhaust_target_roi"]))
    exhaust_name_map = {
        "HOLD": "🛡️ 1. 무한 대기 (존버)",
        "REBALANCE_QUARTER": "✂️ 2. 쿼터 순환 매매",
        "LOWER_TARGET": f"🎯 3. 목표가 하향 (+{exhaust_roi*100:.1f}%)"
    }
    exhaust_name = exhaust_name_map.get(exhaust_act, exhaust_act)

    st.caption(f"**상태**: {status_display} | **전략 시작일**: {st_data.get('start_date', '-')} | **총 예산**: ${budget:,.2f} | **소진 시 대응**: {exhaust_name}")
    st.progress(min(1.0, max(0.0, float(curr_round) / float(div_count))))

    # 무한매수 사이클 진행 상태 친절 안내
    if raw_status == "BUYING" and curr_round > 0:
        target_roi_pct = st_data.get("target_roi", 0.10) * 100
        target_p = round(avg_p * (1.0 + st_data.get("target_roi", 0.10)), 2) if avg_p > 0 else 0.0
        st.info(
            f"💡 **무한매수 사이클 진행 안내**: 현재 **{curr_round}/{div_count}회차 분할 매수 체결 완료** 상태입니다. "
            f"(보유 수량: **{total_qty:,}주**, 평단가: **${avg_p:.2f}**, 목표 익절가: **${target_p:.2f}** (+{target_roi_pct:.1f}%))\n\n"
            f"- **'운용 중(BUYING)'의 의미**: 무한매수법은 1회성 매매가 아니라 총 {div_count}회차에 걸쳐 매일 분할 매수를 누적하는 전략입니다. 목표가 도달 시 **'전량 익절 매도(COMPLETED)'**로 사이클이 종료되며, 그 전까지는 포지션을 보유하며 다음 회차 매수를 준비하는 정상 운용 상태입니다."
        )

    # 40회차 소진 시 대응 모드 상태 배너 표시
    is_exhausted = (curr_round >= div_count)
    if is_exhausted:
        if exhaust_act == "LOWER_TARGET":
            st.warning(
                f"🚨 **[{div_count}회차 최대치 도달 - 목표수익률 하향 탈출 모드 가동]** "
                f"목표 수익률이 **+{exhaust_roi*100:.1f}%**로 하향 조정되어 빠른 원금 회수 익절 매도 주문이 발주됩니다."
            )
        elif exhaust_act == "REBALANCE_QUARTER":
            st.warning(
                f"🚨 **[{div_count}회차 최대치 도달 - 쿼터 순환 매매 모드 가동]** "
                f"1회차 분량 매도 및 당일 LOC 재매수를 통해 평단가를 강제로 인하하는 리밸런싱이 진행됩니다."
            )
        else:
            st.info(
                f"🛡️ **[{div_count}회차 최대치 도달 - 무한 대기(존버) 모드 가동]** "
                f"추가 매수를 중단하고 원금을 보존하며, 반등 시점까지 +{st_data.get('target_roi', 0.10)*100:.1f}% 전량 익절 매도 주문을 유지합니다."
            )

    # 2. 당일 주문 제안 생성
    calc_price = cur_p if cur_p > 0 else (avg_p if avg_p > 0 else 50.0)
    orders = bot.infinite_strategy.generate_daily_orders(
        symbol, calc_price, st_data,
        avg_price=avg_p, total_qty=total_qty
    )

    # 2. 당일 주문 제안 + 즉시 실행 (제안/실행 통합 UI)
    st.markdown("#### ⚡ 당일 주문 제안 및 즉시 실행")

    # 직전 주문 실행 결과 알림 표시 (리런 후에도 피드백 유지)
    order_res_key = f"order_result_{symbol}"
    if order_res_key in st.session_state:
        prev_res = st.session_state.pop(order_res_key)
        if prev_res.get("success") and prev_res.get("executed", 0) > 0:
            st.success(f"🎉 [{symbol}] 주문이 정상 접수되었습니다! (성공: {prev_res['executed']}건)")
        elif prev_res.get("failed", 0) > 0:
            st.error(f"❌ [{symbol}] 주문 실행 실패! (성공: {prev_res.get('executed', 0)}건, 실패: {prev_res.get('failed', 0)}건)")
        else:
            st.info(f"ℹ️ [{symbol}] 실행된 주문이 없습니다.")
        for msg in prev_res.get("messages", []):
            st.write(f"- {msg}")
        st.divider()

    s_orders = [o for o in orders if o["action"] == "SELL"]
    b_orders = [o for o in orders if o["action"] == "BUY"]

    col_det1, col_det2 = st.columns(2)
    with col_det1:
        # 헤더 + 실행 버튼을 같은 라인에 배치
        hdr_col1, btn_col1 = st.columns([3, 1])
        with hdr_col1:
            st.markdown("#### 🔴 당일 전량 익절 매도 주문 (지정가)")
        with btn_col1:
            if st.button("매도 실행", key=f"exec_sell_{symbol}", type="primary", width="stretch"):
                result = bot.execute_daily_orders(symbol, action_filter="SELL")
                st.session_state[order_res_key] = result
                st.rerun()

        if s_orders:
            for s in s_orders:
                st.info(f"**익절 매도**: ${s['price']:.2f} (수량: {s['qty']:,}주 / +10% 익절)")
        else:
            st.write("보유 수량이 없거나 익절 조건 미충족")

    with col_det2:
        # 헤더 + 실행 버튼을 같은 라인에 배치
        hdr_col2, btn_col2 = st.columns([3, 1])
        with hdr_col2:
            st.markdown("#### 🟢 당일 분할 매수 주문 (LOC)")
        with btn_col2:
            if st.button("매수 실행", key=f"exec_buy_{symbol}", type="primary", width="stretch"):
                result = bot.execute_daily_orders(symbol, action_filter="BUY")
                st.session_state[order_res_key] = result
                st.rerun()

        if b_orders:
            for b in b_orders:
                st.success(f"**LOC 매수**: ${b['price']:.2f} 이하 (수량: {b['qty']:,}주)")
            st.caption("ℹ️ **LOC 주문 안내**: 장 마감 시점(새벽)에 체결되므로, 접수 직후에는 체결이 아닌 '미체결 접수' 상태로 유지됩니다. 하단 '거래요청 이력(미체결)'에서 접수 현황을 확인하실 수 있습니다.")
        else:
            st.write("매수 조건 미충족 또는 최대 회차 도달")

    st.markdown("---")

    # 3. 전략 시작일 변경
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
    chart_data = bot.api.get_daily_chart(symbol, count=60)

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
            sell_dates, sell_prices, sell_texts = [], [], []
            fail_dates, fail_prices, fail_texts = [], [], []
            avg_dates, avg_costs = [], []

            # 날짜별 평단가 추이 계산 (매수 체결 기준 누적 평단가)
            cum_qty = 0.0
            cum_cost = 0.0
            last_avg = 0.0

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
                        # 매수 체결 시 누적 수량/비용 갱신하여 평단가 계산
                        cum_qty += h_qty
                        cum_cost += h_qty * h_price
                        if cum_qty > 0:
                            last_avg = cum_cost / cum_qty
                        avg_dates.append(h_date)
                        avg_costs.append(last_avg)
                elif "매도" in h_type:
                    if is_failed:
                        fail_dates.append(h_date)
                        fail_prices.append(h_price)
                        fail_texts.append(f"❌ 매도 실패: {h_qty}주 @ ${h_price:.2f} ({h_status})")
                    else:
                        sell_dates.append(h_date)
                        sell_prices.append(h_price)
                        sell_texts.append(f"🎉 익절 매도: {h_qty}주 @ ${h_price:.2f} ({h_status})")
                        # 매도 시 수량 감소 (평단가는 유지)
                        cum_qty = max(0.0, cum_qty - h_qty)
                        if cum_qty > 0:
                            avg_dates.append(h_date)
                            avg_costs.append(last_avg)

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
            if avg_dates:
                fig.add_trace(go.Scatter(
                    x=avg_dates, y=avg_costs, mode='lines+markers', name='📉 날짜별 평단가 추이',
                    line=dict(color='#4ADE80', width=3, dash='dot'),
                    marker=dict(size=6, color='#4ADE80'),
                    text=[f"평단가: ${c:.2f}" for c in avg_costs], hoverinfo='text'
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

        try:
            st.plotly_chart(fig, width="stretch")
        except TypeError:
            st.plotly_chart(fig, use_container_width=True)
    else:
        if chart_data:
            df_c = pd.DataFrame(chart_data)
            df_c['date_fmt'] = pd.to_datetime(df_c['date'], format='%Y%m%d', errors='coerce').dt.strftime('%Y-%m-%d')
            st.line_chart(df_c.set_index('date_fmt')['close'])
        st.info("💡 `pip install plotly`를 가상환경(.venv)에 설치하시면 대화형 매수/매도 이력 마커 차트가 표출됩니다.")


    # 5. 종목 매매 및 체결/실패 히스토리 테이블 (KIS API 실계좌 단일 소스)
    st.subheader(f"📜 [{symbol}] 매수/매도 체결")
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

    st.markdown("---")

    # 6. TQQQ 거래요청 이력 상세 (inquire-ccnl, TTTS3035R/VTTS3035R)
    st.subheader(f"📋 [{symbol}] 거래요청 이력 상세")
    with st.expander(f"🔍 [{symbol}] 거래요청 이력 상세 보기 (start_date 이후)", expanded=False):
        # start_date 이후의 거래 이력 조회 (inquire-ccnl API)
        ccnl_start = clean_sd if clean_sd and clean_sd.isdigit() else default_start
        logger.info(f"[대시보드] 거래요청 이력 상세 조회 시작: symbol={symbol}, start_date={ccnl_start}, end_date={end_date_fmt}")
        ccnl_history = bot.api.get_overseas_order_ccnl(
            symbol=symbol,
            start_date=ccnl_start,
            end_date=end_date_fmt
        )
        logger.info(f"[대시보드] 거래요청 이력 상세 조회 완료: {len(ccnl_history)}건 (symbol={symbol})")

        if ccnl_history:
            ccnl_rows = []
            for h in ccnl_history:
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

                ccnl_rows.append({
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
            # 최신 날짜가 위로 오도록 내림차순 정렬 (일시 기준)
            ccnl_rows.sort(key=lambda r: str(r.get("일시", "")), reverse=True)
            st.dataframe(pd.DataFrame(ccnl_rows), width="stretch", hide_index=True)
        else:
            st.info(f"start_date({ccnl_start}) 이후의 거래요청 이력이 없습니다.")


def page_main_dashboard():
    """메인 대시보드: 무한매수 현황 & 당일 주문"""
    render_css()
    render_sidebar()

    st.title("🇺🇸 KIS 라오어 무한매수법 전담 자동투자 시스템")

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
                        "상태": "🟢 운용 중" if st_d.get("status") == "BUYING" else ("🔵 익절 완료" if st_d.get("status") == "COMPLETED" else "🟡 대기 중")
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
    st.subheader("종목별로 무한매수 파라미터를 수정하고 [설정 적용] 버튼을 누르면 변경 사항이 반영됩니다.")
    st.caption("ℹ️ 설정을 변경하여 적용하면 **설정값만 업데이트**되며, 진행 중인 전략 상태(진행 회차, 상태, 시작일)는 유지됩니다.")

    # 직전 설정 저장 결과 피드백 표시
    if "cfg_save_result" in st.session_state:
        res_type, res_msg = st.session_state.pop("cfg_save_result")
        if res_type == "success":
            st.success(res_msg)
        else:
            st.warning(res_msg)

    # Google Sheets 연동 상태 확인 및 상단 배너
    gss = bot.infinite_state_mgr.gss_mgr if hasattr(bot.infinite_state_mgr, "gss_mgr") else None
    is_gss_connected = bool(gss and gss.is_connected)

    col_gss_status, col_gss_reload = st.columns([7, 3])
    with col_gss_status:
        if is_gss_connected:
            sheet_title = getattr(gss.spreadsheet, "title", "구글 시트")
            st.success(f"🟢 **Google Sheets 영속 연동 중** (`{sheet_title}` > `Settings` 워크시트 우선 로딩)")
        else:
            st.warning("⚠️ **Google Sheets 미연동**: Streamlit Cloud(streamlit.io)는 재시작 시 로컬 파일이 초기화될 수 있으므로, 영속 저장을 위해 Secrets(`gcp_service_account`) 설정을 권장합니다.")
    
    with col_gss_reload:
        if st.button("🔄 구글 시트에서 설정 다시 불러오기", width="stretch"):
            if is_gss_connected:
                loaded = config.load_settings_from_google_sheet(gss)
                if loaded:
                    st.session_state.cfg_stocks = list(config.INFINITE_STOCKS)
                    st.session_state.cfg_stock_configs = {
                        sym: config.get_stock_config(sym)
                        for sym in st.session_state.cfg_stocks
                    }
                    bot.reload_settings_from_config()
                    st.success("✅ 구글 시트에서 최신 설정을 성공적으로 불러와 적용했습니다!")
                    st.rerun()
                else:
                    st.info("구글 시트에 저장된 설정이 없어 현재 설정을 유지합니다.")
            else:
                st.error("구글 시트에 연결되어 있지 않습니다.")

    # 현재 설정값을 세션 상태에 저장 (페이지 리로드 시 유지)
    if "cfg_stocks" not in st.session_state:
        st.session_state.cfg_stocks = list(getattr(config, "INFINITE_STOCKS", ["TQQQ"]))
    if "cfg_stock_configs" not in st.session_state:
        # 종목별 설정: {symbol: {total_budget_usd, division_count, target_roi, exhaust_action, exhaust_target_roi}}
        st.session_state.cfg_stock_configs = {}
        for sym in st.session_state.cfg_stocks:
            st.session_state.cfg_stock_configs[sym] = config.get_stock_config(sym)
    if "cfg_max_stocks" not in st.session_state:
        st.session_state.cfg_max_stocks = int(getattr(config, "MAX_STOCKS_HOLDING", 5))
    if "cfg_api_delay" not in st.session_state:
        st.session_state.cfg_api_delay = float(getattr(config, "API_CALL_DELAY", 0.2))

    # 종목 추가/삭제 처리
    with st.expander("➕ 종목 추가 / 삭제", expanded=False):
        col_add1, col_add2 = st.columns([3, 1])
        with col_add1:
            new_stock_input = st.text_input(
                "새 종목 코드 (티커)",
                placeholder="예: SOXL, SPXL, TQQQ",
                key="cfg_input_new_stock"
            )
        with col_add2:
            if st.button("종목 추가", key="cfg_btn_add_stock", type="primary"):
                new_stock = new_stock_input.strip().upper()
                if not new_stock:
                    st.warning("종목 코드를 입력해주세요.")
                elif new_stock in st.session_state.cfg_stocks:
                    st.warning(f"'{new_stock}'은(는) 이미 등록된 종목입니다.")
                else:
                    # 새 종목의 기본 설정값은 현재 전역 기본값 사용
                    default_cfg = config.get_stock_config(new_stock)
                    st.session_state.cfg_stocks.append(new_stock)
                    st.session_state.cfg_stock_configs[new_stock] = default_cfg
                    st.success(f"'{new_stock}' 종목이 추가되었습니다. 아래에서 설정값을 입력하세요.")
                    st.rerun()

        # 기존 종목 삭제
        if len(st.session_state.cfg_stocks) > 1:
            col_del1, col_del2 = st.columns([3, 1])
            with col_del1:
                del_stock = st.selectbox(
                    "삭제할 종목 선택",
                    options=st.session_state.cfg_stocks,
                    key="cfg_input_del_stock"
                )
            with col_del2:
                if st.button("종목 삭제", key="cfg_btn_del_stock"):
                    if del_stock in st.session_state.cfg_stocks:
                        st.session_state.cfg_stocks.remove(del_stock)
                        st.session_state.cfg_stock_configs.pop(del_stock, None)
                        st.success(f"'{del_stock}' 종목이 삭제되었습니다.")
                        st.rerun()
        else:
            st.caption("최소 1개 이상의 종목이 필요합니다.")

    st.divider()

    # 종목별 설정 입력 폼
    st.markdown("### 🇺🇸 라오어 무한매수법 v2.0 파라미터 (종목별)")
    st.write(f"- **전담 매매 전략**: `라오어 무한매수법 v2.0 (INFINITE_BUYING)`")

    # 각 종목 입력값을 저장할 임시 변수
    new_stock_configs = {}
    for idx, sym in enumerate(st.session_state.cfg_stocks):
        cfg = st.session_state.cfg_stock_configs.get(sym, config.get_stock_config(sym))
        with st.expander(f"📌 {sym} 설정", expanded=True):
            col1, col2 = st.columns(2)
            with col1:
                new_budget = st.number_input(
                    f"{sym} - 종목당 총 예산 ($)",
                    min_value=100.0,
                    max_value=1000000.0,
                    value=float(cfg.get("total_budget_usd", 5000.0)),
                    step=100.0,
                    key=f"cfg_input_budget_{sym}",
                    help="이 종목의 분할 매수에 사용할 총 예산 (USD)"
                )
                new_division = st.number_input(
                    f"{sym} - 총 분할 매수 횟수 (회차)",
                    min_value=1,
                    max_value=200,
                    value=int(cfg.get("division_count", 40)),
                    step=1,
                    key=f"cfg_input_division_{sym}",
                    help="이 종목의 무한매수 총 분할 횟수 (예: 40 = 40회차)"
                )
            with col2:
                new_roi = st.number_input(
                    f"{sym} - 전량 익절 목표 수익률 (%)",
                    min_value=1.0,
                    max_value=100.0,
                    value=float(cfg.get("target_roi", 0.10)) * 100.0,
                    step=1.0,
                    key=f"cfg_input_roi_{sym}",
                    help="이 종목의 전량 익절 매도 목표 수익률 (예: 10 = +10%)"
                )

                # 40회차 소진 대응 옵션 - 종목별 선택
                exhaust_options = [
                    ("HOLD", "🛡️ 1. 무한 대기 (추가 매수 중단, +10% 익절 매도 대기)"),
                    ("REBALANCE_QUARTER", "✂️ 2. 쿼터 손절 & 순환 매매 (1회차 매도 + LOC 재매수로 평단가 인하)"),
                    ("LOWER_TARGET", "🎯 3. 목표수익률 하향 빠른 탈출 (도달 시 목표 수익률 자동 하향)"),
                ]
                action_keys = [opt[0] for opt in exhaust_options]
                current_idx = action_keys.index(cfg.get("exhaust_action", "HOLD")) if cfg.get("exhaust_action", "HOLD") in action_keys else 0

                selected_action_tuple = st.selectbox(
                    f"{sym} - 40회차 소진 시 대응 전략",
                    options=exhaust_options,
                    index=current_idx,
                    format_func=lambda x: x[1],
                    key=f"cfg_input_exhaust_action_{sym}",
                    help="이 종목이 최대 분할 회차까지 매수했으나 목표가에 도달하지 않았을 때의 동작 방식"
                )
                new_exhaust_action = selected_action_tuple[0]

                if new_exhaust_action == "LOWER_TARGET":
                    new_exhaust_roi = st.number_input(
                        f"{sym} - 40회차 소진 시 탈출 목표 수익률 (%)",
                        min_value=0.5,
                        max_value=50.0,
                        value=float(cfg.get("exhaust_target_roi", 0.05)) * 100.0,
                        step=0.5,
                        key=f"cfg_input_exhaust_roi_{sym}",
                        help="이 종목이 40회차에 도달 시 적용할 하향 목표 수익률 (예: 5 = +5.0%)"
                    )
                else:
                    new_exhaust_roi = float(cfg.get("exhaust_target_roi", 0.05)) * 100.0

            new_stock_configs[sym] = {
                "total_budget_usd": float(new_budget),
                "division_count": int(new_division),
                "target_roi": float(new_roi) / 100.0,
                "exhaust_action": new_exhaust_action,
                "exhaust_target_roi": float(new_exhaust_roi) / 100.0,
            }

    st.divider()

    # 설정 변경 감지
    stocks_list = list(st.session_state.cfg_stocks)
    changed = False

    # 종목 리스트 변경 감지
    if stocks_list != list(getattr(config, "INFINITE_STOCKS", ["TQQQ"])):
        changed = True

    # 각 종목의 설정 변경 감지
    if not changed:
        for sym in stocks_list:
            new_cfg = new_stock_configs.get(sym, {})
            old_cfg = config.get_stock_config(sym)
            if (abs(new_cfg.get("total_budget_usd", 0) - old_cfg["total_budget_usd"]) > 0.01 or
                new_cfg.get("division_count", 0) != old_cfg["division_count"] or
                abs(new_cfg.get("target_roi", 0) - old_cfg["target_roi"]) > 0.0001 or
                new_cfg.get("exhaust_action", "") != old_cfg["exhaust_action"] or
                abs(new_cfg.get("exhaust_target_roi", 0) - old_cfg["exhaust_target_roi"]) > 0.0001):
                changed = True
                break

    if changed:
        st.warning("설정값이 변경되었습니다. [설정 적용] 버튼을 누르면 변경 사항이 반영됩니다. (전략 진행 상태는 유지)")

    if st.button("💾 설정 적용", type="primary", width="stretch", disabled=not changed):
        # 1. config 모듈의 설정값을 런타임에 업데이트
        setattr(config, "INFINITE_STOCKS", stocks_list)
        setattr(config, "TARGET_STOCKS", stocks_list)
        setattr(config, "INFINITE_STOCK_CONFIGS", new_stock_configs)

        # 2. 봇의 설정값도 동기화
        bot.infinite_stocks = stocks_list
        bot.target_symbols = stocks_list

        # 3. 무한매수 설정값만 업데이트 (전략 진행 상태는 유지)
        for sym in stocks_list:
            cfg = new_stock_configs[sym]
            bot.infinite_state_mgr.update_settings(
                sym,
                total_budget_usd=cfg["total_budget_usd"],
                division_count=cfg["division_count"],
                target_roi=cfg["target_roi"],
                exhaust_action=cfg["exhaust_action"],
                exhaust_target_roi=cfg["exhaust_target_roi"]
            )

        # 4. 영속 설정 저장 (로컬 JSON + Google Sheet)
        settings_data = {
            "infinite_stocks": stocks_list,
            "infinite_stock_configs": new_stock_configs,
            "max_stocks_holding": st.session_state.cfg_max_stocks,
            "api_call_delay": st.session_state.cfg_api_delay,
        }

        # 4-1. 로컬 JSON 파일에 저장
        try:
            with open(config.SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(settings_data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 영속 설정 파일({config.SETTINGS_FILE}) 저장 완료")
        except Exception as e:
            logger.error(f"영속 설정 파일({config.SETTINGS_FILE}) 저장 실패: {e}")
            st.error(f"설정 파일 저장 실패: {e}")

        # 4-2. Google Sheet 'Settings' 워크시트에 저장 (영속화)
        gss_saved = False
        gss_msg = ""
        try:
            gss = bot.infinite_state_mgr.gss_mgr
            if gss and gss.is_connected:
                gss_saved, gss_msg = gss.sync_settings_to_sheet(settings_data)
            else:
                gss_msg = "Google Sheets 미연동 상태 (로컬 파일에만 저장됨)"
                logger.warning("Google Sheet 미연동 상태 - 설정값은 로컬 파일에만 저장됩니다.")
        except Exception as e:
            gss_msg = f"Google Sheet 저장 예외: {e}"
            logger.warning(gss_msg)

        # 5. 세션 상태에 새 설정값 저장
        st.session_state.cfg_stocks = stocks_list
        st.session_state.cfg_stock_configs = new_stock_configs

        logger.info(f"⚙️ 무한매수 설정 변경 완료: 종목={stocks_list}")
        for sym in stocks_list:
            cfg = new_stock_configs[sym]
            logger.info(f"  - {sym}: 예산=${cfg['total_budget_usd']:,.0f}, 분할={cfg['division_count']}회, 목표=+{cfg['target_roi']*100:.1f}%, 소진대응={cfg['exhaust_action']}")

        if gss_saved:
            st.session_state["cfg_save_result"] = ("success", f"✅ 설정이 구글 시트('Settings' 시트) 및 로컬 파일에 성공적으로 영속 저장되었습니다! (진행 상태 유지)")
        else:
            st.session_state["cfg_save_result"] = ("warning", f"⚠️ 설정이 로컬에 저장되었으나 구글 시트 동기화 실패: {gss_msg}\nStreamlit Cloud(streamlit.io) 인스턴스 재시작 시 유실될 수 있으니 구글 시트 권한/Secrets를 확인하세요.")
        st.rerun()

    # 현재 적용 중인 설정 요약 표시
    st.markdown("### 📋 현재 적용 중인 설정")
    for sym in getattr(config, "INFINITE_STOCKS", ["TQQQ"]):
        cfg = config.get_stock_config(sym)
        cur_ex = cfg["exhaust_action"]
        cur_ex_name = {
            "HOLD": "🛡️ 무한대기",
            "REBALANCE_QUARTER": "✂️ 쿼터순환",
            "LOWER_TARGET": f"🎯 하향(+{cfg['exhaust_target_roi']*100:.0f}%)"
        }.get(cur_ex, cur_ex)
        col_sum1, col_sum2, col_sum3, col_sum4, col_sum5 = st.columns(5)
        with col_sum1:
            st.metric("운용 대상", sym)
        with col_sum2:
            st.metric("총 예산", f"${cfg['total_budget_usd']:,.0f}")
        with col_sum3:
            st.metric("분할 횟수", f"{cfg['division_count']} 회차")
        with col_sum4:
            st.metric("목표 수익률", f"+{cfg['target_roi']*100:.1f}%")
        with col_sum5:
            st.metric("40회차 소진 대응", cur_ex_name)
        st.divider()


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
