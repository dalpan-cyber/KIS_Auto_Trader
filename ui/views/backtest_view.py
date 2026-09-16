"""
KIS Auto Trading - Backtest View
FinanceDataReader 기반 과거 데이터 시뮬레이션 및 수익률 분석 뷰
시장 국면 프리셋(AUTO/BULL/VOLATILE/BEAR/CUSTOM) 및 core.strategy 단일 원천 연동
"""
import time
import datetime
import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from time_utils import today
from backtester import Backtester
from core.strategy import list_strategies
import app_config as config

def render_backtest():
    """4. 백테스팅 페이지 (FinanceDataReader)"""
    st.title("🧪 Quant Backtester • 알고리즘 백테스팅")
    st.caption("실시간 스크리너/매매 엔진과 100% 동일한 core.strategy 단일 원천(SSOT) 알고리즘으로 과거 데이터를 시뮬레이션합니다.")

    with st.expander("⚙️ 백테스팅 설정 파라미터 & 시장 국면 모드", expanded=True):
        # -------------------------------------------------------------
        # 백테스트 시장 국면 프리셋 선택
        # -------------------------------------------------------------
        preset_options = {
            "AUTO": "🤖 지수 연동 자동 감지 (AUTO - 일별 KOSPI 국면에 맞춰 실시간 스위칭)",
            "BULL": "🔥 상승장 모드 (Bull - 목표익절 +8%, 20일선 트레일링, 손절 -5.0%, 타임컷 12일)",
            "VOLATILE": "⚡ 변동성/횡보장 모드 (Volatile - 목표익절 +5%, 트레일링 3.5%, 손절 -3.5%, 타임컷 6일)",
            "BEAR": "🛡️ 하락장/방어 모드 (Bear - 목표익절 +3%, 칼손절 -2.5%, 컷오프 70점, 타임컷 3일)",
            "CUSTOM": "🛠️ 사용자 직접 커스텀 설정 (Custom)"
        }
        
        current_global_mode = config.CURRENT_SETTINGS.get("regime_preset_mode", "AUTO")
        bt_mode = st.radio(
            "백테스트 운영 모드 선택",
            options=list(preset_options.keys()),
            format_func=lambda x: preset_options[x],
            index=list(preset_options.keys()).index(current_global_mode) if current_global_mode in preset_options else 0,
            horizontal=False,
            key="bt_regime_radio"
        )

        bt_display = config.CURRENT_SETTINGS.copy()
        if bt_mode in config.MARKET_REGIME_PRESETS:
            bt_display.update(config.MARKET_REGIME_PRESETS[bt_mode])
        elif bt_mode == "AUTO":
            bt_display.update(config.MARKET_REGIME_PRESETS.get("BULL", {}))

        col_b1, col_b2 = st.columns(2)
        with col_b1:
            bt_start = st.date_input(
                "시작일자",
                value=datetime.date(2025, 1, 1),
                max_value=today() - datetime.timedelta(days=10)
            )
            bt_capital = st.number_input(
                "초기 투자 원금 (원)",
                min_value=1000000,
                max_value=1000000000,
                value=10000000,
                step=1000000
            )
            bt_max_hold = st.number_input(
                "최대 보유 종목 수",
                min_value=1,
                max_value=20,
                value=int(bt_display.get("max_holding_stocks", 5)),
                step=1
            )
            bt_target_profit = st.number_input(
                "목표 익절 수익률 (예: 0.08 = +8%)",
                min_value=0.01,
                max_value=0.50,
                value=float(bt_display.get("target_profit_rate", 0.08)),
                step=0.01
            )

        with col_b2:
            bt_end = st.date_input(
                "종료일자",
                value=datetime.date(2025, 12, 31),
                max_value=today()
            )
            bt_budget = st.number_input(
                "1종목당 최대 매수 예산 (원)",
                min_value=100000,
                max_value=100000000,
                value=int(bt_display.get("max_buy_budget_per_stock", 1000000)),
                step=100000
            )
            bt_stop_loss = st.number_input(
                "손절 기준 수익률 (예: -0.05 = -5%)",
                min_value=-0.50,
                max_value=-0.01,
                value=float(bt_display.get("stop_loss_rate", -0.05)),
                step=0.01
            )
            universe_mode = st.selectbox(
                "백테스트 유니버스 선택",
                ["관심종목 100개 전체 (Watchlist)", "대형 우량주 10개 (Top 10)", "직접 입력"]
            )

            # 전략 선택 (플러그인 전략)
            strategies = list_strategies()
            strategy_options = {s["name"]: f"{s['display_name']} - {s.get('description', '')}" for s in strategies}
            current_strategy = config.CURRENT_SETTINGS.get("strategy_name", "momentum")
            if current_strategy not in strategy_options:
                current_strategy = strategies[0]["name"] if strategies else "momentum"
            bt_strategy = st.selectbox(
                "백테스트 전략 선택 (플러그인 전략)",
                options=list(strategy_options.keys()),
                format_func=lambda x: strategy_options.get(x, x),
                index=list(strategy_options.keys()).index(current_strategy) if current_strategy in strategy_options else 0
            )

        if universe_mode == "관심종목 100개 전체 (Watchlist)":
            bt_universe = config.CURRENT_SETTINGS.get("watchlist", [])
        elif universe_mode == "대형 우량주 10개 (Top 10)":
            bt_universe = [
                {"code": "005930", "name": "삼성전자"},
                {"code": "000660", "name": "SK하이닉스"},
                {"code": "373220", "name": "LG에너지솔루션"},
                {"code": "207940", "name": "삼성바이오로직스"},
                {"code": "005380", "name": "현대차"},
                {"code": "000270", "name": "기아"},
                {"code": "068270", "name": "셀트리온"},
                {"code": "035420", "name": "NAVER"},
                {"code": "105560", "name": "KB금융"},
                {"code": "055550", "name": "신한지주"}
            ]
        else:
            custom_codes_raw = st.text_input("종목코드 입력 (쉼표로 구분)", value="005930,000660,035420,005380")
            bt_universe = [{"code": c.strip(), "name": c.strip()} for c in custom_codes_raw.split(",") if c.strip()]

        st.caption(f"선택된 유니버스 종목 수: **{len(bt_universe)}개** • 운영 모드: **{preset_options[bt_mode]}**")
        btn_run_bt = st.button("🚀 백테스팅 실행", type="primary", width="stretch")

    if btn_run_bt:
        if bt_start >= bt_end:
            st.error("⚠️ 시작일이 종료일보다 앞서야 합니다.")
        else:
            prog_bar = st.progress(0, text="데이터 다운로드 및 백테스팅 준비 중...")
            
            def update_progress(val):
                prog_bar.progress(int(val * 100), text=f"백테스팅 시뮬레이션 진행 중... ({int(val * 100)}%)")

            # 임시 백테스트 설정 오버라이드
            run_settings = config.CURRENT_SETTINGS.copy()
            run_settings["regime_preset_mode"] = bt_mode
            run_settings["target_profit_rate"] = float(bt_target_profit)
            run_settings["stop_loss_rate"] = float(bt_stop_loss)

            tester = Backtester(
                start_date=bt_start.strftime("%Y-%m-%d"),
                end_date=bt_end.strftime("%Y-%m-%d"),
                universe=bt_universe,
                initial_capital=float(bt_capital),
                budget_per_stock=float(bt_budget),
                max_holdings=int(bt_max_hold),
                target_profit_rate=float(bt_target_profit),
                stop_loss_rate=float(bt_stop_loss),
                strategy_name=bt_strategy
            )

            with st.spinner("과거 데이터 기반 전략 시뮬레이션 계산 중..."):
                bt_result = tester.run(progress_callback=update_progress)
                prog_bar.progress(100, text="백테스팅 완료!")
                st.session_state["bt_result"] = bt_result
                st.session_state["bt_params"] = {
                    "start": bt_start.strftime("%Y-%m-%d"),
                    "end": bt_end.strftime("%Y-%m-%d"),
                    "initial": bt_capital,
                    "universe_count": len(bt_universe),
                    "mode": bt_mode
                }
                time.sleep(0.5)
                st.rerun()

    if "bt_result" in st.session_state:
        res = st.session_state["bt_result"]
        if "error" in res:
            st.error(f"❌ {res['error']}")
        else:
            summary_bt = res["summary"]
            daily_eq = res["daily_equity"]
            trades_df = res["trade_history"]
            bench_df = res.get("benchmark_df")
            params = st.session_state.get("bt_params", {})

            st.markdown("### 📊 시뮬레이션 성과 요약")
            col_m1, col_m2, col_m3, col_m4, col_m5 = st.columns(5)
            
            tot_ret = summary_bt.get("total_return_pct", 0.0)
            ret_color = "normal" if tot_ret >= 0 else "inverse"
            
            col_m1.metric("총 수익률", f"{tot_ret:+.2f}%", delta=f"{summary_bt.get('total_profit_krw', 0):+,.0f}원")
            col_m2.metric("최대 낙폭 (MDD)", f"{summary_bt.get('mdd_pct', 0):.2f}%")
            col_m3.metric("연환산 수익률 (CAGR)", f"{summary_bt.get('cagr_pct', 0):.2f}%")
            col_m4.metric("승률 (Win Rate)", f"{summary_bt.get('win_rate', 0):.1f}%", f"{summary_bt.get('win_count', 0)}승 {summary_bt.get('loss_count', 0)}패")
            col_m5.metric("손익비 (Profit Factor)", f"{summary_bt.get('profit_factor', 0):.2f}")

            st.divider()

            # -------------------------------------------------------------
            # [자산 변화 & 벤치마크 비교 차트]
            # -------------------------------------------------------------
            st.markdown("### 📈 누적 수익률 곡선 vs KOSPI 벤치마크")
            if not daily_eq.empty:
                fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.05,
                                    subplot_titles=["누적 수익률 (%)", "낙폭 (Drawdown %)"])

                fig.add_trace(go.Scatter(
                    x=daily_eq["date"],
                    y=daily_eq["return_pct"],
                    mode="lines",
                    name="KIS Auto 전략",
                    line=dict(color="#38bdf8", width=2.5)
                ), row=1, col=1)

                if bench_df is not None and not bench_df.empty:
                    bench_sub = bench_df[(bench_df["date"] >= params.get("start", "")) & (bench_df["date"] <= params.get("end", ""))]
                    if not bench_sub.empty:
                        f_close = float(bench_sub.iloc[0]["Close"])
                        bench_ret = (bench_sub["Close"] - f_close) / f_close * 100
                        fig.add_trace(go.Scatter(
                            x=bench_sub["date"],
                            y=bench_ret,
                            mode="lines",
                            name="KOSPI 지수 (KS11)",
                            line=dict(color="#94a3b8", width=1.5, dash="dash")
                        ), row=1, col=1)

                fig.add_trace(go.Scatter(
                    x=daily_eq["date"],
                    y=daily_eq["drawdown"],
                    mode="lines",
                    name="Drawdown",
                    fill="tozeroy",
                    line=dict(color="#f43f5e", width=1)
                ), row=2, col=1)

                fig.update_layout(
                    height=520,
                    margin=dict(l=20, r=20, t=30, b=20),
                    template="plotly_dark",
                    hovermode="x unified",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig, width="stretch")

            # -------------------------------------------------------------
            # [매매 내역 테이블]
            # -------------------------------------------------------------
            st.divider()
            st.markdown("### 📋 체결 및 청산 매매 내역")
            if not trades_df.empty:
                tab_t1, tab_t2 = st.tabs(["전체 매매 내역", "매도 청산 분석"])
                with tab_t1:
                    st.dataframe(
                        trades_df[[
                            "date", "code", "name", "action", "sell_type", "price", "qty", "amount", "profit_pct", "profit_krw", "holding_days", "reasons"
                        ]].rename(columns={
                            "date": "거래일", "code": "종목코드", "name": "종목명", "action": "구분",
                            "sell_type": "유형", "price": "체결가", "qty": "수량", "amount": "거래금액",
                            "profit_pct": "수익률(%)", "profit_krw": "손익금(원)", "holding_days": "보유일수", "reasons": "사유"
                        }),
                        width="stretch",
                        height=350
                    )
                with tab_t2:
                    sells_only = trades_df[trades_df["action"] == "SELL"]
                    if not sells_only.empty:
                        type_summary = sells_only.groupby("sell_type").agg(
                            건수=("price", "count"),
                            총손익_원=("profit_krw", "sum"),
                            평균수익률_pct=("profit_pct", "mean"),
                            평균보유일수=("holding_days", "mean")
                        ).reset_index()
                        st.dataframe(type_summary, width="stretch")
            else:
                st.info("해당 기간 동안 발생한 매매 체결 내역이 없습니다.")
