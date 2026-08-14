"""
테스트: CTOS4001R API 응답에서 주문단가/체결단가가 USD 기준으로 올바르게 파싱되는지 검증
"""
import json
from unittest.mock import patch
import requests

import kis_api
from kis_api import KISApiClient

class MockResponse:
    def __init__(self, data, status_code=200, headers=None):
        self._data = data
        self.status_code = status_code
        self.headers = headers or {"tr_cont": ""}
        self.text = json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else str(data)
    
    def json(self):
        return self._data

def make_client():
    client = KISApiClient.__new__(KISApiClient)
    client.access_token = "test-token"
    client.token_issued_at = 0
    client.token_expires_in = 86400
    client.cano = "12345678"
    client.acnt_prdt_cd = "01"
    client.mock = False
    client.url_base = "https://openapi.koreainvestment.com:9443"
    client.last_call_time = 0
    client.last_token_attempt_time = 0
    client._token_file_path = "token_kis_real.json"
    client._mock_balance_deposit = 10000000
    client._mock_usd_deposit = 5000.0
    client._mock_holdings = {}
    client.app_key = "test-app-key"
    client.app_secret = "test-app-secret"
    return client

def test_ctos4001r_price_with_ovrs_field():
    """ovrs_stck_ccld_unpr(USD)가 존재하는 경우 올바른 USD 값 사용"""
    client = make_client()
    
    mock_data = {
        "rt_cd": "0",
        "msg_cd": "00000",
        "msg1": "정상",
        "output1": [
            {
                "odno": "1234567890",
                "pdno": "TQQQ",
                "sll_buy_dvsn_cd": "02",
                "sll_buy_dvsn_name": "매수",
                "ccld_qty": "10",
                "ft_ccld_qty": "10",
                "ord_unpr": "100.00",            # 주문단가 $100.00
                "ovrs_stck_ccld_unpr": "102.50", # 체결단가 $102.50
                "ft_ccld_unpr2": "146425.00",    # 원화 기준 (102.50 * 1428.54)
                "trad_dt": "20260720",
                "ord_tmd": "103000",
                "prcs_stat_name": "체결",
                "tr_amt": "1025.00",
                "crcy_cd": "USD",
                "nccs_qty": "0"
            }
        ],
        "output2": {}
    }
    
    mock_resp = MockResponse(mock_data)
    
    with patch.object(requests, "get", return_value=mock_resp):
        results = client.get_overseas_execution_history(symbol="TQQQ", start_date="20260701", end_date="20260731")
    
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    r = results[0]
    print(f"Record: price={r['price']}, executed_price={r['executed_price']}")
    assert r["price"] == 100.00, f"ord_price should be 100.00, got {r['price']}"
    assert r["executed_price"] == 102.50, f"exec_price should be 102.50 (USD), got {r['executed_price']}"
    assert r["executed_price"] != 146425.00, "exec_price should NOT be the KRW value!"
    print("  ✓ ovrs_stck_ccld_unpr(USD) 사용: 102.50 (非 146425.00 韩元值)")
    print("  ✓ 未使用 ft_ccld_unpr2(韩元) 字段")
    
    print("\n✅ CTOS4001R USD价格验证 PASS")
    return True

def test_ctos4001r_price_without_ovrs_field():
    """ovrs_stck_ccld_unpr(USD)가 없는 경우, ft_ccld_unpr2(원화)를 사용하지 않고 0 처리"""
    client = make_client()
    
    mock_data = {
        "rt_cd": "0",
        "msg_cd": "00000",
        "msg1": "정상",
        "output1": [
            {
                "odno": "1234567891",
                "pdno": "TQQQ",
                "sll_buy_dvsn_cd": "02",
                "sll_buy_dvsn_name": "매수",
                "ccld_qty": "10",
                "ft_ccld_qty": "10",
                "ord_unpr": "100.00",
                # ovrs_stck_ccld_unpr 없음
                "ft_ccld_unpr2": "142850.00",  # 원화 기준
                "trad_dt": "20260721",
                "ord_tmd": "103000",
                "prcs_stat_name": "체결",
                "tr_amt": "1025.00",
                "crcy_cd": "USD",
                "nccs_qty": "0"
            }
        ],
        "output2": {}
    }
    
    mock_resp = MockResponse(mock_data)
    
    with patch.object(requests, "get", return_value=mock_resp):
        results = client.get_overseas_execution_history(symbol="TQQQ", start_date="20260701", end_date="20260731")
    
    assert len(results) == 1, f"Expected 1 result, got {len(results)}"
    r = results[0]
    print(f"Record: price={r['price']}, executed_price={r['executed_price']}")
    assert r["price"] == 100.00, f"ord_price should be 100.00, got {r['price']}"
    assert r["executed_price"] == 0.0, f"exec_price should be 0.0 (no USD field), got {r['executed_price']}"
    assert r["executed_price"] != 142850.00, "exec_price should NOT be the KRW value!"
    print("  ✓ 未使用 ft_ccld_unpr2(韩元) 字段，exec_price=0.0")
    
    print("\n✅ CTOS4001R 无USD字段时验证 PASS")
    return True

def test_execution_balance_price():
    """get_overseas_execution_balance 中价格字段使用 USD 计价"""
    client = make_client()
    
    mock_data = {
        "rt_cd": "0",
        "msg_cd": "00000",
        "msg1": "정상",
        "output1": [
            {
                "ovrs_pdno": "TQQQ",
                "ovrs_item_name": "TQQQ",
                "ovrs_cblc_qty": "10",
                "ft_ccld_qty": "10",
                "nccs_qty": "0",
                "pchs_avg_pric": "105.00",      # 매입평균가격 USD
                "ft_ccld_unpr": "149997.00",     # FT체결단가 원화 (105*1428.54)
                "ft_ccld_unpr3": "149997.00",    # FT체결단가3 원화
                "now_pric2": "110.00",
                "last_prik": "110.00",
                "evlu_pfls_rt": "4.76"
            }
        ],
        "output2": {}
    }
    
    mock_resp = MockResponse(mock_data)
    
    with patch.object(requests, "get", return_value=mock_resp):
        result = client.get_overseas_execution_balance(symbol="TQQQ")
    
    assert result.get("success"), f"Expected success, got {result}"
    holdings = result.get("holdings", [])
    assert len(holdings) == 1, f"Expected 1 holding, got {len(holdings)}"
    h = holdings[0]
    print(f"Holding: avg_price={h['avg_price']}, executed_price={h['executed_price']}")
    assert h["avg_price"] == 105.00, f"avg_price should be 105.00 (USD), got {h['avg_price']}"
    assert h["executed_price"] == 105.00, f"executed_price should be 105.00 (USD), got {h['executed_price']}"
    assert h["executed_price"] != 149997.00, "executed_price should NOT be the KRW value!"
    print("  ✓ 使用 pchs_avg_pric(USD) 而非 ft_ccld_unpr(韩元)")
    
    print("\n✅ Execution Balance USD价格验证 PASS")
    return True

if __name__ == "__main__":
    test_ctos4001r_price_with_ovrs_field()
    test_ctos4001r_price_without_ovrs_field()
    test_execution_balance_price()
    print("\n🎉 所有价格USD验证测试PASS")