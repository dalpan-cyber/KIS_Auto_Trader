"""
Google Sheets 연동 및 동기화 매니저 모듈 (domestic_sheet_manager.py)
KIS Auto Trader v2.0의 설정, 매수/매도 제안, 포지션 추적 상태, 손절 쿨다운, 매매일지를 구글 시트와 실시간 동기화합니다.
"""
import os
import json
import logging
import datetime
from typing import Dict, Any, List, Optional

from core.sheets.base_sheet import BaseSheetManager, GSPREAD_AVAILABLE
import time_utils
import app_config as config

logger = logging.getLogger("DomesticSheetManager")

def _get_config_val(name: str, default: Any = None) -> Any:
    try:
        import app_config as config
        return getattr(config, name, default)
    except Exception:
        return default


class DomesticSheetManager(BaseSheetManager):
    """Google Sheets 국내 퀀트 매매일지 및 상태 동기화 관리 클래스"""

    def __init__(
        self,
        sheet_name: Optional[str] = None,
        sheet_key: Optional[str] = None,
        enabled: Optional[bool] = None,
        service_account_file: Optional[str] = None
    ):
        name = sheet_name or _get_config_val("DOMESTIC_GOOGLE_SHEET_NAME", _get_config_val("GOOGLE_SHEET_NAME", os.getenv("DOMESTIC_GOOGLE_SHEET_NAME", os.getenv("GOOGLE_SHEET_NAME", "KIS_Auto2_매매일지"))))
        key = sheet_key or _get_config_val("DOMESTIC_GOOGLE_SHEET_KEY", _get_config_val("GOOGLE_SHEET_KEY", os.getenv("DOMESTIC_GOOGLE_SHEET_KEY", os.getenv("GOOGLE_SHEET_KEY", ""))))
        
        if not key:
            try:
                import streamlit as st
                if hasattr(st, "secrets"):
                    if "DOMESTIC_GOOGLE_SHEET_KEY" in st.secrets:
                        key = str(st.secrets["DOMESTIC_GOOGLE_SHEET_KEY"])
                    elif "GOOGLE_SHEET_KEY" in st.secrets:
                        key = str(st.secrets["GOOGLE_SHEET_KEY"])
            except Exception:
                pass

        is_enabled = enabled if enabled is not None else _get_config_val("GOOGLE_SHEET_ENABLED", True)

        self.settings_worksheet: Optional[Any] = None
        self.proposals_worksheet: Optional[Any] = None
        self.proposals_state_worksheet: Optional[Any] = None
        self.positions_worksheet: Optional[Any] = None
        self.cooldown_worksheet: Optional[Any] = None
        self.trade_history_worksheet: Optional[Any] = None

        super().__init__(
            sheet_name=name,
            sheet_key=key,
            enabled=is_enabled,
            service_account_file=service_account_file
        )

    def _init_worksheets(self):
        """국내 퀀트 전용 워크시트 초기화"""
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
        if self.positions_worksheet:
            try:
                cur_hdrs = self.positions_worksheet.row_values(1)
                exp_hdrs = ["종목코드", "종목명", "매수단가", "최고가", "1차익절완료", "매수전략", "갱신일시"]
                if cur_hdrs != exp_hdrs:
                    self.positions_worksheet.update(range_name="A1:G1", values=[exp_hdrs])
            except Exception:
                pass

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

    # =========================================================================
    # 1. Settings (설정값 & 감시종목) 동기화
    # =========================================================================
    def sync_settings_to_sheet(self, settings: Dict[str, Any]) -> bool:
        """설정값을 'Settings' 워크시트에 저장"""
        if not self.is_connected or not self.settings_worksheet:
            return False

        try:
            now_str = time_utils.now_str()
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
            now_str = proposals_data.get("updated_at") or time_utils.now_str()
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

                # 최신 100건 유지: 행 수가 101(헤더 1행 + 데이터 100건)을 초과하면 오래된 내역 롤링 정리
                try:
                    all_rows = self.proposals_worksheet.get_all_values()
                    max_data_rows = 100
                    if len(all_rows) > max_data_rows + 1:
                        header = all_rows[0]
                        trimmed = all_rows[-max_data_rows:]
                        self.proposals_worksheet.clear()
                        self.proposals_worksheet.update(range_name="A1", values=[header] + trimmed)
                        self.proposals_worksheet.resize(rows=max(120, len(trimmed) + 20), cols=len(header))
                        logger.info(f"🧹 Google Sheet 'Proposals' 최신 {len(trimmed)}건 유지 (오래된 제안 자동 롤링 정리 완료)")
                except Exception as ex:
                    logger.warning(f"Google Sheet Proposals 롤링 정리 중 오류 발생 (계속 진행): {ex}")
            return True
        except Exception as e:
            logger.warning(f"Google Sheet Proposals 동기화 실패: {e}")
            return False

    def sync_proposals_state_to_sheet(self, proposals_data: Dict[str, Any]) -> bool:
        """마지막 스크리닝 결과(추천, 관망 후보 등)를 'ProposalsState' 워크시트에 최신화"""
        if not self.is_connected or not self.proposals_state_worksheet:
            return False

        try:
            now_s = time_utils.now_str()
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
            now_str = time_utils.now_str()
            rows = []
            for raw_code, data in positions.items():
                code_str = str(raw_code).strip().lstrip("'")
                code_6 = code_str.zfill(6) if code_str.isdigit() and len(code_str) < 6 else code_str

                # 종목명이 코드와 같거나 비어있으면 매핑에서 검색
                name = data.get("name", code_6)
                if (not name or name == raw_code or name == code_6) and hasattr(config, "STOCK_NAMES"):
                    name = config.STOCK_NAMES.get(code_6, name)

                strat_name = data.get("strategy", "momentum")
                strat_disp = data.get("strategy_display_name", "")
                if not strat_disp:
                    if strat_name == "monthly_trend":
                        strat_disp = "월간 10개월 추세 (GTAA)"
                    elif strat_name == "rebound":
                        strat_disp = "52주 신저가 반등"
                    elif strat_name == "multi":
                        strat_disp = "슈퍼시그널"
                    else:
                        strat_disp = "모멘텀 추세추종"

                # 구글 시트에서 앞자리 0이 잘리지 않도록 텍스트 접두사(') 추가
                formatted_code = f"'{code_6}" if code_6.isdigit() else code_6

                rows.append([
                    formatted_code,
                    name,
                    data.get("avg_buy_price", 0.0),
                    data.get("highest_price", 0.0),
                    "Y" if data.get("is_partial_sold", False) else "N",
                    strat_disp,
                    data.get("last_updated", data.get("updated_at", now_str))
                ])

            # 헤더 확인 및 보정
            expected_headers = ["종목코드", "종목명", "매수단가", "최고가", "1차익절완료", "매수전략", "갱신일시"]
            try:
                cur_headers = self.positions_worksheet.row_values(1)
                if cur_headers != expected_headers:
                    self.positions_worksheet.update(range_name="A1:G1", values=[expected_headers])
            except Exception:
                pass

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
                raw_code = str(rec.get("종목코드", "")).strip().lstrip("'")
                if not raw_code:
                    continue
                code = raw_code.zfill(6) if raw_code.isdigit() and len(raw_code) < 6 else raw_code

                strat_raw = str(rec.get("매수전략", "") or "").strip()
                # 과거 6열 시절 갱신일시 컬럼에 전략이 들어갔던 경우 보정
                if not strat_raw or strat_raw == "momentum":
                    alt_strat = str(rec.get("갱신일시", "")).strip()
                    if alt_strat in ("momentum", "rebound", "monthly_trend", "multi") or any(k in alt_strat for k in ("모멘텀", "반등", "월봉", "월간", "슈퍼")):
                        strat_raw = alt_strat

                # 정규화된 전략 키 및 표시명 결정
                strat_key = "momentum"
                s_lower = strat_raw.lower()
                if any(k in s_lower for k in ("monthly", "월봉", "월간", "gtaa")):
                    strat_key = "monthly_trend"
                    strat_disp = "월간 10개월 추세 (GTAA)"
                elif any(k in s_lower for k in ("rebound", "반등", "52주", "신저가")):
                    strat_key = "rebound"
                    strat_disp = "52주 신저가 반등"
                elif any(k in s_lower for k in ("multi", "&", "슈퍼", "super", "복수")):
                    strat_key = "multi"
                    strat_disp = "슈퍼시그널"
                elif any(k in s_lower for k in ("momentum", "모멘텀", "추세")):
                    strat_key = "momentum"
                    strat_disp = "모멘텀 추세추종"
                else:
                    strat_key = "momentum"
                    strat_disp = strat_raw or "모멘텀 추세추종"

                last_upd = str(rec.get("갱신일시", ""))
                if last_upd in ("momentum", "rebound", "monthly_trend", "multi"):
                    last_upd = now_str()

                positions[code] = {
                    "code": code,
                    "name": str(rec.get("종목명", code)),
                    "avg_buy_price": float(rec.get("매수단가", 0.0) or 0.0),
                    "highest_price": float(rec.get("최고가", 0.0) or 0.0),
                    "is_partial_sold": str(rec.get("1차익절완료", "N")).upper() in ("Y", "TRUE", "1"),
                    "strategy": strat_key,
                    "strategy_display_name": strat_disp,
                    "last_updated": last_upd,
                    "updated_at": last_upd
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
            now_str = time_utils.now_str()
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
            now_str = trade_info.get("executed_at") or time_utils.now_str()
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

