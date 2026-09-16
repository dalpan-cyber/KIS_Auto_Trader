"""
Google Sheets 연동 및 동기화 매니저 모듈 (google_sheet_manager.py)
KIS Auto Trader v2.0의 설정, 매수/매도 제안, 포지션 추적 상태, 손절 쿨다운, 매매일지를 구글 시트와 실시간 동기화합니다.
"""
import os
import json
import logging
import datetime
from typing import Dict, Any, List, Optional

import app_config as config

logger = logging.getLogger("GoogleSheetManager")

GSPREAD_AVAILABLE = False
try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    logger.warning("gspread 또는 google-auth 패키지가 설치되지 않았습니다. 구글 시트 연동이 비활성화됩니다.")


class DomesticSheetManager:
    """Google Sheets 국내 퀀트 매매일지 및 상태 동기화 관리 클래스"""

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
        self.sheet_name = sheet_name or getattr(config, "DOMESTIC_GOOGLE_SHEET_NAME", getattr(config, "GOOGLE_SHEET_NAME", "KIS_Auto2_매매일지"))
        self.sheet_key = sheet_key or getattr(config, "DOMESTIC_GOOGLE_SHEET_KEY", getattr(config, "GOOGLE_SHEET_KEY", ""))
        if not self.sheet_key:
            try:
                import streamlit as st
                if hasattr(st, "secrets"):
                    if "DOMESTIC_GOOGLE_SHEET_KEY" in st.secrets:
                        self.sheet_key = str(st.secrets["DOMESTIC_GOOGLE_SHEET_KEY"])
                    elif "GOOGLE_SHEET_KEY" in st.secrets:
                        self.sheet_key = str(st.secrets["GOOGLE_SHEET_KEY"])
            except Exception:
                pass
        self.enabled = enabled if enabled is not None else getattr(config, "GOOGLE_SHEET_ENABLED", True)

        self.client: Optional[Any] = None
        self.spreadsheet: Optional[Any] = None
        self.settings_worksheet: Optional[Any] = None
        self.proposals_worksheet: Optional[Any] = None
        self.proposals_state_worksheet: Optional[Any] = None
        self.positions_worksheet: Optional[Any] = None
        self.cooldown_worksheet: Optional[Any] = None
        self.trade_history_worksheet: Optional[Any] = None
        self.is_connected = False

        if self.enabled and GSPREAD_AVAILABLE:
            self._connect()

    def _get_credentials(self) -> Optional[Any]:
        """다양한 경로에서 GCP Service Account Credentials 획득"""
        # 1. Streamlit Secrets (st.secrets["gcp_service_account"] 또는 st.secrets["GCP_SERVICE_ACCOUNT_JSON"])
        try:
            import streamlit as st
            if hasattr(st, "secrets"):
                if "gcp_service_account" in st.secrets:
                    secret_dict = dict(st.secrets["gcp_service_account"])
                    logger.info("Streamlit Secrets [gcp_service_account]에서 GCP 서비스 계정 정보 로드 성공")
                    return Credentials.from_service_account_info(secret_dict, scopes=self.SCOPES)
                elif "GCP_SERVICE_ACCOUNT_JSON" in st.secrets:
                    val = st.secrets["GCP_SERVICE_ACCOUNT_JSON"]
                    if isinstance(val, str) and val.strip().startswith("{"):
                        return Credentials.from_service_account_info(json.loads(val), scopes=self.SCOPES)
                    elif hasattr(val, "items"):
                        return Credentials.from_service_account_info(dict(val), scopes=self.SCOPES)
        except Exception as e:
            logger.debug(f"Streamlit Secrets GCP 로드 예외: {e}")

        # 2. 환경변수 GCP_SERVICE_ACCOUNT_JSON (JSON 문자열 또는 파일 경로)
        env_json = getattr(config, "GCP_SERVICE_ACCOUNT_JSON", "") or os.getenv("GCP_SERVICE_ACCOUNT_JSON", "")
        if env_json:
            env_json_str = env_json.strip()
            if env_json_str.startswith("{"):
                try:
                    info = json.loads(env_json_str)
                    logger.info("환경변수 GCP_SERVICE_ACCOUNT_JSON(JSON)에서 정보 로드 성공")
                    return Credentials.from_service_account_info(info, scopes=self.SCOPES)
                except Exception as e:
                    logger.warning(f"환경변수 GCP_SERVICE_ACCOUNT_JSON JSON 파싱 실패: {e}")
            elif os.path.exists(env_json_str):
                try:
                    logger.info(f"지정된 GCP 키 파일({env_json_str})에서 정보 로드 성공")
                    return Credentials.from_service_account_file(env_json_str, scopes=self.SCOPES)
                except Exception as e:
                    logger.warning(f"GCP 키 파일({env_json_str}) 로드 실패: {e}")

        # 3. 로컬 서비스 계정 파일 자동 탐색
        possible_files = [
            "kis-auto-trader-1024280eca64.json",
            "gcp_key.json",
            "service_account.json",
            "credentials.json"
        ]
        try:
            for fname in os.listdir(os.path.dirname(__file__) or "."):
                if fname.endswith(".json") and fname not in possible_files:
                    if fname.startswith("kis-auto-trader-") or fname.startswith("gcp_"):
                        possible_files.append(fname)
        except Exception:
            pass

        base_dir = os.path.dirname(__file__)
        for fname in possible_files:
            fpath = os.path.join(base_dir, fname) if base_dir else fname
            if os.path.exists(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8") as kf:
                        content = kf.read()
                        if "private_key" in content and "service_account" in content:
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
                    "💡 [Google Sheets 안내] GCP 서비스 계정 인증키 파일이 없거나 환경변수가 설정되지 않아 구글 시트 연동을 건너땁니다."
                )
                self.is_connected = False
                return False

            sa_email = getattr(creds, "service_account_email", "알 수 없음")
            self.client = gspread.authorize(creds)

            # 스프레드시트 열기 (KEY 우선, 없으면 NAME으로 열기 시도)
            if self.sheet_key:
                self.spreadsheet = self.client.open_by_key(self.sheet_key)
            else:
                try:
                    self.spreadsheet = self.client.open(self.sheet_name)
                except gspread.exceptions.SpreadsheetNotFound:
                    logger.info(f"구글 시트 '{self.sheet_name}'을 이름으로 찾지 못했습니다. 스프레드시트 생성을 시도합니다...")
                    try:
                        self.spreadsheet = self.client.create(self.sheet_name)
                    except Exception as create_err:
                        logger.warning(
                            f"💡 [Google Sheets 안내] 서비스 계정 직접 생성 실패 ({create_err}).\n"
                            f"   GCP 서비스 계정은 자체 드라이브 용량이 제공되지 않으므로,\n"
                            f"   사용자 본인의 구글 드라이브에서 새 스프레드시트를 만드신 후,\n"
                            f"   1) 우측 상단 [공유] 버튼에서 아래 서비스 계정 이메일을 '편집자(Editor)'로 추가하세요:\n"
                            f"      👉 {sa_email}\n"
                            f"   2) 스프레드시트 URL의 키(ID)를 .env 파일의 GOOGLE_SHEET_KEY=\"...\" 에 입력해주세요."
                        )
                        self.is_connected = False
                        return False

            # 1. 'Settings' 워크시트 (설정값 & 감시종목)
            self.settings_worksheet = self._get_or_create_worksheet(
                "Settings",
                headers=["설정키", "설정값", "설명", "최종갱신시각"],
                rows="100", cols="6"
            )

            # 2. 'Proposals' 워크시트 (15:10 스크리닝 매수/매도 제안)
            self.proposals_worksheet = self._get_or_create_worksheet(
                "Proposals",
                headers=["일시", "구분", "종목코드", "종목명", "현재가/추천가", "추천수량", "예상금액", "종합점수", "추세", "수급", "모멘텀", "거래량배수", "매매사유"],
                rows="500", cols="15"
            )

            # 3. 'PositionsState' 워크시트 (트레일링 스탑 포지션 추적 상태)
            self.positions_worksheet = self._get_or_create_worksheet(
                "PositionsState",
                headers=["종목코드", "종목명", "매수단가", "최고가", "1차익절완료", "매수전략", "갱신일시"],
                rows="100", cols="8"
            )

            # 4. 'Cooldown' 워크시트 (손절 쿨다운 관리)
            self.cooldown_worksheet = self._get_or_create_worksheet(
                "Cooldown",
                headers=["종목코드", "재매수가능일자", "등록일시"],
                rows="100", cols="5"
            )

            # 5. 'TradeHistory' 워크시트 (체결 일지)
            self.trade_history_worksheet = self._get_or_create_worksheet(
                "TradeHistory",
                headers=["체결일시", "구분", "종목코드", "종목명", "체결수량", "체결단가", "체결금액", "수익률(%)", "실현손익", "주문번호", "비고"],
                rows="1000", cols="12"
            )

            # 6. 'ProposalsState' 워크시트 (마지막 스크리닝 결과 및 관망/추천 종목 상태 보존)
            self.proposals_state_worksheet = self._get_or_create_worksheet(
                "ProposalsState",
                headers=["키", "값JSON", "갱신일시"],
                rows="30", cols="5"
            )

            self.is_connected = True
            logger.info(f"🟢 Google Sheets 연동 성공! (서비스 계정: {sa_email} | 시트: {self.spreadsheet.title})")
            return True
        except Exception as e:
            sa_email = getattr(creds, "service_account_email", "알 수 없음") if 'creds' in locals() and creds else "미인증"
            logger.warning(
                f"🚨 Google Sheets 연결 실패: {e}\n"
                f"💡 [필수 체크] 구글 시트 우측 상단 '공유' 버튼에서 아래 이메일을 '편집자(Editor)'로 추가하세요:\n"
                f"   👉 {sa_email}"
            )
            self.is_connected = False
            return False

    def _get_or_create_worksheet(self, title: str, headers: List[str], rows: str = "100", cols: str = "10"):
        """워크시트 가져오기 또는 생성"""
        if not self.spreadsheet:
            return None
        try:
            ws = self.spreadsheet.worksheet(title)
            return ws
        except Exception:
            try:
                ws = self.spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
                ws.append_row(headers)
                return ws
            except Exception as e:
                logger.warning(f"워크시트 '{title}' 생성 중 예외: {e}")
                return None

    # =========================================================================
    # 1. Settings (설정값 & 감시종목) 동기화
    # =========================================================================
    def sync_settings_to_sheet(self, settings: Dict[str, Any]) -> bool:
        """설정값을 'Settings' 워크시트에 저장"""
        if not self.is_connected or not self.settings_worksheet:
            return False

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows = []
            for key, val in settings.items():
                if isinstance(val, (dict, list)):
                    val_str = json.dumps(val, ensure_ascii=False)
                else:
                    val_str = str(val)
                rows.append([key, val_str, "", now_str])

            # 헤더 제외 기존 데이터 삭제 후 일괄 작성
            try:
                all_records = self.settings_worksheet.get_all_records()
                if all_records:
                    self.settings_worksheet.delete_rows(2, len(all_records) + 1)
            except Exception:
                pass

            if rows:
                self.settings_worksheet.append_rows(rows)
                logger.info(f"📊 Google Sheet 'Settings'에 {len(rows)}개 설정값 동기화 완료")
            return True
        except Exception as e:
            logger.warning(f"Google Sheet Settings 동기화 실패: {e}")
            return False

    def read_settings_from_sheet(self) -> Dict[str, Any]:
        """Google Sheet 'Settings'에서 설정값 읽기"""
        if not self.is_connected or not self.settings_worksheet:
            return {}

        settings = {}
        try:
            records = self.settings_worksheet.get_all_records()
            for rec in records:
                key = str(rec.get("설정키", "")).strip()
                val = str(rec.get("설정값", "")).strip()
                if not key or not val:
                    continue

                if val.startswith("{") or val.startswith("["):
                    try:
                        settings[key] = json.loads(val)
                        continue
                    except Exception:
                        pass

                # 불리언/숫자 파싱
                if val.lower() == "true":
                    settings[key] = True
                elif val.lower() == "false":
                    settings[key] = False
                else:
                    try:
                        if "." in val:
                            settings[key] = float(val)
                        else:
                            settings[key] = int(val)
                    except ValueError:
                        settings[key] = val

            return settings
        except Exception as e:
            logger.warning(f"Google Sheet Settings 읽기 실패: {e}")
            return {}

    # =========================================================================
    # 2. Proposals (스크리닝 매수/매도 제안) 동기화
    # =========================================================================
    def sync_proposals_to_sheet(self, proposals_data: Dict[str, Any]) -> bool:
        """15:10 스크리닝 매수/매도 제안을 'Proposals' 워크시트에 누적 기록"""
        if not self.is_connected or not self.proposals_worksheet:
            return False

        try:
            now_str = proposals_data.get("updated_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            buy_proposals = proposals_data.get("buy_proposals", [])
            sell_proposals = proposals_data.get("sell_proposals", [])

            rows = []
            for b in buy_proposals:
                reasons_str = "; ".join(b.get("reasons", []))
                rows.append([
                    now_str,
                    b.get("buy_type", "신규매수"),
                    b.get("code", ""),
                    b.get("name", ""),
                    b.get("current_price", 0),
                    b.get("recommended_qty", 0),
                    b.get("estimated_amount", 0),
                    b.get("score", 0),
                    b.get("trend_score", 0),
                    b.get("supply_score", 0),
                    b.get("momentum_score", 0),
                    b.get("vol_ratio", 0.0),
                    reasons_str
                ])

            for s in sell_proposals:
                reasons_str = "; ".join(s.get("reasons", []))
                rows.append([
                    now_str,
                    s.get("sell_type", "매도"),
                    s.get("code", ""),
                    s.get("name", ""),
                    s.get("current_price", 0),
                    s.get("sell_qty", 0),
                    int(s.get("current_price", 0) * s.get("sell_qty", 0)),
                    "", "", "", "", "",
                    reasons_str
                ])

            if rows:
                self.proposals_worksheet.append_rows(rows)
                logger.info(f"📊 Google Sheet 'Proposals'에 제안 {len(rows)}건 누적 저장 완료")
            return True
        except Exception as e:
            logger.warning(f"Google Sheet Proposals 동기화 실패: {e}")
            return False

    def sync_proposals_state_to_sheet(self, proposals_data: Dict[str, Any]) -> bool:
        """마지막 스크리닝 결과(추천, 관망 후보 등)를 'ProposalsState' 워크시트에 최신화"""
        if not self.is_connected or not self.proposals_state_worksheet:
            return False

        try:
            now_s = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            meta = {
                "generated_at": proposals_data.get("generated_at", now_s),
                "screening_type": proposals_data.get("screening_type", "CLOSING_BUY_1515"),
                "last_recommended_at": proposals_data.get("last_recommended_at", "-"),
                "sell_checked_at": proposals_data.get("sell_checked_at", "-"),
                "status": proposals_data.get("status", "READY"),
                "holdings_count": proposals_data.get("holdings_count", 0)
            }
            rows = [
                ["metadata", json.dumps(meta, ensure_ascii=False), now_s],
                ["buy_proposals", json.dumps(proposals_data.get("buy_proposals", []), ensure_ascii=False), now_s],
                ["last_recommended_proposals", json.dumps(proposals_data.get("last_recommended_proposals", []), ensure_ascii=False), now_s],
                ["top_candidates", json.dumps(proposals_data.get("top_candidates", []), ensure_ascii=False), now_s],
                ["sell_proposals", json.dumps(proposals_data.get("sell_proposals", []), ensure_ascii=False), now_s]
            ]

            # 기존 행 삭제 후 다시 기록
            try:
                all_records = self.proposals_state_worksheet.get_all_records()
                if all_records:
                    self.proposals_state_worksheet.delete_rows(2, len(all_records) + 1)
            except Exception:
                pass

            self.proposals_state_worksheet.append_rows(rows)
            logger.info("📊 Google Sheet 'ProposalsState'에 스크리닝 상태 최신화 완료")
            return True
        except Exception as e:
            logger.warning(f"Google Sheet ProposalsState 동기화 실패: {e}")
            return False

    def read_proposals_state_from_sheet(self) -> Dict[str, Any]:
        """Google Sheet 'ProposalsState'에서 마지막 스크리닝 상태 복원"""
        if not self.is_connected or not self.proposals_state_worksheet:
            return {}

        try:
            records = self.proposals_state_worksheet.get_all_records()
            data: Dict[str, Any] = {}
            for rec in records:
                key = str(rec.get("키", "")).strip()
                val_raw = rec.get("값JSON", "")
                if not key or not val_raw:
                    continue
                try:
                    val = json.loads(str(val_raw))
                    if key == "metadata" and isinstance(val, dict):
                        data.update(val)
                    else:
                        data[key] = val
                except Exception as ex:
                    logger.debug(f"ProposalsState 필드 '{key}' 파싱 실패: {ex}")
            return data
        except Exception as e:
            logger.warning(f"Google Sheet ProposalsState 읽기 실패: {e}")
            return {}

    # =========================================================================
    # 3. PositionsState (트레일링 스탑 포지션 추적) 동기화
    # =========================================================================
    def sync_positions_state_to_sheet(self, positions: Dict[str, Dict[str, Any]]) -> bool:
        """포지션 상태를 'PositionsState' 워크시트에 최신화"""
        if not self.is_connected or not self.positions_worksheet:
            return False

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows = []
            for code, data in positions.items():
                rows.append([
                    code,
                    data.get("name", code),
                    data.get("avg_buy_price", 0.0),
                    data.get("highest_price", 0.0),
                    "Y" if data.get("is_partial_sold", False) else "N",
                    data.get("strategy_display_name", data.get("strategy", "모멘텀")),
                    data.get("last_updated", data.get("updated_at", now_str))
                ])

            # 기존 데이터 삭제 후 최신 상태 작성
            try:
                all_records = self.positions_worksheet.get_all_records()
                if all_records:
                    self.positions_worksheet.delete_rows(2, len(all_records) + 1)
            except Exception:
                pass

            if rows:
                self.positions_worksheet.append_rows(rows)
            return True
        except Exception as e:
            logger.warning(f"Google Sheet PositionsState 동기화 실패: {e}")
            return False

    def read_positions_state_from_sheet(self) -> Dict[str, Dict[str, Any]]:
        """Google Sheet 'PositionsState'에서 포지션 상태 읽기"""
        if not self.is_connected or not self.positions_worksheet:
            return {}

        positions = {}
        try:
            records = self.positions_worksheet.get_all_records()
            for rec in records:
                code = str(rec.get("종목코드", "")).strip()
                if not code:
                    continue
                strat_raw = str(rec.get("매수전략", "momentum") or "momentum")
                positions[code] = {
                    "code": code,
                    "name": str(rec.get("종목명", code)),
                    "avg_buy_price": float(rec.get("매수단가", 0.0) or 0.0),
                    "highest_price": float(rec.get("최고가", 0.0) or 0.0),
                    "is_partial_sold": str(rec.get("1차익절완료", "N")).upper() in ("Y", "TRUE", "1"),
                    "strategy": strat_raw,
                    "strategy_display_name": strat_raw,
                    "last_updated": str(rec.get("갱신일시", "")),
                    "updated_at": str(rec.get("갱신일시", ""))
                }
            return positions
        except Exception as e:
            logger.warning(f"Google Sheet PositionsState 읽기 실패: {e}")
            return {}

    # =========================================================================
    # 4. Cooldown (손절 종목 재매수 쿨다운) 동기화
    # =========================================================================
    def sync_cooldown_to_sheet(self, cooldown_map: Dict[str, str]) -> bool:
        """쿨다운 목록을 'Cooldown' 워크시트에 최신화"""
        if not self.is_connected or not self.cooldown_worksheet:
            return False

        try:
            now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            rows = []
            for code, end_date in cooldown_map.items():
                rows.append([code, str(end_date), now_str])

            # 기존 데이터 삭제 후 최신화
            try:
                all_records = self.cooldown_worksheet.get_all_records()
                if all_records:
                    self.cooldown_worksheet.delete_rows(2, len(all_records) + 1)
            except Exception:
                pass

            if rows:
                self.cooldown_worksheet.append_rows(rows)
            return True
        except Exception as e:
            logger.warning(f"Google Sheet Cooldown 동기화 실패: {e}")
            return False

    def read_cooldown_from_sheet(self) -> Dict[str, str]:
        """Google Sheet 'Cooldown'에서 쿨다운 목록 읽기"""
        if not self.is_connected or not self.cooldown_worksheet:
            return {}

        cd_map = {}
        try:
            records = self.cooldown_worksheet.get_all_records()
            for rec in records:
                code = str(rec.get("종목코드", "")).strip()
                end_date = str(rec.get("재매수가능일자", "")).strip()
                if code and end_date:
                    cd_map[code] = end_date
            return cd_map
        except Exception as e:
            logger.warning(f"Google Sheet Cooldown 읽기 실패: {e}")
            return {}

    # =========================================================================
    # 5. TradeHistory (매매 체결 일지) 동기화
    # =========================================================================
    def record_trade(self, trade_info: Dict[str, Any]) -> bool:
        """체결된 매수/매도 건을 'TradeHistory'에 누적 기록"""
        if not self.is_connected or not self.trade_history_worksheet:
            return False

        try:
            now_str = trade_info.get("executed_at") or datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                now_str,
                trade_info.get("side", "매수"),
                trade_info.get("code", ""),
                trade_info.get("name", ""),
                trade_info.get("qty", 0),
                trade_info.get("price", 0),
                trade_info.get("amount", 0),
                trade_info.get("profit_rate", 0.0),
                trade_info.get("profit_loss", 0),
                trade_info.get("order_no", "-"),
                trade_info.get("note", "")
            ]
            self.trade_history_worksheet.append_row(row)
            logger.info(f"📊 Google Sheet 'TradeHistory'에 [{trade_info.get('name')}] 체결 기록 저장 성공")
            return True
        except Exception as e:
            logger.warning(f"Google Sheet TradeHistory 기록 실패: {e}")
            return False


# =============================================================================
# 싱글톤 인스턴스 제공 및 별칭
# =============================================================================
GoogleSheetManager = DomesticSheetManager

_sheet_manager_instance: Optional[DomesticSheetManager] = None

def get_domestic_sheet_manager() -> DomesticSheetManager:
    """DomesticSheetManager 싱글톤 인스턴스 반환"""
    global _sheet_manager_instance
    if _sheet_manager_instance is None:
        _sheet_manager_instance = DomesticSheetManager()
    return _sheet_manager_instance

def get_sheet_manager() -> DomesticSheetManager:
    """하위 호환성을 위한 헬퍼"""
    return get_domestic_sheet_manager()

