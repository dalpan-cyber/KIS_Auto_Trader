"""
KIS Auto Trading - UI Styles & Theme Module
Streamlit CSS 커스텀 스타일링 및 공통 차트 렌더러
"""
from typing import Optional
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from time_utils import today

CUSTOM_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@300;400;500;600;700;800&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif;
    }
    
    /* 사이드바 배경 및 테두리 */
    [data-testid="stSidebar"] {
        background-color: #0b0f19;
        border-right: 1px solid #1e293b;
    }
    
    /* 기본 사이드바 버튼 (비활성 메뉴) */
    [data-testid="stSidebar"] .stButton > button[kind="secondary"] {
        background-color: #111827 !important;
        border: 1px solid #1f2937 !important;
        color: #94a3b8 !important;
        border-radius: 10px !important;
        padding: 12px 16px !important;
        font-size: 0.92rem !important;
        font-weight: 500 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        display: flex !important;
        width: 100% !important;
        margin-bottom: 6px !important;
        transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }
    
    [data-testid="stSidebar"] .stButton > button[kind="secondary"]:hover {
        background-color: #1e293b !important;
        border-color: #38bdf8 !important;
        color: #f8fafc !important;
        transform: translateX(4px) !important;
    }
    
    /* 활성(Selected) 메뉴 버튼 */
    [data-testid="stSidebar"] .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, rgba(14, 165, 233, 0.2), rgba(99, 102, 241, 0.25)) !important;
        border: 1px solid #38bdf8 !important;
        color: #38bdf8 !important;
        box-shadow: 0 0 15px rgba(56, 189, 248, 0.2) !important;
        border-radius: 10px !important;
        padding: 12px 16px !important;
        font-size: 0.92rem !important;
        font-weight: 700 !important;
        text-align: left !important;
        justify-content: flex-start !important;
        display: flex !important;
        width: 100% !important;
        margin-bottom: 6px !important;
    }
    
    /* 상태 배지 */
    .badge-mock {
        background: linear-gradient(135deg, rgba(245, 158, 11, 0.15), rgba(217, 119, 6, 0.25));
        color: #fbbf24;
        border: 1px solid rgba(245, 158, 11, 0.4);
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        padding: 4px 10px;
        border-radius: 20px;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    .badge-real {
        background: linear-gradient(135deg, rgba(239, 68, 68, 0.15), rgba(185, 28, 28, 0.25));
        color: #f87171;
        border: 1px solid rgba(239, 68, 68, 0.4);
        font-size: 0.75rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        padding: 4px 10px;
        border-radius: 20px;
        display: inline-flex;
        align-items: center;
        gap: 6px;
    }
    
    .status-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        display: inline-block;
    }
    .dot-mock { background-color: #fbbf24; box-shadow: 0 0 8px #fbbf24; }
    .dot-real { background-color: #f87171; box-shadow: 0 0 8px #f87171; }
    
    .sidebar-account-box {
        background-color: #111827;
        border: 1px solid #1f2937;
        border-radius: 10px;
        padding: 12px 14px;
        margin-top: 10px;
        margin-bottom: 15px;
    }

    .nav-header {
        font-size: 0.72rem;
        font-weight: 700;
        color: #64748b;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        margin-bottom: 10px;
    }

    .score-badge {
        background: rgba(30, 41, 59, 0.8);
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 4px 8px;
        font-size: 0.8rem;
        font-weight: 600;
        color: #38bdf8;
        display: inline-block;
        margin-right: 4px;
    }

    .timeline-container {
        background: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 12px;
        padding: 14px 18px;
        margin-bottom: 20px;
    }

    /* ============================================================
       매도 버튼 색상 (sell button color variants)
       Streamlit은 버튼 wrapper div에 'st-key-...' 클래스를 부여하므로
       [class*="st-key-btn_sell_..."] button 형태로 지정해야 합니다.
       ============================================================ */
    [class*="st-key-btn_sell_urgent"] button,
    div[class*="st-key-btn_sell_urgent"] button,
    .stButton[class*="st-key-btn_sell_urgent"] button,
    button[class*="st-key-btn_sell_urgent"] {
        background: linear-gradient(135deg, #dc2626, #991b1b) !important;
        border: 1px solid #ef4444 !important;
        color: #ffffff !important;
        box-shadow: 0 0 15px rgba(239, 68, 68, 0.35) !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_urgent"] button *,
    div[class*="st-key-btn_sell_urgent"] button *,
    button[class*="st-key-btn_sell_urgent"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_urgent"] button:hover,
    div[class*="st-key-btn_sell_urgent"] button:hover,
    button[class*="st-key-btn_sell_urgent"]:hover {
        background: linear-gradient(135deg, #ef4444, #b91c1c) !important;
        border-color: #f87171 !important;
        color: #ffffff !important;
        box-shadow: 0 0 20px rgba(239, 68, 68, 0.5) !important;
    }
    [class*="st-key-btn_sell_urgent"] button:active,
    div[class*="st-key-btn_sell_urgent"] button:active {
        background: linear-gradient(135deg, #991b1b, #7f1d1d) !important;
        border-color: #ef4444 !important;
        color: #ffffff !important;
    }

    [class*="st-key-btn_sell_profit"] button,
    div[class*="st-key-btn_sell_profit"] button,
    .stButton[class*="st-key-btn_sell_profit"] button,
    button[class*="st-key-btn_sell_profit"] {
        background: linear-gradient(135deg, #2563eb, #1e40af) !important;
        border: 1px solid #3b82f6 !important;
        color: #ffffff !important;
        box-shadow: 0 0 15px rgba(59, 130, 246, 0.35) !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_profit"] button *,
    div[class*="st-key-btn_sell_profit"] button *,
    button[class*="st-key-btn_sell_profit"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_profit"] button:hover,
    div[class*="st-key-btn_sell_profit"] button:hover,
    button[class*="st-key-btn_sell_profit"]:hover {
        background: linear-gradient(135deg, #3b82f6, #1d4ed8) !important;
        border-color: #60a5fa !important;
        color: #ffffff !important;
        box-shadow: 0 0 20px rgba(59, 130, 246, 0.5) !important;
    }
    [class*="st-key-btn_sell_profit"] button:active,
    div[class*="st-key-btn_sell_profit"] button:active {
        background: linear-gradient(135deg, #1e40af, #1e3a8a) !important;
        border-color: #3b82f6 !important;
        color: #ffffff !important;
    }

    [class*="st-key-btn_sell_timecut"] button,
    div[class*="st-key-btn_sell_timecut"] button,
    .stButton[class*="st-key-btn_sell_timecut"] button,
    button[class*="st-key-btn_sell_timecut"] {
        background: linear-gradient(135deg, #f59e0b, #b45309) !important;
        border: 1px solid #fbbf24 !important;
        color: #ffffff !important;
        box-shadow: 0 0 15px rgba(245, 158, 11, 0.35) !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_timecut"] button *,
    div[class*="st-key-btn_sell_timecut"] button *,
    button[class*="st-key-btn_sell_timecut"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_timecut"] button:hover,
    div[class*="st-key-btn_sell_timecut"] button:hover,
    button[class*="st-key-btn_sell_timecut"]:hover {
        background: linear-gradient(135deg, #fbbf24, #d97706) !important;
        border-color: #fcd34d !important;
        color: #ffffff !important;
        box-shadow: 0 0 20px rgba(245, 158, 11, 0.5) !important;
    }
    [class*="st-key-btn_sell_timecut"] button:active,
    div[class*="st-key-btn_sell_timecut"] button:active {
        background: linear-gradient(135deg, #b45309, #92400e) !important;
        border-color: #fbbf24 !important;
        color: #ffffff !important;
    }

    [class*="st-key-btn_sell_deadcross"] button,
    div[class*="st-key-btn_sell_deadcross"] button,
    .stButton[class*="st-key-btn_sell_deadcross"] button,
    button[class*="st-key-btn_sell_deadcross"] {
        background: linear-gradient(135deg, #7c3aed, #5b21b6) !important;
        border: 1px solid #8b5cf6 !important;
        color: #ffffff !important;
        box-shadow: 0 0 15px rgba(139, 92, 246, 0.35) !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_deadcross"] button *,
    div[class*="st-key-btn_sell_deadcross"] button *,
    button[class*="st-key-btn_sell_deadcross"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_deadcross"] button:hover,
    div[class*="st-key-btn_sell_deadcross"] button:hover,
    button[class*="st-key-btn_sell_deadcross"]:hover {
        background: linear-gradient(135deg, #8b5cf6, #6d28d9) !important;
        border-color: #a78bfa !important;
        color: #ffffff !important;
        box-shadow: 0 0 20px rgba(139, 92, 246, 0.5) !important;
    }
    [class*="st-key-btn_sell_deadcross"] button:active,
    div[class*="st-key-btn_sell_deadcross"] button:active {
        background: linear-gradient(135deg, #5b21b6, #4c1d95) !important;
        border-color: #8b5cf6 !important;
        color: #ffffff !important;
    }

    [class*="st-key-btn_sell_rsi"] button,
    div[class*="st-key-btn_sell_rsi"] button,
    .stButton[class*="st-key-btn_sell_rsi"] button,
    button[class*="st-key-btn_sell_rsi"] {
        background: linear-gradient(135deg, #0891b2, #155e75) !important;
        border: 1px solid #06b6d4 !important;
        color: #ffffff !important;
        box-shadow: 0 0 15px rgba(6, 182, 212, 0.35) !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_rsi"] button *,
    div[class*="st-key-btn_sell_rsi"] button *,
    button[class*="st-key-btn_sell_rsi"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_rsi"] button:hover,
    div[class*="st-key-btn_sell_rsi"] button:hover,
    button[class*="st-key-btn_sell_rsi"]:hover {
        background: linear-gradient(135deg, #06b6d4, #0e7490) !important;
        border-color: #22d3ee !important;
        color: #ffffff !important;
        box-shadow: 0 0 20px rgba(6, 182, 212, 0.5) !important;
    }
    [class*="st-key-btn_sell_rsi"] button:active,
    div[class*="st-key-btn_sell_rsi"] button:active {
        background: linear-gradient(135deg, #155e75, #164e63) !important;
        border-color: #06b6d4 !important;
        color: #ffffff !important;
    }

    [class*="st-key-btn_sell_default"] button,
    div[class*="st-key-btn_sell_default"] button,
    .stButton[class*="st-key-btn_sell_default"] button,
    button[class*="st-key-btn_sell_default"] {
        background: linear-gradient(135deg, #059669, #065f46) !important;
        border: 1px solid #10b981 !important;
        color: #ffffff !important;
        box-shadow: 0 0 15px rgba(16, 185, 129, 0.35) !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_default"] button *,
    div[class*="st-key-btn_sell_default"] button *,
    button[class*="st-key-btn_sell_default"] * {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    [class*="st-key-btn_sell_default"] button:hover,
    div[class*="st-key-btn_sell_default"] button:hover,
    button[class*="st-key-btn_sell_default"]:hover {
        background: linear-gradient(135deg, #10b981, #047857) !important;
        border-color: #34d399 !important;
        color: #ffffff !important;
        box-shadow: 0 0 20px rgba(16, 185, 129, 0.5) !important;
    }
    [class*="st-key-btn_sell_default"] button:active,
    div[class*="st-key-btn_sell_default"] button:active {
        background: linear-gradient(135deg, #065f46, #064e3b) !important;
        border-color: #10b981 !important;
        color: #ffffff !important;
    }

    /* ============================================================
       수익률 아이콘 (profit rate icon)
       ============================================================ */
    .profit-icon {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        font-size: 0.75rem;
        font-weight: 800;
        margin-right: 6px;
        vertical-align: middle;
    }
    .profit-icon-up {
        background: rgba(239, 68, 68, 0.2);
        color: #ef4444;
        border: 1px solid rgba(239, 68, 68, 0.5);
        box-shadow: 0 0 8px rgba(239, 68, 68, 0.3);
    }
    .profit-icon-down {
        background: rgba(59, 130, 246, 0.2);
        color: #3b82f6;
        border: 1px solid rgba(59, 130, 246, 0.5);
        box-shadow: 0 0 8px rgba(59, 130, 246, 0.3);
    }
</style>
"""

def apply_custom_styles():
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

def render_interactive_stock_chart(api_client, screener_engine, code: str, name: str, avg_buy_price: Optional[float] = None, profit_rate: Optional[float] = None):
    """보유 종목 및 추천 종목의 실시간 캔들 차트, 이동평균선, 볼린저밴드, 거래량, RSI 시각화 렌더러"""
    with st.spinner(f"📈 {name}({code}) 실시간 일봉 차트 및 보조지표 로드 중..."):
        candles = api_client.get_daily_chart(code, count=65)
        realtime = api_client.get_stock_price(code)
        if realtime.get("rt_cd") == "0" and realtime.get("price", 0) > 0:
            today_str = today().strftime("%Y%m%d")
            if not candles or candles[-1].get("date") != today_str:
                candles.append({
                    "date": today_str,
                    "close": realtime["price"],
                    "open": realtime.get("stck_oprc", realtime["price"]),
                    "high": realtime.get("stck_hgpr", realtime["price"]),
                    "low": realtime.get("stck_lwpr", realtime["price"]),
                    "volume": realtime.get("acml_vol", 0),
                    "change_rate": realtime.get("prdy_ctrt", 0.0)
                })
            else:
                candles[-1].update({
                    "close": realtime["price"],
                    "open": realtime.get("stck_oprc", candles[-1].get("open", realtime["price"])),
                    "high": realtime.get("stck_hgpr", candles[-1].get("high", realtime["price"])),
                    "low": realtime.get("stck_lwpr", candles[-1].get("low", realtime["price"])),
                    "volume": realtime.get("acml_vol", candles[-1].get("volume", 0)),
                    "change_rate": realtime.get("prdy_ctrt", candles[-1].get("change_rate", 0.0))
                })

        df_tech = screener_engine.calculate_technical_indicators(candles, is_intraday=True)
        if df_tech is not None and not df_tech.empty:
            fig = make_subplots(
                rows=3, cols=1,
                shared_xaxes=True,
                vertical_spacing=0.04,
                row_heights=[0.55, 0.20, 0.25],
                subplot_titles=(
                    f"{name} ({code}) 일봉 캔들 & 이동평균선 & 볼린저밴드",
                    "거래량 & 20일 거래량 이평",
                    "RSI (14)"
                )
            )

            # 1. 캔들스틱
            fig.add_trace(
                go.Candlestick(
                    x=df_tech["date"],
                    open=df_tech["open"],
                    high=df_tech["high"],
                    low=df_tech["low"],
                    close=df_tech["close"],
                    name="캔들",
                    increasing_line_color="#ef4444",
                    decreasing_line_color="#3b82f6"
                ),
                row=1, col=1
            )
            fig.add_trace(go.Scatter(x=df_tech["date"], y=df_tech["ma5"], line=dict(color="#f59e0b", width=1.5), name="5일선"), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_tech["date"], y=df_tech["ma20"], line=dict(color="#10b981", width=2), name="20일선"), row=1, col=1)
            if "ma60" in df_tech:
                fig.add_trace(go.Scatter(x=df_tech["date"], y=df_tech["ma60"], line=dict(color="#8b5cf6", width=1.5), name="60일선"), row=1, col=1)

            fig.add_trace(go.Scatter(x=df_tech["date"], y=df_tech["bb_upper"], line=dict(color="rgba(148, 163, 184, 0.5)", dash="dot", width=1), name="BB상단", showlegend=False), row=1, col=1)
            fig.add_trace(go.Scatter(x=df_tech["date"], y=df_tech["bb_lower"], line=dict(color="rgba(148, 163, 184, 0.5)", dash="dot", width=1), fill="tonexty", fillcolor="rgba(148, 163, 184, 0.05)", name="BB하단", showlegend=False), row=1, col=1)

            if avg_buy_price and avg_buy_price > 0:
                ann_text = f"매입평단가: {avg_buy_price:,.0f}원 ({profit_rate:+.2f}%)" if profit_rate is not None else f"매입평단가: {avg_buy_price:,.0f}원"
                fig.add_hline(
                    y=avg_buy_price,
                    line_dash="dash",
                    line_color="#fbbf24",
                    line_width=2,
                    annotation_text=ann_text,
                    annotation_position="top right",
                    annotation_font_color="#fbbf24",
                    row=1, col=1
                )

            # 2. 거래량
            colors = ["#ef4444" if row["close"] >= row["open"] else "#3b82f6" for _, row in df_tech.iterrows()]
            fig.add_trace(go.Bar(x=df_tech["date"], y=df_tech["volume"], marker_color=colors, name="거래량"), row=2, col=1)
            fig.add_trace(go.Scatter(x=df_tech["date"], y=df_tech["vol_ma20"], line=dict(color="#fbbf24", width=1.5), name="전일 20일 거래량이평"), row=2, col=1)

            # 3. RSI
            fig.add_trace(go.Scatter(x=df_tech["date"], y=df_tech["rsi14"], line=dict(color="#06b6d4", width=2), name="RSI(14)"), row=3, col=1)
            fig.add_hline(y=70, line_dash="dash", line_color="#ef4444", row=3, col=1)
            fig.add_hline(y=30, line_dash="dash", line_color="#3b82f6", row=3, col=1)

            fig.update_layout(
                height=560,
                template="plotly_dark",
                paper_bgcolor="#0b0f19",
                plot_bgcolor="#0f172a",
                font=dict(color="#f1f5f9", family="Pretendard, -apple-system, sans-serif"),
                xaxis_rangeslider_visible=False,
                margin=dict(l=20, r=20, t=40, b=20),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="right",
                    x=1,
                    font=dict(color="#f8fafc", size=11)
                )
            )

            # 서브플롯 타이틀 글자색을 밝은 화이트(#f8fafc)로 강조
            for ann in fig["layout"]["annotations"]:
                ann["font"] = dict(color="#f8fafc", size=13, family="Pretendard, -apple-system, sans-serif")

            # X축/Y축 눈금 및 그리드 선명도 개선
            fig.update_xaxes(
                showgrid=True,
                gridcolor="#1e293b",
                tickfont=dict(color="#cbd5e1", size=10),
                linecolor="#334155"
            )
            fig.update_yaxes(
                showgrid=True,
                gridcolor="#1e293b",
                tickfont=dict(color="#cbd5e1", size=10),
                linecolor="#334155"
            )

            st.plotly_chart(fig, width="stretch")

            latest = df_tech.iloc[-1]
            m1, m2, m3, m4, m5 = st.columns(5)
            with m1:
                st.metric("현재가", f"{latest['close']:,.0f}원", delta=f"{latest.get('change_rate', 0):+.2f}%")
            with m2:
                rsi_val = latest['rsi14']
                prev_rsi = df_tech.iloc[-2]['rsi14'] if len(df_tech) >= 2 else rsi_val
                st.metric("RSI(14)", f"{rsi_val:.1f}", delta=f"{rsi_val - prev_rsi:+.1f}")
            with m3:
                vol_ratio = (latest['volume'] / (latest['vol_ma20'] + 1e-9)) * 100 if latest.get('vol_ma20') else 0
                st.metric("20일 평균대비 거래량", f"{vol_ratio:.0f}%")
            with m4:
                st.metric("20일선 (중기)", f"{latest['ma20']:,.0f}원")
            with m5:
                st.metric("볼린저 하단 (지지선)", f"{latest['bb_lower']:,.0f}원")
        else:
            st.warning("차트 데이터를 불러올 수 없습니다.")
