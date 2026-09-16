"""
KIS Auto Trading - Settings View
전략 파라미터, 시장 국면 프리셋(BULL/VOLATILE/BEAR/AUTO) 및 관심종목(Watchlist) 관리 뷰
프리셋 변경 시 폼 입력값 실시간 동기화 지원
전략별 설정 스키마(settings_schema) 기반 동적 폼 렌더링
"""
import time
from typing import Dict, Any, List
import streamlit as st
import app_config as config
from core.strategy import list_strategies, get_strategy_settings_schema, get_strategy_specific_settings_keys


def _render_schema_item(
    item: Dict[str, Any],
    current_value: Any,
    key_prefix: str = ""
) -> Any:
    """
    설정 스키마 항목을 Streamlit 위젯으로 렌더링하고 사용자 입력값 반환.
    """
    key = item["key"]
    label = item.get("label", key)
    desc = item.get("description", "")
    item_type = item.get("type", "number")
    widget_key = f"{key_prefix}_{key}"

    if item_type == "toggle":
        val = st.toggle(label, value=bool(current_value), key=widget_key)
        if desc:
            st.caption(desc)
        return val

    elif item_type == "number":
        min_v = item.get("min")
        max_v = item.get("max")
        step = item.get("step", 1)

        # Streamlit number_input는 value/min_value/max_value/step이 모두 동일 타입이어야 함
        # 정수형 설정이면 int로, 실수형 설정이면 float로 통일
        default_val = item.get("default", 0)
        current_val = current_value if current_value is not None else default_val

        # 정수형 판단: default가 int이고 step이 int이면 정수형으로 처리
        is_int_type = isinstance(default_val, int) and isinstance(step, int) and not isinstance(default_val, bool)

        if is_int_type:
            val = st.number_input(
                label,
                min_value=int(min_v) if min_v is not None else None,
                max_value=int(max_v) if max_v is not None else None,
                value=int(current_val),
                step=int(step),
                key=widget_key
            )
        else:
            val = st.number_input(
                label,
                min_value=float(min_v) if min_v is not None else None,
                max_value=float(max_v) if max_v is not None else None,
                value=float(current_val),
                step=float(step),
                key=widget_key
            )
        if desc:
            st.caption(desc)
        return val

    elif item_type == "text":
        val = st.text_input(label, value=str(current_value) if current_value is not None else str(item.get("default", "")), key=widget_key)
        if desc:
            st.caption(desc)
        return val

    elif item_type == "select":
        options = item.get("options", [])
        option_values = [o[0] for o in options]
        option_labels = [o[1] for o in options]
        current_idx = option_values.index(current_value) if current_value in option_values else 0
        val = st.selectbox(
            label,
            options=option_values,
            format_func=lambda x: option_labels[option_values.index(x)] if x in option_values else x,
            index=current_idx,
            key=widget_key
        )
        if desc:
            st.caption(desc)
        return val

    return current_value


def render_settings():
    """7. 전략 및 시스템 설정 페이지"""
    st.title("⚙️ Strategy & System Settings • 전략 파라미터 및 환경 설정")

    # -------------------------------------------------------------
    # [상단: 시장 국면 프리셋 선택기]
    # -------------------------------------------------------------
    st.markdown("### 🎯 시장 국면별 원클릭 프리셋 (Market Regime Preset)")
    
    preset_options = {
        "AUTO": "🤖 지수 연동 자동 감지 (AUTO - KOSPI 국면에 맞춰 실시간 스위칭)",
        "BULL": "🔥 상승장 모드 (Bull - 목표익절 +8%, 20일선 트레일링, 손절 -5.0%, 타임컷 12일)",
        "VOLATILE": "⚡ 변동성/횡보장 모드 (Volatile - 목표익절 +5%, 트레일링 3.5%, 손절 -3.5%, 타임컷 6일)",
        "BEAR": "🛡️ 하락장/방어 모드 (Bear - 목표익절 +3%, 칼손절 -2.5%, 컷오프 70점, 타임컷 3일)",
        "CUSTOM": "🛠️ 사용자 직접 커스텀 설정 (Custom)"
    }
    
    current_mode = config.CURRENT_SETTINGS.get("regime_preset_mode", "AUTO")
    current_idx = list(preset_options.keys()).index(current_mode) if current_mode in preset_options else 0

    selected_mode_key = st.radio(
        "전략 운영 모드 선택 (선택 시 아래 설정 항목에 해당 프리셋 기본값이 즉시 반영됩니다)",
        options=list(preset_options.keys()),
        format_func=lambda x: preset_options[x],
        index=current_idx,
        horizontal=False,
        key="regime_preset_radio"
    )

    # -------------------------------------------------------------
    # 프리셋 선택에 따른 UI 표시용 설정값 계산 (실시간 동기화)
    # -------------------------------------------------------------
    display_settings = config.CURRENT_SETTINGS.copy()
    if selected_mode_key in config.MARKET_REGIME_PRESETS:
        preset_vals = config.MARKET_REGIME_PRESETS[selected_mode_key]
        for k, v in preset_vals.items():
            if k not in ["name", "description"]:
                display_settings[k] = v
        st.info(f"**선택된 프리셋 안내:** {preset_vals.get('description', '')}\n\n👉 *아래 폼에 **{preset_vals.get('name')}**의 권장 파라미터가 자동으로 입력되었습니다. 확인 후 하단 [설정 저장] 버튼을 누르시면 적용됩니다.*")
    elif selected_mode_key == "AUTO":
        st.info("💡 **지수 연동 자동 감지(AUTO) 모드**: 코스피 지수의 20일/60일 이동평균선 위치와 기울기를 실시간 분석하여 **상승장(BULL) / 횡보장(VOLATILE) / 하락장(BEAR)** 파라미터를 실시간 자동 전환합니다.")
    else:
        st.info("🛠️ **사용자 직접 커스텀 설정**: 원하시는 모든 파라미터를 자유롭게 수정하여 저장할 수 있습니다.")

    st.divider()

    with st.form("settings_form_page"):
        st.write("**🧩 매수/매도 전략 선택 및 동시 운용 (Strategy Plugins)**")
        st.caption("실행할 전략을 선택하세요 (1개 또는 여러 개 동시 선택 가능). 복수 전략 선택 시 스크리너가 각 전략을 동시에 평가하며, 여러 전략에서 동시 포착된 종목은 '슈퍼 시그널'로 우선순위 가산점(+10점)이 부여됩니다.")

        strategies = list_strategies()
        strategy_options = {s["name"]: s["display_name"] for s in strategies}
        current_active = display_settings.get("active_strategies", [])
        if not current_active:
            current_active = [display_settings.get("strategy_name", "momentum")]

        # 각 전략별 활성화 체크박스 렌더링
        active_checkbox_map = {}
        strat_cols = st.columns(len(strategies)) if strategies else [st]
        for idx, strat in enumerate(strategies):
            s_name = strat["name"]
            s_disp = strat["display_name"]
            s_desc = strat.get("description", "")
            is_active = s_name in current_active
            with strat_cols[idx % len(strat_cols)]:
                active_checkbox_map[s_name] = st.checkbox(
                    f"**{s_disp}**",
                    value=is_active,
                    key=f"chk_active_{s_name}",
                    help=s_desc
                )
                st.caption(f"_{s_desc}_")
        st.divider()

        # =============================================================
        # 탭 기반 설정 폼 렌더링 (공통 설정 + 등록된 각 전략별 고유 설정)
        # =============================================================
        tab_titles = ["📋 공통 리스크 / 매매 설정"] + [f"🎯 {s['display_name']}" for s in strategies]
        all_tabs = st.tabs(tab_titles)

        # 1) 첫 번째 탭: 공통 설정 (category='common')
        common_tab = all_tabs[0]
        sample_schema = get_strategy_settings_schema(strategies[0]["name"]) if strategies else []
        common_items = [item for item in sample_schema if item.get("category", "common") == "common"]

        common_values: Dict[str, Any] = {}
        with common_tab:
            st.write("**📋 공통 리스크 및 매매 설정 (Common Settings)**")
            st.caption("모든 전략이 공유하는 리스크 관리 및 포지션 사이징 파라미터입니다. 시장 국면 프리셋(BULL/VOLATILE/BEAR)에 따라 자동 조정됩니다.")

            common_groups = {
                "익절/손절": ["target_profit_rate", "stop_loss_rate", "trailing_stop_pct", "partial_sell_ratio", "rsi_overbought_sell"],
                "타임컷": ["time_stop_enabled", "time_stop_days", "time_stop_min_profit"],
                "시장 국면 필터": ["market_regime_filter_enabled", "market_regime_cutoff_normal", "market_regime_cutoff_weak", "market_regime_block_weak"],
                "쿨다운": ["cooldown_enabled", "cooldown_days"],
                "ATR 동적 손절": ["atr_stop_loss_enabled", "atr_stop_loss_multiple", "atr_stop_loss_min_pct", "atr_stop_loss_max_pct", "atr_stop_loss_use_low_break"],
                "포지션 사이징": ["volatility_sizing_enabled", "risk_per_trade", "atr_stop_multiple", "max_position_ratio", "min_position_ratio"],
                "스크리닝 점수": ["score_cap_trend", "score_cap_momentum", "score_cap_volume", "buy_score_threshold"],
                "매수 제한": ["max_daily_buy_count", "max_buy_budget_per_stock", "max_holding_stocks"],
                "기타": ["use_realtime_candle"]
            }

            for group_name, group_keys in common_groups.items():
                group_items = [item for item in common_items if item["key"] in group_keys]
                if not group_items:
                    continue
                st.markdown(f"**{group_name}**")
                cols = st.columns(2)
                for i, item in enumerate(group_items):
                    col = cols[i % 2]
                    with col:
                        key = item["key"]
                        current_val = display_settings.get(key, item.get("default"))
                        common_values[key] = _render_schema_item(item, current_val, key_prefix=f"common_{selected_mode_key}")
                st.divider()

        # 2) 나머지 탭: 각 등록 전략별 고유 설정 (category='strategy')
        strategies_values_map: Dict[str, Dict[str, Any]] = {}
        for idx, strat in enumerate(strategies):
            s_name = strat["name"]
            s_disp = strat["display_name"]
            s_desc = strat.get("description", "")
            s_tab = all_tabs[idx + 1]

            with s_tab:
                st.write(f"**🎯 {s_disp} 전략 고유 파라미터**")
                st.caption(s_desc)

                is_currently_checked = active_checkbox_map.get(s_name, False)
                status_badge = "🟢 현재 활성화(ON) 설정됨" if is_currently_checked else "⚪ 현재 비활성화(OFF) 상태 (위 체크박스에서 활성화 가능)"
                st.info(f"**전략 운용 상태:** {status_badge}")

                s_schema = get_strategy_settings_schema(s_name)
                s_specific_keys = get_strategy_specific_settings_keys(s_name)
                s_saved = config.get_strategy_settings(s_name)
                s_display = display_settings.copy()
                for k, v in s_saved.items():
                    if k in s_specific_keys:
                        s_display[k] = v

                strat_items = [item for item in s_schema if item.get("category", "common") == "strategy"]
                strategies_values_map[s_name] = {}

                if strat_items:
                    cols = st.columns(2)
                    for i, item in enumerate(strat_items):
                        col = cols[i % 2]
                        with col:
                            key = item["key"]
                            current_val = s_display.get(key, item.get("default"))
                            strategies_values_map[s_name][key] = _render_schema_item(
                                item, current_val, key_prefix=f"strat_{s_name}_{selected_mode_key}"
                            )
                else:
                    st.caption("이 전략은 별도의 고유 설정 없이 공통 설정을 따릅니다.")

        st.divider()

        # --- 시스템 설정 (전략과 무관한 전역 설정) ---
        st.write("**⚙️ 시스템 설정 (System Settings)**")
        f_mock = st.toggle("모의투자 모드 활성화 (체크 해제 시 실전투자)", value=display_settings.get("mock_trading", True))
        f_telegram = st.toggle("텔레그램 알림 활성화 (기본: OFF)", value=display_settings.get("telegram_enabled", False))
        if f_telegram:
            st.caption("⚠️ 텔레그램 알림을 활성화하면 매수/매도 이벤트가 텔레그램으로 전송됩니다. api.telegram.org에 접속 가능해야 합니다.")
        else:
            st.caption("텔레그램 알림이 꺼져 있습니다. 켜려면 위 토글을 활성화하세요.")
        f_time = st.text_input(
            "종가 매수 스크리닝 시각 (KST)",
            value=display_settings.get("premarket_time", "15:10")
        )
        st.divider()

        save_btn = st.form_submit_button("💾 설정 저장하기 (Save Settings)", width="stretch")
        if save_btn:
            selected_active = [s_name for s_name, is_on in active_checkbox_map.items() if is_on]
            if not selected_active:
                st.warning("⚠️ 최소 1개 이상의 전략이 활성화되어야 합니다. 기본값으로 모멘텀 추세추종 전략이 자동 선택됩니다.")
                selected_active = ["momentum"]

            # 1. 전역 설정 저장 (공통 설정 + 시스템 설정)
            global_settings = {
                "mock_trading": f_mock,
                "regime_preset_mode": selected_mode_key,
                "telegram_enabled": f_telegram,
                "premarket_time": f_time,
                "strategy_name": selected_active[0],
                "active_strategies": selected_active,
            }

            # 공통 설정 값을 전역 설정에 병합
            for k, v in common_values.items():
                global_settings[k] = v

            # 2. 다중 전략 일괄 저장
            ok = config.save_multiple_strategy_settings(
                active_strategies=selected_active,
                strategies_settings_map=strategies_values_map,
                global_settings=global_settings
            )

            if ok:
                active_labels = [strategy_options.get(s, s) for s in selected_active]
                st.success(f"✅ 전략 및 시스템 설정이 성공적으로 저장되었습니다! (운영 모드: {preset_options[selected_mode_key]}, 활성 전략: {', '.join(active_labels)})")
                time.sleep(0.8)
                st.rerun()
            else:
                st.error("❌ 설정 저장에 실패했습니다.")

    # -------------------------------------------------------------
    # [중단: Google Sheets 연동 현황]
    # -------------------------------------------------------------
    st.divider()
    st.markdown("### 📊 Google Sheets 클라우드 동기화 현황")

    try:
        from google_sheet_manager import get_sheet_manager
        sheet_mgr = get_sheet_manager()
        is_conn = sheet_mgr.is_connected
        status_color = "#22c55e" if is_conn else "#f59e0b"
        status_text = "🟢 연결 정상 (실시간 동기화 활성)" if is_conn else "⚠️ 미연결 (로컬 JSON 모드로 안전 동작 중)"

        g_col1, g_col2 = st.columns([2, 1])
        with g_col1:
            st.markdown(
                f"""
                <div style='background:#1e293b; padding:12px 16px; border-radius:8px; border:1px solid #334155; margin-bottom:12px;'>
                    <div style='font-size:1.05em; font-weight:bold; color:{status_color}; margin-bottom:6px;'>
                        {status_text}
                    </div>
                    <div style='font-size:0.85em; color:#94a3b8; line-height:1.6;'>
                        • <b>스프레드시트 이름</b>: {sheet_mgr.sheet_name}<br>
                        • <b>스프레드시트 KEY</b>: {sheet_mgr.sheet_key or '(미지정 - .env의 GOOGLE_SHEET_KEY 설정 필요)'}<br>
                        • <b>서비스 계정 봇 이메일</b>: <code>kis-sheets-bot@kis-auto-trader.iam.gserviceaccount.com</code>
                    </div>
                </div>
                """,
                unsafe_allow_html=True
            )
            if not is_conn:
                st.info(
                    "💡 **구글 시트 연동 방법**:\n"
                    "1. 구글 드라이브에서 새 스프레드시트를 생성합니다.\n"
                    "2. 우측 상단 **[공유]** 버튼에서 위 서비스 계정 이메일을 **편집자(Editor)**로 추가합니다.\n"
                    "3. 스프레드시트 URL 상의 ID(키)를 `.env` 파일의 `GOOGLE_SHEET_KEY=\"...\"` 에 입력 후 재시작하세요."
                )

        with g_col2:
            st.write("")
            st.write("")
            if st.button("🔄 구글 시트로 즉시 동기화", use_container_width=True, disabled=not is_conn):
                with st.spinner("구글 시트로 동기화 중..."):
                    sync_s = sheet_mgr.sync_settings_to_sheet(config.CURRENT_SETTINGS)
                    from screener import StockScreener
                    proposals = StockScreener.load_proposals()
                    sync_p = sheet_mgr.sync_proposals_to_sheet(proposals)
                    from core.position_tracker import PositionTracker
                    pt = PositionTracker()
                    sync_pos = sheet_mgr.sync_positions_state_to_sheet(pt.load_positions_state())
                    sync_cd = sheet_mgr.sync_cooldown_to_sheet(pt.load_cooldown())
                    if sync_s:
                        st.success("✅ 구글 시트 5대 탭 동기화 완료!")
                    else:
                        st.error("❌ 구글 시트 동기화 실패")
    except Exception as e:
        st.caption(f"Google Sheets 모듈 로드 중: {e}")

    # -------------------------------------------------------------
    # [하단: 관심종목(Watchlist) 관리]
    # -------------------------------------------------------------
    st.divider()
    st.markdown("### 📋 관심종목 유니버스 (Watchlist)")
    
    current_wl = config.CURRENT_SETTINGS.get("watchlist", [])
    st.write(f"현재 등록된 종목 수: **{len(current_wl)}개**")

    cols = st.columns(4)
    for idx, item in enumerate(current_wl):
        col = cols[idx % 4]
        with col:
            st.markdown(
                f"<div style='background:#1e293b; padding:8px 12px; border-radius:6px; margin-bottom:6px; border:1px solid #334155;'>"
                f"<strong style='color:#38bdf8;'>{item.get('name')}</strong> "
                f"<span style='color:#94a3b8; font-size:0.85em;'>({item.get('code')})</span>"
                f"<span style='float:right; font-size:0.75em; color:#cbd5e1; background:#0f172a; padding:2px 6px; border-radius:4px;'>{item.get('market', 'KOSPI')}</span>"
                f"</div>",
                unsafe_allow_html=True
            )
