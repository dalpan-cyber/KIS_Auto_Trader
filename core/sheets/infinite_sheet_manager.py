"""
Google Sheets 연동 및 동기화 매니저 모듈 (google_sheet_manager.py)
Streamlit Cloud 및 로컬 환경에서 무한매수법 상태(State) 및 매매/실패 이력(History)을 구글 시트와 실시간 동기화합니다.
"""
import os
import json
import logging
import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger("GoogleSheetManager")

def _get_config_val(name: str, default: Any = None) -> Any:
    try:
        import config
        return getattr(config, name, default)
    except Exception:
        return default

from core.sheets.base_sheet import BaseSheetManager, GSPREAD_AVAILABLE


class InfiniteSheetManager(BaseSheetManager):
    """Google Sheets 무한매수 매매일지 및 상태 동기화 관리 클래스"""

    def __init__(
        self,
        sheet_name: Optional[str] = None,
        sheet_key: Optional[str] = None,
        enabled: Optional[bool] = None,
        service_account_file: Optional[str] = None
    ):
        name = sheet_name or _get_config_val("INFINITE_GOOGLE_SHEET_NAME", _get_config_val("GOOGLE_SHEET_NAME", os.getenv("INFINITE_GOOGLE_SHEET_NAME", os.getenv("GOOGLE_SHEET_NAME", "KIS_무한매수_매매일지"))))
        key = sheet_key or _get_config_val("INFINITE_GOOGLE_SHEET_KEY", _get_config_val("GOOGLE_SHEET_KEY", os.getenv("INFINITE_GOOGLE_SHEET_KEY", os.getenv("GOOGLE_SHEET_KEY", ""))))
        is_enabled = enabled if enabled is not None else _get_config_val("GOOGLE_SHEET_ENABLED", True)

        self.state_worksheet: Optional[Any] = None
        self.holdings_worksheet: Optional[Any] = None
        self.history_worksheet: Optional[Any] = None
        self.exec_balance_worksheet: Optional[Any] = None
        self.completed_worksheet: Optional[Any] = None
        self.settings_worksheet: Optional[Any] = None

        super().__init__(
            sheet_name=name,
            sheet_key=key,
            enabled=is_enabled,
            service_account_file=service_account_file
        )

    def _init_worksheets(self):
        """무한매수 전용 워크시트 초기화"""
        # 1. 'CompletedTrades' 워크시트 (전량 매도 완료 일지)
        self.completed_worksheet = self._get_or_create_worksheet(
            title="CompletedTrades",
            headers=["완료일시", "티커", "시작일자", "매도일자", "완료회차", "매도수량", "매수평단가($)", "매도단가($)", "총매수금액($)", "총매도금액($)", "실현손익($)", "수익률(%)", "상태"],
            rows="500",
            cols="14"
        )
        # 2. 'Settings' 워크시트 (무한매수 전략 설정값)
        self.settings_worksheet = self._get_or_create_worksheet(
            title="Settings",
            headers=["설정키", "설정값", "설명", "최종갱신시각"],
            rows="50",
            cols="10"
        )
        # 3. 'State' 워크시트 (진행 회차 및 상태)
        self.state_worksheet = self._get_or_create_worksheet(
            title="State",
            headers=["티커", "시작일", "진행회차", "총예산($)", "목표수익률(%)", "상태", "최종갱신시각"],
            rows="50",
            cols="10"
        )

    def sync_all_states(self, states: Dict[str, Dict[str, Any]]):
        """전체 종목 전략 상태를 'State' 워크시트에 반영 (보유수량/평단가는 API에서 실시간 조회)"""
        if not self.is_connected or not self.state_worksheet:
            return

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                all_records = self.state_worksheet.get_all_records()
            except Exception:
                all_records = []

            ticker_row_map = {}
            for idx, rec in enumerate(all_records, start=2):
                if rec.get("티커"):
                    ticker_row_map[str(rec["티커"]).upper()] = idx

            for symbol, state in states.items():
                sym_upper = symbol.upper()
                row_data = [
                    sym_upper,
                    state.get("start_date", "-"),
                    state.get("current_round", 0),
                    state.get("total_budget_usd", 0.0),
                    round(state.get("target_roi", 0.10) * 100, 1),
                    state.get("status", "IDLE"),
                    now_str
                ]

                if sym_upper in ticker_row_map:
                    row_idx = ticker_row_map[sym_upper]
                    self.state_worksheet.update([row_data], range_name=f"A{row_idx}:G{row_idx}")
                else:
                    self.state_worksheet.append_row(row_data)

            logger.debug("Google Sheet 'State' 워크시트 동기화 성공")
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                logger.debug("Google Sheet State API 호출 할당량 초과 (다음 턴 재시도)")
            else:
                logger.warning(f"Google Sheet State 동기화 예외: {e}")

    def read_states_from_sheet(self) -> Dict[str, Dict[str, Any]]:
        """Google Sheet 'State' 워크시트에서 사용자가 수동 편집한 전략 상태 읽어오기"""
        if not self.is_connected or not self.state_worksheet:
            return {}

        sheet_states = {}
        try:
            records = self.state_worksheet.get_all_records()
            for rec in records:
                ticker = str(rec.get("티커", "")).strip().upper()
                if not ticker:
                    continue
                roi_val = rec.get("목표수익률(%)", 10.0)
                try:
                    roi_float = float(roi_val) / 100.0 if float(roi_val) > 1.0 else float(roi_val)
                except Exception:
                    roi_float = 0.10

                sheet_states[ticker] = {
                    "symbol": ticker,
                    "division_count": 40,
                    "start_date": str(rec.get("시작일", "-")).strip(),
                    "current_round": float(rec.get("진행회차", 0.0) or 0.0),
                    "total_budget_usd": float(rec.get("총예산($)", 5000.0) or 5000.0),
                    "target_roi": round(roi_float, 4),
                    "status": str(rec.get("상태", "IDLE")).strip().upper(),
                }
            if sheet_states:
                logger.info(f"📊 Google Sheet 'State'에서 {len(sheet_states)}개 종목 상태 불러오기 성공 ({', '.join(sheet_states.keys())})")
        except Exception as e:
            logger.warning(f"Google Sheet 상태 읽기 실패: {e}")
        return sheet_states

    def sync_holdings(self, holdings: Dict[str, Dict[str, Any]], current_prices: Dict[str, float] = None):
        """
        실계좌 보유 종목 평가 금액을 'Holdings' 워크시트에 동기화
        - holdings: {symbol: {name, qty, avg_price, current_price, pnl_rate}}
        - current_prices: {symbol: current_price} (현재가가 holdings에 없을 때 보조)
        """
        if not self.is_connected or not self.holdings_worksheet:
            return

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            current_prices = current_prices or {}

            # 기존 데이터 삭제 (헤더 제외)
            try:
                all_records = self.holdings_worksheet.get_all_records()
                if all_records:
                    self.holdings_worksheet.delete_rows(2, len(all_records) + 1)
            except Exception:
                pass

            if not holdings:
                return

            rows = []
            for symbol, h in holdings.items():
                qty = h.get("qty", 0)
                avg_p = h.get("avg_price", 0.0)
                cur_p = h.get("current_price", 0.0) or current_prices.get(symbol, 0.0)
                eval_amt = qty * cur_p if cur_p > 0 else 0.0
                pnl = eval_amt - (qty * avg_p) if avg_p > 0 else 0.0
                pnl_rate = (pnl / (qty * avg_p) * 100) if (qty * avg_p) > 0 else 0.0

                rows.append([
                    symbol,
                    h.get("name", f"종목_{symbol}"),
                    qty,
                    round(avg_p, 2),
                    round(cur_p, 2),
                    round(eval_amt, 2),
                    round(pnl, 2),
                    round(pnl_rate, 2),
                    now_str
                ])

            if rows:
                self.holdings_worksheet.append_rows(rows)
                logger.debug(f"Google Sheet 'Holdings' 워크시트 동기화 성공 ({len(rows)}개 종목)")
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                logger.debug("Google Sheet Holdings API 호출 할당량 초과 (다음 턴 재시도)")
            else:
                logger.warning(f"Google Sheet Holdings 동기화 예외: {e}")

    def sync_execution_balance(self, holdings: List[Dict[str, Any]]):
        """
        해외주식 체결기준 현물 잔고를 'ExecutionBalance' 워크시트에 동기화
        - holdings: get_overseas_execution_balance() 결과 리스트
        - 체결수량/체결단가/미체결수량을 포함한 체결기준 잔고를 기록
        """
        if not self.is_connected or not self.exec_balance_worksheet:
            return

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 기존 데이터 삭제 (헤더 제외)
            try:
                all_records = self.exec_balance_worksheet.get_all_records()
                if all_records:
                    self.exec_balance_worksheet.delete_rows(2, len(all_records) + 1)
            except Exception:
                pass

            if not holdings:
                return

            rows = []
            for h in holdings:
                code = h.get("code", "")
                if not code:
                    continue
                qty = int(h.get("qty", 0) or 0)
                exec_qty = int(h.get("executed_qty", 0) or 0)
                unexec_qty = int(h.get("unexecuted_qty", 0) or 0)
                avg_p = float(h.get("avg_price", 0.0) or 0.0)
                exec_p = float(h.get("executed_price", 0.0) or 0.0)
                cur_p = float(h.get("current_price", 0.0) or 0.0)
                pnl_rate = float(h.get("pnl_rate", 0.0) or 0.0)

                rows.append([
                    code,
                    h.get("name", f"해외_{code}"),
                    qty,
                    exec_qty,
                    unexec_qty,
                    round(avg_p, 2),
                    round(exec_p, 2),
                    round(cur_p, 2),
                    round(pnl_rate, 2),
                    now_str
                ])

            if rows:
                self.exec_balance_worksheet.append_rows(rows)
                logger.info(f"📊 Google Sheet 'ExecutionBalance' 워크시트 동기화 성공 ({len(rows)}개 종목)")
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                logger.debug("Google Sheet ExecutionBalance API 호출 할당량 초과 (다음 턴 재시도)")
            else:
                logger.warning(f"Google Sheet ExecutionBalance 동기화 예외: {e}")

    def read_execution_history_from_sheet(self, symbol: str = "") -> List[Dict[str, Any]]:
        """Google Sheet 'ExecutionHistory' 워크시트에서 저장된 매매 이력 읽어오기"""
        if not self.is_connected or not self.history_worksheet:
            return []

        history = []
        try:
            # NOTE: get_all_records()는 헤더 중복/빈 값이 있으면 실패하므로, get_all_values()로 원시 데이터를 읽는다.
            all_values = self.history_worksheet.get_all_values()
            if len(all_values) <= 1:
                return history

            header = all_values[0]
            col_idx = {}
            for i, h in enumerate(header):
                h_clean = str(h).strip()
                if h_clean and h_clean not in col_idx:
                    col_idx[h_clean] = i

            idx_time = col_idx.get("일시", -1)
            idx_ticker = col_idx.get("티커", -1)
            idx_type = col_idx.get("구분", -1)
            idx_ord_qty = col_idx.get("주문수량", col_idx.get("수량", -1))
            idx_exec_qty = col_idx.get("체결수량", col_idx.get("수량", -1))
            idx_ord_price = col_idx.get("주문단가($)", col_idx.get("단가($)", -1))
            idx_exec_price = col_idx.get("체결단가($)", col_idx.get("단가($)", -1))
            idx_status = col_idx.get("상태", -1)
            idx_ord_no = col_idx.get("주문번호", -1)

            for row in all_values[1:]:
                if not row or all(not str(c).strip() for c in row):
                    continue

                def _get(idx):
                    return str(row[idx]).strip() if idx >= 0 and idx < len(row) else ""

                rec_sym = _get(idx_ticker).upper()
                if symbol and rec_sym != symbol.upper():
                    continue

                def _to_int(s):
                    try:
                        return int(float(s.replace(",", ""))) if s else 0
                    except (ValueError, AttributeError):
                        return 0

                def _to_float(s):
                    try:
                        return float(s.replace(",", "").replace("$", "")) if s else 0.0
                    except (ValueError, AttributeError):
                        return 0.0

                history.append({
                    "order_time": _get(idx_time) or "-",
                    "symbol": rec_sym,
                    "order_type": _get(idx_type) or "-",
                    "qty": _to_int(_get(idx_ord_qty)),
                    "executed_qty": _to_int(_get(idx_exec_qty)),
                    "price": _to_float(_get(idx_ord_price)),
                    "executed_price": _to_float(_get(idx_exec_price)),
                    "status": _get(idx_status) or "-",
                    "order_no": _get(idx_ord_no) or "-"
                })
        except Exception as e:
            logger.warning(f"Google Sheet ExecutionHistory 읽기 실패: {e}")
        return history

    def sync_execution_history(self, history: List[Dict[str, Any]]):
        """
        KIS API 실계좌 체결/미체결 이력을 'ExecutionHistory' 워크시트에 누적 동기화
        - history: get_overseas_execution_balance() 결과 리스트 (TTTS3012R 체결기준)
        - 기존 수동 작성건이나 이전 기록을 지우지 않고 새 이력만 추가(병합)
        - TTTS3012R(체결기준) 데이터 형식: {code, name, qty, executed_qty, unexecuted_qty, avg_price, executed_price, current_price, pnl_rate}
        """
        if not self.is_connected or not self.history_worksheet:
            return

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # 1. 기존 시트 데이터 키 수집 (중복 방지)
            # NOTE: 주문번호+티커+일시만으로는 동일 주문번호의 부분체결/다중 레코드가 누락될 수 있으므로,
            # 구분(주문타입) + 주문수량 + 체결수량까지 포함한 복합 키를 사용한다.
            # NOTE: get_all_records()는 헤더 중복/빈 값이 있으면 실패하므로, get_all_values()로 원시 데이터를 읽는다.
            existing_keys = set()
            try:
                all_values = self.history_worksheet.get_all_values()
                if len(all_values) > 1:
                    header = all_values[0]
                    # 헤더 인덱스 매핑 (컬럼명 → 인덱스)
                    col_idx = {}
                    for i, h in enumerate(header):
                        h_clean = str(h).strip()
                        if h_clean and h_clean not in col_idx:
                            col_idx[h_clean] = i
                    # 필수 컬럼 인덱스
                    idx_ord_no = col_idx.get("주문번호", -1)
                    idx_time = col_idx.get("일시", -1)
                    idx_ticker = col_idx.get("티커", -1)
                    idx_type = col_idx.get("구분", -1)
                    idx_ord_qty = col_idx.get("주문수량", -1)
                    idx_exec_qty = col_idx.get("체결수량", -1)
                    idx_ord_price = col_idx.get("주문단가($)", -1)
                    idx_exec_price = col_idx.get("체결단가($)", -1)

                    for row in all_values[1:]:
                        if not row or all(not str(c).strip() for c in row):
                            continue
                        ord_no = str(row[idx_ord_no]).strip() if idx_ord_no >= 0 and idx_ord_no < len(row) else ""
                        ord_time = str(row[idx_time]).strip() if idx_time >= 0 and idx_time < len(row) else ""
                        ticker = str(row[idx_ticker]).strip().upper() if idx_ticker >= 0 and idx_ticker < len(row) else ""
                        order_type = str(row[idx_type]).strip() if idx_type >= 0 and idx_type < len(row) else ""
                        ord_qty = str(row[idx_ord_qty]).strip() if idx_ord_qty >= 0 and idx_ord_qty < len(row) else ""
                        exec_qty = str(row[idx_exec_qty]).strip() if idx_exec_qty >= 0 and idx_exec_qty < len(row) else ""
                        ord_price = str(row[idx_ord_price]).strip() if idx_ord_price >= 0 and idx_ord_price < len(row) else ""
                        exec_price = str(row[idx_exec_price]).strip() if idx_exec_price >= 0 and idx_exec_price < len(row) else ""
                        if ord_no or ord_time:
                            existing_keys.add(f"{ord_no}|{ticker}|{ord_time}|{order_type}|{ord_qty}|{exec_qty}|{ord_price}|{exec_price}")
                    logger.info(f"[ExecutionHistory] 기존 시트 데이터 행 {len(all_values) - 1}건, 기존 복합키 {len(existing_keys)}개 수집")
                else:
                    logger.info("[ExecutionHistory] 기존 시트에 데이터 없음 (헤더만 있거나 빈 시트)")
            except Exception as e:
                logger.warning(f"[ExecutionHistory] 기존 시트 레코드 수집 실패: {e}")

            # 2. 신규 이력 추가
            new_rows = []
            skipped_existing = 0
            for h in history:
                # TTTS3012R(체결기준) 데이터 형식인지 확인
                # - 체결기준: {code, name, qty, executed_qty, unexecuted_qty, avg_price, executed_price, current_price, pnl_rate}
                # - 기존 주문이력: {order_no, order_time, symbol, order_type, qty, executed_qty, price, executed_price, status}
                is_exec_balance_format = "code" in h and "executed_qty" in h and "unexecuted_qty" in h

                if is_exec_balance_format:
                    # TTTS3012R 체결기준 데이터
                    ticker = str(h.get("code", "")).strip().upper()
                    order_type = "체결기준"
                    qty = int(h.get("qty", 0) or 0)
                    exec_qty = int(h.get("executed_qty", 0) or 0)
                    unexec_qty = int(h.get("unexecuted_qty", 0) or 0)
                    price = float(h.get("avg_price", 0.0) or 0.0)
                    exec_price = float(h.get("executed_price", 0.0) or 0.0)
                    ord_no = f"EXEC_{ticker}"
                    ord_time = now_str
                    status = "체결" if exec_qty > 0 else "미체결"
                    # 체결기준 데이터는 티커+체결수량+체결단가로 중복 판단
                    dedup_key = f"{ord_no}|{ticker}|{ord_time}|{order_type}|{qty}|{exec_qty}|{price}|{exec_price}"
                else:
                    # 기존 주문이력 데이터
                    ord_no = str(h.get("order_no", "")).strip()
                    ord_time = str(h.get("order_time", "")).strip()
                    ticker = str(h.get("symbol", "")).strip().upper()
                    order_type = str(h.get("order_type", "-")).strip()
                    qty = int(h.get("qty", 0) or 0)
                    exec_qty = int(h.get("executed_qty", 0) or 0)
                    price = float(h.get("price", 0.0) or 0.0)
                    exec_price = float(h.get("executed_price", 0.0) or 0.0)
                    status = str(h.get("status", "-")).strip()
                    dedup_key = f"{ord_no}|{ticker}|{ord_time}|{order_type}|{qty}|{exec_qty}|{price}|{exec_price}"

                if not ticker:
                    continue

                if dedup_key in existing_keys:
                    skipped_existing += 1
                    logger.debug(f"[ExecutionHistory] 기존 키로 스킵: {dedup_key}")
                    continue

                existing_keys.add(dedup_key)
                total_amt = exec_qty * exec_price if exec_qty > 0 else (qty * price)

                new_rows.append([
                    ord_time,
                    ticker,
                    order_type,
                    qty,
                    exec_qty,
                    round(price, 2),
                    round(exec_price, 2),
                    round(total_amt, 2),
                    status,
                    ord_no,
                    now_str
                ])

            if new_rows:
                self.history_worksheet.append_rows(new_rows)
                logger.info(f"📊 Google Sheet 'ExecutionHistory'에 신규 이력 {len(new_rows)}건 누적 동기화 성공 (총 {len(history)}건 중 기존키 스킵 {skipped_existing}건)")
            else:
                logger.info(f"[ExecutionHistory] 신규 추가 없음 (총 {len(history)}건 중 기존키 스킵 {skipped_existing}건, 모두 기존 데이터와 중복)")
        except Exception as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                logger.debug("Google Sheet ExecutionHistory API 호출 할당량 초과 (다음 턴 재시도)")
            else:
                logger.warning(f"Google Sheet ExecutionHistory 동기화 예외: {e}")

    def record_completed_cycle(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        completed_round: float,
        qty: int,
        avg_price: float,
        sell_price: float,
        status: str = "COMPLETED"
    ):
        """
        무한매수 전량 익절 매도 완료 시, 완료된 차수의 최종 실현 손익 및 주요 정보를 'CompletedTrades' 워크시트에 기록
        """
        if not self.is_connected:
            return

        try:
            # CompletedTrades 워크시트 확보 시도
            if not self.completed_worksheet and self.spreadsheet:
                try:
                    self.completed_worksheet = self.spreadsheet.worksheet("CompletedTrades")
                except Exception:
                    self.completed_worksheet = self.spreadsheet.add_worksheet(title="CompletedTrades", rows="500", cols="14")
                    headers = ["완료일시", "티커", "시작일자", "매도일자", "완료회차", "매도수량", "매수평단가($)", "매도단가($)", "총매수금액($)", "총매도금액($)", "실현손익($)", "수익률(%)", "상태"]
                    self.completed_worksheet.append_row(headers)

            if not self.completed_worksheet:
                return

            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            total_buy_amt = qty * avg_price if qty > 0 and avg_price > 0 else 0.0
            total_sell_amt = qty * sell_price if qty > 0 and sell_price > 0 else 0.0
            pnl = total_sell_amt - total_buy_amt
            roi_pct = (pnl / total_buy_amt * 100) if total_buy_amt > 0 else 0.0

            row = [
                now_str,
                symbol.upper(),
                start_date or "-",
                end_date or datetime.date.today().strftime("%Y-%m-%d"),
                completed_round,
                qty,
                round(avg_price, 2),
                round(sell_price, 2),
                round(total_buy_amt, 2),
                round(total_sell_amt, 2),
                round(pnl, 2),
                round(roi_pct, 2),
                status
            ]

            self.completed_worksheet.append_row(row)
            logger.info(f"📊 Google Sheet 'CompletedTrades'에 [{symbol}] 무한매수 완료 일지 기록 성공 (실현손익: ${pnl:.2f}, 수익률: {roi_pct:.2f}%)")
        except Exception as e:
            logger.warning(f"Google Sheet CompletedTrades 기록 예외: {e}")

    def get_completed_trades(self, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Google Sheet 'CompletedTrades' 워크시트에서 전량 익절 매도 완료 이력 목록을 조회
        """
        if not self.is_connected:
            return []

        try:
            if not self.completed_worksheet and self.spreadsheet:
                try:
                    self.completed_worksheet = self.spreadsheet.worksheet("CompletedTrades")
                except Exception:
                    return []

            if not self.completed_worksheet:
                return []

            records = self.completed_worksheet.get_all_records()
            if records and limit and len(records) > limit:
                return records[-limit:]
            return records or []
        except Exception as e:
            logger.warning(f"Google Sheet CompletedTrades 조회 예외: {e}")
            return []


    def sync_settings_to_sheet(self, settings: Dict[str, Any]) -> tuple:
        """
        무한매수 설정값을 'Settings' 워크시트에 저장
        - settings: {"infinite_stocks": [...], "infinite_stock_configs": {...}, ...}
        - UI에서 설정 변경 시 호출되어 Google Sheet에 영속 저장
        :return: (성공 여부: bool, 결과 메시지: str)
        """
        if not self.is_connected or not self.settings_worksheet:
            err_msg = "Google Sheets가 연결되지 않았거나 'Settings' 워크시트를 찾을 수 없습니다."
            logger.warning(err_msg)
            return False, err_msg

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            headers = ["설정키", "설정값", "설명", "최종갱신시각"]

            # 설정 설명을 위한 매핑 dict
            key_descriptions = {
                "infinite_stocks": "무한매수 대상 종목 티커 목록",
                "infinite_stock_configs": "종목별 상세 매수/매도 파라미터 (JSON)",
                "max_stocks_holding": "최대 보유 종목 수",
                "api_call_delay": "API 호출 지연 시간 (초)",
                "infinite_total_budget_usd": "종목당 총 예산 ($)",
                "infinite_division_count": "총 분할 횟수",
                "infinite_target_roi": "전량 익절 목표 수익률",
                "infinite_exhaust_action": "소진 시 대응 모드",
                "infinite_exhaust_target_roi": "소진 시 탈출 목표 수익률"
            }

            # 설정값을 문자열로 변환 (리스트는 쉼표 구분 문자열로, dict는 JSON 문자열로)
            all_rows = [headers]
            for key, value in settings.items():
                if isinstance(value, list):
                    value_str = ", ".join(str(v) for v in value)
                elif isinstance(value, dict):
                    value_str = json.dumps(value, ensure_ascii=False)
                else:
                    value_str = str(value)
                desc = key_descriptions.get(key, "")
                all_rows.append([key, value_str, desc, now_str])

            # 원자적 업데이트: 시트 클리어 후 전체 데이터 일괄 업데이트
            self.settings_worksheet.clear()
            self.settings_worksheet.update(all_rows, range_name=f"A1:D{len(all_rows)}")
            
            success_msg = f"📊 Google Sheet 'Settings' 워크시트에 설정값 {len(all_rows)-1}건 영속 저장 완료 ({now_str})"
            logger.info(success_msg)
            return True, success_msg
        except Exception as e:
            err_msg = f"Google Sheet Settings 저장 실패: {e}"
            if "429" in str(e) or "Quota exceeded" in str(e):
                err_msg = "Google Sheet API 호출 한도 초과 (잠시 후 다시 시도하세요)"
                logger.debug(err_msg)
            else:
                logger.warning(err_msg)
            return False, err_msg

    def read_settings_from_sheet(self) -> Dict[str, Any]:
        """
        Google Sheet 'Settings' 워크시트에서 무한매수 설정값 읽어오기
        - GitHub Actions 자동 실행 시에도 이 값을 읽어 동일한 설정 적용
        - 반환: {"infinite_stocks": [...], "infinite_stock_configs": {...}, ...}
        """
        if not self.is_connected or not self.settings_worksheet:
            return {}

        settings = {}
        try:
            records = self.settings_worksheet.get_all_records()
            for rec in records:
                key = str(rec.get("설정키", "")).strip()
                value = str(rec.get("설정값", "")).strip()
                if not key or not value:
                    continue

                # 값 타입 변환
                if key == "infinite_stocks":
                    settings[key] = [s.strip().upper() for s in value.split(",") if s.strip()]
                elif key == "infinite_stock_configs":
                    # JSON 문자열로 저장된 종목별 설정 파싱
                    try:
                        parsed = json.loads(value)
                        if isinstance(parsed, dict):
                            settings[key] = parsed
                    except (json.JSONDecodeError, ValueError):
                        logger.warning(f"Google Sheet 'infinite_stock_configs' JSON 파싱 실패: {value[:100]}...")
                elif key in ("infinite_total_budget_usd", "infinite_target_roi", "infinite_exhaust_target_roi", "api_call_delay"):
                    try:
                        settings[key] = float(value)
                    except ValueError:
                        settings[key] = value
                elif key in ("infinite_division_count", "max_stocks_holding"):
                    try:
                        settings[key] = int(float(value))
                    except ValueError:
                        settings[key] = value
                elif key == "infinite_exhaust_action":
                    settings[key] = str(value).strip().upper()
                else:
                    settings[key] = value

            if settings:
                logger.info(f"📊 Google Sheet 'Settings'에서 설정값 {len(settings)}건 불러오기 성공")
        except Exception as e:
            logger.warning(f"Google Sheet Settings 읽기 실패: {e}")
        return settings


# 하위 호환성을 위한 별칭
GoogleSheetManager = InfiniteSheetManager

_infinite_sheet_manager_instance: Optional[InfiniteSheetManager] = None

def get_infinite_sheet_manager() -> InfiniteSheetManager:
    """InfiniteSheetManager 싱글톤 인스턴스 반환"""
    global _infinite_sheet_manager_instance
    if _infinite_sheet_manager_instance is None:
        _infinite_sheet_manager_instance = InfiniteSheetManager()
    return _infinite_sheet_manager_instance

