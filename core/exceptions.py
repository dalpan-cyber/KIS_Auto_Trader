"""
KIS Auto Trading - Core Exceptions Module
시스템 전반에서 사용되는 커스텀 예외 계층 정의
"""

class KISError(Exception):
    """KIS 자동매매 시스템 기본 예외"""
    pass

class KISApiError(KISError):
    """KIS Open API 통신 및 응답 오류"""
    def __init__(self, message: str, status_code: int = 0, error_code: str = ""):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code

class KISAuthError(KISApiError):
    """토큰 발급 및 인증 관련 오류"""
    pass

class KISRateLimitError(KISApiError):
    """API 호출 제한(429) 초과 오류"""
    pass

class KISOrderError(KISApiError):
    """주문 발주 및 정정/취소 오류"""
    pass

class StrategyError(KISError):
    """전략 및 지표 계산 관련 오류"""
    pass

class StorageError(KISError):
    """파일 저장 및 데이터 직렬화 오류"""
    pass
