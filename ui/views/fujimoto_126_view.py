"""
KIS Auto Trading - Fujimoto Shigeru 1:2:6 Split Exit & Zone Notification View
일본 전설적 트레이더 후지모토 시게루의 '1:2:6 매매법'에 기반하여
현재 KIS 계좌 보유 주식 및 수동(매뉴얼) 등록 종목의 3대 지표(RSI, MACD, 일목균형표 구름대) 구간을 진단하고
1:2:6 비율(1/9, 2/9, 6/9) 분할청산 추천 및 텔레그램 알림(Noti)을 제공하는 전용 관제 페이지
"""
import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots

import app_config as config
from time_utils import today, now_str
from core.stock_code import normalize_stock_code
from core.indicators import calculate_technical_indicators, evaluate_fujimoto_126_exit
from telegram_notifier import notifier
from ui.flash import flash
from ui.views.stock_checker_view import _resolve_stock


STAGE_LABELS = {
    0: "0단계 (미청산 · 9/9 보유)",
    1: "1차 완료 (1/9 청산 · 잔여 8/9)",
    2: "2차 완료 (1+2/9 청산 · 잔여 6/9)",
    3: "3차 완료 (전량 청산 완료)"
}


def _fetch_stock_df_and_price(api, code: str, fallback_price: float = 0.0):
    """종목의 일봉(최소 85봉) 및 실시간 현재가를 조회하여 기술적 지표 DataFrame 반환"""
    candles = api.get_daily_chart(code, count=90) or []
    rt = api.get_stock_price(code) or {}
    curr_price = float(rt.get("price", 0.0) or fallback_price or 0.0)
    stock_name = rt.get("name") or rt.get("hts_kor_isnm") or ""

    if rt.get("rt_cd") == "0" and curr_price > 0:
        today_str = today().strftime("%Y%m%d")
        is_weekend = (today().weekday() >= 5)
        entry = {
            "date": today_str,
            "close": curr_price,
            "open": float(rt.get("stck_oprc", curr_price) or curr_price),
            "high": float(rt.get("stck_hgpr", curr_price) or curr_price),
            "low": float(rt.get("stck_lwpr", curr_price) or curr_price),
            "volume": int(rt.get("acml_vol", 0) or 0)
        }
        if not is_weekend:
            if not candles or str(candles[-1].get("date", "")) != today_str:
                candles.append(entry)
            else:
                candles[-1].update(entry)

    df = calculate_technical_indicators(candles, is_intraday=True)
    if curr_price <= 0 and df is not None and not df.empty:
        curr_price = float(df.iloc[-1]["close"])
    return df, curr_price, stock_name


def _render_fujimoto_126_chart(df: pd.DataFrame, name: str, code: str, avg_buy_price: float, buy_date: str, chart_key: str):
    """일목균형표 구름대(선행스팬 A/B) + 매수가/매수일 마커 + MACD + RSI 3단 인터랙티브 차트"""
    if df is None or df.empty:
        st.warning("차트를 표시할 일봉 데이터가 부족합니다.")
        return

    plot_df = df.tail(75).copy().reset_index(drop=True)
    dates = plot_df["date"].astype(str).tolist()
    formatted_dates = [f"{d[:4]}-{d[4:6]}-{d[6:8]}" if len(d) == 8 else d for d in dates]

    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.04,
        row_heights=[0.56, 0.22, 0.22],
        subplot_titles=(
            f"📈 {name} ({code}) 일봉 & 일목균형표 구름대 (3단계 추세 기준)",
            "📊 MACD (12, 26, 9) — 2단계 모멘텀 데드/골든크로스",
            "⚡ RSI (14) — 1단계 과열(70) 이탈 & 과매도(30) 회복"
        )
    )

    # 1. 일목균형표 구름대 (선행스팬 A, B 채우기)
    if "senkou_span_a" in plot_df.columns and "senkou_span_b" in plot_df.columns:
        fig.add_trace(
            go.Scatter(
                x=formatted_dates,
                y=plot_df["senkou_span_a"],
                line=dict(color="rgba(16, 185, 129, 0.45)", width=1),
                name="선행스팬 A",
                hoverinfo="skip"
            ),
            row=1, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=formatted_dates,
                y=plot_df["senkou_span_b"],
                line=dict(color="rgba(239, 68, 68, 0.45)", width=1),
                fill="tonexty",
                fillcolor="rgba(56, 189, 248, 0.13)",
                name="일목 구름대 (Span A-B)"
            ),
            row=1, col=1
        )

    # 2. 캔들 차트 (한국식: 양봉 빨강, 음봉 파랑)
    fig.add_trace(
        go.Candlestick(
            x=formatted_dates,
            open=plot_df["open"],
            high=plot_df["high"],
            low=plot_df["low"],
            close=plot_df["close"],
            increasing_line_color="#ef4444",
            decreasing_line_color="#3b82f6",
            name="일봉"
        ),
        row=1, col=1
    )

    # 전환선 & 기준선
    if "tenkan_sen" in plot_df.columns:
        fig.add_trace(
            go.Scatter(
                x=formatted_dates,
                y=plot_df["tenkan_sen"],
                line=dict(color="#f59e0b", width=1.3, dash="dot"),
                name="전환선 (9일)"
            ),
            row=1, col=1
        )
    if "kijun_sen" in plot_df.columns:
        fig.add_trace(
            go.Scatter(
                x=formatted_dates,
                y=plot_df["kijun_sen"],
                line=dict(color="#a855f7", width=1.5),
                name="기준선 (26일)"
            ),
            row=1, col=1
        )

    # 매수가 수평선 표시
    if avg_buy_price > 0:
        fig.add_hline(
            y=avg_buy_price,
            line_dash="dash",
            line_color="#22c55e",
            line_width=1.8,
            annotation_text=f"매수가 {avg_buy_price:,.0f}원",
            annotation_position="top left",
            annotation_font_color="#4ade80",
            row=1, col=1
        )

    # 매수일 수직 마커 표시
    if buy_date:
        clean_bd = str(buy_date).strip().replace(".", "-").replace("/", "-")
        if len(clean_bd) == 8 and clean_bd.isdigit():
            clean_bd = f"{clean_bd[:4]}-{clean_bd[4:6]}-{clean_bd[6:8]}"
        if clean_bd in formatted_dates:
            fig.add_vline(
                x=clean_bd,
                line_dash="dot",
                line_color="#fde047",
                line_width=1.5,
                row=1, col=1
            )
            fig.add_annotation(
                x=clean_bd,
                y=float(plot_df["high"].max()),
                text=f"📅 매수일 ({clean_bd})",
                showarrow=True,
                arrowhead=2,
                arrowcolor="#fde047",
                font=dict(color="#fde047", size=11),
                bgcolor="rgba(15, 23, 42, 0.85)",
                row=1, col=1
            )

    # 3. MACD 서브플롯 (Row 2)
    if "macd_hist" in plot_df.columns:
        hist_colors = ["#ef4444" if v >= 0 else "#3b82f6" for v in plot_df["macd_hist"]]
        fig.add_trace(
            go.Bar(
                x=formatted_dates,
                y=plot_df["macd_hist"],
                marker_color=hist_colors,
                name="MACD Hist"
            ),
            row=2, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=formatted_dates,
                y=plot_df["macd_line"],
                line=dict(color="#38bdf8", width=1.5),
                name="MACD"
            ),
            row=2, col=1
        )
        fig.add_trace(
            go.Scatter(
                x=formatted_dates,
                y=plot_df["macd_signal"],
                line=dict(color="#f97316", width=1.5),
                name="Signal"
            ),
            row=2, col=1
        )

    # 4. RSI 서브플롯 (Row 3)
    if "rsi14" in plot_df.columns:
        fig.add_trace(
            go.Scatter(
                x=formatted_dates,
                y=plot_df["rsi14"],
                line=dict(color="#c084fc", width=1.8),
                name="RSI(14)"
            ),
            row=3, col=1
        )
        fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", line_width=1, row=3, col=1, annotation_text="과열 70 (1차 청산 기준)", annotation_position="top right")
        fig.add_hline(y=30, line_dash="dash", line_color="#38bdf8", line_width=1, row=3, col=1, annotation_text="과매도 30 (1차 매수 기준)", annotation_position="bottom right")

    fig.update_layout(
        template="plotly_dark",
        height=740,
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
        paper_bgcolor="#0b0f19",
        plot_bgcolor="#0f172a"
    )
    fig.update_xaxes(type="category", nticks=10)
    st.plotly_chart(fig, width="stretch", key=chart_key)


def render_fujimoto_126(api, screener, summary: Dict[str, Any], holdings: List[Dict[str, Any]]):
    """후지모토 시게루 1:2:6 분할청산 관제 메인 뷰 렌더러"""
    st.title("📐 후지모토 시게루 1:2:6 구간 알림 & 분할청산 관제")
    st.caption(
        "일본의 전설적 트레이더 후지모토 시게루의 **'가격이 아니라 증거(지표)에 따라 1:2:6으로 나누어 대응한다'**는 매매 원칙에 따라, "
        "현재 보유 종목과 수동 등록 종목의 **구간을 실시간 진단(Noti)**하고 **1/9 · 2/9 · 6/9 분할청산**을 추천합니다."
    )

    # 1. 전략 핵심 요약 배너
    st.markdown("""
        <div style="background: linear-gradient(135deg, #0f172a, #1e1b4b); border: 1px solid #334155; border-radius: 12px; padding: 14px 18px; margin-bottom: 16px;">
            <div style="font-size: 0.9rem; font-weight: 800; color: #38bdf8; margin-bottom: 8px;">
                🧭 후지모토 시게루 1 : 2 : 6 분할 매수 · 분할 청산 3대 증거 원칙
            </div>
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 10px; font-size: 0.8rem; color: #e2e8f0;">
                <div style="background: rgba(15, 23, 42, 0.75); padding: 10px 12px; border-radius: 8px; border-left: 3px solid #eab308;">
                    <b style="color: #fde047;">① 1차 구간 (비중 1/9 · 11.1%)</b><br>
                    • <b>매수:</b> RSI 30 과매도 회복 시 정찰병 <code>1</code> 투입<br>
                    • <b>청산:</b> <b>RSI 70 과열 도달 후 70 하향 이탈</b> 시 <code>1/9</code> 선제 익절
                </div>
                <div style="background: rgba(15, 23, 42, 0.75); padding: 10px 12px; border-radius: 8px; border-left: 3px solid #f97316;">
                    <b style="color: #fb923c;">② 2차 구간 (비중 2/9 · 22.2%)</b><br>
                    • <b>매수:</b> MACD 골든크로스 확인 시 <code>2</code> 추가 투입<br>
                    • <b>청산:</b> <b>MACD 데드크로스(시그널 하향이탈)</b> 시 <code>2/9</code> 추가 청산
                </div>
                <div style="background: rgba(15, 23, 42, 0.75); padding: 10px 12px; border-radius: 8px; border-left: 3px solid #ef4444;">
                    <b style="color: #f87171;">③ 3차 구간 (비중 6/9 · 66.7%)</b><br>
                    • <b>매수:</b> 일목균형표 구름대 상향 돌파 시 승부처 <code>6</code> 투입<br>
                    • <b>청산:</b> <b>일목 구름대 하단 이탈</b> 또는 <b>손절선 침범</b> 시 <code>6/9(전량)</code> 청산
                </div>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # 2. 로컬 JSON + Google Sheet(Fujimoto126 탭)에서 1:2:6 포지션 상태 로드
    tracker = screener.position_tracker
    force_sheet = st.session_state.pop("force_126_sheet_sync", False)
    saved_126_map = tracker.load_fujimoto_126_positions(force_sheet_sync=force_sheet)
    positions_state = tracker.load_positions_state()

    # 3. 수동(매뉴얼) 종목 추가 및 관리 Expander
    with st.expander("➕ 수동(매뉴얼) 종목 추가 & 구글 시트 동기화 관리 (타 증권사 보유 / 관심 추적 종목)", expanded=False):
        st.caption(
            "현재 KIS 계좌에 없더라도 **종목명(또는 코드), 매수일, 매수가, 수량**을 등록하면 **로컬 JSON(`fujimoto_126_positions.json`)과 구글 시트(`Fujimoto126` 워크시트)에 동시 저장**되어 실시간 시그널 및 텔레그램 알림을 받을 수 있습니다."
        )
        col_f1, col_f2, col_f3, col_f4, col_f5, col_f6 = st.columns([2.2, 1.1, 1.4, 1.5, 1.2, 1.2])
        with col_f1:
            manual_query = st.text_input("종목명 또는 6자리 코드", key="f126_manual_query", placeholder="예: 삼성전자, 파두, 005930")
        with col_f2:
            manual_market = st.selectbox("시장", ["KOSPI", "KOSDAQ"], key="f126_manual_market")
        with col_f3:
            manual_buy_date = st.date_input("매수일", value=today(), key="f126_manual_buy_date")
        with col_f4:
            manual_buy_price = st.number_input("매수가 (평단가, 원)", min_value=0, value=50000, step=500, key="f126_manual_buy_price")
        with col_f5:
            manual_qty = st.number_input("보유수량 (기본 9주)", min_value=1, value=9, step=1, key="f126_manual_qty", help="1:2:6 비율 계산이 딱 떨어지도록 미지정 시 9주를 기본으로 사용합니다.")
        with col_f6:
            st.write("")
            st.write("")
            if st.button("➕ 종목 등록/수정", key="f126_add_manual_btn", type="primary", width="stretch"):
                code_resolved, name_resolved, mkt_resolved = _resolve_stock(manual_query, default_market=manual_market)
                if not code_resolved:
                    st.error("❌ 종목을 식별할 수 없습니다. 정확한 종목명이나 6자리 숫자 종목코드를 입력해 주세요.")
                elif manual_buy_price <= 0:
                    st.error("❌ 매수가(평단가)는 0원보다 커야 합니다.")
                else:
                    # API로 정확한 종목명 확인 시도
                    rt_info = api.get_stock_price(code_resolved) or {}
                    api_name = rt_info.get("name") or rt_info.get("hts_kor_isnm")
                    if api_name and not api_name.startswith("종목_"):
                        name_resolved = api_name
                    buy_date_str = manual_buy_date.strftime("%Y-%m-%d")
                    tracker.upsert_fujimoto_126_position(
                        code=code_resolved,
                        name=name_resolved or code_resolved,
                        avg_buy_price=float(manual_buy_price),
                        buy_date=buy_date_str,
                        qty=int(manual_qty),
                        market=mkt_resolved,
                        is_manual=True,
                        exit_126_stage=0
                    )
                    flash(f"✅ [{name_resolved}({code_resolved})] 수동 관제 종목 등록 완료! (로컬 JSON & Google Sheet 동기화됨)")
                    st.rerun()

        # 등록된 수동 종목 목록 및 빠른 삭제
        manual_only = {k: v for k, v in saved_126_map.items() if v.get("is_manual", False)}
        c_sync1, c_sync2 = st.columns([3, 1])
        with c_sync1:
            if manual_only:
                st.markdown(f"**📝 현재 등록된 수동 관제 종목 ({len(manual_only)}개):** " + ", ".join(
                    f"`{v.get('name', k)}({k}) | 매수일:{v.get('buy_date', '-')} | {float(v.get('avg_buy_price', 0)):,.0f}원`"
                    for k, v in manual_only.items()
                ))
            else:
                st.caption("현재 등록된 수동 관제 종목이 없습니다. 위 입력창에서 종목·매수일·매수가를 추가해 보세요.")
        with c_sync2:
            if st.button("🔄 구글 시트 강제 동기화", key="f126_force_sheet_btn", width="stretch"):
                st.session_state["force_126_sheet_sync"] = True
                flash("📊 Google Sheet 'Fujimoto126' 탭과 최신 상태를 동기화했습니다.")
                st.rerun()

    # 4. KIS 보유 종목 + 수동 등록 종목 통합 리스트 구성
    combined_positions: List[Dict[str, Any]] = []
    kis_codes = set()

    for h in holdings:
        raw_code = str(h.get("code", "")).strip().lstrip("'")
        if not raw_code:
            continue
        code_6 = normalize_stock_code(raw_code)
        kis_codes.add(code_6)

        pos_st = positions_state.get(code_6) or positions_state.get(raw_code) or {}
        f126_st = saved_126_map.get(code_6) or {}

        buy_date_val = f126_st.get("buy_date") or pos_st.get("buy_date") or ""
        if len(str(buy_date_val)) == 8 and str(buy_date_val).isdigit():
            buy_date_val = f"{buy_date_val[:4]}-{buy_date_val[4:6]}-{buy_date_val[6:8]}"

        combined_positions.append({
            "code": code_6,
            "name": h.get("name", f126_st.get("name", code_6)),
            "is_manual": False,
            "market": f126_st.get("market", "KOSPI"),
            "buy_date": buy_date_val,
            "avg_buy_price": float(h.get("avg_buy_price", h.get("avg_price", 0.0)) or 0.0),
            "current_price": float(h.get("current_price", 0.0) or 0.0),
            "qty": int(h.get("quantity", h.get("qty", 0)) or 0),
            "exit_126_stage": int(f126_st.get("exit_126_stage", 0) or 0)
        })

    for code_6, m_item in saved_126_map.items():
        if code_6 in kis_codes:
            continue
        if not m_item.get("is_manual", True):
            continue
        combined_positions.append({
            "code": code_6,
            "name": m_item.get("name", code_6),
            "is_manual": True,
            "market": m_item.get("market", "KOSPI"),
            "buy_date": str(m_item.get("buy_date", "") or ""),
            "avg_buy_price": float(m_item.get("avg_buy_price", 0.0) or 0.0),
            "current_price": 0.0,
            "qty": int(m_item.get("qty", 9) or 9),
            "exit_126_stage": int(m_item.get("exit_126_stage", 0) or 0)
        })

    if not combined_positions:
        st.info("현재 관제 중인 보유 주식이 없습니다. KIS 계좌에 주식을 보유하거나 위 **[➕ 수동(매뉴얼) 종목 추가]** 탭에서 종목·매수일·매수가를 등록해 주세요.")
        _render_risk_2pct_calculator(summary)
        return

    # 5. 각 관제 종목별 일봉 지표 및 1:2:6 분할청산 시그널 평가
    sl_rate_setting = float(config.CURRENT_SETTINGS.get("stop_loss_rate", -0.05) or -0.05)
    evaluated_list: List[Dict[str, Any]] = []
    dfs_by_code: Dict[str, pd.DataFrame] = {}

    with st.spinner("📐 보유 및 수동 등록 종목의 3대 지표(RSI·MACD·일목구름대) 및 1:2:6 구간을 분석 중입니다..."):
        for item in combined_positions:
            c_code = item["code"]
            df, live_price, api_stock_name = _fetch_stock_df_and_price(api, c_code, fallback_price=item["current_price"])
            if df is not None:
                dfs_by_code[c_code] = df
            if api_stock_name and (item["name"] == c_code or item["name"].startswith("종목_")):
                item["name"] = api_stock_name

            eval_res = evaluate_fujimoto_126_exit(
                df=df,
                avg_buy_price=item["avg_buy_price"],
                holding_qty=item["qty"],
                buy_date=item["buy_date"],
                current_exit_stage=item["exit_126_stage"],
                stop_loss_rate=sl_rate_setting
            )
            merged_item = {**item, **eval_res}
            evaluated_list.append(merged_item)

    # 6. 요약 메트릭 & 자동/수동 텔레그램 Noti 컨트롤 바
    action_items = [x for x in evaluated_list if x.get("is_action_needed")]
    stage1_cnt = sum(1 for x in evaluated_list if x.get("target_stage") == 1 and x.get("is_action_needed"))
    stage2_cnt = sum(1 for x in evaluated_list if x.get("target_stage") == 2 and x.get("is_action_needed"))
    stage3_cnt = sum(1 for x in evaluated_list if x.get("target_stage") == 3 and x.get("is_action_needed"))
    cruise_cnt = len(evaluated_list) - len(action_items)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("전체 관제 종목", f"{len(evaluated_list)}종목", f"KIS {len(kis_codes)} / 수동 {len(evaluated_list)-len(kis_codes)}")
    m2.metric("🟢 홀딩/과열대기", f"{cruise_cnt}종목")
    m3.metric("🟡 1차 청산 권고 (1/9)", f"{stage1_cnt}종목", delta="RSI 70 이탈" if stage1_cnt else None, delta_color="off")
    m4.metric("🟠 2차 청산 권고 (2/9)", f"{stage2_cnt}종목", delta="MACD 데드" if stage2_cnt else None, delta_color="off")
    m5.metric("🔴 3차 전량 권고 (6/9)", f"{stage3_cnt}종목", delta="구름대 이탈/손절" if stage3_cnt else None, delta_color="inverse" if stage3_cnt else "off")

    # 자동 알림 토글 & 일괄 알림 발송 버튼
    c_noti1, c_noti2 = st.columns([3, 1.5])
    with c_noti1:
        auto_noti = st.checkbox(
            "🔔 페이지 조회 시 신규 분할청산 구간 진입 종목 자동 텔레그램 알림 발송 (당일 중복 방지 적용)",
            value=True,
            key="f126_auto_telegram_noti"
        )
    with c_noti2:
        if st.button(
            f"📲 시그널 종목({len(action_items)}건) 즉시 텔레그램 발송",
            key="f126_manual_bulk_noti_btn",
            disabled=(len(action_items) == 0),
            width="stretch"
        ):
            sent_cnt = 0
            for act in action_items:
                ok = notifier.send_126_exit_notification(
                    name=act["name"],
                    code=act["code"],
                    is_manual=act["is_manual"],
                    buy_date=act.get("buy_date", "-"),
                    avg_buy_price=act["avg_buy_price"],
                    current_price=act["current_price"],
                    profit_rate=act["profit_rate"],
                    holding_qty=act["holding_qty"],
                    target_stage=act["target_stage"],
                    action_label=act["action_label"],
                    recommended_qty=act["recommended_qty"],
                    recommended_ratio_str=act["recommended_ratio_str"],
                    rsi14=act.get("rsi14", 50.0),
                    macd_status=act.get("macd_status", "-"),
                    cloud_pos_label=act.get("cloud_pos_label", "-"),
                    reasons=act.get("reasons", []),
                    force=True
                )
                if ok:
                    sent_cnt += 1
            if sent_cnt > 0:
                flash(f"📲 텔레그램으로 {sent_cnt}건의 1:2:6 분할청산 추천 알림을 전송했습니다!")
            else:
                st.warning("⚠️ 텔레그램 발송에 실패했습니다. [⚙️ 시스템 환경설정]에서 텔레그램 알림 활성화 및 봇 설정을 확인하세요.")

    # 자동 알림 처리 (당일 미발송 시그널만 1회 자동 전송)
    if auto_noti and action_items:
        auto_sent = 0
        for act in action_items:
            ok = notifier.send_126_exit_notification(
                name=act["name"],
                code=act["code"],
                is_manual=act["is_manual"],
                buy_date=act.get("buy_date", "-"),
                avg_buy_price=act["avg_buy_price"],
                current_price=act["current_price"],
                profit_rate=act["profit_rate"],
                holding_qty=act["holding_qty"],
                target_stage=act["target_stage"],
                action_label=act["action_label"],
                recommended_qty=act["recommended_qty"],
                recommended_ratio_str=act["recommended_ratio_str"],
                rsi14=act.get("rsi14", 50.0),
                macd_status=act.get("macd_status", "-"),
                cloud_pos_label=act.get("cloud_pos_label", "-"),
                reasons=act.get("reasons", []),
                force=False
            )
            if ok:
                auto_sent += 1
        if auto_sent > 0:
            st.toast(f"📲 신규 1:2:6 분할청산 시그널 {auto_sent}건이 텔레그램으로 자동 발송되었습니다.", icon="🔔")

    st.divider()

    # 7. 긴급/권고 분할청산 알림 배너 (시그널 발생 종목이 있을 때 상단 하이라이트)
    if action_items:
        st.subheader(f"🚨 현재 분할청산 시그널 발생 종목 ({len(action_items)}건)")
        for act in action_items:
            src_badge = "📝 수동등록" if act["is_manual"] else "🏦 KIS보유"
            border_col = "#ef4444" if act["target_stage"] == 3 else ("#f97316" if act["target_stage"] == 2 else "#eab308")
            st.markdown(f"""
                <div style="background: rgba(15, 23, 42, 0.9); border: 1px solid {border_col}; border-left: 5px solid {border_col}; border-radius: 10px; padding: 12px 16px; margin-bottom: 10px;">
                    <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;">
                        <div>
                            <span style="font-size: 0.75rem; background: #1e293b; color: #cbd5e1; padding: 2px 7px; border-radius: 4px; margin-right: 6px;">{src_badge}</span>
                            <b style="font-size: 1.02rem; color: #f8fafc;">{act['name']} ({act['code']})</b>
                            <span style="font-size: 0.8rem; color: #94a3b8; margin-left: 8px;">매수일: {act.get('buy_date') or '-'} | 매수가: {act['avg_buy_price']:,.0f}원 | 현재가: <b>{act['current_price']:,.0f}원 ({act['profit_rate']:+.2f}%)</b></span>
                        </div>
                        <div style="font-weight: 800; color: {border_col}; font-size: 0.95rem;">
                            {act['action_label']} ➔ 추천 매도: {act['recommended_qty']:,}주 ({act['recommended_ratio_str']}, 약 {act['recommended_amount']:,.0f}원)
                        </div>
                    </div>
                    <div style="font-size: 0.8rem; color: #cbd5e1; margin-top: 6px;">
                        • <b>판정 근거:</b> {' / '.join(act.get('reasons', []))}
                    </div>
                </div>
            """, unsafe_allow_html=True)

    # 8. 전체 관제 종목 상세 카드 & 단계 제어 리스트
    st.subheader("📋 관제 종목별 3대 지표 진단 & 1:2:6 분할청산 컨트롤")

    for idx, item in enumerate(evaluated_list):
        code = item["code"]
        name = item["name"]
        is_manual = item["is_manual"]
        src_badge_html = (
            '<span style="background:#312e81;color:#c7d2fe;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700;">📝 수동 등록</span>'
            if is_manual else
            '<span style="background:#064e3b;color:#6ee7b7;padding:2px 8px;border-radius:4px;font-size:0.75rem;font-weight:700;">🏦 KIS 보유</span>'
        )
        pr = item.get("profit_rate", 0.0)
        pr_color = "#ef4444" if pr > 0 else ("#38bdf8" if pr < 0 else "#94a3b8")

        with st.container(border=True):
            top_c1, top_c2, top_c3 = st.columns([3.2, 2.8, 2.0])
            with top_c1:
                st.markdown(
                    f"{src_badge_html} &nbsp; <b style='font-size:1.08rem;color:#f8fafc;'>{name}</b> "
                    f"<span style='color:#94a3b8;font-size:0.85rem;'>({code})</span> &nbsp; "
                    f"<span style='font-size:0.88rem;font-weight:700;'>{item.get('phase_badge', '')}</span>",
                    unsafe_allow_html=True
                )
                st.caption(
                    f"📅 매수일: **{item.get('buy_date') or '미지정'}** | "
                    f"매수가: **{item['avg_buy_price']:,.0f}원** | "
                    f"현재가: **{item['current_price']:,.0f}원** | "
                    f"수량: **{item['holding_qty']:,}주**"
                )
            with top_c2:
                rec_detail_str = f"({item['recommended_qty']:,}주 / {item['recommended_ratio_str']})" if item.get("is_action_needed") else ""
                st.markdown(
                    f"<div style='font-size:0.84rem;line-height:1.45;'>"
                    f"💰 수익률: <b style='color:{pr_color};font-size:0.98rem;'>{pr:+.2f}% ({item.get('profit_loss', 0):+,.0f}원)</b><br>"
                    f"🎯 <b>추천 액션:</b> <b style='color:#38bdf8;'>{item.get('action_label', '홀딩 유지')}</b> "
                    f"{rec_detail_str}"
                    f"</div>",
                    unsafe_allow_html=True
                )
            with top_c3:
                # 3대 지표 미니 신호등
                rsi_v = item.get("rsi14", 50.0)
                rsi_col = "#ef4444" if rsi_v >= 70 else ("#38bdf8" if rsi_v <= 30 else "#e2e8f0")
                macd_st = item.get("macd_status", "-")
                macd_col = "#10b981" if "골든" in macd_st else "#f97316"
                cloud_pos = item.get("cloud_pos", "ABOVE")
                cloud_col = "#10b981" if cloud_pos == "ABOVE" else ("#eab308" if cloud_pos == "INSIDE" else "#ef4444")

                st.markdown(
                    f"<div style='font-size:0.76rem;background:#0f172a;padding:6px 10px;border-radius:6px;border:1px solid #1e293b;'>"
                    f"• <b>1단계 RSI(14):</b> <span style='color:{rsi_col};font-weight:700;'>{rsi_v:.1f}</span> (최고 {item.get('max_rsi_since_buy', rsi_v):.1f})<br>"
                    f"• <b>2단계 MACD:</b> <span style='color:{macd_col};font-weight:700;'>{macd_st}</span> ({item.get('macd_hist', 0):+.1f})<br>"
                    f"• <b>3단계 구름대:</b> <span style='color:{cloud_col};font-weight:700;'>{item.get('cloud_pos_label', '-')}</span> (하단 {item.get('cloud_bottom', 0):,.0f}원)"
                    f"</div>",
                    unsafe_allow_html=True
                )

            # 하단 컨트롤 바: 청산 단계 변경, 텔레그램 개별 발송, 수동 종목 삭제
            ctrl_c1, ctrl_c2, ctrl_c3, ctrl_c4 = st.columns([3.0, 1.5, 1.5, 1.2])
            with ctrl_c1:
                cur_st = int(item.get("current_exit_stage", 0) or 0)
                new_st = st.selectbox(
                    "현재 분할청산 완료 단계 (변경 시 JSON & 구글 시트 자동 저장)",
                    options=[0, 1, 2, 3],
                    index=min(3, max(0, cur_st)),
                    format_func=lambda s: STAGE_LABELS.get(s, str(s)),
                    key=f"f126_stage_sel_{code}_{idx}",
                    label_visibility="collapsed"
                )
            with ctrl_c2:
                if st.button("💾 청산단계 저장", key=f"f126_save_stage_{code}_{idx}", width="stretch"):
                    tracker.update_fujimoto_126_stage(
                        code=code,
                        stage=new_st,
                        name=name,
                        avg_buy_price=item["avg_buy_price"],
                        qty=item["holding_qty"],
                        buy_date=item.get("buy_date", ""),
                        is_manual=is_manual
                    )
                    flash(f"✅ [{name}] 청산 단계가 '{STAGE_LABELS[new_st]}'(으)로 저장되었습니다. (JSON & Google Sheet 반영)")
                    st.rerun()
            with ctrl_c3:
                if st.button("📲 텔레그램 알림", key=f"f126_single_noti_{code}_{idx}", width="stretch"):
                    ok = notifier.send_126_exit_notification(
                        name=name,
                        code=code,
                        is_manual=is_manual,
                        buy_date=item.get("buy_date", "-"),
                        avg_buy_price=item["avg_buy_price"],
                        current_price=item["current_price"],
                        profit_rate=item["profit_rate"],
                        holding_qty=item["holding_qty"],
                        target_stage=max(1, item.get("target_stage", 1)),
                        action_label=item.get("action_label", "현재 구간 리포트"),
                        recommended_qty=item.get("recommended_qty", 0),
                        recommended_ratio_str=item.get("recommended_ratio_str", "-"),
                        rsi14=item.get("rsi14", 50.0),
                        macd_status=item.get("macd_status", "-"),
                        cloud_pos_label=item.get("cloud_pos_label", "-"),
                        reasons=item.get("reasons", []),
                        force=True
                    )
                    if ok:
                        flash(f"📲 [{name}] 1:2:6 구간 진단 알림을 텔레그램으로 전송했습니다!")
                        st.rerun()
                    else:
                        st.warning("텔레그램 전송 실패: 환경설정에서 텔레그램 활성화 여부를 확인해 주세요.")
            with ctrl_c4:
                if is_manual:
                    if st.button("🗑️ 종목 삭제", key=f"f126_del_btn_{code}_{idx}", width="stretch"):
                        tracker.delete_fujimoto_126_position(code)
                        flash(f"🗑️ [{name}({code})] 수동 관제 종목이 삭제되었습니다. (JSON & Google Sheet 동기화됨)")
                        st.rerun()
                else:
                    st.caption("🏦 KIS 계좌 연동")

    st.divider()

    # 9. 종목별 1:2:6 전용 차트 (일목균형표 구름대 + 매수가/매수일 + MACD + RSI)
    st.subheader("📊 종목별 1:2:6 일목균형표 구름대 · MACD · RSI 정밀 차트")
    chart_options = [
        f"[{'수동' if x['is_manual'] else 'KIS'}] {x['name']} ({x['code']}) | {x.get('phase_badge', '')} | 수익률 {x.get('profit_rate', 0):+.2f}%"
        for x in evaluated_list
    ]
    sel_idx = st.selectbox(
        "상세 차트를 확인할 관제 종목 선택",
        options=range(len(evaluated_list)),
        format_func=lambda i: chart_options[i],
        key="f126_chart_select"
    )
    sel_item = evaluated_list[sel_idx]
    sel_df = dfs_by_code.get(sel_item["code"])
    _render_fujimoto_126_chart(
        df=sel_df,
        name=sel_item["name"],
        code=sel_item["code"],
        avg_buy_price=sel_item["avg_buy_price"],
        buy_date=sel_item.get("buy_date", ""),
        chart_key=f"f126_plotly_{sel_item['code']}"
    )

    # 10. 계좌 2% 손실 한도 기반 1:2:6 매수 금액 역산 계산기 (영상 09:08 핵심 리스크 원칙)
    _render_risk_2pct_calculator(summary)


def _render_risk_2pct_calculator(summary: Dict[str, Any]):
    """영상 09:08 '계좌 2% 손실로 매수 금액 정하기' 및 1:2:6 분할 투입 계산기"""
    with st.expander("🧮 [보너스 도구] 계좌 2% 허용 손실 기반 1:2:6 적정 매수 금액 역산기 (영상 09:08 원칙)", expanded=False):
        st.caption(
            "후지모토 시게루 1:2:6 매매법의 리스크 관리 핵심: **'내가 틀렸을 때 계좌 전체 자산의 2% 이상 잃지 않도록 손절 폭에서 거꾸로 총 매수 한도와 1:2:6 분할 금액을 정한다'**"
        )
        default_asset = int(summary.get("tot_asset", 0) or 10000000)
        c1, c2, c3 = st.columns(3)
        with c1:
            total_asset = st.number_input("계좌 총 자산 (원)", min_value=100000, value=max(100000, default_asset), step=1000000, key="f126_calc_asset")
        with c2:
            risk_pct = st.slider("1회 매매 최대 허용 손실률 (계좌 대비 %)", min_value=0.5, max_value=5.0, value=2.0, step=0.5, key="f126_calc_risk_pct")
        with c3:
            stop_loss_dist_pct = st.slider("종목 손절 폭 (매수가 대비 -%)", min_value=2.0, max_value=15.0, value=5.0, step=0.5, key="f126_calc_sl_dist")

        max_loss_krw = total_asset * (risk_pct / 100.0)
        total_position_budget = min(total_asset, max_loss_krw / (stop_loss_dist_pct / 100.0))
        unit_1 = total_position_budget * (1.0 / 9.0)
        unit_2 = total_position_budget * (2.0 / 9.0)
        unit_6 = total_position_budget * (6.0 / 9.0)

        st.markdown(f"""
            <div style="background:#0f172a;border:1px solid #1e293b;border-radius:10px;padding:12px 16px;margin-top:8px;font-size:0.85rem;">
                • <b>1회 최대 허용 손실액 ({risk_pct:.1f}%):</b> <span style="color:#ef4444;font-weight:700;">-{max_loss_krw:,.0f}원</span>
                &nbsp;|&nbsp; <b>역산된 종목 총 투입 한도:</b> <span style="color:#38bdf8;font-weight:800;">{total_position_budget:,.0f}원</span> (손절폭 -{stop_loss_dist_pct:.1f}% 기준)<br>
                <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:10px;">
                    <div style="background:#111827;padding:8px 12px;border-radius:6px;border-left:3px solid #eab308;">
                        <b>1단계 (RSI 30 회복 · 1/9)</b><br><span style="color:#fde047;font-size:1.0rem;font-weight:700;">{unit_1:,.0f}원</span>
                    </div>
                    <div style="background:#111827;padding:8px 12px;border-radius:6px;border-left:3px solid #f97316;">
                        <b>2단계 (MACD 골든 · 2/9)</b><br><span style="color:#fb923c;font-size:1.0rem;font-weight:700;">{unit_2:,.0f}원</span>
                    </div>
                    <div style="background:#111827;padding:8px 12px;border-radius:6px;border-left:3px solid #10b981;">
                        <b>3단계 (구름대 돌파 · 6/9)</b><br><span style="color:#34d399;font-size:1.0rem;font-weight:700;">{unit_6:,.0f}원</span>
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)
