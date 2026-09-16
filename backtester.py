"""
Backtesting Engine for KIS Auto Trading Strategy
FinanceDataReader 기반 과거 데이터 시뮬레이션
core.indicators 및 core.strategy 모듈의 공통 알고리즘을 100% 동일하게 직접 호출하여 실행합니다.
"""
import os
import logging
import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np
import FinanceDataReader as fdr

import app_config as config
from screener import StockScreener
from core.indicators import calculate_technical_indicators
from core.strategy import get_strategy, get_default_strategy_name

logger = logging.getLogger("Backtester")

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")

class Backtester:
    def __init__(
        self,
        start_date: str,
        end_date: str,
        universe: Optional[List[Dict[str, str]]] = None,
        initial_capital: float = 10000000.0,
        budget_per_stock: float = 1000000.0,
        max_holdings: int = 5,
        target_profit_rate: float = 0.08,   # 개선 1: +8% 목표 익절
        stop_loss_rate: float = -0.05,       # 개선 2: -5% 동적 손절 하한
        fee_rate: float = 0.0015,           # 매수/매도 수수료 (0.15%)
        tax_rate: float = 0.0020,           # 매도 시 거래세 (0.20%)
        strategy_name: Optional[str] = None
    ):
        self.start_date = start_date
        self.end_date = end_date
        self.universe = universe or config.CURRENT_SETTINGS.get("watchlist", [])
        self.initial_capital = initial_capital
        self.budget_per_stock = budget_per_stock
        self.max_holdings = max_holdings
        self.target_profit_rate = target_profit_rate
        self.stop_loss_rate = stop_loss_rate
        self.fee_rate = fee_rate
        self.tax_rate = tax_rate
        self.strategy = get_strategy(strategy_name or config.CURRENT_SETTINGS.get("strategy_name", get_default_strategy_name()))
        self.screener = StockScreener(strategy_name=strategy_name)

    def fetch_universe_data(self, progress_callback=None) -> Dict[str, pd.DataFrame]:
        """유니버스 전 종목에 대해 백테스트 시작일 이전 120영업일부터의 일봉 데이터 다운로드 및 로컬 캐싱"""
        data_map = {}
        start_dt = pd.to_datetime(self.start_date) - datetime.timedelta(days=120)
        start_str = start_dt.strftime("%Y-%m-%d")
        os.makedirs(CACHE_DIR, exist_ok=True)

        total = len(self.universe)
        atr_period = int(config.CURRENT_SETTINGS.get("atr_period", 14))

        for idx, item in enumerate(self.universe):
            code = item.get("code")
            name = item.get("name", code)
            cache_file = os.path.join(CACHE_DIR, f"{code}_{start_str}_{self.end_date}.pkl")
            df = None

            # 1. 로컬 캐시 확인
            if os.path.exists(cache_file):
                try:
                    df = pd.read_pickle(cache_file)
                    if df is not None and not df.empty:
                        df["date"] = pd.to_datetime(df["date"].astype(str)).dt.strftime("%Y-%m-%d")
                        if "ma5" not in df.columns or "atr" not in df.columns:
                            df = calculate_technical_indicators(df, is_intraday=False, atr_period=atr_period)
                except Exception as e:
                    logger.warning(f"[{name}({code})] 캐시 로드 실패: {e}")
                    df = None

            # 2. 캐시 부재 시 FDR 다운로드 후 캐싱
            if df is None or df.empty:
                try:
                    df = fdr.DataReader(code, start_str, self.end_date)
                    if df is not None and not df.empty and len(df) >= 60:
                        df = df.reset_index()
                        rename_cols = {}
                        for col in df.columns:
                            col_lower = str(col).lower()
                            if "date" in col_lower or "날짜" in col_lower:
                                rename_cols[col] = "date"
                            elif "close" in col_lower or "종가" in col_lower:
                                rename_cols[col] = "close"
                            elif "open" in col_lower or "시가" in col_lower:
                                rename_cols[col] = "open"
                            elif "high" in col_lower or "고가" in col_lower:
                                rename_cols[col] = "high"
                            elif "low" in col_lower or "저가" in col_lower:
                                rename_cols[col] = "low"
                            elif "volume" in col_lower or "거래량" in col_lower:
                                rename_cols[col] = "volume"
                            elif "change" in col_lower or "등락" in col_lower:
                                rename_cols[col] = "change_rate"

                        df = df.rename(columns=rename_cols)
                        df["date"] = pd.to_datetime(df["date"].astype(str)).dt.strftime("%Y-%m-%d")
                        df = df.sort_values(by="date").reset_index(drop=True)

                        # core 순수 지표 계산 함수 적용
                        df = calculate_technical_indicators(df, is_intraday=False, atr_period=atr_period)
                        df.to_pickle(cache_file)
                except Exception as e:
                    logger.warning(f"[{name}({code})] FDR 데이터 수집 실패: {e}")
                    df = None

            if df is not None and not df.empty:
                data_map[code] = {
                    "name": name,
                    "market": item.get("market", "KOSPI"),
                    "df": df
                }

            if progress_callback:
                progress_callback((idx + 1) / total * 0.4)

        return data_map

    def fetch_benchmark_data(self) -> Optional[pd.DataFrame]:
        """벤치마크(KOSPI 지수) 일별 데이터 다운로드"""
        try:
            bench_df = fdr.DataReader("KS11", self.start_date, self.end_date)
            if bench_df is not None and not bench_df.empty:
                bench_df = bench_df.reset_index()
                bench_df["date"] = pd.to_datetime(bench_df["Date"]).dt.strftime("%Y-%m-%d")
                first_close = float(bench_df.iloc[0]["Close"])
                bench_df["benchmark_return"] = (bench_df["Close"] - first_close) / first_close * 100
                return bench_df[["date", "Close", "benchmark_return"]]
        except Exception as e:
            logger.warning(f"KOSPI 벤치마크 데이터 로드 실패: {e}")
        return None

    def run(self, progress_callback=None) -> Dict[str, Any]:
        """과거 데이터 기반 일별 전략 백테스팅 시뮬레이션 메인 루프"""
        logger.info(f"=== [Backtester] 백테스트 시작: {self.start_date} ~ {self.end_date} ===")

        universe_data = self.fetch_universe_data(progress_callback=progress_callback)
        if not universe_data:
            return {"error": "유니버스 데이터를 불러올 수 없습니다."}

        bench_df = self.fetch_benchmark_data()

        # 전체 거래일 목록 추출
        all_dates = set()
        for c, v in universe_data.items():
            df = v["df"]
            dates = df[(df["date"] >= self.start_date) & (df["date"] <= self.end_date)]["date"].tolist()
            all_dates.update(dates)

        trade_dates = sorted(list(all_dates))
        if not trade_dates:
            return {"error": "선택한 기간 내 거래일 데이터가 존재하지 않습니다."}

        # 시뮬레이션 상태 변수
        cash = self.initial_capital
        holdings: Dict[str, Dict[str, Any]] = {}
        daily_equity_history: List[Dict[str, Any]] = []
        trade_history: List[Dict[str, Any]] = []

        cooldown_days = int(config.CURRENT_SETTINGS.get("cooldown_days", 4))
        cooldown_until: Dict[str, str] = {} # code -> date string
        daily_buy_count_limit = int(config.CURRENT_SETTINGS.get("max_daily_buy_count", 2))

        total_sim_days = len(trade_dates)

        # 일별 시뮬레이션 루프
        for day_idx, current_date in enumerate(trade_dates):
            current_dt = pd.to_datetime(current_date)

            # -------------------------------------------------------------
            # [Step 1: 당일 시장 국면 (Market Regime) 판별 및 프리셋 동적 적용]
            # -------------------------------------------------------------
            market_regime = {"regime": "BULL"}
            if bench_df is not None and not bench_df.empty:
                bench_sub = bench_df[bench_df["date"] <= current_date]
                if len(bench_sub) >= 20:
                    market_regime = self.strategy.get_market_regime(bench_sub, ma_period=int(config.CURRENT_SETTINGS.get("market_regime_ma_period", 20)))

            eff_settings = config.get_effective_settings_for_regime(market_regime.get("regime", "BULL"), config.CURRENT_SETTINGS)
            daily_stop_loss_rate = float(eff_settings.get("stop_loss_rate", self.stop_loss_rate))
            daily_target_profit_rate = float(eff_settings.get("target_profit_rate", self.target_profit_rate))
            daily_buy_count_limit = int(eff_settings.get("max_daily_buy_count", 2))

            # -------------------------------------------------------------
            # [Step 2: 보유 종목 평가 및 매도 시그널 검증]
            # -------------------------------------------------------------
            stocks_to_delete = []

            for code, pos in list(holdings.items()):
                if code not in universe_data:
                    continue

                stock_full_df = universe_data[code]["df"]
                sub_df = stock_full_df[stock_full_df["date"] <= current_date]
                if sub_df.empty:
                    continue

                current_row = sub_df.iloc[-1]
                pos["holding_days"] += 1

                close_price = float(current_row["close"])
                high_price = float(current_row["high"])
                low_price = float(current_row["low"])
                avg_price = pos["avg_buy_price"]

                low_profit_rate = (low_price - avg_price) / avg_price * 100
                high_profit_rate = (high_price - avg_price) / avg_price * 100
                close_profit_rate = (close_price - avg_price) / avg_price * 100

                holding_dict = {
                    "code": code,
                    "name": pos["name"],
                    "quantity": pos["qty"],
                    "avg_buy_price": avg_price,
                    "current_price": close_price,
                    "profit_rate": close_profit_rate,
                    "profit_loss": (close_price - avg_price) * pos["qty"]
                }

                pos["highest_price"] = max(pos.get("highest_price", avg_price), high_price)
                is_partial_sold = pos.get("is_partial_sold", False)

                df_tech = sub_df.tail(65)
                is_recently_bought = (pos["holding_days"] < 2)

                sell_signal = self.strategy.evaluate_sell(
                    holding=holding_dict,
                    df=df_tech,
                    is_recently_bought=is_recently_bought,
                    stop_loss_rate=daily_stop_loss_rate,
                    target_profit_rate=daily_target_profit_rate,
                    settings=eff_settings,
                    is_partial_sold=is_partial_sold,
                    highest_price=pos["highest_price"],
                    holding_days=pos["holding_days"],
                    market_regime=market_regime
                )

                sell_price = close_price
                if sell_signal:
                    if sell_signal.get("is_urgent", False):
                        sell_price = min(close_price, avg_price * (1 + daily_stop_loss_rate))
                    elif "익절" in sell_signal.get("sell_type", "") and not is_partial_sold:
                        sell_price = max(close_price, avg_price * (1 + daily_target_profit_rate))

                    sell_qty = sell_signal.get("sell_qty", pos["qty"])
                    sell_type = sell_signal.get("sell_type", "매도")
                    sell_reason = " • ".join(sell_signal.get("reasons", []))

                    gross_amount = sell_qty * sell_price
                    fee_cost = gross_amount * self.fee_rate
                    tax_cost = gross_amount * self.tax_rate
                    net_amount = gross_amount - (fee_cost + tax_cost)

                    profit_krw = (sell_price - avg_price) * sell_qty - (fee_cost + tax_cost)
                    profit_pct = (profit_krw / (avg_price * sell_qty)) * 100

                    cash += net_amount

                    trade_history.append({
                        "date": current_date,
                        "code": code,
                        "name": pos["name"],
                        "action": "SELL",
                        "sell_type": sell_type,
                        "price": sell_price,
                        "qty": sell_qty,
                        "amount": gross_amount,
                        "fee_tax": fee_cost + tax_cost,
                        "profit_krw": profit_krw,
                        "profit_pct": profit_pct,
                        "holding_days": pos["holding_days"],
                        "reasons": sell_reason
                    })

                    # 손절 시 인메모리 쿨다운 등록
                    if sell_signal.get("is_urgent", False) or "손절" in sell_type:
                        future_date = (current_dt + datetime.timedelta(days=cooldown_days * 2)).strftime("%Y-%m-%d")
                        cooldown_until[code] = future_date

                    # 분할 익절 처리
                    if sell_signal.get("is_partial_take", False) and sell_qty < pos["qty"]:
                        pos["qty"] -= sell_qty
                        pos["is_partial_sold"] = True
                    else:
                        stocks_to_delete.append(code)

            for c in stocks_to_delete:
                del holdings[c]

            # -------------------------------------------------------------
            # [Step 3: 15:15 종가 매수 종목 스크리닝 및 발주]
            # -------------------------------------------------------------
            available_slots = self.max_holdings - len(holdings)
            today_buy_candidates = []

            if available_slots > 0:
                for code, v in universe_data.items():
                    if code in holdings:
                        continue

                    # 손절 쿨다운 체크
                    if code in cooldown_until and current_date <= cooldown_until[code]:
                        continue

                    df = v["df"]
                    sub_df = df[df["date"] <= current_date]
                    if len(sub_df) < 30:
                        continue

                    sub_65 = sub_df.tail(65)

                    # core 매수 신호 단일 원천 함수 호출
                    signal = self.strategy.evaluate_buy(
                        df=sub_65,
                        code=code,
                        name=v["name"],
                        held_codes=set(holdings.keys()),
                        budget=self.budget_per_stock,
                        market_regime=market_regime,
                        settings=eff_settings,
                        is_in_cooldown=False
                    )

                    if signal and signal.get("score", 0) >= signal.get("buy_threshold", 45):
                        today_buy_candidates.append(signal)

                # 점수 높은 순 정렬 후 상위 종목 매수
                today_buy_candidates.sort(key=lambda x: (x.get("score", 0), x.get("vol_ratio", 0)), reverse=True)
                actual_buy_count = 0

                for candidate in today_buy_candidates:
                    if actual_buy_count >= min(available_slots, daily_buy_count_limit):
                        break

                    c_code = candidate["code"]
                    c_name = candidate["name"]
                    c_price = candidate["current_price"]
                    c_qty = candidate.get("recommended_qty", int(self.budget_per_stock // c_price))

                    if c_qty <= 0:
                        c_qty = 1

                    gross_buy_amt = c_qty * c_price
                    buy_fee = gross_buy_amt * self.fee_rate
                    total_buy_required = gross_buy_amt + buy_fee

                    if cash >= total_buy_required:
                        cash -= total_buy_required
                        holdings[c_code] = {
                            "name": c_name,
                            "qty": c_qty,
                            "avg_buy_price": c_price,
                            "entry_date": current_date,
                            "holding_days": 0,
                            "highest_price": c_price,
                            "is_partial_sold": False
                        }

                        trade_history.append({
                            "date": current_date,
                            "code": c_code,
                            "name": c_name,
                            "action": "BUY",
                            "sell_type": "종가 매수",
                            "price": c_price,
                            "qty": c_qty,
                            "amount": gross_buy_amt,
                            "fee_tax": buy_fee,
                            "profit_krw": 0.0,
                            "profit_pct": 0.0,
                            "holding_days": 0,
                            "reasons": " • ".join(candidate.get("reasons", []))
                        })

                        actual_buy_count += 1
                        available_slots -= 1

            # -------------------------------------------------------------
            # [Step 4: 당일 마감 총 평가 자산 산출]
            # -------------------------------------------------------------
            current_stock_eval = 0.0
            for h_code, h_pos in holdings.items():
                if h_code in universe_data:
                    h_df = universe_data[h_code]["df"]
                    h_sub = h_df[h_df["date"] <= current_date]
                    if not h_sub.empty:
                        c_prc = float(h_sub.iloc[-1]["close"])
                        current_stock_eval += h_pos["qty"] * c_prc
                    else:
                        current_stock_eval += h_pos["qty"] * h_pos["avg_buy_price"]

            total_equity = cash + current_stock_eval
            return_pct = (total_equity - self.initial_capital) / self.initial_capital * 100

            daily_equity_history.append({
                "date": current_date,
                "total_equity": total_equity,
                "cash": cash,
                "stock_eval": current_stock_eval,
                "return_pct": return_pct,
                "holdings_count": len(holdings)
            })

            if progress_callback:
                progress_callback(0.4 + (day_idx + 1) / total_sim_days * 0.6)

        # -------------------------------------------------------------
        # [Step 5: 성과 지표 계산 및 결과 패키징]
        # -------------------------------------------------------------
        daily_eq_df = pd.DataFrame(daily_equity_history)
        trades_df = pd.DataFrame(trade_history)

        if not daily_eq_df.empty:
            daily_eq_df["peak"] = daily_eq_df["total_equity"].cummax()
            daily_eq_df["drawdown"] = (daily_eq_df["total_equity"] - daily_eq_df["peak"]) / daily_eq_df["peak"] * 100
            mdd = daily_eq_df["drawdown"].min()
            final_equity = float(daily_eq_df.iloc[-1]["total_equity"])
            total_return_pct = (final_equity - self.initial_capital) / self.initial_capital * 100
        else:
            mdd = 0.0
            final_equity = self.initial_capital
            total_return_pct = 0.0

        num_days = len(trade_dates)
        cagr = ((final_equity / self.initial_capital) ** (252.0 / max(1, num_days)) - 1) * 100 if num_days > 0 and final_equity > 0 else 0.0

        # 매매 승률 및 손익비
        if not trades_df.empty:
            sells_df = trades_df[trades_df["action"] == "SELL"]
            win_trades = sells_df[sells_df["profit_krw"] > 0]
            loss_trades = sells_df[sells_df["profit_krw"] <= 0]

            total_wins = len(win_trades)
            total_losses = len(loss_trades)
            win_rate = (total_wins / len(sells_df) * 100) if len(sells_df) > 0 else 0.0

            total_gain = win_trades["profit_krw"].sum()
            total_loss = abs(loss_trades["profit_krw"].sum())
            profit_factor = (total_gain / total_loss) if total_loss > 0 else 999.0
        else:
            total_wins = 0
            total_losses = 0
            win_rate = 0.0
            profit_factor = 0.0

        summary = {
            "initial_capital": self.initial_capital,
            "final_equity": final_equity,
            "total_profit_krw": final_equity - self.initial_capital,
            "total_return_pct": total_return_pct,
            "cagr_pct": cagr,
            "mdd_pct": mdd,
            "total_trades": len(trades_df),
            "sell_trades_count": total_wins + total_losses,
            "win_count": total_wins,
            "loss_count": total_losses,
            "win_rate": win_rate,
            "profit_factor": profit_factor
        }

        return {
            "summary": summary,
            "daily_equity": daily_eq_df,
            "trade_history": trades_df,
            "benchmark_df": bench_df
        }
