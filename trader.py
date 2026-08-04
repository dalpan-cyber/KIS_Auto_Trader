"""
자동 매매 메인 코어 모듈 (trader.py)
KIS Open API, 매매 전략, 리스크 관리자를 통합하여 실시간 자동 매매 루프 실행
"""
import time
import logging
import pandas as pd
from typing import Dict, List, Any, Optional, Tuple

import config
from kis_api import KISApiClient
from strategy import StrategyFactory, Signal
from risk_manager import RiskManager


class TraderBot:
    """
    한국투자증권 KIS Open API 자동 매매 봇 메인 클래스
    """

    def __init__(self, api: Optional[KISApiClient] = None):
        self.api = api or KISApiClient()
        self.logger = logging.getLogger("TraderBot")

        # 설정 및 객체 로드
        self.target_symbols = config.TARGET_STOCKS
        self.strategy = StrategyFactory.create_strategy(
            config.STRATEGY_NAME,
            short_period=config.SHORT_MA_PERIOD,
            long_period=config.LONG_MA_PERIOD,
            k=config.K_VALUE
        )
        self.risk_mgr = RiskManager(
            stop_loss_ratio=config.STOP_LOSS_RATIO,
            take_profit_ratio=config.TAKE_PROFIT_RATIO,
            trailing_stop_ratio=config.TRAILING_STOP_RATIO,
            invest_ratio_per_stock=config.INVEST_RATIO_PER_STOCK,
            max_stocks_holding=config.MAX_STOCKS_HOLDING
        )

        # 사용자 승인 모드 여부 (True: 제안 후 사용자 승인 주문, False: 즉시 자동 주문)
        self.require_approval = getattr(config, "REQUIRE_USER_APPROVAL", True)

        # 계좌 및 상태 데이터
        self.total_eval_amount = 0.0
        self.available_cash = 0.0
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
        """계좌 잔고 및 보유 종목 수신"""
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
            self.holdings = new_holdings
            self.logger.info(f"[계좌잔고] 예수금: {self.available_cash:,.0f}원 | 총 자산: {self.total_eval_amount:,.0f}원 | 보유종목: {len(self.holdings)}개")
        else:
            self.logger.error(f"계좌 잔고 조회 실패: {res.get('msg')}")

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

    def approve_proposal(self, proposal_id: str) -> bool:
        """사용자가 매매 제안을 승인했을 때 실제 주문 실행"""
        if proposal_id not in self.pending_proposals:
            self.logger.warning(f"존재하지 않는 제안 ID입니다: {proposal_id}")
            return False

        prop = self.pending_proposals[proposal_id]
        symbol = prop["symbol"]
        action = prop["action"]
        qty = prop["qty"]
        is_buy = (action == "BUY")

        self.logger.info(f"✅ [{symbol}] 사용자가 매매 제안을 승인하였습니다! {prop['action_kr']} 주문을 전송합니다 ({qty}주)")
        order_res = self.api.order_cash(symbol, qty, price=0, buy=is_buy)
        
        if order_res.get("success"):
            if not is_buy:
                self.risk_mgr.reset_highest_price(symbol)
            self.risk_mgr.reset_error()
            del self.pending_proposals[proposal_id]
            self.logger.info(f"🎉 [{symbol}] {prop['action_kr']} 주문 체결 완료!")
            # 주문 실행 후 잔고 즉시 갱신
            self.fetch_account_balance()
            return True
        else:
            self.logger.error(f"❌ [{symbol}] {prop['action_kr']} 주문 실행 실패: {order_res.get('msg')}")
            self.risk_mgr.record_error()
            return False

    def reject_proposal(self, proposal_id: str):
        """사용자가 매매 제안을 거절했을 때 제거"""
        if proposal_id in self.pending_proposals:
            prop = self.pending_proposals.pop(proposal_id)
            self.logger.info(f"❌ [{prop['symbol']}] {prop['action_kr']} 제안이 사용자에 의해 거절되었습니다.")

    def run_trading_cycle(self):
        """
        단일 트레이딩 사이클 실행
        - 보유 종목 잔고 및 현재가 모니터링
        - 리스크 관리 / 매매 전략 감시
        - require_approval 설정에 따라 (승인 대기 제안 생성 vs 즉시 주문)
        """
        if self.risk_mgr.is_circuit_broken():
            self.logger.error("서킷브레이커 발동 상태입니다. 매매 진행 중단.")
            return

        # 1. 잔고 및 보유 정보 갱신
        self.fetch_account_balance()

        # 2. 대상 종목별 시세 조회 및 신호 감시
        for symbol in self.target_symbols:
            try:
                # 현재가 조회
                price_res = self.api.get_stock_price(symbol)
                if not price_res.get("success"):
                    continue

                cur_price = float(price_res["price"])
                self.current_prices[symbol] = cur_price
                self.logger.debug(f"[{symbol}] 현재가: {cur_price:,.0f}원")

                # A. 보유 종목 리스크 검사 (손절/익절/트레일링스탑)
                if symbol in self.holdings:
                    holding_info = self.holdings[symbol]
                    qty = holding_info["qty"]
                    avg_price = holding_info["avg_price"]

                    should_sell, reason = self.risk_mgr.evaluate_holding_risk(symbol, cur_price, avg_price)
                    if should_sell and qty > 0:
                        if self.require_approval:
                            self.create_proposal(symbol, "SELL", qty, cur_price, reason)
                        else:
                            self.logger.info(f"🚨 [{symbol}] 리스크 관리 자동 매도 실행! 사유: {reason}")
                            order_res = self.api.order_cash(symbol, qty, price=0, buy=False)
                            if order_res.get("success"):
                                self.risk_mgr.reset_highest_price(symbol)
                                self.risk_mgr.reset_error()
                            else:
                                self.risk_mgr.record_error()
                        continue  # 리스크 매도/제안 처리한 종목은 이번 루프 신호검사 건너뜀

                # B. 일봉 데이터 조회 및 전략 신호 검사
                daily_list = self.api.get_daily_chart(symbol, period="D", count=30)
                if not daily_list:
                    continue

                df_daily = pd.DataFrame(daily_list)
                holding_qty = self.holdings.get(symbol, {}).get("qty", 0)

                signal = self.strategy.generate_signal(symbol, cur_price, df_daily, holding_qty)

                # C. 매수 신호 처리
                if signal == Signal.BUY:
                    qty_to_buy = self.risk_mgr.calculate_buy_quantity(
                        symbol, cur_price, self.total_eval_amount, self.available_cash, len(self.holdings)
                    )
                    if qty_to_buy > 0:
                        reason_str = f"{self.strategy.name} 전략 매수 신호(골든크로스/돌파)"
                        if self.require_approval:
                            self.create_proposal(symbol, "BUY", qty_to_buy, cur_price, reason_str)
                        else:
                            self.logger.info(f"🛒 [{symbol}] 매수 신호 포착! {qty_to_buy}주 시장가 매수 주문 전송")
                            order_res = self.api.order_cash(symbol, qty_to_buy, price=0, buy=True)
                            if order_res.get("success"):
                                self.risk_mgr.reset_error()
                            else:
                                self.risk_mgr.record_error()

                # D. 전략 매도 신호 처리
                elif signal == Signal.SELL and holding_qty > 0:
                    reason_str = f"{self.strategy.name} 전략 매도 신호(데드크로스)"
                    if self.require_approval:
                        self.create_proposal(symbol, "SELL", holding_qty, cur_price, reason_str)
                    else:
                        self.logger.info(f"💰 [{symbol}] 전략 매도 신호 포착! {holding_qty}주 시장가 매도 주문 전송")
                        order_res = self.api.order_cash(symbol, holding_qty, price=0, buy=False)
                        if order_res.get("success"):
                            self.risk_mgr.reset_highest_price(symbol)
                            self.risk_mgr.reset_error()
                        else:
                            self.risk_mgr.record_error()

            except Exception as e:
                self.logger.error(f"[{symbol}] 매매 루틴 실행 중 예외 발생: {e}", exc_info=True)
                self.risk_mgr.record_error()
