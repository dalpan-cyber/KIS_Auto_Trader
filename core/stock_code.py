"""
KIS Auto Trading - Stock Code Utility
국내 종목코드 정규화 (구글 시트 텍스트 접두사(') 제거 및 앞자리 0 복원)
"""


def normalize_stock_code(code) -> str:
    """종목코드를 6자리 문자열로 정규화 (예: 5930 -> '005930', "'000100" -> '000100'). 해외 티커는 그대로 반환"""
    c_str = str(code).strip().lstrip("'")
    return c_str.zfill(6) if c_str.isdigit() and len(c_str) < 6 else c_str
