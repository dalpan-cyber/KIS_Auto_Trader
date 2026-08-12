"""
무한매수법 상태 영속성 관리 클래스 (infinite_state_manager.py)
- JSON에는 전략 상태(시작일, 진행회차, 예산, 목표수익률, 상태)만 기록
- 보유 수량/평단가/체결 이력은 KIS API에서 실시간 조회 (Source of Truth = API)
"""
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
    """무한매수법 전략 상태 관리 클래스 (로컬 JSON + Google Sheets 동기화)"""

    def __init__(self, file_path: str = DEFAULT_STATE_FILE, enable_gss: Optional[bool] = None):
        self.file_path = file_path
        if enable_gss is None:
            enable_gss = (file_path == DEFAULT_STATE_FILE)
        self.gss_mgr = GoogleSheetManager(enabled=enable_gss)
        self.load_state()

    def load_state(self) -> Dict[str, Dict[str, Any]]:
        """로컬 JSON 파일 및 Google Sheets에서 무한매수 전략 상태 로드 (양방향 동기화)"""
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

        # 구글 시트에 사용자가 수동 수정한 전략 상태가 있다면 동기화 반영 (양방향 동기화)
        if hasattr(self, "gss_mgr") and self.gss_mgr and self.gss_mgr.is_connected:
            sheet_states = self.gss_mgr.read_states_from_sheet()
            for symbol, s_data in sheet_states.items():
                if symbol not in self.states:
                    s_data.setdefault("division_count", 40)
                    self.states[symbol] = s_data
                else:
                    # 구글 시트 수동 변경사항(진행회차, 총예산, 목표수익률, 매매상태 등) 반영
                    sheet_status = s_data.get("status")
                    if sheet_status:
                        self.states[symbol]["status"] = sheet_status

                    # 매수 진행 중일 경우 구글 시트의 오래된(작은) 회차가 JSON의 최신 회차를 강제로 덮어쓰지 않도록 max 적용
                    sheet_round = s_data.get("current_round", 0)
                    json_round = self.states[symbol].get("current_round", 0)
                    if self.states[symbol].get("status") in ["IDLE", "COMPLETED"]:
                        self.states[symbol]["current_round"] = sheet_round
                    else:
                        self.states[symbol]["current_round"] = max(json_round, sheet_round)

                    self.states[symbol]["total_budget_usd"] = s_data.get("total_budget_usd", self.states[symbol].get("total_budget_usd", 5000.0))
                    self.states[symbol]["target_roi"] = s_data.get("target_roi", self.states[symbol].get("target_roi", 0.10))
                    self.states[symbol].setdefault("division_count", 40)

        return self.states

    def save_state(self):
        """현재 무한매수 전략 상태를 로컬 JSON 파일 및 Google Sheets로 저장"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.states, f, ensure_ascii=False, indent=2)
            logger.debug("무한매수 상태 파일 저장 완료")
        except Exception as e:
            logger.error(f"무한매수 상태 파일 저장 실패: {e}")

        # Google Sheets 상의 전체 종목 전략 상태 동기화
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
        종목별 전략 상태 조회 (없으면 기본값 생성)
        - 전략 상태만 관리: start_date, current_round, division_count, total_budget_usd, target_roi, status
        - 보유 수량/평단가/체결 이력은 API에서 실시간 조회하므로 여기서 관리하지 않음
        """
        symbol_upper = symbol.upper()
        if symbol_upper not in self.states:
            self.states[symbol_upper] = {
                "symbol": symbol_upper,
                "start_date": datetime.now().strftime("%Y-%m-%d"),
                "total_budget_usd": default_budget_usd,
                "division_count": division_count,
                "current_round": 0,
                "target_roi": target_roi,
                "status": "IDLE",  # IDLE, BUYING, COMPLETED, PAUSED_MAX
            }
            self.save_state()
        return self.states[symbol_upper]

    def update_budget(self, symbol: str, total_budget_usd: float):
        """총 예산 업데이트"""
        state = self.get_symbol_state(symbol)
        state["total_budget_usd"] = total_budget_usd
        self.save_state()

    def update_start_date(self, symbol: str, start_date: str):
        """전략 시작일 업데이트"""
        state = self.get_symbol_state(symbol)
        state["start_date"] = start_date
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
        state["status"] = "IDLE"
        logger.info(f"🔄 [{symbol}] 무한매수 회차 초기화 완료! (상태: IDLE)")
        self.save_state()

    def advance_round(self, symbol: str, round_inc: float = 0.5):
        """매수 주문 접수/체결 시 진행 회차 증가"""
        state = self.get_symbol_state(symbol)
        state["current_round"] = min(state.get("division_count", 40), state.get("current_round", 0) + round_inc)
        state["status"] = "BUYING"
        self.save_state()

    def complete_round(self, symbol: str):
        """전량 익절 매도 시 회차 리셋 및 상태 COMPLETED"""
        state = self.get_symbol_state(symbol)
        state["current_round"] = 0
        state["status"] = "COMPLETED"
        self.save_state()
