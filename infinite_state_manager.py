import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional

from google_sheet_manager import GoogleSheetManager

logger = logging.getLogger("InfiniteStateManager")

DEFAULT_STATE_FILE = "infinite_trader_state.json"

class InfiniteStateManager:
    """무한매수법 상태 영속성 관리 클래스 (로컬 JSON + Google Sheets 동기화)"""

    def __init__(self, file_path: str = DEFAULT_STATE_FILE):
        self.file_path = file_path
        self.states: Dict[str, Dict[str, Any]] = {}
        self.gss_mgr = GoogleSheetManager()
        self.load_state()

    def load_state(self) -> Dict[str, Dict[str, Any]]:
        """로컬 JSON 파일에서 무한매수 상태 로드"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    self.states = json.load(f)
                logger.info(f"무한매수 상태 파일 로드 완료 ({len(self.states)}개 종목)")
            except Exception as e:
                logger.error(f"무한매수 상태 파일 로드 실패: {e}")
                self.states = {}
        else:
            self.states = {}
        return self.states

    def save_state(self):
        """현재 무한매수 상태를 로컬 JSON 파일 및 Google Sheets로 저장"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.states, f, ensure_ascii=False, indent=2)
            logger.debug("무한매수 상태 파일 저장 완료")
        except Exception as e:
            logger.error(f"무한매수 상태 파일 저장 실패: {e}")

        # Google Sheets 상의 전체 종목 상태 동기화
        if hasattr(self, "gss_mgr") and self.gss_mgr:
            self.gss_mgr.sync_all_states(self.states)

    def get_symbol_state(
        self,
        symbol: str,
        default_budget_usd: float = 10000.0,
        division_count: int = 40,
        target_roi: float = 0.10
    ) -> Dict[str, Any]:
        """
        종목별 상태 조회 (없으면 기본값 생성)
        """
        symbol_upper = symbol.upper()
        if symbol_upper not in self.states:
            self.states[symbol_upper] = {
                "symbol": symbol_upper,
                "total_budget_usd": default_budget_usd,
                "division_count": division_count,
                "current_round": 0,
                "avg_price": 0.0,
                "total_qty": 0,
                "target_roi": target_roi,
                "status": "IDLE",  # IDLE, BUYING, COMPLETED, PAUSED_MAX
                "history": []
            }
            self.save_state()
        return self.states[symbol_upper]

    def update_budget(self, symbol: str, total_budget_usd: float):
        """총 예산 업데이트"""
        state = self.get_symbol_state(symbol)
        state["total_budget_usd"] = total_budget_usd
        self.save_state()

    def update_last_order_date(self, symbol: str, date_str: str):
        """당일 주문 전송 날짜 기록 (중복 주문 발주 방지용)"""
        state = self.get_symbol_state(symbol)
        state["last_order_date"] = date_str
        self.save_state()

    def record_buy_execution(self, symbol: str, qty: int, price: float, round_inc: float = 1.0):
        """
        매수 체결 기록 및 평단가/회차/누적수량 갱신 (JSON + Google Sheet)
        """
        state = self.get_symbol_state(symbol)
        if qty <= 0 or price <= 0:
            return

        old_qty = state["total_qty"]
        old_avg = state["avg_price"]
        new_qty = old_qty + qty

        # 이동평균 매수단가 계산
        new_avg = ((old_qty * old_avg) + (qty * price)) / new_qty
        state["total_qty"] = new_qty
        state["avg_price"] = round(new_avg, 4)
        state["current_round"] = min(state["division_count"], state["current_round"] + round_inc)
        state["status"] = "BUYING"

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_item = {
            "date": now_str,
            "type": "BUY",
            "status_label": "🟢 매수 체결 완료",
            "qty": qty,
            "price": price,
            "round": state["current_round"],
            "avg_price": state["avg_price"],
            "total_qty": state["total_qty"],
            "note": "매수 체결 성공"
        }
        state["history"].append(history_item)

        tot_ord_amt = qty * price
        logger.info(
            f"✅ [{symbol}] 무한매수 체결 기록: +{qty}주 @ ${price:.2f} (주문금액: ${tot_ord_amt:,.2f}) | "
            f"진행 회차: {state['current_round']}/{state['division_count']}회차 | "
            f"누적 수량: {state['total_qty']}주 | 평단가: ${state['avg_price']:.2f}"
        )
        self.save_state()

        if hasattr(self, "gss_mgr") and self.gss_mgr:
            self.gss_mgr.append_history_entry(
                symbol=symbol,
                entry_type="BUY",
                qty=qty,
                price=price,
                round_val=state["current_round"],
                avg_price=state["avg_price"],
                total_qty=state["total_qty"],
                note="매수 체결 성공"
            )

    def record_buy_failure(self, symbol: str, qty: int, price: float, reason: str):
        """
        매수 실패/거부 이력 기록 (APBK1681, 예수금 부족 등)
        """
        state = self.get_symbol_state(symbol)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_item = {
            "date": now_str,
            "type": "BUY_FAILED",
            "status_label": "❌ 매수 실패",
            "qty": qty,
            "price": price,
            "round": state.get("current_round", 0),
            "avg_price": state.get("avg_price", 0.0),
            "total_qty": state.get("total_qty", 0),
            "note": reason
        }
        state["history"].append(history_item)
        logger.warning(f"❌ [{symbol}] 무한매수 실패 기록: {qty}주 @ ${price:.2f} | 원인: {reason}")
        self.save_state()

        if hasattr(self, "gss_mgr") and self.gss_mgr:
            self.gss_mgr.append_history_entry(
                symbol=symbol,
                entry_type="BUY_FAILED",
                qty=qty,
                price=price,
                round_val=state.get("current_round", 0),
                avg_price=state.get("avg_price", 0.0),
                total_qty=state.get("total_qty", 0),
                note=f"매수 실패: {reason}"
            )

    def record_order_sent(self, symbol: str, qty: int, price: float, ord_type: str, desc: str):
        """
        매수 LOC 주문 접수 완료 기록
        """
        state = self.get_symbol_state(symbol)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        history_item = {
            "date": now_str,
            "type": "ORDER_SENT",
            "status_label": "⏳ LOC 주문 접수",
            "qty": qty,
            "price": price,
            "round": state.get("current_round", 0),
            "avg_price": state.get("avg_price", 0.0),
            "total_qty": state.get("total_qty", 0),
            "note": desc
        }
        state["history"].append(history_item)
        self.save_state()

        if hasattr(self, "gss_mgr") and self.gss_mgr:
            self.gss_mgr.append_history_entry(
                symbol=symbol,
                entry_type="ORDER_SENT",
                qty=qty,
                price=price,
                round_val=state.get("current_round", 0),
                avg_price=state.get("avg_price", 0.0),
                total_qty=state.get("total_qty", 0),
                note=desc
            )

    def record_sell_execution(self, symbol: str, qty: int, price: float):
        """
        익절 매도 체결 및 회차 초기화 (1회차/0회차 리셋)
        """
        state = self.get_symbol_state(symbol)
        old_avg = state["avg_price"]
        roi = ((price - old_avg) / old_avg * 100) if old_avg > 0 else 0.0
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        history_item = {
            "date": now_str,
            "type": "SELL",
            "status_label": "🎉 익절 매도 완료",
            "qty": qty,
            "price": price,
            "avg_price": old_avg,
            "roi_pct": round(roi, 2),
            "note": f"익절 매도 완료 (수익률: +{roi:.2f}%)"
        }
        state["history"].append(history_item)

        # 전량 익절 시 리셋
        if qty >= state["total_qty"]:
            logger.info(f"🎉 [{symbol}] 무한매수 전량 익절 성공! 수익률: +{roi:.2f}% | 회차 0으로 리셋")
            state["total_qty"] = 0
            state["avg_price"] = 0.0
            state["current_round"] = 0
            state["status"] = "COMPLETED"
        else:
            state["total_qty"] = max(0, state["total_qty"] - qty)
            if state["total_qty"] == 0:
                state["avg_price"] = 0.0
                state["current_round"] = 0
                state["status"] = "COMPLETED"

        self.save_state()

        if hasattr(self, "gss_mgr") and self.gss_mgr:
            self.gss_mgr.append_history_entry(
                symbol=symbol,
                entry_type="SELL",
                qty=qty,
                price=price,
                round_val=0,
                avg_price=old_avg,
                total_qty=state["total_qty"],
                roi_pct=roi,
                note=f"익절 매도 성공 (수익률: +{roi:.2f}%)"
            )

    def start_buying(self, symbol: str):
        """수동 무한매수 시작 (상태를 BUYING으로 설정)"""
        state = self.get_symbol_state(symbol)
        state["status"] = "BUYING"
        logger.info(f"▶ [{symbol}] 무한매수 매매 루프 수동 시작! (상태: BUYING)")
        self.save_state()

    def stop_buying(self, symbol: str):
        """무한매수 강제 중지 (상태를 STOPPED로 설정)"""
        state = self.get_symbol_state(symbol)
        state["status"] = "STOPPED"
        logger.info(f"⏹ [{symbol}] 무한매수 강제 중지 완료! (상태: STOPPED)")
        self.save_state()

    def reset_round(self, symbol: str):
        """수동 회차 초기화"""
        state = self.get_symbol_state(symbol)
        state["current_round"] = 0
        state["total_qty"] = 0
        state["avg_price"] = 0.0
        state["status"] = "IDLE"
        logger.info(f"🔄 [{symbol}] 무한매수 회차 초기화 완료! (상태: IDLE)")
        self.save_state()

