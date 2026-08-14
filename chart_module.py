"""
주가차트 및 매매체결 이력 그래프 모듈 (chart_module.py)

- 주가 일별 차트: KIS Open API /uapi/overseas-price/v1/quotations/dailyprice (HHDFS76240000)
- 매매 체결 이력: KIS Open API 해외주식 체결/미체결 이력 (CTOS4001R)
- Plotly 기반 대화형 차트 생성 (Streamlit / PyQt5 공용)
- Matplotlib 기반 정적 차트 생성 (PyQt5 GUI용)
"""
import datetime
import logging
from typing import Dict, Any, List, Optional

import pandas as pd

PLOTLY_AVAILABLE = False
try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_AVAILABLE = True
except ImportError:
    pass

MATPLOTLIB_AVAILABLE = False
try:
    import matplotlib
    matplotlib.use("Agg")  # GUI 백엔드와 충돌 방지
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.figure import Figure

    # 한글 폰트 설정 (Windows: Malgun Gothic, macOS: AppleGothic, Linux: NanumGothic)
    import matplotlib.font_manager as fm
    _korean_fonts = ["Malgun Gothic", "AppleGothic", "NanumGothic", "Noto Sans CJK KR", "NanumBarunGothic"]
    _font_found = False
    for _fname in _korean_fonts:
        try:
            _font_path = fm.findfont(fm.FontProperties(family=_fname), fallback_to_default=False)
            if _font_path:
                plt.rcParams["font.family"] = _fname
                _font_found = True
                break
        except Exception:
            continue
    if not _font_found:
        # 폰트 미발견 시 기본 폰트 사용 (한글 깨짐 경고)
        logger.warning("한글 지원 폰트를 찾지 못했습니다. 차트의 한글 텍스트가 깨질 수 있습니다.")

    # 마이너스 기호 표시 설정
    plt.rcParams["axes.unicode_minus"] = False

    MATPLOTLIB_AVAILABLE = True
except ImportError:
    pass

logger = logging.getLogger("ChartModule")


# -----------------------------------------------------------------------------
# 1. 주가 일별 차트 데이터 조회 (HHDFS76240000 dailyprice API)
# -----------------------------------------------------------------------------
def fetch_daily_price_chart(
    api,
    symbol: str,
    exchange: str = "NAS",
    count: int = 60,
    gubn: str = "2",
    modp: str = "1"
) -> List[Dict[str, Any]]:
    """
    KIS Open API /uapi/overseas-price/v1/quotations/dailyprice (HHDFS76240000)를
    사용하여 해외 주식 일별 주가 차트 데이터를 조회한다.

    Args:
        api: KISApiClient 인스턴스
        symbol: 종목코드 (예: TSLA, TQQQ, AAPL)
        exchange: 거래소코드 (HKS, NYS, NAS, AMS, TSE, SHS, SZS, SHI, SZI, HSX, HNX)
        count: 조회할 일수 (기본 60일)
        gubn: 일/주/월구분 (0: 일, 1: 주, 2: 월)
        modp: 수정주가반영여부 (0: 미반영, 1: 반영)

    Returns:
        List[Dict]: [{"date": "YYYY-MM-DD", "close": float, "open": float,
                      "high": float, "low": float, "volume": int}, ...]
    """
    if not PLOTLY_AVAILABLE:
        logger.warning("plotly가 설치되지 않아 차트 데이터 조회만 수행합니다.")

    # KIS Open API /uapi/overseas-price/v1/quotations/dailyprice (HHDFS76240000) 직접 호출
    # GUBN: 0=일, 1=주, 2=월
    # BYMD: 조회기준일자 (공란 시 오늘 날짜)
    # MODP: 수정주가반영여부 (0=미반영, 1=반영)
    result = api.get_overseas_daily_price(
        symbol=symbol,
        exchange=exchange,
        gubn=gubn,
        bymd="",
        modp=modp
    )

    if not result.get("success"):
        logger.warning(f"[차트] [{symbol}] 일별 차트 API 호출 실패: {result.get('msg', '')}")
        return []

    # output2가 일별차트 데이터
    raw_output = result.get("output2", [])
    if not raw_output:
        # output2가 없으면 output1도 확인
        raw_output = result.get("output1", [])

    chart_data = []
    for item in raw_output[:count]:
        c_val = float(item.get("clos", item.get("last", item.get("stck_clpr", 0))) or 0)
        if c_val > 0:
            raw_date = str(item.get("xymd", item.get("ksam_date", item.get("date", item.get("stck_bsop_date", ""))))).strip()
            if raw_date and raw_date.isdigit() and len(raw_date) == 8:
                norm_date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
            else:
                norm_date = raw_date
            chart_data.append({
                "date": norm_date,
                "close": c_val,
                "open": float(item.get("open", item.get("stck_oprc", 0)) or 0),
                "high": float(item.get("high", item.get("stck_hgpr", 0)) or 0),
                "low": float(item.get("low", item.get("stck_lwpr", 0)) or 0),
                "volume": int(item.get("tvol", item.get("voum", item.get("acml_vol", 0))) or 0)
            })

    if not chart_data:
        logger.warning(f"[차트] [{symbol}] 일별 차트 데이터가 비어 있습니다.")
        return []

    logger.info(f"[차트] [{symbol}] 일별 차트 데이터 {len(chart_data)}건 조회 완료 (HHDFS76240000 dailyprice API)")
    return chart_data


# -----------------------------------------------------------------------------
# 2. 매매 체결 이력 조회
# -----------------------------------------------------------------------------
def fetch_execution_history(
    api,
    symbol: str = "",
    start_date: str = "",
    end_date: str = ""
) -> List[Dict[str, Any]]:
    """
    KIS Open API 해외주식 체결/미체결 이력 (CTOS4001R)을 조회한다.

    Args:
        api: KISApiClient 인스턴스
        symbol: 종목코드 (비우면 전체 종목)
        start_date: 조회 시작일자 (YYYYMMDD, 기본: 오늘)
        end_date: 조회 종료일자 (YYYYMMDD, 기본: 오늘)

    Returns:
        List[Dict]: 매매 체결 이력 리스트
    """
    if not start_date:
        start_date = datetime.date.today().strftime("%Y%m%d")
    if not end_date:
        end_date = datetime.date.today().strftime("%Y%m%d")

    history = api.get_overseas_execution_history(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date
    )

    logger.info(f"[차트] [{symbol or '전체'}] 체결 이력 {len(history)}건 조회 완료 (기간: {start_date}~{end_date})")
    return history


# -----------------------------------------------------------------------------
# 3. 주가 차트 + 매매 체결 이력 통합 그래프 생성 (Plotly)
# -----------------------------------------------------------------------------
def create_stock_chart_with_trades(
    symbol: str,
    chart_data: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
    avg_price: float = 0.0,
    title: str = ""
) -> Optional[Any]:
    """
    주가 일별 차트와 매매 체결 이력을 하나의 Plotly 그래프로 생성한다.

    - 주가 종가: 파란색 라인+마커
    - 매수 체결: 초록색 상향 삼각형 마커
    - 매도 체결: 빨간색 하향 삼각형 마커
    - 실패/미체결: 주황색 X 마커
    - 평단가: 주황색 점선 수평선

    Args:
        symbol: 종목코드
        chart_data: 일별 주가 데이터 리스트
        history: 매매 체결 이력 리스트
        avg_price: 평단가 (0이면 표시 안함)
        title: 차트 제목 (비우면 자동 생성)

    Returns:
        plotly.graph_objects.Figure 또는 None (plotly 미설치 시)
    """
    if not PLOTLY_AVAILABLE:
        logger.warning("plotly가 설치되지 않아 차트를 생성할 수 없습니다. `pip install plotly` 실행 필요.")
        return None

    if not chart_data:
        logger.warning(f"[차트] [{symbol}] 차트 데이터가 없어 그래프를 생성할 수 없습니다.")
        return None

    df_chart = pd.DataFrame(chart_data)

    # 날짜 정규화 (YYYYMMDD -> YYYY-MM-DD)
    def _normalize_date_str(d):
        s = str(d).strip()
        if s.isdigit() and len(s) == 8:
            return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
        return s

    if 'date' in df_chart.columns and 'close' in df_chart.columns:
        df_chart['date_fmt'] = df_chart['date'].apply(_normalize_date_str)
        df_chart['date_fmt'] = pd.to_datetime(df_chart['date_fmt'], errors='coerce').dt.strftime('%Y-%m-%d')
        df_chart = df_chart.sort_values('date_fmt').dropna(subset=['date_fmt'])
    else:
        logger.warning(f"[차트] [{symbol}] 차트 데이터에 date/close 컬럼이 없습니다.")
        return None

    # 서브플롯: 주가 차트 (상단) + 거래량 (하단)
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.75, 0.25],
        subplot_titles=(f"{title or f'{symbol} 주가 차트'}", "거래량")
    )

    # 1) 주가 종가 라인
    fig.add_trace(
        go.Scatter(
            x=df_chart['date_fmt'],
            y=df_chart['close'],
            mode='lines+markers',
            name=f'{symbol} 종가',
            line=dict(color='#38BDF8', width=2),
            marker=dict(size=4, color='#38BDF8'),
            hovertemplate='%{x}<br>종가: $%{y:.2f}<extra></extra>'
        ),
        row=1, col=1
    )

    # 2) 거래량 바 차트
    if 'volume' in df_chart.columns:
        vol_colors = ['#22C55E' if c >= 0 else '#EF4444' for c in df_chart['close'].diff().fillna(0)]
        fig.add_trace(
            go.Bar(
                x=df_chart['date_fmt'],
                y=df_chart['volume'],
                name='거래량',
                marker_color=vol_colors,
                opacity=0.6,
                hovertemplate='%{x}<br>거래량: %{y:,.0f}<extra></extra>'
            ),
            row=2, col=1
        )

    # 3) 매매 체결 이력 마커
    if history:
        buy_dates, buy_prices, buy_texts = [], [], []
        sell_dates, sell_prices, sell_texts = [], [], []
        fail_dates, fail_prices, fail_texts = [], [], []

        for h in history:
            h_date = str(h.get("order_time", ""))[:10]
            if h_date and h_date.isdigit() and len(h_date) == 8:
                h_date = f"{h_date[:4]}-{h_date[4:6]}-{h_date[6:8]}"

            h_type = str(h.get("order_type", ""))
            h_qty = int(h.get("executed_qty", 0) or h.get("qty", 0) or 0)
            h_price = float(h.get("executed_price", 0.0) or h.get("price", 0.0) or 0.0)
            h_status = str(h.get("status", ""))

            # 실패/미체결/취소 상태 판별
            is_failed = any(kw in h_status for kw in ["실패", "미체결", "취소", "FAIL", "REJECT"])

            if h_price <= 0:
                continue

            if "매수" in h_type:
                if is_failed:
                    fail_dates.append(h_date)
                    fail_prices.append(h_price)
                    fail_texts.append(f"❌ 매수 실패: {h_qty}주 @ ${h_price:.2f} ({h_status})")
                else:
                    buy_dates.append(h_date)
                    buy_prices.append(h_price)
                    buy_texts.append(f"🟢 매수 체결: {h_qty}주 @ ${h_price:.2f} ({h_status})")
            elif "매도" in h_type:
                if is_failed:
                    fail_dates.append(h_date)
                    fail_prices.append(h_price)
                    fail_texts.append(f"❌ 매도 실패: {h_qty}주 @ ${h_price:.2f} ({h_status})")
                else:
                    sell_dates.append(h_date)
                    sell_prices.append(h_price)
                    sell_texts.append(f"🔴 매도 체결: {h_qty}주 @ ${h_price:.2f} ({h_status})")

        # 매수 체결 마커 (초록색 상향 삼각형)
        if buy_dates:
            fig.add_trace(
                go.Scatter(
                    x=buy_dates, y=buy_prices,
                    mode='markers',
                    name='🟢 매수 체결',
                    marker=dict(symbol='triangle-up', size=13, color='#22C55E', line=dict(width=1, color='white')),
                    text=buy_texts,
                    hoverinfo='text',
                    hovertemplate='%{text}<extra></extra>'
                ),
                row=1, col=1
            )

        # 매도 체결 마커 (빨간색 하향 삼각형)
        if sell_dates:
            fig.add_trace(
                go.Scatter(
                    x=sell_dates, y=sell_prices,
                    mode='markers',
                    name='🔴 매도 체결',
                    marker=dict(symbol='triangle-down', size=13, color='#EF4444', line=dict(width=1, color='white')),
                    text=sell_texts,
                    hoverinfo='text',
                    hovertemplate='%{text}<extra></extra>'
                ),
                row=1, col=1
            )

        # 실패/미체결 마커 (주황색 X)
        if fail_dates:
            fig.add_trace(
                go.Scatter(
                    x=fail_dates, y=fail_prices,
                    mode='markers',
                    name='❌ 실패/미체결',
                    marker=dict(symbol='x', size=12, color='#F97316', line=dict(width=1, color='white')),
                    text=fail_texts,
                    hoverinfo='text',
                    hovertemplate='%{text}<extra></extra>'
                ),
                row=1, col=1
            )

    # 4) 평단가 수평선
    if avg_price > 0:
        fig.add_hline(
            y=avg_price,
            line_dash="dash",
            line_color="#F59E0B",
            annotation_text=f"평단가 (${avg_price:.2f})",
            annotation_position="top left",
            row=1, col=1
        )

    # 5) 레이아웃 설정
    fig.update_layout(
        template="plotly_dark",
        margin=dict(l=20, r=20, t=50, b=20),
        height=500,
        xaxis_title="날짜",
        yaxis_title="주가 ($)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )

    # 서브플롯 축 레이블
    fig.update_xaxes(title_text="날짜", row=2, col=1)
    fig.update_yaxes(title_text="주가 ($)", row=1, col=1)
    fig.update_yaxes(title_text="거래량", row=2, col=1)

    return fig


# -----------------------------------------------------------------------------
# 4. 매매 체결 이력 전용 그래프 (타임라인)
# -----------------------------------------------------------------------------
def create_execution_history_chart(
    symbol: str,
    history: List[Dict[str, Any]],
    title: str = ""
) -> Optional[Any]:
    """
    매매 체결 이력만을 별도로 시각화하는 타임라인 그래프를 생성한다.

    - X축: 주문/체결 일시
    - Y축: 체결 단가 ($)
    - 매수: 초록색 상향 삼각형
    - 매도: 빨간색 하향 삼각형
    - 실패: 주황색 X

    Args:
        symbol: 종목코드
        history: 매매 체결 이력 리스트
        title: 차트 제목

    Returns:
        plotly.graph_objects.Figure 또는 None
    """
    if not PLOTLY_AVAILABLE:
        logger.warning("plotly가 설치되지 않아 차트를 생성할 수 없습니다.")
        return None

    if not history:
        logger.warning(f"[차트] [{symbol}] 체결 이력이 없어 그래프를 생성할 수 없습니다.")
        return None

    fig = go.Figure()

    buy_dates, buy_prices, buy_texts = [], [], []
    sell_dates, sell_prices, sell_texts = [], [], []
    fail_dates, fail_prices, fail_texts = [], [], []

    for h in history:
        h_time = str(h.get("order_time", ""))
        h_type = str(h.get("order_type", ""))
        h_qty = int(h.get("executed_qty", 0) or h.get("qty", 0) or 0)
        h_price = float(h.get("executed_price", 0.0) or h.get("price", 0.0) or 0.0)
        h_status = str(h.get("status", ""))

        is_failed = any(kw in h_status for kw in ["실패", "미체결", "취소", "FAIL", "REJECT"])

        if h_price <= 0:
            continue

        if "매수" in h_type:
            if is_failed:
                fail_dates.append(h_time)
                fail_prices.append(h_price)
                fail_texts.append(f"❌ 매수 실패: {h_qty}주 @ ${h_price:.2f} ({h_status})")
            else:
                buy_dates.append(h_time)
                buy_prices.append(h_price)
                buy_texts.append(f"🟢 매수 체결: {h_qty}주 @ ${h_price:.2f} ({h_status})")
        elif "매도" in h_type:
            if is_failed:
                fail_dates.append(h_time)
                fail_prices.append(h_price)
                fail_texts.append(f"❌ 매도 실패: {h_qty}주 @ ${h_price:.2f} ({h_status})")
            else:
                sell_dates.append(h_time)
                sell_prices.append(h_price)
                sell_texts.append(f"🔴 매도 체결: {h_qty}주 @ ${h_price:.2f} ({h_status})")

    if buy_dates:
        fig.add_trace(go.Scatter(
            x=buy_dates, y=buy_prices,
            mode='markers+lines',
            name='🟢 매수 체결',
            line=dict(color='#22C55E', width=1, dash='dot'),
            marker=dict(symbol='triangle-up', size=14, color='#22C55E', line=dict(width=1, color='white')),
            text=buy_texts, hoverinfo='text',
            hovertemplate='%{text}<extra></extra>'
        ))

    if sell_dates:
        fig.add_trace(go.Scatter(
            x=sell_dates, y=sell_prices,
            mode='markers+lines',
            name='🔴 매도 체결',
            line=dict(color='#EF4444', width=1, dash='dot'),
            marker=dict(symbol='triangle-down', size=14, color='#EF4444', line=dict(width=1, color='white')),
            text=sell_texts, hoverinfo='text',
            hovertemplate='%{text}<extra></extra>'
        ))

    if fail_dates:
        fig.add_trace(go.Scatter(
            x=fail_dates, y=fail_prices,
            mode='markers',
            name='❌ 실패/미체결',
            marker=dict(symbol='x', size=12, color='#F97316', line=dict(width=1, color='white')),
            text=fail_texts, hoverinfo='text',
            hovertemplate='%{text}<extra></extra>'
        ))

    fig.update_layout(
        template="plotly_dark",
        title=title or f"{symbol} 매매 체결 이력",
        margin=dict(l=20, r=20, t=50, b=20),
        height=350,
        xaxis_title="주문/체결 일시",
        yaxis_title="체결 단가 ($)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="closest",
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)'
    )

    return fig


# -----------------------------------------------------------------------------
# 5. 통합 차트 생성 헬퍼 (데이터 조회 + 그래프 생성)
# -----------------------------------------------------------------------------
def build_stock_dashboard_chart(
    api,
    symbol: str,
    exchange: str = "NAS",
    count: int = 60,
    start_date: str = "",
    end_date: str = "",
    avg_price: float = 0.0
) -> Dict[str, Any]:
    """
    주가 차트 + 매매 체결 이력 통합 대시보드 차트를 한 번에 생성한다.

    Args:
        api: KISApiClient 인스턴스
        symbol: 종목코드
        exchange: 거래소코드
        count: 조회 일수
        start_date: 체결이력 조회 시작일 (YYYYMMDD)
        end_date: 체결이력 조회 종료일 (YYYYMMDD)
        avg_price: 평단가

    Returns:
        Dict: {
            "chart_data": List[Dict],
            "history": List[Dict],
            "figure": plotly Figure 또는 None,
            "history_figure": plotly Figure 또는 None
        }
    """
    # 1) 주가 일별 차트 데이터 조회 (HHDFS76240000 dailyprice API)
    chart_data = fetch_daily_price_chart(api, symbol, exchange=exchange, count=count)

    # 2) 매매 체결 이력 조회
    if not start_date:
        start_date = (datetime.date.today() - datetime.timedelta(days=count)).strftime("%Y%m%d")
    if not end_date:
        end_date = datetime.date.today().strftime("%Y%m%d")

    history = fetch_execution_history(api, symbol=symbol, start_date=start_date, end_date=end_date)

    # 3) 통합 주가 + 체결 이력 그래프
    figure = create_stock_chart_with_trades(
        symbol=symbol,
        chart_data=chart_data,
        history=history,
        avg_price=avg_price,
        title=f"{symbol} 주가 차트 및 매매 체결 이력"
    )

    # 4) 체결 이력 전용 그래프
    history_figure = create_execution_history_chart(
        symbol=symbol,
        history=history,
        title=f"{symbol} 매매 체결 이력 타임라인"
    )

    return {
        "chart_data": chart_data,
        "history": history,
        "figure": figure,
        "history_figure": history_figure
    }


# -----------------------------------------------------------------------------
# 6. Streamlit 렌더링 헬퍼
# -----------------------------------------------------------------------------
def render_chart_in_streamlit(st, figure, use_container_width: bool = True):
    """
    Streamlit에서 Plotly 차트를 렌더링한다.

    Args:
        st: streamlit 모듈
        figure: plotly Figure
        use_container_width: 컨테이너 폭 사용 여부
    """
    if figure is not None and PLOTLY_AVAILABLE:
        st.plotly_chart(figure, use_container_width=use_container_width)
    else:
        st.warning("plotly가 설치되지 않아 차트를 표시할 수 없습니다. `pip install plotly` 실행 필요.")


# -----------------------------------------------------------------------------
# 7. PyQt5 렌더링 헬퍼 (HTML 파일로 내보내기)
# -----------------------------------------------------------------------------
def export_chart_to_html(figure, filepath: str) -> bool:
    """
    Plotly 차트를 HTML 파일로 내보낸다. (PyQt5 QWebEngineView에서 표시 가능)

    Args:
        figure: plotly Figure
        filepath: 저장할 HTML 파일 경로

    Returns:
        bool: 성공 여부
    """
    if figure is None or not PLOTLY_AVAILABLE:
        logger.warning("plotly가 설치되지 않아 HTML 내보내기를 수행할 수 없습니다.")
        return False

    try:
        figure.write_html(filepath, include_plotlyjs='cdn', full_html=True)
        logger.info(f"[차트] HTML 차트 파일 저장 완료: {filepath}")
        return True
    except Exception as e:
        logger.error(f"[차트] HTML 차트 파일 저장 실패: {e}")
        return False
# -----------------------------------------------------------------------------
# 8. Matplotlib 기반 차트 생성 (PyQt5 GUI용)
# -----------------------------------------------------------------------------
def create_matplotlib_stock_chart(
    symbol: str,
    chart_data: List[Dict[str, Any]],
    history: List[Dict[str, Any]],
    avg_price: float = 0.0,
    title: str = ""
) -> Optional[Figure]:
    """
    Matplotlib 기반 주가 차트 + 매매 체결 이력 통합 그래프를 생성한다.
    PyQt5 GUI에서 FigureCanvasQTAgg로 표시할 수 있다.

    Args:
        symbol: 종목코드
        chart_data: 일별 주가 데이터 리스트
        history: 매매 체결 이력 리스트
        avg_price: 평단가 (0이면 표시 안함)
        title: 차트 제목

    Returns:
        matplotlib.figure.Figure 또는 None
    """
    if not MATPLOTLIB_AVAILABLE:
        logger.warning("matplotlib이 설치되지 않아 차트를 생성할 수 없습니다.")
        return None

    if not chart_data:
        logger.warning(f"[차트] [{symbol}] 차트 데이터가 없어 그래프를 생성할 수 없습니다.")
        return None

    # 다크 테마 설정
    plt.style.use('dark_background')

    fig, (ax1, ax2) = plt.subplots(
        2, 1,
        figsize=(10, 6),
        gridspec_kw={'height_ratios': [3, 1]},
        sharex=True
    )
    fig.patch.set_facecolor('#121826')
    ax1.set_facecolor('#0F172A')
    ax2.set_facecolor('#0F172A')

    # 날짜 파싱
    dates = []
    closes = []
    volumes = []

    for item in chart_data:
        d_str = str(item.get("date", ""))
        if d_str.isdigit() and len(d_str) == 8:
            d_str = f"{d_str[:4]}-{d_str[4:6]}-{d_str[6:8]}"
        try:
            d = datetime.datetime.strptime(d_str, "%Y-%m-%d")
        except Exception:
            continue
        dates.append(d)
        closes.append(float(item.get("close", 0)))
        volumes.append(int(item.get("volume", 0)))

    if not dates:
        logger.warning(f"[차트] [{symbol}] 날짜 파싱 실패로 차트를 생성할 수 없습니다.")
        return None

    # 1) 주가 종가 라인
    ax1.plot(dates, closes, color='#38BDF8', linewidth=2, marker='o', markersize=3, label=f'{symbol} 종가')
    ax1.fill_between(dates, closes, min(closes) * 0.95, alpha=0.1, color='#38BDF8')

    # 2) 매매 체결 이력 마커
    if history:
        buy_dates, buy_prices = [], []
        sell_dates, sell_prices = [], []
        fail_dates, fail_prices = [], []

        for h in history:
            h_time = str(h.get("order_time", ""))[:10]
            if h_time.isdigit() and len(h_time) == 8:
                h_time = f"{h_time[:4]}-{h_time[4:6]}-{h_time[6:8]}"
            try:
                h_dt = datetime.datetime.strptime(h_time, "%Y-%m-%d")
            except Exception:
                continue

            h_type = str(h.get("order_type", ""))
            h_qty = int(h.get("executed_qty", 0) or h.get("qty", 0) or 0)
            h_price = float(h.get("executed_price", 0.0) or h.get("price", 0.0) or 0.0)
            h_status = str(h.get("status", ""))

            is_failed = any(kw in h_status for kw in ["실패", "미체결", "취소", "FAIL", "REJECT"])

            if h_price <= 0:
                continue

            if "매수" in h_type:
                if is_failed:
                    fail_dates.append(h_dt)
                    fail_prices.append(h_price)
                else:
                    buy_dates.append(h_dt)
                    buy_prices.append(h_price)
            elif "매도" in h_type:
                if is_failed:
                    fail_dates.append(h_dt)
                    fail_prices.append(h_price)
                else:
                    sell_dates.append(h_dt)
                    sell_prices.append(h_price)

        if buy_dates:
            ax1.scatter(buy_dates, buy_prices, marker='^', s=120, color='#22C55E',
                        edgecolors='white', linewidth=0.5, zorder=5, label='Buy Executed')
        if sell_dates:
            ax1.scatter(sell_dates, sell_prices, marker='v', s=120, color='#EF4444',
                        edgecolors='white', linewidth=0.5, zorder=5, label='Sell Executed')
        if fail_dates:
            ax1.scatter(fail_dates, fail_prices, marker='x', s=100, color='#F97316',
                        linewidth=2, zorder=5, label='Failed/Unfilled')

    # 3) 평단가 수평선
    if avg_price > 0:
        ax1.axhline(y=avg_price, color='#F59E0B', linestyle='--', linewidth=1.5,
                    label=f'Avg Price (${avg_price:.2f})')

    # 4) 거래량 바 차트
    if volumes:
        colors = ['#22C55E' if closes[i] >= (closes[i-1] if i > 0 else closes[i]) else '#EF4444'
                  for i in range(len(closes))]
        ax2.bar(dates, volumes, color=colors, alpha=0.6, width=0.8)

    # 5) 축 및 레이블 설정
    ax1.set_title(title or f"{symbol} Stock Price & Trade History", color='#E2E8F0', fontsize=14, fontweight='bold')
    ax1.set_ylabel('Price ($)', color='#94A3B8')
    ax1.legend(loc='upper left', fontsize=8, facecolor='#1A202C', edgecolor='#2D3748')
    ax1.grid(True, alpha=0.2, color='#334155')
    ax1.tick_params(colors='#94A3B8')

    ax2.set_ylabel('Volume', color='#94A3B8')
    ax2.grid(True, alpha=0.2, color='#334155')
    ax2.tick_params(colors='#94A3B8')

    # X축 날짜 포맷
    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax1.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    fig.tight_layout()
    return fig


def create_matplotlib_execution_chart(
    symbol: str,
    history: List[Dict[str, Any]],
    title: str = ""
) -> Optional[Figure]:
    """
    Matplotlib 기반 매매 체결 이력 전용 타임라인 그래프를 생성한다.

    Args:
        symbol: 종목코드
        history: 매매 체결 이력 리스트
        title: 차트 제목

    Returns:
        matplotlib.figure.Figure 또는 None
    """
    if not MATPLOTLIB_AVAILABLE:
        logger.warning("matplotlib이 설치되지 않아 차트를 생성할 수 없습니다.")
        return None

    if not history:
        logger.warning(f"[차트] [{symbol}] 체결 이력이 없어 그래프를 생성할 수 없습니다.")
        return None

    plt.style.use('dark_background')

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor('#121826')
    ax.set_facecolor('#0F172A')

    buy_dates, buy_prices = [], []
    sell_dates, sell_prices = [], []
    fail_dates, fail_prices = [], []

    for h in history:
        h_time = str(h.get("order_time", ""))
        h_type = str(h.get("order_type", ""))
        h_qty = int(h.get("executed_qty", 0) or h.get("qty", 0) or 0)
        h_price = float(h.get("executed_price", 0.0) or h.get("price", 0.0) or 0.0)
        h_status = str(h.get("status", ""))

        is_failed = any(kw in h_status for kw in ["실패", "미체결", "취소", "FAIL", "REJECT"])

        if h_price <= 0:
            continue

        try:
            h_dt = datetime.datetime.strptime(h_time[:10], "%Y-%m-%d")
        except Exception:
            try:
                h_dt = datetime.datetime.strptime(h_time[:8], "%Y%m%d")
            except Exception:
                continue

        if "매수" in h_type:
            if is_failed:
                fail_dates.append(h_dt)
                fail_prices.append(h_price)
            else:
                buy_dates.append(h_dt)
                buy_prices.append(h_price)
        elif "매도" in h_type:
            if is_failed:
                fail_dates.append(h_dt)
                fail_prices.append(h_price)
            else:
                sell_dates.append(h_dt)
                sell_prices.append(h_price)

    if buy_dates:
        ax.scatter(buy_dates, buy_prices, marker='^', s=150, color='#22C55E',
                   edgecolors='white', linewidth=0.5, zorder=5, label='Buy Executed')
    if sell_dates:
        ax.scatter(sell_dates, sell_prices, marker='v', s=150, color='#EF4444',
                   edgecolors='white', linewidth=0.5, zorder=5, label='Sell Executed')
    if fail_dates:
        ax.scatter(fail_dates, fail_prices, marker='x', s=120, color='#F97316',
                   linewidth=2, zorder=5, label='Failed/Unfilled')

    ax.set_title(title or f"{symbol} Trade Execution History Timeline", color='#E2E8F0', fontsize=14, fontweight='bold')
    ax.set_xlabel('Order/Execution Time', color='#94A3B8')
    ax.set_ylabel('Execution Price ($)', color='#94A3B8')
    ax.legend(loc='upper left', fontsize=9, facecolor='#1A202C', edgecolor='#2D3748')
    ax.grid(True, alpha=0.2, color='#334155')
    ax.tick_params(colors='#94A3B8')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator())
    fig.autofmt_xdate()

    fig.tight_layout()
    return fig