"""
Google Sheet Manager 통합 브릿지 모듈 (google_sheet_manager.py)
기존 KIS_Auto_Trader (라오어 무한매수법) 및 KIS_Auto2 (국내 퀀트) 간의
구글 시트 2원화 유지를 위해 각각의 매니저를 연결하고 하위 호환성을 100% 보장합니다.
"""
from core.sheets.infinite_sheet_manager import InfiniteSheetManager, get_infinite_sheet_manager
from core.sheets.domestic_sheet_manager import DomesticSheetManager, get_domestic_sheet_manager

# 하위 호환성 매핑
# 1. KIS_Auto_Trader 기존 무한매수 매니저 호환: GoogleSheetManager -> InfiniteSheetManager
GoogleSheetManager = InfiniteSheetManager

# 2. KIS_Auto2 기존 국내 퀀트 매니저 호환: get_sheet_manager -> get_domestic_sheet_manager
get_sheet_manager = get_domestic_sheet_manager

__all__ = [
    "InfiniteSheetManager",
    "get_infinite_sheet_manager",
    "DomesticSheetManager",
    "get_domestic_sheet_manager",
    "GoogleSheetManager",
    "get_sheet_manager",
]
