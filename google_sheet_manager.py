"""
Google Sheets 연동 및 동기화 매니저 모듈 (google_sheet_manager.py)
Streamlit Cloud 및 로컬 환경에서 무한매수법 상태(State) 및 매매/실패 이력(History)을 구글 시트와 실시간 동기화합니다.
"""
import os
import json
import logging
import datetime
from typing import Dict, Any, List, Optional

import config

logger = logging.getLogger("GoogleSheetManager")

# Google Sheets 라이브러리 (gspread, google.oauth2.service_account) 동적 로드
GSPREAD_AVAILABLE = False
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    logger.warning("gspread 또는 google-auth 패키지가 설치되지 않았습니다. 구글 시트 연동이 비활성화됩니다.")


class GoogleSheetManager:
    """Google Sheets 매매일지 및 상태 동기화 관리 클래스"""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    def __init__(
        self,
        sheet_name: Optional[str] = None,
        sheet_key: Optional[str] = None,
        enabled: Optional[bool] = None
    ):
        self.sheet_name = sheet_name or getattr(config, "GOOGLE_SHEET_NAME", "KIS_무한매수_매매일지")
        self.sheet_key = sheet_key or getattr(config, "GOOGLE_SHEET_KEY", "")
        self.enabled = enabled if enabled is not None else getattr(config, "GOOGLE_SHEET_ENABLED", True)

        self.client: Optional[Any] = None
        self.spreadsheet: Optional[Any] = None
        self.state_worksheet: Optional[Any] = None
        self.holdings_worksheet: Optional[Any] = None
        self.history_worksheet: Optional[Any] = None
        self.exec_balance_worksheet: Optional[Any] = None
        self.is_connected = False

        if self.enabled and GSPREAD_AVAILABLE:
            self._connect()

    def _get_credentials(self) -> Optional[Any]:
        """다양한 경로에서 GCP Service Account Credentials 획득"""
        # 1. Streamlit Secrets (st.secrets["gcp_service_account"])
        try:
            import streamlit as st
            if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
                secret_dict = dict(st.secrets["gcp_service_account"])
                logger.info("Streamlit Secrets에서 GCP 서비스 계정 정보 로드 성공")
                return Credentials.from_service_account_info(secret_dict, scopes=self.SCOPES)
        except Exception:
            pass

        # 2. 환경변수 GCP_SERVICE_ACCOUNT_JSON (JSON 문자열)
        env_json = getattr(config, "GCP_SERVICE_ACCOUNT_JSON", "") or os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")
        if env_json and env_json.strip().startswith("{"):
            try:
                info = json.loads(env_json)
                logger.info("환경변수 GCP_SERVICE_ACCOUNT_JSON에서 정보 로드 성공")
                return Credentials.from_service_account_info(info, scopes=self.SCOPES)
            except Exception as e:
                logger.warning(f"환경변수 GCP_SERVICE_ACCOUNT_JSON 파싱 실패: {e}")

        # 3. 로컬 서비스 계정 파일 자동 탐색 (gcp_key.json, service_account.json 또는 GCP JSON 키 파일)
        possible_files = ["gcp_key.json", "service_account.json", "credentials.json", "gcp_service_account.json"]
        try:
            for fname in os.listdir("."):
                if fname.endswith(".json") and fname not in possible_files:
                    if not fname.startswith("token_kis_") and not fname.startswith("infinite_"):
                        possible_files.append(fname)
        except Exception:
            pass

        for fpath in possible_files:
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as _kf:
                        _content = _kf.read()
                        if "private_key" in _content and "service_account" in _content:
                            logger.info(f"로컬 GCP 서비스 계정 인증키 파일 탐색 성공: {fpath}")
                            return Credentials.from_service_account_file(fpath, scopes=self.SCOPES)
                except Exception as e:
                    logger.warning(f"로컬 파일 {fpath} 로드 실패: {e}")

        return None

    def _connect(self) -> bool:
        """Google Sheet 서비스 연결 및 워크시트 초기화"""
        try:
            creds = self._get_credentials()
            if not creds:
                logger.warning(
                    "💡 [Google Sheets 안내] GCP 서비스 계정 인증키(gcp_key.json)가 폴더에 없거나 환경변수/Secrets가 설정되지 않아 구글 시트 연동을 건너땁니다. "
                    "(구글 콘솔에서 다운로드받은 JSON 키 파일을 'gcp_key.json'으로 프로젝트 폴더에 넣어주시면 자동 연동됩니다.)"
                )
                self.is_connected = False
                return False

            sa_email = getattr(creds, "service_account_email", "알 수 없음")
            self.client = gspread.authorize(creds)

            # 스프레드시트 열기 (KEY 우선, 없으면 NAME)
            if self.sheet_key:
                self.spreadsheet = self.client.open_by_key(self.sheet_key)
            else:
                try:
                    self.spreadsheet = self.client.open(self.sheet_name)
                except gspread.exceptions.SpreadsheetNotFound:
                    logger.info(f"구글 시트 '{self.sheet_name}' 생성 시도 (서비스 계정: {sa_email})...")
                    self.spreadsheet = self.client.create(self.sheet_name)

            # 'State' 워크시트 준비
            try:
                self.state_worksheet = self.spreadsheet.worksheet("State")
            except Exception:
                self.state_worksheet = self.spreadsheet.add_worksheet(title="State", rows="50", cols="10")
                headers = ["티커", "시작일", "진행회차", "총예산($)", "목표수익률(%)", "상태", "최종갱신시각"]
                self.state_worksheet.append_row(headers)

            # 'Holdings' 워크시트 준비 (주식평가 금액 - KIS API 실계좌)
            try:
                self.holdings_worksheet = self.spreadsheet.worksheet("Holdings")
            except Exception:
                self.holdings_worksheet = self.spreadsheet.add_worksheet(title="Holdings", rows="100", cols="10")
                headers = ["티커", "종목명", "보유수량", "평단가($)", "현재가($)", "평가금액($)", "평가손익($)", "수익률(%)", "최종갱신시각"]
                self.holdings_worksheet.append_row(headers)

            # 'ExecutionHistory' 워크시트 준비 (매수/매도 & 체결/실패 이력)
            try:
                self.history_worksheet = self.spreadsheet.worksheet("ExecutionHistory")
            except Exception:
                self.history_worksheet = self.spreadsheet.add_worksheet(title="ExecutionHistory", rows="1000", cols="12")
                headers = ["일시", "티커", "구분", "주문수량", "체결수량", "주문단가($)", "체결단가($)", "총금액($)", "상태", "주문번호", "최종갱신시각"]
                self.history_worksheet.append_row(headers)

            # 'ExecutionBalance' 워크시트 준비 (체결기준 현물 잔고 - TTTT1006R)
            try:
                self.exec_balance_worksheet = self.spreadsheet.worksheet("ExecutionBalance")
            except Exception:
                self.exec_balance_worksheet = self.spreadsheet.add_worksheet(title="ExecutionBalance", rows="100", cols="12")
                headers = ["티커", "종목명", "보유수량", "체결수량", "미체결수량", "평단가($)", "체결단가($)", "현재가($)", "수익률(%)", "최종갱신시각"]
                self.exec_balance_worksheet.append_row(headers)

            self.is_connected = True
            logger.info(f"🟢 Google Sheets 연동 성공! (서비스 계정: {sa_email} | 시트: {self.spreadsheet.title})")
            return True
        except Exception as e:
            sa_email = getattr(creds, "service_account_email", "알 수 없음") if 'creds' in locals() and creds else "미인증"
            logger.warning(
                f"🚨 Google Sheets 연결/접근 실패: {e}\n"
                f"💡 [필수 체크] 구글 시트 상단 '공유' 버튼에서 아래 서비스 계정 이메일을 '편집자(Editor)'로 추가했는지 확인하세요:\n"
                f"   👉 GCP Service Account Email: {sa_email}"
            )
            self.is_connected = False
            return False

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
        - history: get_overseas_execution_balance() 결과 리스트 (TTTT1006R 체결기준)
        - 기존 수동 작성건이나 이전 기록을 지우지 않고 새 이력만 추가(병합)
        - TTTT1006R(체결기준) 데이터 형식: {code, name, qty, executed_qty, unexecuted_qty, avg_price, executed_price, current_price, pnl_rate}
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
                # TTTT1006R(체결기준) 데이터 형식인지 확인
                # - 체결기준: {code, name, qty, executed_qty, unexecuted_qty, avg_price, executed_price, current_price, pnl_rate}
                # - 기존 주문이력: {order_no, order_time, symbol, order_type, qty, executed_qty, price, executed_price, status}
                is_exec_balance_format = "code" in h and "executed_qty" in h and "unexecuted_qty" in h

                if is_exec_balance_format:
                    # TTTT1006R 체결기준 데이터
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
                    logger.info(f"[ExecutionHistory] 기존 키로 스킵: {dedup_key}")
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
