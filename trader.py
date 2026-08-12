"""
자동 매매 메인 코어 모듈 (trader.py)
KIS Open API, 매매 전략, 리스크 관리자를 통합하여 실시간 자동 매매 루프 실행
"""
import time
import logging
import datetime
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple

import config
from kis_api import KISApiClient
from strategy import StrategyFactory, Signal, InfiniteBuyingStrategy
from risk_manager import RiskManager
from infinite_state_manager import InfiniteStateManager


class TraderBot:
    """
    한국투자증권 KIS Open API 자동 매매 봇 메인 클래스
    """

    def __init__(self, api: Optional[KISApiClient] = None):
        self.api = api or KISApiClient()
        self.logger = logging.getLogger("TraderBot")

        # 무한매수 상태 관리자 로드
        self.infinite_state_mgr = InfiniteStateManager()
        self.infinite_enabled = getattr(config, "INFINITE_BUYING_ENABLED", False)
        self.infinite_stocks = getattr(config, "INFINITE_STOCKS", ["TQQQ", "SOXL"])
        self.infinite_strategy = InfiniteBuyingStrategy(
            division_count=getattr(config, "INFINITE_DIVISION_COUNT", 40),
            target_roi=getattr(config, "INFINITE_TARGET_ROI", 0.10)
        )

        # 설정 및 객체 로드
        self.target_symbols = getattr(config, "TARGET_STOCKS", self.infinite_stocks)
        self.strategy = StrategyFactory.create_strategy(
            getattr(config, "STRATEGY_NAME", "INFINITE_BUYING"),
            division_count=getattr(config, "INFINITE_DIVISION_COUNT", 40),
            target_roi=getattr(config, "INFINITE_TARGET_ROI", 0.10)
        )
        self.risk_mgr = RiskManager(
            stop_loss_ratio=getattr(config, "STOP_LOSS_RATIO", 0.03),
            take_profit_ratio=getattr(config, "TAKE_PROFIT_RATIO", 0.07),
            trailing_stop_ratio=getattr(config, "TRAILING_STOP_RATIO", 0.02),
            invest_ratio_per_stock=getattr(config, "INVEST_RATIO_PER_STOCK", 0.2),
            max_stocks_holding=getattr(config, "MAX_STOCKS_HOLDING", 5)
        )

        # 사용자 승인 모드 여부 (True: 제안 후 사용자 승인 주문, False: 즉시 자동 주문)
        self.require_approval = getattr(config, "REQUIRE_USER_APPROVAL", True)

        # 계좌 및 상태 데이터
        self.total_eval_amount = 0.0
        self.available_cash = 0.0
        self.available_usd_cash = 5000.0  # 외화(USD) 예수금
        self.exchange_rate = 1428.20       # 미국 원/달러 환율
        self.holdings: Dict[str, Dict[str, Any]] = {}  # {symbol: {qty, avg_price, current_price, pnl_rate}}
        self.current_prices: Dict[str, float] = {}

        # 승인 대기 중인 매매 제안 목록 {proposal_id: proposal_dict}
        self.pending_proposals: Dict[str, Dict[str, Any]] = {}

        self.is_running = False

    def initialize_account(self) -> bool:
        """계좌 및 KIS Open API 인증 검증"""
        mode_str = '모의투자(VTS)' if self.api.mock else '실전투자(LIVE)'
        approval_str = '반자동(사용자 승인 모드)' if self.require_approval else '완전자동 모드'
        self.logger.info(f"현재 설정: {mode_str} | 주문방식: {approval_str}")

        if config.MOCK_TRADING_ONLY and not self.api.mock:
            self.logger.critical("🚨 [경고] MOCK_TRADING_ONLY가 True로 설정되어 있으나 실전투자 서버로 설정되었습니다!")
            return False

        # Access Token 발급 시도 (실제 키가 있는 경우)
        if self.api.app_key and self.api.app_secret:
            token_ok = self.api.get_access_token()
            if not token_ok:
                self.logger.warning("Access Token 발급에 실패하였으나 시뮬레이션 데이터로 계속 진행합니다.")
        else:
            self.logger.info("AppKey/AppSecret 미설정: 시뮬레이션 모드로 작동합니다.")

        # 계좌 잔고 및 종목 시세 초기 조회
        self.fetch_account_balance()
        self.fetch_target_prices()
        return True

    def fetch_target_prices(self):
        """감시 대상 종목의 현재가 시세 수신"""
        for code in self.target_symbols:
            try:
                price_res = self.api.get_stock_price(code)
                if price_res.get("success"):
                    self.current_prices[code] = float(price_res["price"])
            except Exception as e:
                self.logger.error(f"[{code}] 현재가 조회 실패: {e}")

    def fetch_account_balance(self):
        """계좌 잔고, 국내 예수금 및 해외 외화(USD) 예수금 수신"""
        res = self.api.get_account_balance()
        if res.get("success"):
            self.available_cash = float(res.get("deposit", 0))
            self.total_eval_amount = float(res.get("total_asset", 0))
            
            holdings_list = res.get("holdings", [])
            new_holdings = {}
            for item in holdings_list:
                code = item["code"]
                new_holdings[code] = {
                    "name": item.get("name", f"종목_{code}"),
                    "qty": item["qty"],
                    "avg_price": item["avg_price"],
                    "current_price": item["current_price"],
                    "pnl_rate": item.get("pnl_rate", 0.0)
                }
            self.logger.info(f"[계좌잔고] 국내 보유 종목: {len(new_holdings)}개 | {list(new_holdings.keys())}")
            self.holdings = new_holdings
            
            # 해외 외화(USD) 예수금 및 환율 수신
            overseas_res = self.api.get_overseas_account_balance()
            if overseas_res.get("success"):
                self.available_usd_cash = float(overseas_res.get("usd_deposit", 5000.0))
                self.exchange_rate = float(overseas_res.get("exchange_rate", 1428.20))
                self.is_usd_simulated = overseas_res.get("is_simulated", True)
                self.logger.info(f"[계좌잔고] 외화예수금: ${self.available_usd_cash:,.2f} | 환율: {self.exchange_rate} | 시뮬레이션: {self.is_usd_simulated}")
            else:
                self.logger.warning(f"[계좌잔고] 외화예수금 조회 실패: {overseas_res.get('msg', 'Unknown')}")

            # 해외주식 보유 잔고 수신 및 통합
            overseas_stock_res = self.api.get_overseas_stock_balance()
            self.logger.info(f"[계좌잔고] 해외주식 잔고 API 응답: success={overseas_stock_res.get('success')}, 보유종목수={len(overseas_stock_res.get('holdings', []))}, is_simulated={overseas_stock_res.get('is_simulated')}, msg={overseas_stock_res.get('msg', '')}")
            if overseas_stock_res.get("success"):
                overseas_items = overseas_stock_res.get("holdings", [])
                self.logger.info(f"[계좌잔고] 해외주식 잔고 상세: {[(item.get('code'), item.get('name'), item.get('qty')) for item in overseas_items]}")
                for item in overseas_items:
                    code = item["code"]
                    new_holdings[code] = {
                        "name": item.get("name", f"해외_{code}"),
                        "qty": item["qty"],
                        "avg_price": item["avg_price"],
                        "current_price": item["current_price"],
                        "pnl_rate": item.get("pnl_rate", 0.0)
                    }
            else:
                self.logger.warning(f"[계좌잔고] 해외주식 잔고 조회 실패: {overseas_stock_res.get('msg', 'Unknown')}")

            # 해외주식 잔고 API가 빈 결과를 반환한 경우, 체결 이력에서 보유 수량/평단가 계산 (Fallback)
            overseas_holdings_count = sum(1 for c in new_holdings if self.api.is_overseas_symbol(c))
            self.logger.info(f"[계좌잔고] 통합 후 해외 보유 종목 수: {overseas_holdings_count}개 | 전체 종목: {list(new_holdings.keys())}")
            if overseas_holdings_count == 0:
                self.logger.warning("[계좌잔고] 해외 보유 종목이 0개입니다. 체결 이력 기반 Fallback을 시도합니다...")
                history_holdings = self._calculate_holdings_from_history()
                if history_holdings:
                    self.logger.info(f"📊 해외주식 잔고 API가 빈 결과를 반환하여 체결 이력에서 보유 수량/평단가를 계산합니다. ({len(history_holdings)}개 종목)")
                    for code, h_data in history_holdings.items():
                        new_holdings[code] = h_data
                else:
                    self.logger.warning("[계좌잔고] 체결 이력 기반 Fallback도 결과가 없습니다. (체결 이력이 없거나, 날짜 범위가 잘못되었을 수 있음)")

            # 체결기준 현물 잔고(TTTT1006R)를 추가 Fallback으로 사용
            # - 기존 잔고 API(TTTS3012R)와 체결 이력 기반 계산이 모두 실패/빈 결과일 때,
            #   체결기준 잔고 API로 실제 체결된 수량/단가를 조회하여 보유 종목을 보정한다.
            overseas_holdings_count = sum(1 for c in new_holdings if self.api.is_overseas_symbol(c))
            if overseas_holdings_count == 0:
                try:
                    today_str = time.strftime("%Y%m%d")
                    default_start = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
                    exec_balance_res = self.api.get_overseas_execution_balance(
                        symbol="",
                        start_date=default_start,
                        end_date=today_str,
                        cblc_dvsn="02"  # 체결(02) 기준으로 조회
                    )
                    if exec_balance_res.get("success"):
                        exec_items = exec_balance_res.get("holdings", [])
                        if exec_items:
                            self.logger.info(f"📊 체결기준 잔고(TTTT1006R)에서 보유 종목 {len(exec_items)}개 조회 성공")
                            for item in exec_items:
                                code = item["code"]
                                new_holdings[code] = {
                                    "name": item.get("name", f"해외_{code}"),
                                    "qty": item.get("qty", item.get("executed_qty", 0)),
                                    "avg_price": item.get("avg_price", item.get("executed_price", 0.0)),
                                    "current_price": item.get("current_price", 0.0),
                                    "pnl_rate": item.get("pnl_rate", 0.0)
                                }
                        else:
                            self.logger.warning("[계좌잔고] 체결기준 잔고(TTTT1006R)도 보유 종목이 0개입니다.")
                    else:
                        self.logger.warning(f"[계좌잔고] 체결기준 잔고(TTTT1006R) 조회 실패: {exec_balance_res.get('msg', 'Unknown')}")
                except Exception as e:
                    self.logger.warning(f"[계좌잔고] 체결기준 잔고(TTTT1006R) 조회 예외: {e}")

            self.holdings = new_holdings

            sim_str = " (시뮬레이션)" if getattr(self, "is_usd_simulated", True) else " (실제 조회)"
            ovrs_hldg_cnt = sum(1 for c in self.holdings if self.api.is_overseas_symbol(c))
            self.logger.info(f"[계좌잔고] 원화예수금: ₩{self.available_cash:,.0f} | 외화예수금: ${self.available_usd_cash:,.2f}{sim_str} | 해외보유종목: {ovrs_hldg_cnt}개 | 총자산: ₩{self.total_eval_amount:,.0f}")
            self.logger.info(f"[계좌잔고] 최종 보유 종목 상세: {[(k, v.get('qty'), v.get('avg_price')) for k, v in self.holdings.items()]}")
        else:
            self.logger.error(f"계좌 잔고 조회 실패: {res.get('msg')}")
    def _calculate_holdings_from_history(self) -> Dict[str, Dict[str, Any]]:
        """
        해외주식 체결 이력에서 보유 수량/평단가를 계산 (잔고 API가 빈 결과일 때 Fallback)
        - 매수 체결 수량은 더하고, 매도 체결 수량은 빼서 현재 보유 수량 계산
        - 평단가는 매수 체결 금액 합계 / 매수 체결 수량 합계로 계산
        """
        result: Dict[str, Dict[str, Any]] = {}
        try:
            self.logger.info(f"[체결이력] 체결 이력 조회 시작: infinite_stocks={self.infinite_stocks}")
            history = []
            for sym in self.infinite_stocks:
                st = self.infinite_state_mgr.get_symbol_state(sym)
                sd = st.get("start_date", "")
                sym_start_date = sd.replace("-", "") if (sd and sd.replace("-", "").isdigit()) else ""
                # NOTE: 상태의 start_date가 없거나 오늘 날짜면, 최소 30일 전부터 조회하여 과거 이력 누락을 방지한다.
                default_start = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
                if sym_start_date and sym_start_date.isdigit():
                    sym_start_date = min(sym_start_date, default_start)  # 더 과거(작은 값)를 선택
                else:
                    sym_start_date = default_start
                sym_history = self.api.get_overseas_execution_history(symbol=sym, start_date=sym_start_date)
                self.logger.info(f"[체결이력] {sym} 조회 결과 (start_date={sym_start_date}): {len(sym_history)}건")
                history.extend(sym_history)
            self.logger.info(f"[체결이력] 체결 이력 조회 결과: {len(history)}건")
            if not history:
                self.logger.warning("[체결이력] 체결 이력이 비어 있습니다. (조회 기간 내 체결 내역이 없거나, API 오류일 수 있음)")
                return result

            # 체결 이력 샘플 로깅 (첫 5건)
            for i, h in enumerate(history[:5]):
                self.logger.info(f"[체결이력] 샘플 #{i+1}: {h}")

            # 종목별 매수/매도 집계
            buy_qty: Dict[str, int] = {}
            buy_amount: Dict[str, float] = {}
            sell_qty: Dict[str, int] = {}
            names: Dict[str, str] = {}

            for h in history:
                symbol = h.get("symbol", "").strip().upper()
                if not symbol or not self.api.is_overseas_symbol(symbol):
                    self.logger.info(f"[체결이력] 해외 종목 아님으로 스킵: symbol={symbol}, raw_symbol={h.get('symbol')}")
                    continue
                order_type = h.get("order_type", "")
                executed_qty = h.get("executed_qty", 0) or 0
                executed_price = h.get("executed_price", 0.0) or 0.0
                status = h.get("status", "")

                self.logger.info(f"[체결이력] 처리: symbol={symbol}, order_type={order_type}, executed_qty={executed_qty}, executed_price={executed_price}, status={status}")

                # 체결된 건만 집계 (미체결/취소 제외)
                if "체결" not in status and "완료" not in status:
                    self.logger.info(f"[체결이력] 체결/완료 상태 아님으로 스킵: status={status}")
                    continue

                if "매수" in order_type:
                    buy_qty[symbol] = buy_qty.get(symbol, 0) + executed_qty
                    buy_amount[symbol] = buy_amount.get(symbol, 0.0) + (executed_qty * executed_price)
                    names.setdefault(symbol, f"해외_{symbol}")
                    self.logger.info(f"[체결이력] 매수 집계: {symbol} 누적수량={buy_qty[symbol]}, 누적금액={buy_amount[symbol]}")
                elif "매도" in order_type:
                    sell_qty[symbol] = sell_qty.get(symbol, 0) + executed_qty
                    self.logger.info(f"[체결이력] 매도 집계: {symbol} 누적수량={sell_qty[symbol]}")
                else:
                    self.logger.info(f"[체결이력] 매수/매도 아님으로 스킵: order_type={order_type}")

            self.logger.info(f"[체결이력] 집계 결과: 매수종목={list(buy_qty.keys())}, 매도종목={list(sell_qty.keys())}")

            for symbol in set(list(buy_qty.keys()) + list(sell_qty.keys())):
                net_qty = buy_qty.get(symbol, 0) - sell_qty.get(symbol, 0)
                if net_qty <= 0:
                    self.logger.info(f"[체결이력] 순수량 0 이하로 스킵: {symbol} net_qty={net_qty}")
                    continue
                avg_price = buy_amount.get(symbol, 0.0) / buy_qty.get(symbol, 1) if buy_qty.get(symbol, 0) > 0 else 0.0
                result[symbol] = {
                    "name": names.get(symbol, f"해외_{symbol}"),
                    "qty": net_qty,
                    "avg_price": round(avg_price, 2),
                    "current_price": self.current_prices.get(symbol, 0.0),
                    "pnl_rate": 0.0
                }
                self.logger.info(f"[체결이력] 최종 계산: {symbol} net_qty={net_qty}, avg_price={round(avg_price, 2)}")

            if result:
                summary_str = ", ".join([f"{s}({d['qty']}주)" for s, d in result.items()])
                self.logger.info(f"📊 체결 이력 기반 보유 종목 계산 완료: {summary_str}")
            else:
                self.logger.warning("[체결이력] 체결 이력이 있지만 계산 결과가 없습니다. (모든 종목이 매도되었거나, 상태/타입 필터링 문제일 수 있음)")
        except Exception as e:
            self.logger.warning(f"체결 이력 기반 보유 종목 계산 실패: {e}")
        return result


    def sync_holdings_to_state(self):
        """
        실시간 계좌 보유 종목 수량/평단가를 갱신하고 Google Sheets에 동기화
        - 보유 수량/평단가는 KIS API가 Source of Truth이므로 JSON에는 기록하지 않음
        - Google Sheets 'Holdings' 워크시트에 주식평가 금액 동기화
        - Google Sheets 'ExecutionHistory' 워크시트에 체결/실패 이력 동기화 (TTTT1006R 체결기준)
        - Google Sheets 'ExecutionBalance' 워크시트에 체결기준 현물 잔고 동기화 (TTTT1006R)
        """
        self.fetch_account_balance()
        self.logger.info("🔄 실계좌 보유 종목 수량/평단가를 API에서 갱신 완료 (JSON에는 전략 상태만 기록)")

        # Google Sheets에 보유 종목 평가 금액 및 체결 이력 동기화 (KIS API 실계좌 데이터)
        if hasattr(self, "infinite_state_mgr") and self.infinite_state_mgr:
            gss = getattr(self.infinite_state_mgr, "gss_mgr", None)
            if gss and gss.is_connected:
                try:
                    gss.sync_holdings(self.holdings, self.current_prices)

                    # 1. 체결/실패 이력 동기화 (TTTT1006R/VTTT1006R 체결기준)
                    # NOTE: TTTS3035R/JTTT3001R 대신 TTTT1006R(체결기준 현물 잔고)을 사용하여
                    #       체결수량/체결단가가 정확히 반영된 데이터를 Google Sheets에 기록한다.
                    today_str = time.strftime("%Y%m%d")
                    default_start = (datetime.date.today() - datetime.timedelta(days=30)).strftime("%Y%m%d")
                    exec_balance = self.api.get_overseas_execution_balance(
                        symbol="",
                        start_date=default_start,
                        end_date=today_str,
                        cblc_dvsn="02"  # 체결(02) 기준으로 조회
                    )
                    if exec_balance.get("success"):
                        exec_holdings = exec_balance.get("holdings", [])
                        self.logger.info(f"[체결기준] TTTT1006R 조회 성공: {len(exec_holdings)}개 종목")
                        # ExecutionHistory 워크시트에 체결기준 데이터 동기화
                        gss.sync_execution_history(exec_holdings)
                        # ExecutionBalance 워크시트에도 동일 데이터 동기화
                        gss.sync_execution_balance(exec_holdings)
                        self.logger.info(f"📊 Google Sheet 'ExecutionHistory'/'ExecutionBalance' 동기화 완료 (체결기준 {len(exec_holdings)}개 종목)")
                    else:
                        self.logger.warning(f"[체결기준] TTTT1006R 조회 실패: {exec_balance.get('msg', 'Unknown')}")

                    self.logger.info("📊 Google Sheet 'Holdings'/'ExecutionHistory'/'ExecutionBalance' 동기화 완료 (KIS API 실계좌)")
                except Exception as e:
                    self.logger.warning(f"Google Sheet Holdings/ExecutionHistory/ExecutionBalance 동기화 예외: {e}")

    def start_infinite_buying(self, symbol: str):
        """특정 종목의 무한매수 수동 시작"""
        self.infinite_state_mgr.start_buying(symbol)
        self.run_infinite_buying_cycle()

    def stop_infinite_buying(self, symbol: str):
        """특정 종목의 무한매수 강제 중지"""
        self.infinite_state_mgr.stop_buying(symbol)

    def create_proposal(
        self,
        symbol: str,
        action: str,  # "BUY" or "SELL"
        qty: int,
        price: float,
        reason: str
    ):
        """매매 제안 생성 (사용자 승인 대기 목록에 추가)"""
        proposal_id = f"{symbol}_{action}"
        stock_name = self.holdings.get(symbol, {}).get("name", f"종목_{symbol}")
        action_kr = "매수" if action == "BUY" else "매도"

        if proposal_id in self.pending_proposals:
            # 이미 동일한 제안이 대기 중이면 현재가/예상금액만 최신화
            self.pending_proposals[proposal_id]["price"] = price
            self.pending_proposals[proposal_id]["total_price"] = price * qty
            return

        proposal = {
            "id": proposal_id,
            "symbol": symbol,
            "stock_name": stock_name,
            "action": action,
            "action_kr": action_kr,
            "qty": qty,
            "price": price,
            "total_price": price * qty,
            "reason": reason,
            "timestamp": time.strftime("%H:%M:%S")
        }
        self.pending_proposals[proposal_id] = proposal
        self.logger.info(f"💡 [{symbol} {stock_name}] {action_kr} 제안 생성! (수량: {qty}주, 이유: {reason}) -> 승인 대기 중...")

    def _check_and_log_apbk1681_guidance(self, symbol: str, err_msg: str):
        """APBK1681 (기본예탁금 / 레버리지 ETF 이수 미충족) 에러 발생 시 상세 조치 방법 안내"""
        if "APBK1681" in err_msg or "기본예탁금" in err_msg:
            self.logger.warning(
                f"💡 [원인 및 조치 안내] [{symbol}] 종목은 한국투자증권 '기본예탁금 충족' 및 '레버리지 ETF 사전교육'이 등록된 계좌만 매수 가능합니다.\n"
                f"   1) 금융투자교육원(https://www.kifin.or.kr)에서 '레버리지 ETF/ETN 사전교육' 이수\n"
                f"   2) 한국투자증권 앱(MTS) > 메뉴 > 안내/신청 > '레버리지ETF 교육이수 등록'\n"
                f"   3) 한국투자증권 앱(MTS) > 메뉴 > 안내/신청 > '해외주식 레버리지 ETF 매매신청 / 기본예탁금 등록'"
            )

    def approve_proposal(self, proposal_id: str) -> bool:
        """사용자가 매매 제안을 승인했을 때 실제 주문 실행"""
        if proposal_id not in self.pending_proposals:
            self.logger.warning(f"존재하지 않는 제안 ID입니다: {proposal_id}")
            return False

        if self.risk_mgr.is_circuit_broken():
            self.logger.error(f"🚨 서킷브레이커 발동 중 (연속 에러 {self.risk_mgr.consecutive_errors}/{self.risk_mgr.max_consecutive_errors}): 매매 승인을 진행하지 않습니다.")
            self.pending_proposals.pop(proposal_id, None)
            return False

        # 제안을 대기 목록에서 즉시 제거하여 중복 실행 및 재시도 폭주 방지
        prop = self.pending_proposals.pop(proposal_id)
        symbol = prop["symbol"]
        action = prop["action"]
        qty = prop["qty"]
        price = prop.get("price", 0.0)
        ord_type = prop.get("ord_type", "00")
        is_buy = (action == "BUY")

        # 전량 매도 시 수량 불일치 자동 안전 보정
        if not is_buy and symbol in self.holdings:
            actual_held_qty = int(self.holdings[symbol].get("qty", 0))
            if actual_held_qty > 0 and actual_held_qty != qty:
                self.logger.warning(
                    f"⚠️ [{symbol}] 전량 익절 매도 수량 불일치 감지! "
                    f"제안 수량: {qty}주 vs 증권사 계좌 실제: {actual_held_qty}주. "
                    f"주문 거부(APBK0013) 방지를 위해 계좌 수량({actual_held_qty}주)으로 자동 조정합니다."
                )
                qty = actual_held_qty

        self.logger.info(f"✅ [{symbol}] 사용자가 매매 제안을 승인하였습니다! {prop['action_kr']} 주문을 전송합니다 ({qty}주)")

        if self.api.is_overseas_symbol(symbol):
            order_res = self.api.order_overseas_cash(symbol, qty, price=price, buy=is_buy, ord_type=ord_type)
            if order_res.get("success"):
                round_inc = prop.get("round_inc", 1.0)
                if is_buy:
                    # 매수 주문 접수/체결 시 진행 회차 증가 (전략 상태만 JSON/구글 시트에 기록)
                    self.infinite_state_mgr.advance_round(symbol, round_inc=round_inc)
                else:
                    # 전량 익절 매도 시 회차 리셋
                    self.infinite_state_mgr.complete_round(symbol)
                self.risk_mgr.reset_error()
                self.logger.info(f"🎉 [{symbol}] 해외주식 무한매수 {prop['action_kr']} 주문 성공!")
                self.fetch_account_balance()
                self.sync_holdings_to_state()
                return True
            else:
                err_msg = order_res.get('msg', '')
                self.logger.error(f"❌ [{symbol}] 해외주식 주문 실행 실패: {err_msg}")
                self._check_and_log_apbk1681_guidance(symbol, err_msg)
                self.risk_mgr.record_error()
                return False
        else:
            order_res = self.api.order_cash(symbol, qty, price=0, buy=is_buy)
            if order_res.get("success"):
                if not is_buy:
                    self.risk_mgr.reset_highest_price(symbol)
                self.risk_mgr.reset_error()
                self.logger.info(f"🎉 [{symbol}] {prop['action_kr']} 주문 체결 완료!")
                self.fetch_account_balance()
                self.sync_holdings_to_state()
                return True
            else:
                err_msg = order_res.get('msg', '')
                self.logger.error(f"❌ [{symbol}] {prop['action_kr']} 주문 실행 실패: {err_msg}")
                self._check_and_log_apbk1681_guidance(symbol, err_msg)
                self.risk_mgr.record_error()
                return False

    def reject_proposal(self, proposal_id: str):
        """사용자가 매매 제안을 거절했을 때 제거"""
        if proposal_id in self.pending_proposals:
            prop = self.pending_proposals.pop(proposal_id)
            self.logger.info(f"❌ [{prop['symbol']}] {prop['action_kr']} 제안이 사용자에 의해 거절되었습니다.")

    def run_infinite_buying_cycle(self):
        """
        라오어 무한매수법 전용 트레이딩 사이클
        - 미국 주식 대상 종목별 상태 조회 및 당일 LOC/지정가 주문 제안 생성/전송
        """
        if not self.infinite_enabled:
            return

        if self.risk_mgr.is_circuit_broken():
            self.logger.error("🚨 서킷브레이커 발동 상태입니다. 무한매수 루틴 진행 중단.")
            return

        self.logger.info("🇺🇸 [무한매수법] 당일 주문 생성 및 감시 루틴 실행")
        today_str = time.strftime("%Y-%m-%d")

        for symbol in self.infinite_stocks:
            try:
                price_res = self.api.get_stock_price(symbol)
                if not price_res.get("success"):
                    self.logger.warning(f"[{symbol}] 현재가 시세 조회 실패")
                    continue

                cur_price = float(price_res["price"])
                state = self.infinite_state_mgr.get_symbol_state(
                    symbol,
                    default_budget_usd=getattr(config, "INFINITE_TOTAL_BUDGET_USD", 10000.0),
                    division_count=getattr(config, "INFINITE_DIVISION_COUNT", 40),
                    target_roi=getattr(config, "INFINITE_TARGET_ROI", 0.10)
                )

                curr_round = state.get("current_round", 0)
                div_count = state.get("division_count", 40)

                # 보유 수량/평단가는 KIS API(실계좌)가 Source of Truth
                # self.holdings는 fetch_account_balance()에서 API로 갱신됨
                actual_held_qty = int(self.holdings.get(symbol, {}).get("qty", 0))
                actual_avg_p = float(self.holdings.get(symbol, {}).get("avg_price", 0.0))

                tot_qty = actual_held_qty
                avg_p = actual_avg_p
                avg_p_str = f"${avg_p:.2f}" if avg_p > 0 else "미보유(-)"

                self.logger.info(
                    f"📊 [{symbol} 무한매수 상태] 진행 회차: {curr_round}/{div_count}회차 | "
                    f"누적 수량: {tot_qty}주 | 평단가: {avg_p_str} | 현재가: ${cur_price:.2f}"
                )

                # 보유 수량/평단가는 KIS API 실계좌가 Source of Truth (JSON에는 저장하지 않음)
                orders = self.infinite_strategy.generate_daily_orders(
                    symbol, cur_price, state,
                    avg_price=actual_avg_p, total_qty=actual_held_qty
                )
                orders_sent = False

                for order in orders:
                    action = order["action"]
                    qty = order["qty"]
                    price = order["price"]
                    ord_type = order["ord_type"]
                    desc = order["desc"]
                    round_inc = order.get("round_inc", 1.0)

                    # 전량 익절 매도 시 실시간 계좌 수량과 자동 맞춰서 수량 불일치 오류 방지
                    if action == "SELL":
                        actual_held_qty = int(self.holdings.get(symbol, {}).get("qty", 0))
                        if actual_held_qty > 0 and qty != actual_held_qty:
                            self.logger.warning(
                                f"⚠️ [{symbol}] 전량 매도 수량 맞춤 보정! 주문 제안: {qty}주 -> 실시간 계좌 보유: {actual_held_qty}주"
                            )
                            qty = actual_held_qty
                            order["qty"] = qty

                    total_ord_amt = qty * price
                    proposal_id = f"INFINITE_{symbol}_{action}_{ord_type}_{price:.2f}"

                    if self.require_approval:
                        if proposal_id not in self.pending_proposals:
                            self.pending_proposals[proposal_id] = {
                                "id": proposal_id,
                                "symbol": symbol,
                                "stock_name": f"{symbol} (무한매수)",
                                "action": action,
                                "action_kr": "LOC 매수" if ord_type == "34" else ("매수" if action == "BUY" else "익절 매도"),
                                "qty": qty,
                                "price": price,
                                "total_price": total_ord_amt,
                                "ord_type": ord_type,
                                "round_inc": round_inc,
                                "reason": desc,
                                "timestamp": time.strftime("%H:%M:%S")
                            }
                            self.logger.info(
                                f"💡 [무한매수 제안] {symbol} {desc} (수량: {qty}주, 단가: ${price:.2f}, 총액: ${total_ord_amt:,.2f}) -> 승인 대기 중"
                            )
                    else:
                        if self.risk_mgr.is_circuit_broken():
                            self.logger.error(f"🚨 서킷브레이커 발동 중: {symbol} 무한매수 자동실행을 중단합니다.")
                            break
                        is_buy = (action == "BUY")
                        action_kr = "LOC 매수" if ord_type == "34" else ("매수" if is_buy else "익절 매도")
                        self.logger.info(
                            f"🚀 [무한매수 자동실행] {symbol} {action_kr} {qty}주 @ ${price:.2f} (주문예상총액: ${total_ord_amt:,.2f}) | {desc}"
                        )
                        order_res = self.api.order_overseas_cash(symbol, qty, price=price, buy=is_buy, ord_type=ord_type)
                        if order_res.get("success"):
                            orders_sent = True
                            if is_buy:
                                # 매수 주문 접수/체결 시 진행 회차 증가 (전략 상태만 JSON/구글 시트에 기록)
                                self.infinite_state_mgr.advance_round(symbol, round_inc=round_inc)
                            else:
                                # 전량 익절 매도 시 회차 리셋
                                self.infinite_state_mgr.complete_round(symbol)
                                self.logger.info(
                                    f"🎉 [{symbol}] 해외주식 익절 매도 주문 접수 성공! "
                                    f"(매도수량: {qty}주, 목표가: ${price:.2f}, 예상총액: ${total_ord_amt:,.2f})"
                                )
                            self.risk_mgr.reset_error()
                        else:
                            err_msg = order_res.get('msg', '')
                            self.logger.error(f"❌ [{symbol}] 해외주식 무한매수 {action_kr} 주문 실패: {err_msg}")
                            self._check_and_log_apbk1681_guidance(symbol, err_msg)
                            self.risk_mgr.record_error()

                # 주문 실행 후 Google Sheets에 보유/체결 이력 동기화
                if orders_sent:
                    self.sync_holdings_to_state()
            except Exception as e:
                self.logger.error(f"[{symbol}] 무한매수 루틴 실행 예외: {e}")


    def run_trading_cycle(self):
        """
        라오어 무한매수법 전담 트레이딩 사이클 실행
        - 계좌 잔고/외화 예수금 갱신 및 미국 주식 무한매수 루틴 실행
        """
        if self.risk_mgr.is_circuit_broken():
            self.logger.error("서킷브레이커 발동 상태입니다. 매매 진행 중단.")
            return

        # 계좌 잔고 및 외화 예수금 갱신
        self.fetch_account_balance()

        # Google Sheets에 보유 종목 평가 금액 및 체결 이력 동기화 (KIS API 실계좌)
        self.sync_holdings_to_state()

        # 라오어 무한매수법 전담 감시 및 주문 제안 생성
        if self.infinite_enabled:
            self.run_infinite_buying_cycle()
