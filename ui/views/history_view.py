"""
KIS Auto Trading - History & Profit View
매매 이력 및 실현/미실현 손익 분석 뷰
"""
import datetime
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from time_utils import now_str, today

def render_history(api):
    """6. 매매 이력 & 수익 분석 페이지"""
    st.title("📜 History & Profit • 매매 이력 및 수익 분석")
    st.caption(f"서버 시각: {now_str()} (KST)")

    col_date1, col_date2, col_date3 = st.columns([1.5, 1.5, 1])
    with col_date1:
        start_date = st.date_input(
            "조회 시작일",
            value=today() - datetime.timedelta(days=30),
            max_value=today()
        )
    with col_date2:
        end_date = st.date_input(
            "조회 종료일",
            value=today(),
            max_value=today()
        )
    with col_date3:
        st.write("")
        st.write("")
        if st.button("🔍 조회", key="btn_history_search", type="primary", width="stretch"):
            st.rerun()

    if start_date > end_date:
        st.error("⚠️ 시작일이 종료일보다 늦을 수 없습니다.")
    else:
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")

        with st.spinner("매매 이력 조회 중..."):
            result = api.get_trade_history_with_profit(start_str, end_str)
            balance_data = api.get_account_balance()
            holdings_data = balance_data.get("holdings", [])
            unrealized_profit = 0.0
            unrealized_by_stock = {}
            for h in holdings_data:
                code = h["code"]
                profit = h.get("profit_loss", 0.0)
                unrealized_profit += profit
                unrealized_by_stock[code] = {
                    "name": h.get("name", ""),
                    "code": code,
                    "quantity": h.get("quantity", 0),
                    "avg_buy_price": h.get("avg_buy_price", 0),
                    "current_price": h.get("current_price", 0),
                    "profit_loss": profit,
                    "profit_rate": h.get("profit_rate", 0)
                }

        orders = result["orders"]
        realized_profit = result["realized_profit"]
        buy_total = result["buy_total"]
        sell_total = result["sell_total"]
        buy_count = result["buy_count"]
        sell_count = result["sell_count"]
        profit_by_stock = result["profit_by_stock"]
        total_profit = realized_profit + unrealized_profit

        st.subheader("📊 손익 요약")
        col1, col2, col3, col4, col5, col6 = st.columns(6)
        with col1:
            st.metric("실현 손익", f"{realized_profit:+,.0f} 원", delta=f"{realized_profit:+,.0f} 원")
        with col2:
            st.metric("미실현 손익(평가)", f"{unrealized_profit:+,.0f} 원", delta=f"{unrealized_profit:+,.0f} 원")
        with col3:
            st.metric("총 손익", f"{total_profit:+,.0f} 원", delta=f"{total_profit:+,.0f} 원")
        with col4:
            st.metric("총 매수 금액", f"{buy_total:,.0f} 원")
        with col5:
            st.metric("총 매도 금액", f"{sell_total:,.0f} 원")
        with col6:
            st.metric("매수/매도 건수", f"{buy_count}건 / {sell_count}건")

        st.divider()

        st.subheader("💼 미실현 손익 (현재 보유 종목 평가)")
        if unrealized_by_stock:
            u_df = pd.DataFrame([
                {
                    "종목명": v["name"],
                    "코드": v["code"],
                    "보유수량": v["quantity"],
                    "매입평균가(원)": v["avg_buy_price"],
                    "현재가(원)": v["current_price"],
                    "평가손익(원)": v["profit_loss"],
                    "수익률(%)": v["profit_rate"]
                }
                for v in unrealized_by_stock.values()
            ])
            u_df["매입평균가(원)"] = u_df["매입평균가(원)"].apply(lambda x: f"{x:,.0f}")
            u_df["현재가(원)"] = u_df["현재가(원)"].apply(lambda x: f"{x:,.0f}")
            u_df["평가손익(원)"] = u_df["평가손익(원)"].apply(lambda x: f"{x:+,.0f}")
            u_df["수익률(%)"] = u_df["수익률(%)"].apply(lambda x: f"{x:+.2f}%")
            st.dataframe(u_df, width="stretch")

            fig_unreal = go.Figure(go.Bar(
                x=[v["name"] for v in unrealized_by_stock.values()],
                y=[v["profit_loss"] for v in unrealized_by_stock.values()],
                marker_color=["#ef4444" if v["profit_loss"] >= 0 else "#3b82f6" for v in unrealized_by_stock.values()],
                text=[f"{v['profit_loss']:+,.0f}" for v in unrealized_by_stock.values()],
                textposition="outside"
            ))
            fig_unreal.update_layout(
                title="보유 종목별 미실현 손익",
                template="plotly_dark",
                height=400,
                yaxis_title="평가손익 (원)",
                margin=dict(l=20, r=20, t=50, b=20)
            )
            st.plotly_chart(fig_unreal, width="stretch")
        else:
            st.info("현재 보유 중인 종목이 없습니다.")

        st.divider()

        sold_stocks = {k: v for k, v in profit_by_stock.items() if v["sell_qty"] > 0}
        if sold_stocks:
            st.subheader("📈 종목별 실현 손익")
            pbs_df = pd.DataFrame([
                {
                    "종목명": v["name"],
                    "코드": k,
                    "매수금액(원)": v["buy_amount"],
                    "매도금액(원)": v["sell_amount"],
                    "매수수량": v["buy_qty"],
                    "매도수량": v["sell_qty"],
                    "실현손익(원)": v["profit"]
                }
                for k, v in sold_stocks.items()
            ])
            pbs_df["매수금액(원)"] = pbs_df["매수금액(원)"].apply(lambda x: f"{x:,.0f}")
            pbs_df["매도금액(원)"] = pbs_df["매도금액(원)"].apply(lambda x: f"{x:,.0f}")
            pbs_df["실현손익(원)"] = pbs_df["실현손익(원)"].apply(lambda x: f"{x:+,.0f}")
            st.dataframe(pbs_df, width="stretch")

            fig_profit = go.Figure(go.Bar(
                x=[v["name"] for v in sold_stocks.values()],
                y=[v["profit"] for v in sold_stocks.values()],
                marker_color=["#ef4444" if v["profit"] >= 0 else "#3b82f6" for v in sold_stocks.values()],
                text=[f"{v['profit']:+,.0f}" for v in sold_stocks.values()],
                textposition="outside"
            ))
            fig_profit.update_layout(
                title="종목별 실현 손익",
                template="plotly_dark",
                height=400,
                yaxis_title="실현 손익 (원)",
                margin=dict(l=20, r=20, t=50, b=20)
            )
            st.plotly_chart(fig_profit, width="stretch")
        else:
            st.info("선택 기간 내 매도 완료된 종목이 없습니다.")

        st.divider()

        st.subheader("📋 매매 이력 상세")
        if not orders:
            st.info("선택 기간 내 매매 이력이 없습니다.")
        else:
            h_df = pd.DataFrame(orders)
            display_cols = ["order_date", "order_time", "name", "code", "buy_sell", "order_qty", "order_price", "ccld_qty", "ccld_price", "status"]
            h_df = h_df[[c for c in display_cols if c in h_df.columns]].copy()
            h_df.columns = ["주문일", "주문시각", "종목명", "코드", "구분", "주문수량", "주문가", "체결수량", "체결가", "상태"]
            h_df["주문가"] = h_df["주문가"].apply(lambda x: f"{x:,.0f}")
            h_df["체결가"] = h_df["체결가"].apply(lambda x: f"{x:,.0f}")
            h_df["체결금액(원)"] = h_df["체결수량"] * h_df["체결가"].str.replace(",", "").astype(float)
            h_df["체결금액(원)"] = h_df["체결금액(원)"].apply(lambda x: f"{x:,.0f}")
            st.dataframe(h_df, width="stretch")

            buy_count_total = len([o for o in orders if o["buy_sell"] == "매수"])
            sell_count_total = len([o for o in orders if o["buy_sell"] == "매도"])
            if buy_count_total + sell_count_total > 0:
                fig_pie = go.Figure(go.Pie(
                    labels=["매수", "매도"],
                    values=[buy_count_total, sell_count_total],
                    hole=0.4,
                    marker_colors=["#ef4444", "#3b82f6"]
                ))
                fig_pie.update_layout(
                    title="매수/매도 건수 비율",
                    template="plotly_dark",
                    height=350
                )
                st.plotly_chart(fig_pie, width="stretch")
