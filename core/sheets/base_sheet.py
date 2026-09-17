"""
Base Google Sheet Manager Module (core/sheets/base_sheet.py)
Google Sheets API 연동을 위한 공통 인증, 스프레드시트 연결 및 워크시트 관리 기반 클래스
"""
import os
import glob
import json
import logging
from typing import Optional, Any, List

logger = logging.getLogger("BaseSheetManager")

# Google Sheets 라이브러리 동적 로드
GSPREAD_AVAILABLE = False
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    logger.warning("gspread 또는 google-auth 패키지가 설치되지 않았습니다. 구글 시트 연동이 비활성화됩니다.")


class BaseSheetManager:
    """구글 시트 연동 기반 클래스 (인증, 연결, 워크시트 탐색 공통화)"""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    def __init__(
        self,
        sheet_name: str,
        sheet_key: str = "",
        enabled: bool = True,
        service_account_file: Optional[str] = None
    ):
        self.sheet_name = sheet_name
        self.sheet_key = sheet_key
        self.enabled = enabled
        self.service_account_file = service_account_file

        self.client: Optional[Any] = None
        self.spreadsheet: Optional[Any] = None
        self.is_connected: bool = False

        if self.enabled and GSPREAD_AVAILABLE:
            self._connect()

    def _get_credentials(self) -> Optional[Any]:
        """다양한 소스(Streamlit Secrets, 환경변수, 로컬 파일)에서 GCP Credentials 자동 획득"""
        # 1. Streamlit Secrets 확인
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                if "gcp_service_account" in st.secrets:
                    secret_dict = dict(st.secrets["gcp_service_account"])
                    logger.info("Streamlit Secrets [gcp_service_account]에서 GCP 인증 정보 로드 성공")
                    return Credentials.from_service_account_info(secret_dict, scopes=self.SCOPES)
                elif "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
                    val = st.secrets["GCP_SERVICE_ACCOUNT_JSON"]
                    if isinstance(val, str) and val.strip().startswith("{"):
                        return Credentials.from_service_account_info(json.loads(val), scopes=self.SCOPES)
        except Exception:
            pass

        # 2. 환경변수 GCP_SERVICE_ACCOUNT_JSON (JSON 문자열)
        env_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")
        if env_json and env_json.strip().startswith("{"):
            try:
                info = json.loads(env_json)
                logger.info("환경변수 GCP_SERVICE_ACCOUNT_JSON에서 인증 정보 로드 성공")
                return Credentials.from_service_account_info(info, scopes=self.SCOPES)
            except Exception as e:
                logger.warning(f"환경변수 GCP_SERVICE_ACCOUNT_JSON 파싱 실패: {e}")

        # 3. 명시적 파일 경로 확인
        if self.service_account_file and os.path.exists(self.service_account_file):
            try:
                logger.info(f"지정된 GCP 서비스 계정 파일 로드: {self.service_account_file}")
                return Credentials.from_service_account_file(self.service_account_file, scopes=self.SCOPES)
            except Exception as e:
                logger.warning(f"GCP 파일({self.service_account_file}) 로드 실패: {e}")

        # 4. 프로젝트 디렉토리 자동 탐색 (kis-auto-trader-*.json, gcp_key.json 등)
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        patterns = [
            os.path.join(base_dir, "kis-auto-trader-*.json"),
            os.path.join(base_dir, "*service_account*.json"),
            os.path.join(base_dir, "gcp_key.json"),
            os.path.join(base_dir, "service_account.json"),
            os.path.join(base_dir, "credentials.json"),
        ]
        for pattern in patterns:
            matched = glob.glob(pattern)
            if matched:
                key_path = matched[0]
                try:
                    logger.info(f"로컬 GCP 키 파일 탐색 성공: {os.path.basename(key_path)}")
                    return Credentials.from_service_account_file(key_path, scopes=self.SCOPES)
                except Exception as e:
                    logger.warning(f"GCP 키 파일({key_path}) 로드 실패: {e}")

        logger.warning("유효한 GCP Service Account 인증 정보를 찾을 수 없습니다.")
        return None

    def _connect(self) -> bool:
        """Google Sheets 클라이언트 인증 및 스프레드시트 오픈"""
        creds = self._get_credentials()
        if not creds:
            logger.warning("GCP 인증 실패로 구글 시트 연동이 비활성화됩니다.")
            return False

        try:
            self.client = gspread.authorize(creds)
            # 1. sheet_key로 우선 접근
            if self.sheet_key:
                try:
                    self.spreadsheet = self.client.open_by_key(self.sheet_key)
                    self.is_connected = True
                    logger.info(f"🟢 Google Sheets 연결 성공! (계정: {creds.service_account_email} | 시트 ID: {self.sheet_key})")
                    self._init_worksheets()
                    return True
                except Exception as e:
                    logger.warning(f"시트 ID({self.sheet_key}) 오픈 실패: {e}. 시트 이름({self.sheet_name})으로 대체 시도...")

            # 2. sheet_name으로 접근
            if self.sheet_name:
                self.spreadsheet = self.client.open(self.sheet_name)
                self.is_connected = True
                logger.info(f"🟢 Google Sheets 연결 성공! (계정: {creds.service_account_email} | 시트: {self.sheet_name})")
                self._init_worksheets()
                return True

        except Exception as e:
            logger.warning(f"Google Sheets 연결 실패: {e}")
            self.is_connected = False
            return False

        return False

    def _init_worksheets(self):
        """자식 클래스에서 필요한 개별 워크시트 초기화 메서드 (오버라이드 구현)"""
        pass

    def _get_or_create_worksheet(
        self,
        title: str,
        headers: List[str],
        rows: str = "100",
        cols: str = "10"
    ) -> Optional[Any]:
        """워크시트를 조회하고, 존재하지 않으면 신규 생성 및 헤더 초기화"""
        if not self.spreadsheet:
            return None
        try:
            ws = self.spreadsheet.worksheet(title)
            return ws
        except gspread.WorksheetNotFound:
            try:
                ws = self.spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
                if headers:
                    ws.append_row(headers)
                logger.info(f"Google Sheets 신규 워크시트 '{title}' 생성 완료")
                return ws
            except Exception as e:
                logger.warning(f"워크시트 '{title}' 생성 실패: {e}")
                return None
        except Exception as e:
            logger.warning(f"워크시트 '{title}' 조회 실패: {e}")
            return None
