"""
KIS Auto Trading - Single Stock Diagnosis View
특정 종목의 매수 조건을 실시간 시세 및 검색 시점 종가 예상 거래량 기준으로 진단하는 전용 뷰
"""
import os
import time
import datetime
from typing import List, Dict, Any, Optional
import pandas as pd
import streamlit as st
from zoneinfo import ZoneInfo

import app_config as config
from time_utils import now as kst_now
from core.indicators import get_intraday_volume_scaling_factor
from core.strategy import get_active_strategies
from ui.styles import render_interactive_stock_chart
from telegram_notifier import notifier
from core.storage import safe_load_json, atomic_save_json

# 최근 검색 기록 파일 경로
_VIEW_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_VIEW_DIR))
RECENT_SEARCHES_FILE = os.path.join(_PROJECT_ROOT, "recent_search_stocks.json")


def _load_recent_searches() -> List[Dict[str, Any]]:
    """최근 검색 종목 목록 로드 (최신순)"""
    data = safe_load_json(RECENT_SEARCHES_FILE, default=[])
    if isinstance(data, list):
        return data
    return []


def _save_recent_search(code: str, name: str, market: str):
    """최근 검색 종목 추가 (최신순 정렬, 중복 제거, 최대 10개)"""
    if not code:
        return
    history = _load_recent_searches()
    # 기존 동일 코드 제거
    history = [item for item in history if isinstance(item, dict) and item.get("code") != code]
    clean_name = name if name and not name.startswith("종목_") else code
    history.insert(0, {
        "code": code,
        "name": clean_name,
        "market": market or "KOSDAQ"
    })
    history = history[:10]
    atomic_save_json(RECENT_SEARCHES_FILE, history)


def _clear_recent_searches():
    """최근 검색 종목 모두 삭제"""
    atomic_save_json(RECENT_SEARCHES_FILE, [])

# 내장 종목 매핑 (자주 찾는 주요 종목 및 기본 유니버스)
DEFAULT_STOCKS = [
    {"code": "440110", "name": "파두", "market": "KOSDAQ"},
    {"code": "445090", "name": "에이직랜드", "market": "KOSDAQ"},
    {"code": "005930", "name": "삼성전자", "market": "KOSPI"},
    {"code": "000660", "name": "SK하이닉스", "market": "KOSPI"},
    {"code": "373220", "name": "LG에너지솔루션", "market": "KOSPI"},
    {"code": "207940", "name": "삼성바이오로직스", "market": "KOSPI"},
    {"code": "005380", "name": "현대차", "market": "KOSPI"},
    {"code": "068270", "name": "셀트리온", "market": "KOSPI"},
    {"code": "035420", "name": "NAVER", "market": "KOSPI"},
    {"code": "035720", "name": "카카오", "market": "KOSPI"},
    {"code": "247540", "name": "에코프로비엠", "market": "KOSDAQ"},
    {"code": "086520", "name": "에코프로", "market": "KOSDAQ"},
    {"code": "028300", "name": "HLB", "market": "KOSDAQ"},
    {"code": "196170", "name": "알테오젠", "market": "KOSDAQ"},
    {"code": "277810", "name": "레인보우로보틱스", "market": "KOSDAQ"}
]

def _resolve_stock(input_str: str, default_market: str = "KOSDAQ"):
    """입력 문자열에서 종목코드와 이름을 자동 식별"""
    raw = input_str.strip()
    if not raw:
        return None, None, default_market

    # 검색 대상 풀 (기본 종목 + 관심종목 + 최근 검색 기록)
    recent = _load_recent_searches()
    pool = DEFAULT_STOCKS + config.CURRENT_SETTINGS.get("watchlist", []) + recent

    # 1. 6자리 숫자 코드인 경우
    if raw.isdigit() and len(raw) == 6:
        for s in pool:
            if s.get("code") == raw:
                return raw, s.get("name", f"종목_{raw}"), s.get("market", default_market)
        return raw, f"종목_{raw}", default_market

    # 2. 이름으로 완전 일치 먼저 확인
    for s in pool:
        s_name = str(s.get("name", ""))
        if raw.lower() == s_name.lower():
            return s.get("code"), s_name, s.get("market", default_market)

    # 3. 이름 부분 일치 확인
    for s in pool:
        s_name = str(s.get("name", ""))
        if raw.lower() in s_name.lower():
            return s.get("code"), s_name, s.get("market", default_market)

    # 4. 문자열 내 6자리 숫자 추출 시도
    digits = "".join(filter(str.isdigit, raw))
    if len(digits) == 6:
        for s in pool:
            if s.get("code") == digits:
                return digits, s.get("name", f"종목_{digits}"), s.get("market", default_market)
        return digits, raw, default_market

    return None, raw, default_market


def render_stock_checker(api, screener, holding_codes):
    """특정 종목 실시간 매수 조건 진단 페이지 렌더러"""
    st.title("🔍 개별 종목 매수 조건 진단 (종가 예상 거래량 반영)")
    st.caption("관심 종목을 입력하면 실시간 시세와 **현재 시점 기준 종가 예상 거래량**을 자동 산출하여 시스템의 모든 알고리즘 매수 적합도를 심층 진단합니다.")

    # 0. 칩 클릭 또는 검색 변경 예약 처리 (위젯 렌더링 전 session_state에 주입)
    recent_searches = _load_recent_searches()
    if "_pending_search" in st.session_state:
        pending = st.session_state.pop("_pending_search")
        st.session_state["input_stock_query"] = pending.get("code") or pending.get("name", "")
        st.session_state["select_stock_market"] = pending.get("market", "KOSDAQ")
    elif "input_stock_query" not in st.session_state:
        if recent_searches:
            st.session_state["input_stock_query"] = recent_searches[0]["code"]
            st.session_state["select_stock_market"] = recent_searches[0].get("market", "KOSDAQ")
        else:
            st.session_state["input_stock_query"] = "파두"
            st.session_state["select_stock_market"] = "KOSDAQ"

    # 시장 옵션 유효성 확인
    market_options = ["KOSDAQ", "KOSPI"]
    if st.session_state.get("select_stock_market") not in market_options:
        st.session_state["select_stock_market"] = "KOSDAQ"

    # 1. 상단 입력 바
    c_in1, c_in2, c_in3 = st.columns([3.0, 1.2, 1.2])
    with c_in1:
        query = st.text_input(
            "종목명 또는 종목코드(6자리) 입력",
            key="input_stock_query",
            placeholder="예: 파두, 에이직랜드, 440110, 005930"
        )
    with c_in2:
        market_choice = st.selectbox(
            "소속 시장",
            market_options,
            key="select_stock_market"
        )
    with c_in3:
        st.write("")
        st.write("")
        btn_run = st.button("🚀 매수 조건 진단", type="primary", width="stretch", key="btn_run_stock_diag")

    # 최근 검색 종목 칩 버튼
    if recent_searches:
        st.markdown("<div style='margin-top:6px;'></div>", unsafe_allow_html=True)
        r_head1, r_head2 = st.columns([5, 1])
        with r_head1:
            st.markdown("<small style='color:#94a3b8;'>🕒 <b>최근 검색 종목:</b> (클릭 시 즉시 진단)</small>", unsafe_allow_html=True)
        with r_head2:
            if st.button("🗑️ 전체 삭제", key="btn_clear_recent_searches", help="최근 검색 기록을 초기화합니다."):
                _clear_recent_searches()
                st.rerun()

        displayed_recent = recent_searches[:6]
        recent_cols = st.columns(6)
        for idx, item in enumerate(displayed_recent):
            rcode = item.get("code", "")
            rname = item.get("name", rcode)
            rmkt = item.get("market", "KOSDAQ")
            btn_label = f"{rname} ({rcode})"
            with recent_cols[idx]:
                if st.button(btn_label, key=f"chip_recent_{rcode}_{idx}", width="stretch"):
                    st.session_state["_pending_search"] = {
                        "code": rcode,
                        "name": rname,
                        "market": rmkt
                    }
                    st.rerun()

    # 빠른 선택 칩 버튼
    st.markdown("<small style='color:#94a3b8;'>⭐ <b>빠른 진단 추천:</b></small>", unsafe_allow_html=True)
    chip_cols = st.columns(6)
    quick_stocks = [
        ("파두 (440110)", "440110", "KOSDAQ"),
        ("에이직랜드 (445090)", "445090", "KOSDAQ"),
        ("삼성전자 (005930)", "005930", "KOSPI"),
        ("SK하이닉스 (000660)", "000660", "KOSPI"),
        ("알테오젠 (196170)", "196170", "KOSDAQ"),
        ("에코프로비엠 (247540)", "247540", "KOSDAQ")
    ]
    for idx, (label, qcode, qmkt) in enumerate(quick_stocks):
        with chip_cols[idx]:
            if st.button(label, key=f"chip_quick_{qcode}", width="stretch"):
                st.session_state["_pending_search"] = {
                    "code": qcode,
                    "name": label.split()[0],
                    "market": qmkt
                }
                st.rerun()

    code, name, market = _resolve_stock(query, market_choice)

    if not code:
        st.warning("⚠️ 6자리 종목코드나 유효한 종목명을 입력해주세요. (예: 파두, 440110)")
        return

    # 세션 상태 갱신
    st.session_state["_target_code"] = code
    st.session_state["_target_name"] = name
    st.session_state["_target_market"] = market

    st.markdown("---")

    # 2. 거래량 비례 추정 계수 현황 안내 카드
    current_time_kst = kst_now()
    cur_str = current_time_kst.strftime("%H:%M:%S")
    scaling_mult = get_intraday_volume_scaling_factor(current_time_kst.time())
    
    t_min = current_time_kst.hour * 60 + current_time_kst.minute
    m_open = 9 * 60
    m_close = 15 * 60 + 30
    
    is_weekend = (current_time_kst.weekday() >= 5)

    if is_weekend:
        timing_desc = f"주말 휴장 ({cur_str}) • 가장 최근 영업일 확정 종가 기준 분석 (보정 배율 1.00배)"
    elif t_min < m_open:
        timing_desc = f"장 시작 전 ({cur_str}) • 전일 확정 종가 기준 (보정 배율 1.00배)"
    elif t_min >= m_close:
        timing_desc = f"장 마감 후 ({cur_str}) • 당일 종가 확정 데이터 (1.00배)"
    else:
        elapsed_m = max(10, t_min - m_open)
        timing_desc = f"정규장 진행 중 ({cur_str}, 개장 후 {elapsed_m}분 경과) • 15:30 종가 예상 거래량 환산 배율: **{scaling_mult:.2f}배** (390분/{elapsed_m}분)"

    st.info(f"⏱️ **[거래량 시간 보정 현황]** {timing_desc}")

    # 3. 데이터 조회 및 진단 실행
    with st.spinner(f"[{name}({code})] 실시간 시세, 투자자 수급 및 기술적 지표 분석 중..."):
        realtime = api.get_stock_price(code)
        if realtime.get("rt_cd") != "0" or realtime.get("price", 0) <= 0:
            st.error(f"❌ 종목 시세 조회 실패: {realtime.get('msg1', '종목코드를 확인하세요.')}")
            return

        # KIS API에서 수신한 정규 종목명이 있으면 이름 보정
        real_name = realtime.get("name")
        if real_name and (not name or name.startswith("종목_")):
            name = real_name
            st.session_state["_target_name"] = name

        # 정상 조회된 유효 종목을 최근 검색 목록에 저장
        _save_recent_search(code, name, market)

        cur_price = float(realtime["price"])
        chg_rate = float(realtime.get("prdy_ctrt", 0.0))
        chg_diff = float(realtime.get("diff", 0.0))
        cum_vol = int(realtime.get("acml_vol", 0))
        d250_high = float(realtime.get("d250_hgpr", 0.0))

        # 투자자 동향 & 체결강도
        inv_data = None
        try:
            inv_data = api.get_investor_trend(code)
        except Exception:
            pass

        vol_power = None
        try:
            vol_power = api.get_execution_strength(code)
        except Exception:
            pass

        # 일봉 데이터 및 지표 계산 (현재 시각 거래량 보정치 적용)
        candles = api.get_daily_chart(code, count=65)
        today_str = current_time_kst.strftime("%Y%m%d")
        candle_entry = {
            "date": today_str,
            "close": cur_price,
            "open": realtime.get("stck_oprc", cur_price),
            "high": realtime.get("stck_hgpr", cur_price),
            "low": realtime.get("stck_lwpr", cur_price),
            "volume": cum_vol,
            "change_rate": chg_rate,
            "d250_hgpr": d250_high
        }
        if not is_weekend:
            if not candles or candles[-1].get("date") != today_str:
                candles.append(candle_entry)
            else:
                candles[-1].update(candle_entry)
        else:
            if candles:
                candles[-1]["d250_hgpr"] = d250_high

        df = screener.calculate_technical_indicators(candles, is_intraday=True, eval_time=current_time_kst.time())
        if df is not None and not df.empty and d250_high > 0:
            df["d250_hgpr"] = d250_high

        # screener 종합 매수 평가
        final_buy = screener.evaluate_buy_signals(
            code=code,
            name=name,
            held_codes=holding_codes,
            is_intraday=True,
            market=market,
            return_raw_eval=False,
            eval_time=current_time_kst.time()
        )
        raw_eval = screener.evaluate_buy_signals(
            code=code,
            name=name,
            held_codes=holding_codes,
            is_intraday=True,
            market=market,
            return_raw_eval=True,
            eval_time=current_time_kst.time()
        )

    # 4. 실시간 시세 및 거래량 추정 메트릭 카드
    last_row = df.iloc[-1] if df is not None and not df.empty else {}
    vol_ma20 = float(last_row.get("vol_ma20", 0.0))
    proj_vol = float(last_row.get("adjusted_volume", cum_vol))
    proj_ratio_pct = (proj_vol / vol_ma20 * 100) if vol_ma20 > 0 else 0.0

    st.markdown(f"### 📊 {name} <small style='color:#64748b'>({code}) • {market}</small>", unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric(
            label="현재가 (최근 종가)",
            value=f"{cur_price:,.0f}원",
            delta=f"{chg_diff:+,.0f}원 ({chg_rate:+.2f}%)"
        )
    with m2:
        vol_m2_label = "현재 누적 거래량" if not is_weekend else "최근 거래일 거래량"
        st.metric(
            label=vol_m2_label,
            value=f"{cum_vol:,.0f}주",
            help="실제 체결 누적량"
        )
    with m3:
        vol_label = "종가 예상 거래량 (환산치)" if not is_weekend else "종가 기준 거래량"
        vol_help = (
            f"현재 거래량 × {scaling_mult:.2f}배 (전일 20일평균: {vol_ma20:,.0f}주)"
            if not is_weekend
            else f"주말 확정 종가 데이터 (전일 20일평균: {vol_ma20:,.0f}주)"
        )
        st.metric(
            label=vol_label,
            value=f"{proj_vol:,.0f}주",
            delta=f"20일평균 대비 {proj_ratio_pct:.0f}%",
            help=vol_help
        )
    with m4:
        power_str = f"{vol_power:.1f}%" if vol_power is not None else "조회불가"
        st.metric(
            label="실시간 체결강도",
            value=power_str,
            delta="매수 우세" if vol_power and vol_power >= 100 else ("매도 우세" if vol_power else None)
        )

    # 수급 & 기술지표 서브 정보
    f_net = inv_data.get("foreigner_net_buy", 0) if inv_data else 0
    i_net = inv_data.get("institution_net_buy", 0) if inv_data else 0
    ma5_v = float(last_row.get("ma5", 0))
    ma20_v = float(last_row.get("ma20", 0))
    ma60_v = float(last_row.get("ma60", 0))
    rsi_v = float(last_row.get("rsi14", 50))
    
    st.markdown(
        f"<div style='background:#1e293b; padding:10px 14px; border-radius:8px; font-size:0.88rem; margin-bottom:15px;'>"
        f"<b>이동평균:</b> MA5={ma5_v:,.0f}원 | MA20={ma20_v:,.0f}원 | MA60={ma60_v:,.0f}원 &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>RSI(14):</b> {rsi_v:.1f} &nbsp;&nbsp;|&nbsp;&nbsp; "
        f"<b>메이저 수급:</b> 외인 <code>{f_net:+,}주</code> / 기관 <code>{i_net:+,}주</code>"
        f"</div>",
        unsafe_allow_html=True
    )

    # 5. 종합 매수 판정 배너
    st.markdown("### 🎯 종합 알고리즘 판정 결과")
    if final_buy and final_buy.get("is_recommended", True):
        st.success(
            f"### 🎉 ★ [매수 추천 대상] - 종합 점수 {final_buy.get('score')}점 달성!\n\n"
            f"- **적용 전략:** `{final_buy.get('strategy_display_name', final_buy.get('strategy'))}`\n"
            f"- **추천 매수가격:** `{final_buy.get('current_price', cur_price):,.0f}원` | **추천 수량:** `{final_buy.get('qty', 1)}주`\n"
            f"- **종가 예상 거래량 수급 게이트를 안정적으로 충족하였습니다.**"
        )
    else:
        top_strat_name = raw_eval.get("strategy_display_name", raw_eval.get("strategy")) if raw_eval else "알고리즘"
        top_score = raw_eval.get("score", 0) if raw_eval else 0
        thresh = config.CURRENT_SETTINGS.get("buy_score_threshold", 65)
        
        st.warning(
            f"### ❌ [매수 실행 보류 (관망)]\n\n"
            f"- **최고 점수 전략:** `{top_strat_name}` (획득: **{top_score}점** / 매수 기준선: **{thresh}점**)\n"
            f"- **판정 사유:** 현재 예상 거래량 또는 기술적 진입 패턴이 시스템 안전 매수 기준에 도달하지 못했습니다."
        )
        if raw_eval and raw_eval.get("block_reasons"):
            st.markdown("**주요 차단/미달 원인:**")
            for br in raw_eval.get("block_reasons", []):
                st.markdown(f"- ⚠️ {br}")

    # 6. 등록된 4가지 전체 전략별 개별 상세 진단
    st.markdown("---")
    st.subheader("📋 4개 전체 전략별 개별 진단 상세")
    
    active_strats = get_active_strategies()
    strat_tabs = st.tabs([f"📌 {s.display_name}" for s in active_strats])
    
    for tab, strat in zip(strat_tabs, active_strats):
        with tab:
            eval_res = strat.evaluate_buy(
                df=df,
                code=code,
                name=name,
                settings=config.CURRENT_SETTINGS,
                return_raw_eval=True,
                investor_data=inv_data,
                volume_power=vol_power
            )
            if not eval_res:
                st.info(f"전략 '{strat.display_name}'에 대한 평가 결과가 없습니다.")
                continue

            is_rec = eval_res.get("is_recommended", False)
            col_res1, col_res2 = st.columns([3, 1])
            with col_res1:
                status_color = "#22c55e" if is_rec else "#f59e0b"
                status_text = "★ 매수 조건 충족 (BUY)" if is_rec else "❌ 조건 미충족 (PASS/관망)"
                st.markdown(f"#### <span style='color:{status_color};'>{status_text}</span>", unsafe_allow_html=True)
                
                # 점수 뱃지
                b_list = [f"<span class='score-badge' style='background:#334155; color:#f8fafc; font-weight:bold;'>종합 {eval_res.get('score', 0)}점</span>"]
                if "trend_score" in eval_res:
                    b_list.append(f"<span class='score-badge'>추세 {eval_res['trend_score']}/30</span>")
                if "supply_score" in eval_res:
                    b_list.append(f"<span class='score-badge'>수급 {eval_res['supply_score']}/25</span>")
                if "momentum_score" in eval_res:
                    b_list.append(f"<span class='score-badge'>모멘텀 {eval_res['momentum_score']}/25</span>")
                st.markdown(" ".join(b_list), unsafe_allow_html=True)

                reasons = eval_res.get("reasons", [])
                if reasons:
                    st.markdown("**가점 및 통과 요건:**")
                    for r in reasons:
                        st.markdown(f"- {r}")

                block_reasons = eval_res.get("block_reasons", [])
                if block_reasons:
                    st.markdown("**필터링/탈락 요건:**")
                    for br in block_reasons:
                        st.markdown(f"- ⚠️ {br}")

            with col_res2:
                st.metric("전략 획득 점수", f"{eval_res.get('score', 0)}점")
                gate_ok = eval_res.get("supply_gate_passed", False)
                gate_str = "✅ 통과" if gate_ok else "❌ 미통과"
                st.write(f"**수급 필수 게이트:** {gate_str}")

    # 7. 인터랙티브 실시간 주가 차트
    st.markdown("---")
    with st.expander(f"📈 {name} ({code}) 실시간 주가 차트 및 보조지표 분석", expanded=True):
        render_interactive_stock_chart(
            api_client=api,
            screener_engine=screener,
            code=code,
            name=name,
            chart_key=f"stock_checker_{code}"
        )
