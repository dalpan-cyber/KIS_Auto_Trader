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
        self.history_worksheet: Optional[Any] = None
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

        # 3. 로컬 서비스 계정 파일 검색 (gcp_key.json, service_account.json)
        possible_files = ["gcp_key.json", "service_account.json", "credentials.json"]
        for fpath in possible_files:
            if os.path.exists(fpath):
                try:
                    logger.info(f"로컬 파일 {fpath}에서 서비스 계정 로드 성공")
                    return Credentials.from_service_account_file(fpath, scopes=self.SCOPES)
                except Exception as e:
                    logger.warning(f"로컬 파일 {fpath} 로드 실패: {e}")

        return None

    def _connect(self) -> bool:
        """Google Sheet 서비스 연결 및 워크시트 초기화"""
        try:
            creds = self._get_credentials()
            if not creds:
                logger.info("GCP 서비스 계정 인증 정보가 설정되지 않았습니다. 로컬 JSON 저장소만 사용합니다.")
                self.is_connected = False
                return False

            self.client = gspread.authorize(creds)

            # 스프레드시트 열기 (KEY 우선, 없으면 NAME)
            if self.sheet_key:
                self.spreadsheet = self.client.open_by_key(self.sheet_key)
            else:
                try:
                    self.spreadsheet = self.client.open(self.sheet_name)
                except gspread.exceptions.SpreadsheetNotFound:
                    logger.info(f"구글 시트 '{self.sheet_name}' 생성 중...")
                    self.spreadsheet = self.client.create(self.sheet_name)

            # 'State' 워크시트 준비
            try:
                self.state_worksheet = self.spreadsheet.worksheet("State")
            except Exception:
                self.state_worksheet = self.spreadsheet.add_worksheet(title="State", rows="50", cols="10")
                headers = ["티커", "진행회차", "총예산($)", "평단가($)", "누적수량", "목표수익률(%)", "상태", "마지막주문일자", "최종갱신시각"]
                self.state_worksheet.append_row(headers)

            # 'History' 워크시트 준비
            try:
                self.history_worksheet = self.spreadsheet.worksheet("History")
            except Exception:
                self.history_worksheet = self.spreadsheet.add_worksheet(title="History", rows="1000", cols="12")
                headers = ["일시", "티커", "구분", "수량", "단가($)", "총금액($)", "회차", "평단가($)", "누적수량", "수익률(%)", "비고/상태"]
                self.history_worksheet.append_row(headers)

            self.is_connected = True
            logger.info("🟢 Google Sheets 연동 및 워크시트 초기화 완료!")
            return True
        except Exception as e:
            logger.warning(f"Google Sheets 연결 실패: {e}")
            self.is_connected = False
            return False

    def sync_all_states(self, states: Dict[str, Dict[str, Any]]):
        """전체 종목 상태를 'State' 워크시트에 반영"""
        if not self.is_connected or not self.state_worksheet:
            return

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            all_records = self.state_worksheet.get_all_records()
            ticker_row_map = {}
            for idx, rec in enumerate(all_records, start=2):
                if rec.get("티커"):
                    ticker_row_map[str(rec["티커"]).upper()] = idx

            for symbol, state in states.items():
                sym_upper = symbol.upper()
                row_data = [
                    sym_upper,
                    state.get("current_round", 0),
                    state.get("total_budget_usd", 0.0),
                    state.get("avg_price", 0.0),
                    state.get("total_qty", 0),
                    round(state.get("target_roi", 0.10) * 100, 1),
                    state.get("status", "IDLE"),
                    state.get("last_order_date", "-"),
                    now_str
                ]

                if sym_upper in ticker_row_map:
                    row_idx = ticker_row_map[sym_upper]
                    self.state_worksheet.update(f"A{row_idx}:I{row_idx}", [row_data])
                else:
                    self.state_worksheet.append_row(row_data)

            logger.debug("Google Sheet 'State' 워크시트 동기화 성공")
        except Exception as e:
            logger.warning(f"Google Sheet State 동기화 예외: {e}")

    def append_history_entry(
        self,
        symbol: str,
        entry_type: str,
        qty: int,
        price: float,
        round_val: float = 0.0,
        avg_price: float = 0.0,
        total_qty: int = 0,
        roi_pct: float = 0.0,
        note: str = ""
    ):
        """매매 및 주문 실패 이력을 'History' 워크시트에 추가"""
        if not self.is_connected or not self.history_worksheet:
            return

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            tot_amt = round(qty * price, 2)
            row_data = [
                now_str,
                symbol.upper(),
                entry_type,
                qty,
                round(price, 2),
                tot_amt,
                round_val,
                round(avg_price, 2),
                total_qty,
                round(roi_pct, 2) if roi_pct != 0.0 else "-",
                note
            ]
            self.history_worksheet.append_row(row_data)
            logger.info(f"📊 Google Sheet History 기록 완료: [{symbol}] {entry_type} ({qty}주 @ ${price:.2f})")
        except Exception as e:
            logger.warning(f"Google Sheet History 추가 실패: {e}")
