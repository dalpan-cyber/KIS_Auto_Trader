"""
KIS Auto Trading - Universe Package
한국거래소(KRX) 코스피 200(KOSPI 200) 및 코스닥 150(KOSDAQ 150) 유니버스 정의
(삼성자산운용 KODEX 200 및 KODEX 코스닥150 ETF 포트폴리오 PDF 기준)
"""
from typing import List, Dict
from core.universe.kospi100 import KOSPI_100_STOCKS, get_kospi100_universe
from core.universe.kospi200 import KOSPI_200_STOCKS, get_kospi200_universe
from core.universe.kosdaq150 import KOSDAQ_150_STOCKS, get_kosdaq150_universe

# 주요 지수 추종 대표 KODEX ETF 4종
ETF_STOCKS: List[Dict[str, str]] = [
    {"code": "069500", "name": "KODEX 200", "market": "ETF"},
    {"code": "122630", "name": "KODEX 레버리지", "market": "ETF"},
    {"code": "233740", "name": "KODEX 코스닥150레버리지", "market": "ETF"},
    {"code": "114800", "name": "KODEX 인버스", "market": "ETF"},
]


def get_combined_universe(include_etfs: bool = True) -> List[Dict[str, str]]:
    """
    KODEX 200 및 KODEX 코스닥150 참조 통합 관심종목 유니버스 (총 350~354종목) 반환:
    - KOSPI 200: 200개 종목
    - KOSDAQ 150: 150개 종목
    - 대표 KODEX ETF: 4개 종목 (include_etfs=True 시 포함)
    """
    universe = list(KOSPI_200_STOCKS) + list(KOSDAQ_150_STOCKS)
    if include_etfs:
        universe.extend(ETF_STOCKS)
    return universe


__all__ = [
    "KOSPI_100_STOCKS",
    "get_kospi100_universe",
    "KOSPI_200_STOCKS",
    "get_kospi200_universe",
    "KOSDAQ_150_STOCKS",
    "get_kosdaq150_universe",
    "ETF_STOCKS",
    "get_combined_universe",
]
