"""
라오어 무한매수법 상태 관리자 모듈 (infinite_state_manager.py)
종목별 무한매수 회차(1~40회차), 평단가, 누적 수량, 예산 및 매매 이력을 영속적으로 저장하고 관리합니다.
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("InfiniteStateManager")

DEFAULT_STATE_FILE = "infinite_trader_state.json"

class InfiniteStateManager:
    """무한매수법 상태 영속성 관리 클래스"""

    def __init__(self, file_path: str = DEFAULT_STATE_FILE):
        self.file_path = file_path
        self.states: Dict[str, Dict[str, Any]] = {}
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
        """현재 무한매수 상태를 로컬 JSON 파일로 저장"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.states, f, ensure_ascii=False, indent=2)
            logger.debug("무한매수 상태 파일 저장 완료")
        except Exception as e:
            logger.error(f"무한매수 상태 파일 저장 실패: {e}")

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

    def record_buy_execution(self, symbol: str, qty: int, price: float, round_inc: float = 1.0):
        """
        매수 체결 기록 및 평단가/회차/누적수량 갱신
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

        state["history"].append({
            "type": "BUY",
            "qty": qty,
            "price": price,
            "round": state["current_round"],
            "avg_price": state["avg_price"],
            "total_qty": state["total_qty"]
        })

        logger.info(f"[{symbol}] 무한매수 체결 기록: +{qty}주 @ ${price:.2f} | 회차: {state['current_round']}/{state['division_count']} | 평단가: ${state['avg_price']:.2f}")
        self.save_state()

    def record_sell_execution(self, symbol: str, qty: int, price: float):
        """
        익절 매도 체결 및 회차 초기화 (1회차/0회차 리셋)
        """
        state = self.get_symbol_state(symbol)
        old_avg = state["avg_price"]
        roi = ((price - old_avg) / old_avg * 100) if old_avg > 0 else 0.0

        state["history"].append({
            "type": "SELL",
            "qty": qty,
            "price": price,
            "avg_price": old_avg,
            "roi_pct": round(roi, 2)
        })

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
