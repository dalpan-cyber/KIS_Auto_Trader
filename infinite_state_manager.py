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
DEFAULT_COMPLETED_FILE = "completed_trades.json"


class InfiniteStateManager:
    """무한매수법 전략 상태 관리 클래스 (로컬 JSON + Google Sheets 동기화)"""

    def __init__(self, file_path: str = DEFAULT_STATE_FILE, enable_gss: Optional[bool] = None, completed_file: str = DEFAULT_COMPLETED_FILE):
        self.file_path = file_path
        self.completed_file = completed_file
        if enable_gss is None:
            enable_gss = (file_path == DEFAULT_STATE_FILE)
        self.gss_mgr = GoogleSheetManager(enabled=enable_gss)
        self.load_state()

        # Google Sheets 연동 시 최신 설정 우선 로드 및 전략 상태 동기화
        if self.gss_mgr and self.gss_mgr.is_connected:
            try:
                import config
                config.load_settings_from_google_sheet(gss_instance=self.gss_mgr)
                self._sync_states_with_config()
                # 구글 시트 State 워크시트에서 진행 회차/상태/시작일 복원 (Streamlit Cloud 컨테이너 재시작 시 보존)
                sheet_states = self.gss_mgr.read_states_from_sheet()
                if sheet_states:
                    modified = False
                    for sym, s_st in sheet_states.items():
                        if sym in self.states:
                            if s_st.get("current_round", 0) > 0 and self.states[sym].get("current_round", 0) == 0:
                                self.states[sym]["current_round"] = s_st["current_round"]
                                modified = True
                            if s_st.get("status") and s_st.get("status") != "IDLE" and self.states[sym].get("status") == "IDLE":
                                self.states[sym]["status"] = s_st["status"]
                                modified = True
                            # 구글 시트에 저장된 유효한 시작일 복원 (Streamlit Cloud 재부팅 시 영속화)
                            sheet_sd = str(s_st.get("start_date", "")).strip()
                            if sheet_sd and sheet_sd not in ("-", "", "None") and self.states[sym].get("start_date") != sheet_sd:
                                self.states[sym]["start_date"] = sheet_sd
                                modified = True
                        else:
                            self.states[sym] = s_st
                            modified = True
                    if modified:
                        self.save_state()
            except Exception as e:
                logger.warning(f"구글 시트 설정/상태 동기화 중 예외: {e}")

    def _sync_states_with_config(self):
        """config에 로드된 최신 종목별 설정값을 전략 상태(self.states)에 동기화 (진행 회차/상태는 유지)"""
        try:
            import config
            modified = False
            for sym in getattr(config, "INFINITE_STOCKS", []):
                sym_upper = sym.upper()
                if sym_upper in self.states:
                    cfg = config.get_stock_config(sym_upper)
                    st = self.states[sym_upper]
                    if (st.get("total_budget_usd") != cfg["total_budget_usd"] or
                        st.get("division_count") != cfg["division_count"] or
                        st.get("target_roi") != cfg["target_roi"] or
                        st.get("exhaust_action") != cfg["exhaust_action"] or
                        st.get("exhaust_target_roi") != cfg["exhaust_target_roi"]):
                        st["total_budget_usd"] = cfg["total_budget_usd"]
                        st["division_count"] = cfg["division_count"]
                        st["target_roi"] = cfg["target_roi"]
                        st["exhaust_action"] = cfg["exhaust_action"]
                        st["exhaust_target_roi"] = cfg["exhaust_target_roi"]
                        modified = True
            if modified:
                self.save_state()
                logger.info("⚙️ 구글 시트 최신 설정값으로 종목 전략 상태 동기화 완료 (진행 회차 보존)")
        except Exception as e:
            logger.debug(f"전략 상태 동기화 예외: {e}")

    def load_state(self) -> Dict[str, Dict[str, Any]]:
        """로컬 JSON 파일에서 무한매수 전략 상태 로드 (JSON = Single Source of Truth)"""
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
        """현재 무한매수 전략 상태를 로컬 JSON 파일로 저장 및 구글 시트 State 워크시트 백업"""
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.states, f, ensure_ascii=False, indent=2)
            logger.debug("무한매수 상태 파일 저장 완료")
        except Exception as e:
            logger.error(f"무한매수 상태 파일 저장 실패: {e}")

        # 구글 시트 연동 시 State 워크시트에 진행 회차/전략 상태 실시간 동기화
        if hasattr(self, "gss_mgr") and self.gss_mgr and getattr(self.gss_mgr, "is_connected", False):
            try:
                self.gss_mgr.sync_all_states(self.states)
            except Exception as e:
                logger.debug(f"구글 시트 State 동기화 예외: {e}")

    def get_symbol_state(
        self,
        symbol: str,
        default_budget_usd: float = 10000.0,
        division_count: int = 40,
        target_roi: float = 0.10,
        exhaust_action: str = "HOLD",
        exhaust_target_roi: float = 0.05
    ) -> Dict[str, Any]:
        """
        종목별 전략 상태 조회 (없으면 기본값 생성)
        - 전략 상태만 관리: start_date, current_round, division_count, total_budget_usd, target_roi,
          exhaust_action, exhaust_target_roi, status
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
                "exhaust_action": str(exhaust_action).strip().upper(),
                "exhaust_target_roi": exhaust_target_roi,
                "status": "IDLE",  # IDLE, BUYING, COMPLETED, PAUSED_MAX
                "peak_qty": 0,
                "paused_sell_price": 0.0,
                "last_avg_price": 0.0,
                "last_completed_sell_order_no": "",
            }
            self.save_state()
        # 기존 상태에 exhaust_action/exhaust_target_roi/peak_qty/paused_sell_price/last_avg_price/last_completed_sell_order_no가 없으면 기본값 추가 (하위 호환성)
        if "exhaust_action" not in self.states[symbol_upper]:
            self.states[symbol_upper]["exhaust_action"] = str(exhaust_action).strip().upper()
        if "exhaust_target_roi" not in self.states[symbol_upper]:
            self.states[symbol_upper]["exhaust_target_roi"] = exhaust_target_roi
        if "peak_qty" not in self.states[symbol_upper]:
            self.states[symbol_upper]["peak_qty"] = 0
        if "paused_sell_price" not in self.states[symbol_upper]:
            self.states[symbol_upper]["paused_sell_price"] = 0.0
        if "last_avg_price" not in self.states[symbol_upper]:
            self.states[symbol_upper]["last_avg_price"] = 0.0
        if "last_completed_sell_order_no" not in self.states[symbol_upper]:
            self.states[symbol_upper]["last_completed_sell_order_no"] = ""
        return self.states[symbol_upper]

    def update_budget(self, symbol: str, total_budget_usd: float):
        """총 예산 업데이트"""
        state = self.get_symbol_state(symbol)
        state["total_budget_usd"] = total_budget_usd
        self.save_state()

    def update_division_count(self, symbol: str, division_count: int):
        """총 분할 횟수 업데이트"""
        state = self.get_symbol_state(symbol)
        state["division_count"] = division_count
        self.save_state()

    def update_target_roi(self, symbol: str, target_roi: float):
        """전량 익절 목표 수익률 업데이트"""
        state = self.get_symbol_state(symbol)
        state["target_roi"] = target_roi
        self.save_state()

    def update_exhaust_action(self, symbol: str, exhaust_action: str):
        """40회차 소진 시 대응 모드 업데이트"""
        state = self.get_symbol_state(symbol)
        state["exhaust_action"] = str(exhaust_action).strip().upper()
        self.save_state()

    def update_exhaust_target_roi(self, symbol: str, exhaust_target_roi: float):
        """40회차 소진 시 탈출 목표 수익률 업데이트"""
        state = self.get_symbol_state(symbol)
        state["exhaust_target_roi"] = exhaust_target_roi
        self.save_state()

    def update_start_date(self, symbol: str, start_date: str):
        """전략 시작일 업데이트 및 구글 시트 State 워크시트 즉시 영속화"""
        state = self.get_symbol_state(symbol)
        state["start_date"] = str(start_date).strip()
        self.save_state()
        logger.info(f"📅 [{symbol}] 무한매수 전략 시작일 변경 완료: {start_date} (구글 시트 State 실시간 동기화)")

    def update_settings(
        self,
        symbol: str,
        total_budget_usd: float,
        division_count: int,
        target_roi: float,
        exhaust_action: str = "HOLD",
        exhaust_target_roi: float = 0.05
    ):
        """
        무한매수 설정값만 업데이트 (전략 진행 상태는 유지)
        - 진행 회차, 상태, 시작일은 변경하지 않음
        - 새 예산/분할횟수/목표수익률/소진대응을 상태에 반영
        """
        state = self.get_symbol_state(symbol)
        state["total_budget_usd"] = total_budget_usd
        state["division_count"] = division_count
        state["target_roi"] = target_roi
        state["exhaust_action"] = str(exhaust_action).strip().upper()
        state["exhaust_target_roi"] = exhaust_target_roi
        logger.info(f"⚙️ [{symbol}] 무한매수 설정값 업데이트 완료! (예산: ${total_budget_usd:,.0f}, 분할: {division_count}회, 목표수익률: +{target_roi*100:.1f}%, 소진대응: {exhaust_action}) - 진행 상태 유지")
        self.save_state()

    def reset_all(
        self,
        symbol: str,
        total_budget_usd: float,
        division_count: int,
        target_roi: float,
        exhaust_action: str = "HOLD",
        exhaust_target_roi: float = 0.05
    ):
        """
        무한매수 전략 전체 초기화 (설정 변경 시 호출)
        - 진행 회차를 0으로 리셋하고, 상태를 IDLE로 변경
        - 새 예산/분할횟수/목표수익률/소진대응을 상태에 반영
        """
        state = self.get_symbol_state(symbol)
        state["total_budget_usd"] = total_budget_usd
        state["division_count"] = division_count
        state["target_roi"] = target_roi
        state["exhaust_action"] = str(exhaust_action).strip().upper()
        state["exhaust_target_roi"] = exhaust_target_roi
        state["current_round"] = 0
        state["status"] = "IDLE"
        state["peak_qty"] = 0
        state["paused_sell_price"] = 0.0
        state["start_date"] = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"🔄 [{symbol}] 무한매수 설정 변경으로 전체 초기화 완료! (예산: ${total_budget_usd:,.0f}, 분할: {division_count}회, 목표수익률: +{target_roi*100:.1f}%, 소진대응: {exhaust_action}, 상태: IDLE)")
        self.save_state()

    def start_buying(self, symbol: str):
        """수동 무한매수 시작 (상태를 BUYING으로 설정, 미지정 시에만 시작일 자동 갱신)"""
        state = self.get_symbol_state(symbol)
        if state.get("current_round", 0) == 0 and (not state.get("start_date") or state.get("start_date") in ("-", "None", "")):
            state["start_date"] = datetime.now().strftime("%Y-%m-%d")
        state["status"] = "BUYING"
        logger.info(f"▶ [{symbol}] 무한매수 매매 루프 수동 시작! (상태: BUYING, 시작일: {state.get('start_date')})")
        self.save_state()

    def stop_buying(self, symbol: str):
        """무한매수 강제 중지 (상태를 STOPPED로 설정)"""
        state = self.get_symbol_state(symbol)
        state["status"] = "STOPPED"
        state["paused_sell_price"] = 0.0
        logger.info(f"⏹ [{symbol}] 무한매수 강제 중지 완료! (상태: STOPPED)")
        self.save_state()

    def pause_buying(self, symbol: str, sell_price: float = 0.0):
        """투자 일시중지 (상태를 PAUSED로 설정, 지정 매도가 설정 시 매도만 가능)"""
        state = self.get_symbol_state(symbol)
        state["status"] = "PAUSED"
        state["paused_sell_price"] = float(sell_price) if sell_price else 0.0
        sell_msg = f", 지정 매도가: ${sell_price:.2f}" if sell_price > 0 else " (매수 중단, 기본 익절 매도 유지)"
        logger.info(f"⏸ [{symbol}] 투자 일시중지 설정 완료!{sell_msg} (상태: PAUSED)")
        self.save_state()

    def resume_buying(self, symbol: str):
        """투자 재개 (상태를 BUYING으로 복원, 분할 매수 재개)"""
        state = self.get_symbol_state(symbol)
        state["status"] = "BUYING"
        state["paused_sell_price"] = 0.0
        logger.info(f"▶ [{symbol}] 투자 재개 완료! (상태: BUYING, 매수/매도 정상 가동)")
        self.save_state()

    def reset_round(self, symbol: str):
        """수동 회차 초기화"""
        state = self.get_symbol_state(symbol)
        state["current_round"] = 0
        state["status"] = "IDLE"
        state["peak_qty"] = 0
        state["paused_sell_price"] = 0.0
        state["last_avg_price"] = 0.0
        state["start_date"] = datetime.now().strftime("%Y-%m-%d")
        logger.info(f"🔄 [{symbol}] 무한매수 회차 초기화 완료! (상태: IDLE)")
        self.save_state()

    def update_peak_qty(self, symbol: str, held_qty: int, avg_price: float = 0.0):
        """실제 보유 수량 및 평단가 발생 시 peak_qty 및 last_avg_price 갱신"""
        state = self.get_symbol_state(symbol)
        modified = False
        if held_qty > state.get("peak_qty", 0):
            state["peak_qty"] = held_qty
            modified = True
        if avg_price > 0:
            state["last_avg_price"] = float(avg_price)
            modified = True
        if modified:
            self.save_state()

    def calculate_current_round(self, symbol: str, held_qty: int, avg_price: float) -> float:
        """
        라오어 무한매수법 정석 회차 계산 (체결 성공 횟수 기준):
        매일 0.5회차 매수 주문당 수량(qty_per_order)을 기준으로,
        실제 매수 성공(체결)된 건수(1건당 0.5회차)에 맞추어 진행 회차를 산출합니다.
        
        0.5회차 예산 = (총 예산 / 분할 횟수) / 2
        0.5회차 1건당 주문 수량 = max(1, int(0.5회차 예산 / 평단가))
        진행 회차 = (보유 수량 / 0.5회차 주문 수량) * 0.5 (0.5단위 반올림)
        상한: min(분할 횟수, max(0.5, calc_round))
        """
        if held_qty <= 0 or avg_price <= 0:
            return 0.0
        state = self.get_symbol_state(symbol)
        total_budget = float(state.get("total_budget_usd", 5000.0) or 5000.0)
        division = int(state.get("division_count", 40) or 40)
        if total_budget <= 0 or division <= 0:
            return 0.0

        one_round_budget = total_budget / float(division)
        half_budget = one_round_budget / 2.0
        qty_per_half_round = max(1, int(half_budget / float(avg_price)))

        raw_round = (float(held_qty) / float(qty_per_half_round)) * 0.5
        calc_round = round(raw_round * 2.0) / 2.0
        return min(float(division), max(0.5, calc_round))

    def advance_round(self, symbol: str, round_inc: float = 0.5):
        """매수 주문 접수/체결 시 진행 회차 증가 (미지정 시에만 시작일 자동 최신화)"""
        state = self.get_symbol_state(symbol)
        if state.get("current_round", 0) == 0 and (not state.get("start_date") or state.get("start_date") in ("-", "None", "")):
            state["start_date"] = datetime.now().strftime("%Y-%m-%d")
        state["current_round"] = min(state.get("division_count", 40), state.get("current_round", 0) + round_inc)
        state["status"] = "BUYING"
        self.save_state()

    def complete_round(
        self,
        symbol: str,
        avg_price: float = 0.0,
        sell_price: float = 0.0,
        qty: int = 0,
        sell_order_no: str = ""
    ):
        """전량 익절 매도 시 회차 리셋 및 상태 COMPLETED, Google Sheets 완료 일지 기록"""
        state = self.get_symbol_state(symbol)
        completed_round = state.get("current_round", 0.0)
        start_date = state.get("start_date", "")
        end_date = datetime.now().strftime("%Y-%m-%d")

        eff_avg_p = avg_price if avg_price > 0 else state.get("last_avg_price", 0.0)

        # Google Sheets 매매 완료 일지 기록
        if hasattr(self, "gss_mgr") and self.gss_mgr:
            try:
                self.gss_mgr.record_completed_cycle(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    completed_round=completed_round,
                    qty=qty,
                    avg_price=eff_avg_p,
                    sell_price=sell_price,
                    status="COMPLETED"
                )
            except Exception as e:
                logger.warning(f"구글 시트 완료 일지 기록 중 예외: {e}")

        # 로컬 완료 이력 파일(completed_trades.json)에도 백업 기록
        try:
            total_buy_amt = round(qty * eff_avg_p, 2) if qty > 0 and eff_avg_p > 0 else 0.0
            total_sell_amt = round(qty * sell_price, 2) if qty > 0 and sell_price > 0 else 0.0
            pnl = round(total_sell_amt - total_buy_amt, 2)
            roi_pct = round((pnl / total_buy_amt * 100), 2) if total_buy_amt > 0 else 0.0
            self._save_completed_trade_local({
                "완료일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "티커": symbol.upper(),
                "시작일자": start_date or "-",
                "매도일자": end_date,
                "완료회차": completed_round,
                "매도수량": qty,
                "매수평단가($)": round(eff_avg_p, 2),
                "매도단가($)": round(sell_price, 2),
                "총매수금액($)": total_buy_amt,
                "총매도금액($)": total_sell_amt,
                "실현손익($)": pnl,
                "수익률(%)": roi_pct,
                "상태": "COMPLETED"
            })
        except Exception as e:
            logger.debug(f"로컬 완료 일지 기록 예외: {e}")

        state["current_round"] = 0
        state["status"] = "COMPLETED"
        state["peak_qty"] = 0
        state["paused_sell_price"] = 0.0
        state["last_avg_price"] = 0.0
        if sell_order_no:
            state["last_completed_sell_order_no"] = str(sell_order_no).strip()
        self.save_state()

    def _save_completed_trade_local(self, record: Dict[str, Any]):
        """로컬 JSON 파일에 완료된 사이클 이력 저장"""
        trades = self.load_completed_trades_local()
        # 중복 방지 (동일 티커, 매도일자, 매도수량)
        exists = any(
            t.get("티커") == record.get("티커") and
            t.get("매도일자") == record.get("매도일자") and
            t.get("매도수량") == record.get("매도수량")
            for t in trades
        )
        if not exists:
            trades.append(record)
            try:
                with open(self.completed_file, "w", encoding="utf-8") as f:
                    json.dump(trades, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.debug(f"로컬 완료 이력 저장 실패: {e}")

    def load_completed_trades_local(self) -> List[Dict[str, Any]]:
        """로컬 JSON 파일에서 완료된 사이클 이력 로드"""
        if os.path.exists(self.completed_file):
            try:
                with open(self.completed_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return []
        return []

    def get_completed_trades(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        전량 익절 매도 완료 이력 조회:
        1. Google Sheets 'CompletedTrades' 워크시트에서 우선 조회
        2. 성공 시 로컬 캐시와 병합/동기화
        3. 시트 미연결 또는 빈 결과 시 로컬 캐시 fallback
        """
        records = []
        if hasattr(self, "gss_mgr") and self.gss_mgr and getattr(self.gss_mgr, "is_connected", False):
            try:
                records = self.gss_mgr.get_completed_trades(limit=limit)
                if records:
                    # 로컬 캐시에 동기화
                    try:
                        with open(self.completed_file, "w", encoding="utf-8") as f:
                            json.dump(records, f, ensure_ascii=False, indent=2)
                    except Exception:
                        pass
                    return records
            except Exception as e:
                logger.debug(f"구글 시트 완료 이력 조회 중 예외: {e}")

        local_trades = self.load_completed_trades_local()
        return local_trades[-limit:] if limit and len(local_trades) > limit else local_trades

