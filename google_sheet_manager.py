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

    
