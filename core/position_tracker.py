"""
KIS Auto Trading - Position & Cooldown Tracker Module
라이브 보유 종목별 최고가/분할익절 상태 추적 및 손절 쿨다운 관리
"""
import os
import time
import logging
import datetime
from contextlib import contextmanager
from typing import Dict, Any, Optional
from time_utils import today, now_str
from core.storage import safe_load_json, atomic_save_json
from core.stock_code import normalize_stock_code

logger = logging.getLogger("PositionTracker")

COOLDOWN_API_CACHE_TTL = 300.0

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
POSITIONS_STATE_FILE = os.path.join(BASE_DIR, "positions_state.json")
COOLDOWN_FILE = os.path.join(BASE_DIR, "cooldown.json")

class PositionTracker:
    def __init__(self, positions_file: str = POSITIONS_STATE_FILE, cooldown_file: str = COOLDOWN_FILE):
        self.positions_file = positions_file
        self.cooldown_file = cooldown_file
        self._cooldown_api_cache: Dict[str, Any] = {}
        # 일괄 처리 모드: 포지션 상태를 메모리에서만 갱신하고 종료 시 1회만 저장 (Google Sheet 호출 최소화)
        self._batch_state: Optional[Dict[str, Dict[str, Any]]] = None
        self._batch_dirty = False

    @contextmanager
    def batch_updates(self):
        """보유 종목 일괄 감시 시 포지션 상태를 1회 로드/1회 저장하도록 묶는 컨텍스트"""
        if self._batch_state is not None:
            yield
            return
        self._batch_state = self.load_positions_state()
        self._batch_dirty = False
        try:
            yield
        finally:
            state, dirty = self._batch_state, self._batch_dirty
            self._batch_state = None
            self._batch_dirty = False
            if dirty:
                self.save_positions_state(state)

    # =========================================================================
    # =========================================================================
    # 라이브 포지션 상태 (최고가 & 1차 50% 분할 익절 상태) 관리
    # =========================================================================
    def _normalize_state_keys(self, state: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """종목 코드를 6자리 문자열로 정규화하여 딕셔너리 키 일관성 보장"""
        normalized: Dict[str, Dict[str, Any]] = {}
        for k, v in state.items():
            code_6 = normalize_stock_code(k)
            if isinstance(v, dict):
                v["code"] = code_6
            normalized[code_6] = v
        return normalized

    def load_positions_state(self) -> Dict[str, Dict[str, Any]]:
        """라이브 보유 종목별 최고가 및 1차 익절 상태 로드 (로컬 JSON + Google Sheet 동기화)"""
        if self._batch_state is not None:
            return self._batch_state
        local_state = safe_load_json(self.positions_file, default={})
        local_state = self._normalize_state_keys(local_state)
        try:
            from google_sheet_manager import get_sheet_manager
            sheet_mgr = get_sheet_manager()
            if sheet_mgr.is_connected:
                sheet_state = sheet_mgr.read_positions_state_from_sheet()
                if sheet_state:
                    sheet_state = self._normalize_state_keys(sheet_state)
                    for c_key, s_val in sheet_state.items():
                        if c_key in local_state:
                            loc_val = local_state[c_key]
                            s_val["highest_price"] = max(loc_val.get("highest_price", 0.0), s_val.get("highest_price", 0.0))
                            s_val["is_partial_sold"] = loc_val.get("is_partial_sold", False) or s_val.get("is_partial_sold", False)
                            if "strategy" not in s_val or not s_val["strategy"]:
                                s_val["strategy"] = loc_val.get("strategy", "momentum")
                                s_val["strategy_display_name"] = loc_val.get("strategy_display_name", loc_val.get("strategy", "momentum"))
                        local_state[c_key] = s_val
        except Exception as e:
            logger.debug(f"Google Sheet 포지션 상태 읽기 생략: {e}")
        return local_state

    def save_positions_state(self, state: Dict[str, Dict[str, Any]]) -> bool:
        """라이브 보유 종목별 최고가 및 1차 익절 상태 저장 (로컬 JSON + Google Sheet)"""
        if self._batch_state is not None:
            if state is not self._batch_state:
                self._batch_state.clear()
                self._batch_state.update(state)
            self._batch_dirty = True
            return True
        norm_state = self._normalize_state_keys(state)
        ok = atomic_save_json(self.positions_file, norm_state)
        try:
            from google_sheet_manager import get_sheet_manager
            sheet_mgr = get_sheet_manager()
            if sheet_mgr.is_connected:
                sheet_mgr.sync_positions_state_to_sheet(norm_state)
        except Exception as e:
            logger.debug(f"Google Sheet 포지션 상태 동기화 생략: {e}")
        return ok

    def record_buy(
        self,
        code: str,
        name: str,
        price: float,
        qty: int,
        strategy: str = "momentum",
        strategy_display_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """신규 매수 체결 종목의 포지션 정보 및 진입 전략 기록"""
        c_str = str(code).strip().lstrip("'")
        code_6 = normalize_stock_code(c_str)
        state = self.load_positions_state()
        pos = state.get(code_6, {})
        pos["code"] = code_6
        pos["name"] = name
        pos["avg_buy_price"] = price
        pos["highest_price"] = max(pos.get("highest_price", price), price)
        pos["is_partial_sold"] = False
        pos["strategy"] = strategy
        pos["strategy_display_name"] = strategy_display_name or strategy
        pos["buy_date"] = today().strftime("%Y%m%d")
        pos["last_updated"] = now_str()
        state[code_6] = pos
        self.save_positions_state(state)
        logger.info(f"[{name}({code_6})] 포지션 등록: 매수전략='{strategy}', 단가={price:,.0f}원, 수량={qty}주")
        return pos

    def get_position_strategy(self, code: str) -> Optional[str]:
        """보유 종목의 매수 진입 전략 반환"""
        c_str = str(code).strip().lstrip("'")
        code_6 = normalize_stock_code(c_str)
        state = self.load_positions_state()
        pos = state.get(code_6) or state.get(c_str)
        if pos and pos.get("strategy"):
            return pos["strategy"]
        return None

    def set_position_strategy(
        self,
        code: str,
        strategy: str,
        strategy_display_name: Optional[str] = None,
        name: Optional[str] = None,
        avg_buy_price: float = 0.0,
        current_price: float = 0.0
    ) -> Dict[str, Any]:
        """보유 종목의 진입 전략을 수동으로 변경하거나 신규 지정"""
        c_str = str(code).strip().lstrip("'")
        code_6 = normalize_stock_code(c_str)
        state = self.load_positions_state()
        pos = state.get(code_6, {})
        pos["code"] = code_6
        if name:
            pos["name"] = name
        elif "name" not in pos:
            pos["name"] = code_6
        if avg_buy_price > 0:
            pos["avg_buy_price"] = avg_buy_price
        if current_price > 0:
            pos["highest_price"] = max(pos.get("highest_price", current_price), current_price)

        pos["strategy"] = strategy
        pos["strategy_display_name"] = strategy_display_name or strategy
        pos["last_updated"] = now_str()
        state[code_6] = pos
        self.save_positions_state(state)
        logger.info(f"[{pos.get('name', code_6)}({code_6})] 진입 전략 수동 변경 완료: {strategy} ({strategy_display_name})")
        return pos

    def update_position_state(
        self,
        code: str,
        current_price: float,
        avg_buy_price: float,
        is_partial_take: bool = False,
        strategy: Optional[str] = None
    ) -> Dict[str, Any]:
        """라이브 종목별 최고가 갱신 및 상태 반환"""
        c_str = str(code).strip().lstrip("'")
        code_6 = normalize_stock_code(c_str)
        state = self.load_positions_state()
        is_new = code_6 not in state
        pos = state.get(code_6, {})
        highest_price = max(pos.get("highest_price", avg_buy_price or current_price), current_price)
        is_partial_sold = pos.get("is_partial_sold", False) or is_partial_take
        set_strategy = bool(strategy and not pos.get("strategy"))

        # 최고가/익절상태/전략 변화가 없으면 저장(Google Sheet 재작성) 생략
        changed = (
            is_new
            or highest_price != pos.get("highest_price")
            or is_partial_sold != pos.get("is_partial_sold", False)
            or set_strategy
        )
        if not changed:
            return pos

        pos["code"] = code_6
        pos["highest_price"] = highest_price
        pos["is_partial_sold"] = is_partial_sold
        if set_strategy:
            pos["strategy"] = strategy
        pos["last_updated"] = now_str()
        state[code_6] = pos
        self.save_positions_state(state)
        return pos

    def clear_position_state(self, code: str) -> None:
        """전량 매도된 종목의 포지션 상태 정리"""
        c_str = str(code).strip().lstrip("'")
        code_6 = normalize_stock_code(c_str)
        state = self.load_positions_state()
        changed = False
        for c in (code_6, c_str, c_str.lstrip("0")):
            if c in state:
                del state[c]
                changed = True
        if changed:
            self.save_positions_state(state)

    # =========================================================================
    # 손절 종목 쿨다운 (Cool-down) 관리
    # =========================================================================
    def load_cooldown(self) -> Dict[str, str]:
        """쿨다운 상태 로드: {code: 손절 청산일(YYYYMMDD)}"""
        local_cd = safe_load_json(self.cooldown_file, default={})
        try:
            from google_sheet_manager import get_sheet_manager
            sheet_mgr = get_sheet_manager()
            if sheet_mgr.is_connected:
                sheet_cd = sheet_mgr.read_cooldown_from_sheet()
                if sheet_cd:
                    local_cd.update(sheet_cd)
        except Exception as e:
            logger.debug(f"Google Sheet 쿨다운 읽기 생략: {e}")
        return local_cd

    def save_cooldown(self, cooldown_map: Dict[str, str]) -> bool:
        """쿨다운 상태 저장 (로컬 JSON + Google Sheet)"""
        ok = atomic_save_json(self.cooldown_file, cooldown_map)
        try:
            from google_sheet_manager import get_sheet_manager
            sheet_mgr = get_sheet_manager()
            if sheet_mgr.is_connected:
                sheet_mgr.sync_cooldown_to_sheet(cooldown_map)
        except Exception as e:
            logger.debug(f"Google Sheet 쿨다운 동기화 생략: {e}")
        return ok

    def get_stop_loss_date_from_api(self, api_client: Any, code: str, current_date: Optional[str] = None) -> Optional[str]:
        """
        KIS API 거래이력에서 해당 종목의 최근 손절 매도일 조회 (FIFO 기준).
        계좌 전체의 거래이력(30일)을 메모리에 캐싱하여 종목별 중복 API 조회를 방지합니다.
        """
        if not api_client:
            return None

        # 1. 로컬 쿨다운 파일에 이미 등록된 경우 API 호출 없이 즉시 반환
        local_cooldown = self.load_cooldown()
        if code in local_cooldown:
            return local_cooldown[code]

        try:
            end_date = current_date or today().strftime("%Y%m%d")
            start_dt = datetime.datetime.strptime(end_date, "%Y%m%d") - datetime.timedelta(days=30)
            start_date = start_dt.strftime("%Y%m%d")

            cache_key = f"{start_date}_{end_date}"
            cached = self._cooldown_api_cache.get(cache_key)
            if not cached or time.time() - cached[0] >= COOLDOWN_API_CACHE_TTL:
                # 계좌 전체 거래이력 1회만 조회 (code=None), 5분 TTL로 장중 신규 손절 반영
                orders = api_client.get_order_history(start_date=start_date, end_date=end_date)
                cached = (time.time(), orders if orders is not None else [])
                self._cooldown_api_cache[cache_key] = cached

            orders = cached[1]
            if not orders:
                return None

            stock_orders = [o for o in orders if o.get("code") == code and o.get("ccld_qty", 0) > 0]
            if not stock_orders:
                return None

            stock_orders.sort(key=lambda o: (
                o.get("order_date", "") or "",
                o.get("order_time", "") or ""
            ))

            buy_queue = []
            for o in stock_orders:
                qty = o.get("ccld_qty", 0)
                price = o.get("ccld_price", 0)
                order_date = o.get("order_date", "")

                if o.get("buy_sell") == "매수":
                    buy_queue.append({"qty": qty, "price": price, "date": order_date})
                else:
                    sell_qty_remaining = qty
                    while sell_qty_remaining > 0 and buy_queue:
                        buy_order = buy_queue[0]
                        match_qty = min(buy_order["qty"], sell_qty_remaining)

                        if price < buy_order["price"]:
                            logger.info(f"[{code}] 손절 매도 감지: 매도가 {price} < 매수가 {buy_order['price']} ({order_date})")
                            return order_date

                        buy_order["qty"] -= match_qty
                        sell_qty_remaining -= match_qty
                        if buy_order["qty"] <= 0:
                            buy_queue.pop(0)

            return None
        except Exception as e:
            logger.warning(f"[{code}] API 거래이력 기반 손절일 조회 실패: {e}")
            return None

    def is_in_cooldown(
        self,
        code: str,
        cooldown_days: int = 4,
        cooldown_enabled: bool = True,
        api_client: Any = None,
        current_date: Optional[str] = None,
        use_file_cooldown: bool = False
    ) -> bool:
        """해당 종목이 손절 쿨다운 기간 내에 있는지 확인"""
        if not cooldown_enabled:
            return False

        current = current_date or today().strftime("%Y%m%d")

        if use_file_cooldown:
            cooldown_map = self.load_cooldown()
            stop_date = cooldown_map.get(code)
        else:
            # 먼저 로컬/구글시트 쿨다운 확인 후 없을 때만 API 거래이력 조회
            cooldown_map = self.load_cooldown()
            stop_date = cooldown_map.get(code)
            if not stop_date:
                stop_date = self.get_stop_loss_date_from_api(api_client, code, current_date=current)

        if not stop_date:
            return False

        try:
            stop_dt = datetime.datetime.strptime(stop_date, "%Y%m%d")
            current_dt = datetime.datetime.strptime(current, "%Y%m%d")
            elapsed_days = (current_dt - stop_dt).days
            return elapsed_days < cooldown_days
        except (ValueError, TypeError):
            return False

    def register_stop_loss_cooldown(
        self,
        code: str,
        stop_date: Optional[str] = None,
        cooldown_days: int = 4,
        cooldown_enabled: bool = True,
        use_file_cooldown: bool = False
    ) -> None:
        """손절 청산 종목을 쿨다운 목록에 등록"""
        if not cooldown_enabled:
            return

        if not use_file_cooldown:
            logger.info(f"[{code}] 손절 쿨다운 적용 (API 거래이력 기반, 재매수 금지 {cooldown_days}거래일)")
            return

        cooldown_map = self.load_cooldown()
        cooldown_map[code] = stop_date or today().strftime("%Y%m%d")
        self.save_cooldown(cooldown_map)
        logger.info(f"[{code}] 손절 쿨다운 등록 완료 (재매수 금지 {cooldown_days}거래일)")
