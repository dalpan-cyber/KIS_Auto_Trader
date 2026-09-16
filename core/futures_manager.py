"""
Futures Manager Module
한국투자증권(KIS) 선물/옵션 마스터 테이블을 다운로드 및 파싱하여
개별주식선물(Single Stock Futures) 최근월물 매핑 정보를 관리합니다.
"""
import os
import sys
import zipfile
import logging
import datetime
import urllib.request
from typing import Dict, Optional

logger = logging.getLogger("FuturesManager")

MASTER_URL = "https://new.real.download.dws.co.kr/common/master/fo_stk_code_mts.mst.zip"
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cache")
MST_ZIP_PATH = os.path.join(CACHE_DIR, "fo_stk_code_mts.mst.zip")
MST_FILE_PATH = os.path.join(CACHE_DIR, "fo_stk_code_mts.mst")


class FuturesManager:
    _instance: Optional["FuturesManager"] = None
    _stock_to_futures: Dict[str, str] = {}
    _last_loaded_date: Optional[str] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FuturesManager, cls).__new__(cls)
            cls._instance._init_manager()
        return cls._instance

    def _init_manager(self):
        os.makedirs(CACHE_DIR, exist_ok=True)
        self.load_master()

    def load_master(self, force_download: bool = False) -> bool:
        """
        선물 마스터 파일을 로드하고 개별주식선물 최근월물 매핑 테이블을 구축합니다.
        파일이 없거나 오늘 날짜가 아니면 새로 다운로드합니다.
        """
        today_str = datetime.datetime.now().strftime("%Y%m%d")
        if self._stock_to_futures and self._last_loaded_date == today_str and not force_download:
            return True

        need_download = force_download or not os.path.exists(MST_FILE_PATH)
        if not need_download and os.path.exists(MST_FILE_PATH):
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(MST_FILE_PATH))
            if mtime.strftime("%Y%m%d") != today_str:
                need_download = True

        if need_download:
            success = self._download_master()
            if not success and not os.path.exists(MST_FILE_PATH):
                logger.error("선물 마스터 파일 다운로드 실패 및 기존 캐시 없음")
                return False

        return self._parse_master()

    def _download_master(self) -> bool:
        """KRX/KIS 마스터 zip 다운로드 및 압축 해제"""
        try:
            logger.info(f"파생상품 마스터 다운로드 시작: {MASTER_URL}")
            req = urllib.request.Request(
                MASTER_URL,
                headers={"User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp, open(MST_ZIP_PATH, "wb") as out_f:
                out_f.write(resp.read())

            with zipfile.ZipFile(MST_ZIP_PATH, "r") as zip_ref:
                zip_ref.extractall(CACHE_DIR)

            logger.info("파생상품 마스터 다운로드 및 압축해제 완료")
            return True
        except Exception as e:
            logger.warning(f"파생상품 마스터 다운로드 중 예외 발생: {e}")
            return False

    def _parse_master(self) -> bool:
        """
        fo_stk_code_mts.mst 파일을 파싱하여
        상품종류 == '1' (주식선물) 및 월물구분코드 == '1' (최근월물) 매핑 추출
        """
        if not os.path.exists(MST_FILE_PATH):
            return False

        mapping = {}
        try:
            with open(MST_FILE_PATH, "r", encoding="cp949", errors="ignore") as f:
                for line in f:
                    parts = line.strip().split("|")
                    if len(parts) >= 8:
                        prod_type = parts[0].strip()   # 상품종류 (1: 주식선물)
                        fut_code = parts[1].strip()    # 선물 단축코드 (예: A11609)
                        month_type = parts[6].strip()  # 월물구분코드 (1: 최근월물)
                        stock_code = parts[7].strip()  # 기초자산 주식 단축코드 (예: 005930)

                        if prod_type == "1" and month_type == "1" and stock_code:
                            mapping[stock_code] = fut_code

            self._stock_to_futures = mapping
            self._last_loaded_date = datetime.datetime.now().strftime("%Y%m%d")
            logger.info(f"개별주식선물 최근월물 매핑 로드 완료 (총 {len(mapping)}개 종목 매핑)")
            return True
        except Exception as e:
            logger.error(f"선물 마스터 파일 파싱 실패: {e}")
            return False

    def get_futures_code(self, stock_code: str) -> Optional[str]:
        """주식 종목코드에 해당하는 개별주식선물 최근월물 단축코드 반환 (없으면 None)"""
        if not self._stock_to_futures:
            self.load_master()
        return self._stock_to_futures.get(stock_code)

    def has_futures(self, stock_code: str) -> bool:
        """해당 종목의 주식선물 상장 여부 반환"""
        return self.get_futures_code(stock_code) is not None

    def get_all_mapped_stocks(self) -> Dict[str, str]:
        """전체 주식코드 -> 선물코드 매핑 dict 반환"""
        if not self._stock_to_futures:
            self.load_master()
        return dict(self._stock_to_futures)


# 싱글톤 인스턴스 편의 제공
futures_manager = FuturesManager()
