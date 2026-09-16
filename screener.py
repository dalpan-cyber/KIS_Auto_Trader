"""
Stock Screener & Signal Engine
종가(15:10) 매수 후보 종목 발굴 및 실시간 리스크 관리(손절 최우선 / 분할 익절) 분석 엔진
core.indicators, core.strategy, core.position_tracker 모듈을 기반으로 동작합니다.
"""
import os
import logging
import datetime
from typing import Dict, Any, List, Optional, Set
import pandas as pd

import app_config as config
from kis_api import KISApiClient
from telegram_notifier import notifier
from time_utils import today, now_str
from core.storage import safe_load_json, atomic_save_json
from core.indicators import calculate_technical_indicators
from core.position_tracker import PositionTracker, POSITIONS_STATE_FILE, COOLDOWN_FILE
from core.strategy import get_strategy, get_default_strategy_name, get_active_strategies

PROPOSALS_FILE = os.path.join(os.path.dirname(__file__), "proposals.json")
PROPOSALS_FALLBACK_FILE = os.path.join(os.path.dirname(__file__), "proposals_fallback.json")

class StockScreener:
    def __init__(self, api_client: Optional[KISApiClient] = None, strategy_name: Optional[str] = None):
        self.logger = logging.getLogger("Screener")
        self.api = api_client or KISApiClient()
        self.strategy = get_strategy(strategy_name or config.CURRENT_SETTINGS.get("strategy_name", get_default_strategy_name()))
        self.strategies = get_active_strategies()
        self.position_tracker = PositionTracker(
            positions_file=POSITIONS_STATE_FILE,
            cooldown_file=COOLDOWN_FILE
        )

    # =========================================================================
    # 하위 호환성을 위한 포지션 상태 / 쿨다운 래퍼 메서드
    # =========================================================================
    def _load_positions_state(self) -> Dict[str, Dict[str, Any]]:
        return self.position_tracker.load_positions_state()

    def _save_positions_state(self, state: Dict[str, Dict[str, Any]]) -> bool:
        return self.position_tracker.save_positions_state(state)

    def _update_position_state(
        self,
        code: str,
        current_price: float,
        avg_buy_price: float,
        is_partial_take: bool = False,
        strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        return self.position_tracker.update_position_state(code, current_price, avg_buy_price, is_partial_take, strategy=strategy)

    def _get_holding_strategy(self, code: str):
        """보유 종목의 매수 진입 전략을 조회하여 해당 전략 인스턴스 반환"""
        strat_name = self.position_tracker.get_position_strategy(code)
        if not strat_name:
            try:
                proposals = self.load_proposals()
                for b in proposals.get("buy_proposals", []):
                    if b.get("code") == code:
                        strat_name = b.get("strategy_name", b.get("strategy"))
                        if strat_name:
                            self.position_tracker.update_position_state(
                                code=code,
                                current_price=float(b.get("current_price", 0)),
                                avg_buy_price=float(b.get("current_price", 0)),
                                strategy=strat_name
                            )
                            break
            except Exception:
                pass

        if strat_name and ("&" in strat_name or strat_name == "multi"):
            strat_name = "rebound" if "rebound" in strat_name else "momentum"

        if strat_name:
            s_inst = get_strategy(strat_name)
            if s_inst:
                return s_inst

        return self.strategy

    def _clear_position_state(self, code: str) -> None:
        self.position_tracker.clear_position_state(code)

    def _load_cooldown(self) -> Dict[str, str]:
        return self.position_tracker.load_cooldown()

    def _save_cooldown(self, cooldown_map: Dict[str, str]) -> bool:
        return self.position_tracker.save_cooldown(cooldown_map)

    def _get_stop_loss_date_from_api(self, code: str, current_date: Optional[str] = None) -> Optional[str]:
        return self.position_tracker.get_stop_loss_date_from_api(self.api, code, current_date=current_date)

    def _is_in_cooldown(self, code: str, current_date: Optional[str] = None, use_file_cooldown: bool = False) -> bool:
        return self.position_tracker.is_in_cooldown(
            code=code,
            cooldown_days=int(config.CURRENT_SETTINGS.get("cooldown_days", 4)),
            cooldown_enabled=bool(config.CURRENT_SETTINGS.get("cooldown_enabled", True)),
            api_client=self.api,
            current_date=current_date,
            use_file_cooldown=use_file_cooldown
        )

    def _register_stop_loss_cooldown(self, code: str, stop_date: Optional[str] = None, use_file_cooldown: bool = False) -> None:
        self.position_tracker.register_stop_loss_cooldown(
            code=code,
            stop_date=stop_date,
            cooldown_days=int(config.CURRENT_SETTINGS.get("cooldown_days", 4)),
            cooldown_enabled=bool(config.CURRENT_SETTINGS.get("cooldown_enabled", True)),
            use_file_cooldown=use_file_cooldown
        )

    # =========================================================================
    # 시장 국면 및 기술 지표 계산
    # =========================================================================
    def get_market_regime(self, market: str = "KOSPI") -> Dict[str, Any]:
        """시장 국면 판단"""
        index_code = "069500" if market == "KOSPI" else "229200"
        try:
            candles = self.api.get_daily_chart(index_code, count=40)
            if not candles or len(candles) < 20:
                return {"regime": "NORMAL", "below_ma20": False, "downtrend": False, "ma20": 0.0, "current": 0.0}
            ma_period = int(config.CURRENT_SETTINGS.get("market_regime_ma_period", 20))
            return self.strategy.get_market_regime(candles, ma_period=ma_period)
        except Exception as e:
            self.logger.warning(f"[{market}] 시장 국면 판단 중 예외: {e}")
            return {"regime": "NORMAL", "below_ma20": False, "downtrend": False, "ma20": 0.0, "current": 0.0}

    def calculate_technical_indicators(
        self,
        candles: List[Dict[str, Any]],
        is_intraday: bool = True
    ) -> Optional[pd.DataFrame]:
        """일봉 캔들 데이터를 바탕으로 기술적 보조지표 계산"""
        atr_period = int(config.CURRENT_SETTINGS.get("atr_period", 14))
        return calculate_technical_indicators(candles, is_intraday=is_intraday, atr_period=atr_period)

    # =========================================================================
    # 매수 신호 평가
    # =========================================================================
    def evaluate_buy_signals_from_df(
        self,
        df: pd.DataFrame,
        code: str,
        name: str,
        held_codes: Optional[Set[str]] = None,
        budget: Optional[float] = None,
        market_regime: Optional[Dict[str, Any]] = None,
        current_date: Optional[str] = None,
        use_file_cooldown: bool = False,
        futures_data: Optional[Dict[str, Any]] = None,
        return_raw_eval: bool = False,
        investor_data: Optional[Dict[str, Any]] = None,
        volume_power: Optional[float] = None,
        extra_data: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """기술적 보조지표 DataFrame을 바탕으로 활성화된 모든 전략 매수 신호 평가"""
        in_cooldown = self._is_in_cooldown(code, current_date=current_date, use_file_cooldown=use_file_cooldown)
        active_strats = getattr(self, "strategies", None) or get_active_strategies()

        results = []
        for strat in active_strats:
            try:
                res = strat.evaluate_buy(
                    df=df,
                    code=code,
                    name=name,
                    held_codes=held_codes,
                    budget=budget,
                    market_regime=market_regime,
                    settings=config.CURRENT_SETTINGS,
                    is_in_cooldown=in_cooldown,
                    futures_data=futures_data,
                    return_raw_eval=return_raw_eval,
                    investor_data=investor_data,
                    volume_power=volume_power,
                    extra_data=extra_data
                )
                if res:
                    res["strategy"] = strat.name
                    if "strategy_name" not in res:
                        res["strategy_name"] = strat.name
                    if "strategy_display_name" not in res:
                        res["strategy_display_name"] = strat.display_name
                    results.append(res)
            except Exception as e:
                self.logger.warning(f"[{name}({code})] 전략 '{strat.name}' 평가 중 예외: {e}")

        if not results:
            return None

        # 추천 결과와 미추천(관망) 결과 구분
        recommended_results = [r for r in results if r.get("is_recommended", True)]
        if return_raw_eval and not recommended_results:
            results.sort(key=lambda x: x.get("score", 0), reverse=True)
            return results[0]

        target_results = recommended_results if recommended_results else results
        if len(target_results) == 1:
            return target_results[0]

        # 복수 전략에서 동시 추천된 경우 (슈퍼 시그널)
        # 가장 높은 점수를 기본으로 취하고 보너스 가산점 및 사유 병합
        target_results.sort(key=lambda x: x.get("score", 0), reverse=True)
        best = target_results[0]
        combined_names = " & ".join(r.get("strategy_display_name", r.get("strategy_name")) for r in target_results)
        
        # 보너스 점수 +10점 부여
        if best.get("is_recommended", True):
            best["score"] = best.get("score", 0) + 10
            best["strategy"] = best.get("strategy", best.get("strategy_name", "multi"))
            best["strategy_display_name"] = combined_names
            best["is_multi_strategy"] = True
            best["reasons"] = [f"🌟 [슈퍼 시그널] {combined_names} 복수 알고리즘 동시 포착 (+10점)"] + best.get("reasons", [])
        return best

    def evaluate_buy_signals(
        self,
        code: str,
        name: str,
        held_codes: Optional[Set[str]] = None,
        is_intraday: bool = True,
        market: str = "KOSPI",
        return_raw_eval: bool = False
    ) -> Optional[Dict[str, Any]]:
        """라이브 환경에서 API 데이터 수집 후 매수 신호 평가"""
        candles = self.api.get_daily_chart(code, count=65)

        realtime = self.api.get_stock_price(code)
        d250_hgpr = float(realtime.get("d250_hgpr", 0.0))

        if realtime.get("rt_cd") == "0" and realtime.get("price", 0) > 0:
            today_str = today().strftime("%Y%m%d")
            candle_entry = {
                "date": today_str,
                "close": realtime["price"],
                "open": realtime.get("stck_oprc", realtime["price"]),
                "high": realtime.get("stck_hgpr", realtime["price"]),
                "low": realtime.get("stck_lwpr", realtime["price"]),
                "volume": realtime.get("acml_vol", 0),
                "change_rate": realtime.get("prdy_ctrt", 0.0),
                "d250_hgpr": d250_hgpr
            }
            if not candles or candles[-1].get("date") != today_str:
                candles.append(candle_entry)
            else:
                candles[-1].update(candle_entry)

        df = self.calculate_technical_indicators(candles, is_intraday=is_intraday)
        if df is not None and not df.empty and d250_hgpr > 0:
            df["d250_hgpr"] = d250_hgpr

        market_regime = None
        if config.CURRENT_SETTINGS.get("market_regime_filter_enabled", True):
            market_regime = self.get_market_regime(market=market)

        futures_data = None
        if config.CURRENT_SETTINGS.get("use_futures_filter", True):
            try:
                futures_data = self.api.get_stock_futures_price(code)
            except Exception as e:
                self.logger.warning(f"[{name}({code})] 주식선물 수급 조회 예외: {e}")

        # Step 1: 당일 투자자별 매매동향 (외인/기관 순매수) 조회
        investor_data = None
        if config.CURRENT_SETTINGS.get("use_investor_filter", True):
            try:
                investor_data = self.api.get_investor_trend(code)
            except Exception as e:
                self.logger.warning(f"[{name}({code})] 투자자 매매동향 조회 예외: {e}")

        # Step 3: 당일 실시간 체결강도 조회
        volume_power = None
        if config.CURRENT_SETTINGS.get("use_volume_power_gate", True):
            try:
                volume_power = self.api.get_execution_strength(code)
            except Exception as e:
                self.logger.warning(f"[{name}({code})] 당일 체결강도 조회 예외: {e}")

        # Step 4: 월봉 전략(monthly_trend) 활성화 시 월봉 데이터 수집
        extra_data = {}
        active_strats = getattr(self, "strategies", None) or get_active_strategies()
        if any(s.name == "monthly_trend" for s in active_strats):
            try:
                m_candles = self.api.get_monthly_chart(code, count=15)
                if m_candles:
                    if realtime.get("rt_cd") == "0" and realtime.get("price", 0) > 0:
                        curr_m_str = today().strftime("%Y%m")
                        if m_candles[-1].get("date", "")[:6] == curr_m_str:
                            m_candles[-1]["close"] = realtime["price"]
                            m_candles[-1]["high"] = max(m_candles[-1].get("high", realtime["price"]), realtime["price"])
                            m_candles[-1]["low"] = min(m_candles[-1].get("low", realtime["price"]), realtime["price"])
                        else:
                            m_candles.append({
                                "date": today().strftime("%Y%m%d"),
                                "open": realtime.get("stck_oprc", realtime["price"]),
                                "close": realtime["price"],
                                "high": realtime.get("stck_hgpr", realtime["price"]),
                                "low": realtime.get("stck_lwpr", realtime["price"]),
                                "volume": realtime.get("acml_vol", 0)
                            })
                    extra_data["monthly_df"] = pd.DataFrame(m_candles)
            except Exception as e:
                self.logger.warning(f"[{name}({code})] 월봉 데이터 조회 예외: {e}")

        return self.evaluate_buy_signals_from_df(
            df, code, name,
            held_codes=held_codes,
            market_regime=market_regime,
            use_file_cooldown=False,
            futures_data=futures_data,
            return_raw_eval=return_raw_eval,
            investor_data=investor_data,
            volume_power=volume_power,
            extra_data=extra_data
        )

    # =========================================================================
    # 매도 신호 평가
    # =========================================================================
    def evaluate_sell_signals_from_df(
        self,
        holding: Dict[str, Any],
        df: Optional[pd.DataFrame] = None,
        is_recently_bought: bool = False,
        stop_loss_rate: Optional[float] = None,
        target_profit_rate: Optional[float] = None,
        current_date: Optional[str] = None,
        use_file_cooldown: bool = False,
        is_partial_sold: bool = False,
        highest_price: Optional[float] = None,
        holding_days: int = 0,
        market_regime: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """보유 종목의 진입 전략 알고리즘에 따른 매도 신호 평가"""
        code = holding.get("code")
        strat = self._get_holding_strategy(code)
        res = strat.evaluate_sell(
            holding=holding,
            df=df,
            is_recently_bought=is_recently_bought,
            stop_loss_rate=stop_loss_rate,
            target_profit_rate=target_profit_rate,
            settings=config.CURRENT_SETTINGS,
            is_partial_sold=is_partial_sold,
            highest_price=highest_price,
            holding_days=holding_days,
            market_regime=market_regime
        )
        if res:
            res["strategy_name"] = strat.name
            res["strategy_display_name"] = strat.display_name
            if res.get("is_urgent") and "손절" in res.get("sell_type", ""):
                # 손절 발생 시 쿨다운 등록
                self._register_stop_loss_cooldown(
                    code=code,
                    stop_date=current_date,
                    use_file_cooldown=use_file_cooldown
                )
        return res

    def _is_recently_bought(self, code: str, days: int = 2) -> bool:
        """매수일로부터 지정된 일수 이내에 매수된 종목인지 확인"""
        try:
            end_date = today().strftime("%Y%m%d")
            start_date = (today() - datetime.timedelta(days=days)).strftime("%Y%m%d")
            orders = self.api.get_order_history(start_date=start_date, end_date=end_date)
            for order in orders:
                if order.get("code") == code and order.get("buy_sell") == "매수":
                    return True
        except Exception as e:
            self.logger.warning(f"[{code}] 최근 매수 여부 확인 중 예외: {e}")
        return False

    def evaluate_sell_signals(self, holding: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """라이브 환경에서 보유 종목 매도 분석"""
        code = holding.get("code")
        profit_rate = float(holding.get("profit_rate", 0.0))
        current_price = float(holding.get("current_price", 0.0))
        avg_buy_price = float(holding.get("avg_buy_price", 0.0))

        # 시장 국면 감지 (AUTO 모드에서 프리셋 자동 전환을 위해 필요)
        market_regime = None
        if config.CURRENT_SETTINGS.get("market_regime_filter_enabled", True):
            market_regime = self.get_market_regime(market=holding.get("market", "KOSPI"))

        # 유효 설정 (시장 국면 프리셋 적용)
        regime = (market_regime or {}).get("regime", "BULL")
        eff_settings = config.get_effective_strategy_settings(self.strategy.name, config.CURRENT_SETTINGS)
        eff_settings = config.get_effective_settings_for_regime(regime, eff_settings)

        target_profit_rate = float(eff_settings.get("target_profit_rate", 0.05)) * 100
        stop_loss_rate = float(eff_settings.get("stop_loss_rate", -0.03)) * 100

        pos_state = self._update_position_state(code, current_price, avg_buy_price)
        is_partial_sold = pos_state.get("is_partial_sold", False)
        highest_price = pos_state.get("highest_price", current_price)

        if profit_rate <= stop_loss_rate or (profit_rate >= target_profit_rate and not is_partial_sold):
            sell_res = self.evaluate_sell_signals_from_df(
                holding=holding,
                df=None,
                is_recently_bought=False,
                stop_loss_rate=stop_loss_rate / 100,
                target_profit_rate=target_profit_rate / 100,
                current_date=today().strftime("%Y%m%d"),
                use_file_cooldown=False,
                is_partial_sold=is_partial_sold,
                highest_price=highest_price,
                market_regime=market_regime
            )
            return sell_res

        is_recent = self._is_recently_bought(code, days=2)
        if is_recent and not is_partial_sold:
            self.logger.info(f"[{holding.get('name')}({code})] 매수 후 2영업일 이내 종목으로 기술적 매도 제외")
            return None

        candles = self.api.get_daily_chart(code, count=60)
        realtime = self.api.get_stock_price(code)
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

        holding_strat = self._get_holding_strategy(code)
        if holding_strat and holding_strat.name == "monthly_trend":
            try:
                m_candles = self.api.get_monthly_chart(code, count=15)
                if m_candles and realtime.get("rt_cd") == "0" and realtime.get("price", 0) > 0:
                    curr_m_str = today().strftime("%Y%m")
                    if m_candles[-1].get("date", "")[:6] == curr_m_str:
                        m_candles[-1]["close"] = realtime["price"]
                    else:
                        m_candles.append({"date": today().strftime("%Y%m%d"), "close": realtime["price"]})
                df = pd.DataFrame(m_candles)
            except Exception as e:
                self.logger.warning(f"[{holding.get('name')}({code})] 매도 분석용 월봉 조회 예외: {e}")
                df = self.calculate_technical_indicators(candles, is_intraday=True)
        else:
            df = self.calculate_technical_indicators(candles, is_intraday=True)
        sell_res = self.evaluate_sell_signals_from_df(
            holding=holding,
            df=df,
            is_recently_bought=is_recent,
            stop_loss_rate=stop_loss_rate / 100,
            target_profit_rate=target_profit_rate / 100,
            current_date=today().strftime("%Y%m%d"),
            use_file_cooldown=False,
            is_partial_sold=is_partial_sold,
            highest_price=highest_price,
            market_regime=market_regime
        )
        return sell_res

    # =========================================================================
    # 스크리닝 및 주문 집행
    # =========================================================================
    def run_closing_price_screening(self) -> Dict[str, Any]:
        """15:10 종가 매수 스크리닝 및 제안서 갱신"""
        self.logger.info("=== [15:10] 종가 매수 후보 발굴 및 스크리닝 시작 ===")
        balance = self.api.get_account_balance()
        holdings = balance.get("holdings", [])
        held_codes = {h.get("code") for h in holdings if h.get("code")}
        watchlist = list(config.CURRENT_SETTINGS.get("watchlist", []))

        # Step 2: 당일 거래대금 상위(Top 30) 유동성 주도주 동적 유니버스 확장
        if config.CURRENT_SETTINGS.get("dynamic_universe_enabled", True):
            top_n = int(config.CURRENT_SETTINGS.get("dynamic_universe_top_n", 30))
            try:
                top_traded = self.api.get_top_traded_stocks(count=top_n)
                existing_codes = {s.get("code") for s in watchlist if s.get("code")}
                added_count = 0
                for item in top_traded:
                    code = item.get("code")
                    name = item.get("name")
                    if code and code not in existing_codes:
                        existing_codes.add(code)
                        watchlist.append({
                            "code": code,
                            "name": name,
                            "market": "KOSPI"
                        })
                        if hasattr(config, "STOCK_NAMES"):
                            config.STOCK_NAMES[code] = name
                        added_count += 1
                if added_count > 0:
                    self.logger.info(f"⚡ 당일 거래대금 상위 주도주 {added_count}개 종목 스크리닝 유니버스 동적 편입 (총 {len(watchlist)}종목)")
            except Exception as e:
                self.logger.warning(f"동적 유니버스 확장 중 예외: {e}")

        buy_proposals = []
        unqualified_candidates = []
        for stock in watchlist:
            code = stock.get("code")
            name = stock.get("name")
            market = stock.get("market", "KOSPI")
            try:
                res = self.evaluate_buy_signals(
                    code, name,
                    held_codes=held_codes,
                    is_intraday=True,
                    market=market,
                    return_raw_eval=True
                )
                if res:
                    if res.get("is_recommended", True):
                        buy_proposals.append(res)
                    else:
                        unqualified_candidates.append(res)
            except Exception as e:
                self.logger.warning(f"[{name}({code})] 종가 스크리닝 중 예외: {e}")

        buy_proposals.sort(key=lambda x: x["score"], reverse=True)
        for p in buy_proposals:
            p.setdefault("recommended_price", p.get("current_price", 0))
        top_buy_proposals = buy_proposals

        top_candidates = []
        if not top_buy_proposals:
            unqualified_candidates.sort(key=lambda x: x.get("score", 0), reverse=True)
            top_candidates = unqualified_candidates[:3]

        sell_proposals = []
        for holding in holdings:
            try:
                sell_res = self.evaluate_sell_signals(holding)
                if sell_res:
                    sell_proposals.append(sell_res)
            except Exception as e:
                self.logger.warning(f"[{holding.get('name')}] 매도 분석 예외: {e}")

        # 현재 잔고 기준 실시간 재평가된 매도 신호만 최신 반영 (조건 해제 종목 자동 제외 및 실시간 가격/손익 동기화)
        merged_sell_proposals = sell_proposals

        existing = self.load_proposals()
        if top_buy_proposals:
            last_recommended = top_buy_proposals
            last_rec_at = now_str()
        else:
            last_recommended = existing.get("last_recommended_proposals", [])
            last_rec_at = existing.get("last_recommended_at", "-")
            if not last_recommended and existing.get("buy_proposals"):
                last_recommended = existing.get("buy_proposals")
                last_rec_at = existing.get("generated_at", "-")

        proposals_data = {
            "generated_at": now_str(),
            "screening_type": "CLOSING_BUY_1510",
            "buy_proposals": top_buy_proposals,
            "last_recommended_proposals": last_recommended,
            "last_recommended_at": last_rec_at,
            "top_candidates": top_candidates,
            "sell_proposals": merged_sell_proposals,
            "holdings_count": len(holdings),
            "status": "READY"
        }

        self.save_proposals(proposals_data)
        self.logger.info(f"15:10 종가 스크리닝 완료: 매수 추천 {len(top_buy_proposals)}건 (상위 관망 후보 {len(top_candidates)}건), 매도 추천 {len(sell_proposals)}건")
        self._notify_screening_summary(top_buy_proposals, sell_proposals, len(holdings), top_candidates=top_candidates)

        return proposals_data

    def run_premarket_screening(self) -> Dict[str, Any]:
        """개장 전/정기 스크리닝 (기본 호환용)"""
        return self.run_closing_price_screening()

    def check_market_open_stop_loss(self) -> List[Dict[str, Any]]:
        """09:00 시초가 갭하락 및 보유 종목 긴급 손절 감시"""
        self.logger.info("=== [09:00] 시초가 갭하락 및 긴급 손절 감시 시작 ===")
        balance = self.api.get_account_balance()
        holdings = balance.get("holdings", [])
        urgent_sells = []

        # 시장 국면 감지 및 유효 설정 적용 (AUTO 모드에서 프리셋 자동 전환)
        market_regime = None
        if config.CURRENT_SETTINGS.get("market_regime_filter_enabled", True):
            market_regime = self.get_market_regime(market="KOSPI")
        regime = (market_regime or {}).get("regime", "BULL")
        eff_settings = config.get_effective_strategy_settings(self.strategy.name, config.CURRENT_SETTINGS)
        eff_settings = config.get_effective_settings_for_regime(regime, eff_settings)

        stop_loss_rate = float(eff_settings.get("stop_loss_rate", -0.03)) * 100

        for holding in holdings:
            profit_rate = float(holding.get("profit_rate", 0.0))
            if profit_rate <= stop_loss_rate:
                sell_res = self.evaluate_sell_signals(holding)
                if sell_res:
                    urgent_sells.append(sell_res)
                    if config.CURRENT_SETTINGS.get("auto_execute_orders", False):
                        self.logger.warning(f"[{holding.get('name')}] 09:00 긴급 손절 시장가 매도 자동 발주")
                        self.api.order_stock(
                            code=holding.get("code"),
                            qty=int(holding.get("quantity", 0)),
                            buy_sell="매도",
                            order_type="01"
                        )

        if urgent_sells:
            self._notify_sell_recommendations(urgent_sells)

        return urgent_sells

    def check_sell_signals_now(self) -> Dict[str, Any]:
        """장중 실시간 매도 신호 재분석 및 제안서 갱신"""
        self.logger.info("=== 보유 주식 실시간 매도 신호 재분석 시작 ===")
        existing = self.load_proposals()
        buy_proposals = existing.get("buy_proposals", [])

        balance = self.api.get_account_balance()
        holdings = balance.get("holdings", [])
        holding_codes = {h.get("code") for h in holdings if h.get("code")}
        sell_proposals = []
        for holding in holdings:
            try:
                sell_res = self.evaluate_sell_signals(holding)
                if sell_res:
                    sell_proposals.append(sell_res)
            except Exception as e:
                self.logger.warning(f"[{holding.get('name')}] 매도 분석 예외: {e}")

        # 현재 실시간 잔고 기준 매도 신호만 최신 반영 (조건 해제 종목 자동 제외 및 최신 현재가/평가손익 동기화)
        merged_sell_proposals = sell_proposals

        screening_at = existing.get("generated_at", now_str())
        screening_type = existing.get("screening_type", "CLOSING_BUY_1515")
        last_recommended = existing.get("last_recommended_proposals", [])
        last_rec_at = existing.get("last_recommended_at", "-")
        top_candidates = existing.get("top_candidates", [])

        proposals_data = {
            "generated_at": screening_at,
            "sell_checked_at": now_str(),
            "screening_type": screening_type,
            "buy_proposals": buy_proposals,
            "last_recommended_proposals": last_recommended,
            "last_recommended_at": last_rec_at,
            "top_candidates": top_candidates,
            "sell_proposals": merged_sell_proposals,
            "holdings_count": len(holdings),
            "status": "READY"
        }

        self.save_proposals(proposals_data)
        self.logger.info(f"실시간 매도 신호 재분석 완료: 매도 추천 {len(merged_sell_proposals)}건")
        self._notify_sell_recommendations(sell_proposals)
        return proposals_data

    def execute_top_buy_orders(self) -> List[Dict[str, Any]]:
        """15:18 매수 추천 종목 시장가 주문 집행"""
        self.logger.info("=== [15:18] 종가 매수 추천 종목 주문 집행 시작 ===")
        proposals = self.load_proposals()
        buy_list = proposals.get("buy_proposals", [])

        if not buy_list:
            return []

        if not config.CURRENT_SETTINGS.get("auto_execute_orders", False):
            return []

        # 시장 국면 감지 및 유효 설정 적용 (AUTO 모드에서 프리셋 자동 전환)
        market_regime = None
        if config.CURRENT_SETTINGS.get("market_regime_filter_enabled", True):
            market_regime = self.get_market_regime(market="KOSPI")
        regime = (market_regime or {}).get("regime", "BULL")
        eff_settings = config.get_effective_strategy_settings(self.strategy.name, config.CURRENT_SETTINGS)
        eff_settings = config.get_effective_settings_for_regime(regime, eff_settings)

        executed = []
        max_holdings = int(eff_settings.get("max_holding_stocks", 5))
        max_daily_buy = int(eff_settings.get("max_daily_buy_count", 2))
        balance = self.api.get_account_balance()
        current_holding_count = len(balance.get("holdings", []))
        daily_new_buy_count = 0

        for item in buy_list:
            if current_holding_count >= max_holdings and not item.get("is_additional_buy"):
                continue
            if not item.get("is_additional_buy") and daily_new_buy_count >= max_daily_buy:
                self.logger.info(f"[{item.get('name')}] 1일 최대 신규 매수 제한({max_daily_buy}종목) 도달로 매수 보류")
                continue

            code = item.get("code")
            name = item.get("name")
            qty = int(item.get("recommended_qty", 0))

            if qty <= 0:
                continue

            try:
                self.logger.info(f"[{name}({code})] 15:18 종가 시장가 매수 발주 (수량: {qty}주)")
                res = self.api.order_stock(
                    code=code,
                    qty=qty,
                    buy_sell="매수",
                    order_type="01"
                )
                executed.append({"stock": item, "response": res})
                if res.get("rt_cd") == "0":
                    self.position_tracker.record_buy(
                        code=code,
                        name=name,
                        price=float(item.get("current_price", 0.0)),
                        qty=qty,
                        strategy=item.get("strategy_name", item.get("strategy", "momentum")),
                        strategy_display_name=item.get("strategy_display_name")
                    )
                if not item.get("is_additional_buy"):
                    current_holding_count += 1
                    daily_new_buy_count += 1
            except Exception as e:
                self.logger.error(f"[{name}({code})] 주문 집행 에러: {e}")

        return executed

    def _notify_sell_recommendations(self, sell_proposals: List[Dict[str, Any]]) -> None:
        """매도 추천 종목 텔레그램 알림 전송"""
        if not sell_proposals:
            return

        for sell_item in sell_proposals:
            try:
                notifier.send_sell_recommendation(
                    name=sell_item.get("name", ""),
                    code=sell_item.get("code", ""),
                    holding_qty=int(sell_item.get("holding_qty", 0)),
                    avg_buy_price=float(sell_item.get("avg_buy_price", 0)),
                    current_price=float(sell_item.get("current_price", 0)),
                    profit_rate=float(sell_item.get("profit_rate", 0)),
                    profit_loss=float(sell_item.get("profit_loss", 0)),
                    reasons=sell_item.get("reasons", []),
                    is_urgent=bool(sell_item.get("is_urgent", False)),
                    sell_type=sell_item.get("sell_type", "매도")
                )
            except Exception as e:
                self.logger.warning(f"[{sell_item.get('name')}] 텔레그램 매도 알림 전송 실패: {e}")

    def _notify_screening_summary(
        self,
        buy_list: List[Dict[str, Any]],
        sell_list: List[Dict[str, Any]],
        holdings_count: int,
        top_candidates: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        """스크리닝 요약 알림 전송"""
        try:
            notifier.send_daily_summary(
                buy_count=len(buy_list),
                sell_count=len(sell_list),
                holdings_count=holdings_count,
                buy_list=buy_list,
                sell_list=sell_list,
                top_candidates=top_candidates
            )
        except Exception as e:
            self.logger.warning(f"스크리닝 요약 알림 전송 실패: {e}")

    def save_proposals(self, data: dict) -> bool:
        ok = atomic_save_json(PROPOSALS_FILE, data)
        # fallback 백업 파일에도 저장
        try:
            atomic_save_json(PROPOSALS_FALLBACK_FILE, data)
        except Exception:
            pass

        try:
            from google_sheet_manager import get_sheet_manager
            sheet_mgr = get_sheet_manager()
            if sheet_mgr.is_connected:
                sheet_mgr.sync_proposals_state_to_sheet(data)
                sheet_mgr.sync_proposals_to_sheet(data)
        except Exception as e:
            self.logger.debug(f"Google Sheet Proposals 동기화 생략: {e}")
        return ok

    @staticmethod
    def load_proposals() -> Dict[str, Any]:
        data = safe_load_json(PROPOSALS_FILE, default={})
        
        # 1. 로컬 proposals.json 에 매수추천/최근추천/관망후보 데이터가 비어있는 경우 (Streamlit Cloud 재부팅 등)
        has_content = bool(data.get("buy_proposals") or data.get("last_recommended_proposals") or data.get("top_candidates"))
        if not has_content:
            try:
                from google_sheet_manager import get_sheet_manager
                sheet_mgr = get_sheet_manager()
                if sheet_mgr.is_connected:
                    sheet_data = sheet_mgr.read_proposals_state_from_sheet()
                    if sheet_data and (sheet_data.get("buy_proposals") or sheet_data.get("last_recommended_proposals") or sheet_data.get("top_candidates")):
                        data.update(sheet_data)
                        atomic_save_json(PROPOSALS_FILE, data)
                        logging.getLogger("Screener").info("Google Sheet로부터 스크리닝 상태(ProposalsState) 복원 완료")
            except Exception as e:
                logging.getLogger("Screener").debug(f"Google Sheet ProposalsState 복원 생략: {e}")

        # 2. 여전히 데이터가 비어있다면 git에 포함된 proposals_fallback.json에서 복원 시도
        if not bool(data.get("buy_proposals") or data.get("last_recommended_proposals") or data.get("top_candidates")):
            fallback = safe_load_json(PROPOSALS_FALLBACK_FILE, default={})
            if fallback:
                for k, v in fallback.items():
                    if k not in data or not data[k]:
                        data[k] = v
                atomic_save_json(PROPOSALS_FILE, data)

        # 기본 필드 구조 보장
        data.setdefault("generated_at", "-")
        data.setdefault("screening_type", "CLOSING_BUY_1515")
        data.setdefault("buy_proposals", [])
        data.setdefault("last_recommended_proposals", [])
        data.setdefault("last_recommended_at", "-")
        data.setdefault("top_candidates", [])
        data.setdefault("sell_proposals", [])
        data.setdefault("holdings_count", 0)
        data.setdefault("status", "READY" if (data.get("buy_proposals") or data.get("last_recommended_proposals") or data.get("top_candidates")) else "EMPTY")
        return data
