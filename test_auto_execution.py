"""
자동 실행(GitHub Actions / run_infinite_buying.py) 시나리오 테스트
- 종목별 설정이 자동 실행 경로에서도 올바르게 적용되는지 검증
"""
import os
import sys
import json
import tempfile

# Windows 콘솔 utf-8 출력 설정
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TEST_STATE_FILE = os.path.join(tempfile.gettempdir(), "test_auto_state.json")
if os.path.exists(TEST_STATE_FILE):
    os.remove(TEST_STATE_FILE)

import config

def test_auto_execution_flow():
    """자동 실행 시 종목별 설정이 올바르게 적용되는지 검증"""
    print("=== Test: 자동 실행 시 종목별 설정 적용 ===")
    
    # 1. 설정 파일에서 종목별 설정 로드 (infinite_settings.json)
    with open("infinite_settings.json", "r", encoding="utf-8") as f:
        settings = json.load(f)
    
    config._apply_settings(settings)
    
    assert "TQQQ" in config.INFINITE_STOCK_CONFIGS, "TQQQ 설정이 로드되지 않음"
    assert "TQQQ" in config.INFINITE_STOCKS, f"INFINITE_STOCKS에 TQQQ 없음: {config.INFINITE_STOCKS}"
    
    # 2. run_infinite_buying.py의 주문 발주 모드 시뮬레이션
    from infinite_state_manager import InfiniteStateManager
    
    mgr = InfiniteStateManager(file_path=TEST_STATE_FILE, enable_gss=False)
    
    # run_infinite_buying.py line 85-89과 동일한 로직
    for symbol in config.INFINITE_STOCKS:
        stock_cfg = config.get_stock_config(symbol)
        st_data = mgr.get_symbol_state(
            symbol,
            default_budget_usd=stock_cfg["total_budget_usd"],
            division_count=stock_cfg["division_count"],
            target_roi=stock_cfg["target_roi"],
            exhaust_action=stock_cfg["exhaust_action"],
            exhaust_target_roi=stock_cfg["exhaust_target_roi"]
        )
        assert st_data["total_budget_usd"] == stock_cfg["total_budget_usd"], f"{symbol} 예산 오류"
        assert st_data["division_count"] == stock_cfg["division_count"], f"{symbol} 분할 오류"
        assert st_data["target_roi"] == stock_cfg["target_roi"], f"{symbol} 목표수익률 오류"
        assert st_data["exhaust_action"] == stock_cfg["exhaust_action"], f"{symbol} 소진대응 오류"
        assert st_data["exhaust_target_roi"] == stock_cfg["exhaust_target_roi"], f"{symbol} 탈출목표 오류"
        
        if st_data.get("status") == "IDLE":
            mgr.start_buying(symbol)
    
    # 3. trader.py의 run_infinite_buying_cycle() 시뮬레이션
    from strategy import InfiniteBuyingStrategy
    
    strategy = InfiniteBuyingStrategy()
    
    for symbol in config.INFINITE_STOCKS:
        stock_cfg = config.get_stock_config(symbol)
        state = mgr.get_symbol_state(
            symbol,
            default_budget_usd=stock_cfg["total_budget_usd"],
            division_count=stock_cfg["division_count"],
            target_roi=stock_cfg["target_roi"],
            exhaust_action=stock_cfg["exhaust_action"],
            exhaust_target_roi=stock_cfg["exhaust_target_roi"]
        )
        
        # 주문 생성 시 종목별 설정이 사용되는지 확인
        orders = strategy.generate_daily_orders(symbol, 50.0, state, avg_price=45.0, total_qty=100)
        assert len(orders) > 0, f"{symbol} 주문이 생성되지 않음"
        
        print(f"  ✅ [{symbol}] 설정: 예산=${stock_cfg['total_budget_usd']:,.0f}, 분할={stock_cfg['division_count']}회, 목표=+{stock_cfg['target_roi']*100:.1f}%, 소진대응={stock_cfg['exhaust_action']}")
        print(f"  ✅ [{symbol}] 상태: 회차={state['current_round']}, 상태={state['status']}")
        print(f"  ✅ [{symbol}] 주문: {[(o['action'], o['price']) for o in orders]}")
    
    print("  ✅ PASS")


def test_auto_execution_with_multiple_stocks():
    """자동 실행 시 다중 종목 설정이 올바르게 적용되는지 검증"""
    print("\n=== Test: 자동 실행 시 다중 종목 설정 ===")
    
    # 다중 종목 설정 시뮬레이션
    test_settings = {
        "infinite_stocks": ["TQQQ", "SOXL"],
        "infinite_stock_configs": {
            "TQQQ": {
                "total_budget_usd": 5000.0,
                "division_count": 40,
                "target_roi": 0.10,
                "exhaust_action": "HOLD",
                "exhaust_target_roi": 0.05,
            },
            "SOXL": {
                "total_budget_usd": 8000.0,
                "division_count": 30,
                "target_roi": 0.15,
                "exhaust_action": "LOWER_TARGET",
                "exhaust_target_roi": 0.08,
            },
        },
    }
    config._apply_settings(test_settings)
    
    from infinite_state_manager import InfiniteStateManager
    
    mgr = InfiniteStateManager(file_path=TEST_STATE_FILE, enable_gss=False)
    
    # run_infinite_buying.py의 주문 발주 모드 시뮬레이션
    for symbol in config.INFINITE_STOCKS:
        stock_cfg = config.get_stock_config(symbol)
        # 기존 상태가 있으면 설정값을 업데이트 (자동 실행 시 설정 변경 반영)
        mgr.update_settings(
            symbol,
            total_budget_usd=stock_cfg["total_budget_usd"],
            division_count=stock_cfg["division_count"],
            target_roi=stock_cfg["target_roi"],
            exhaust_action=stock_cfg["exhaust_action"],
            exhaust_target_roi=stock_cfg["exhaust_target_roi"]
        )
        st_data = mgr.get_symbol_state(symbol)
        assert st_data["total_budget_usd"] == stock_cfg["total_budget_usd"], f"{symbol} 예산 오류"
        assert st_data["division_count"] == stock_cfg["division_count"], f"{symbol} 분할 오류"
        assert st_data["exhaust_action"] == stock_cfg["exhaust_action"], f"{symbol} 소진대응 오류"
        
        print(f"  ✅ [{symbol}] 상태 생성: 예산=${st_data['total_budget_usd']:,.0f}, 분할={st_data['division_count']}회, 소진대응={st_data['exhaust_action']}")
    
    print("  ✅ PASS")


def test_google_sheet_settings_sync():
    """Google Sheet 'Settings' 워크시트의 종목별 설정 직렬화/역직렬화 검증"""
    print("\n=== Test: Google Sheet 설정 동기화 (infinite_stock_configs) ===")
    
    # 1. 설정 데이터 구성 (app.py의 settings_data와 동일 구조)
    settings_data = {
        "infinite_stocks": ["TQQQ", "SOXL"],
        "infinite_stock_configs": {
            "TQQQ": {
                "total_budget_usd": 5000.0,
                "division_count": 40,
                "target_roi": 0.10,
                "exhaust_action": "HOLD",
                "exhaust_target_roi": 0.05,
            },
            "SOXL": {
                "total_budget_usd": 8000.0,
                "division_count": 30,
                "target_roi": 0.15,
                "exhaust_action": "LOWER_TARGET",
                "exhaust_target_roi": 0.08,
            },
        },
        "max_stocks_holding": 5,
        "api_call_delay": 0.2,
    }
    
    # 2. sync_settings_to_sheet()의 직렬화 로직 검증 (dict → JSON 문자열)
    serialized_rows = []
    for key, value in settings_data.items():
        if isinstance(value, list):
            value_str = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            value_str = json.dumps(value, ensure_ascii=False)
        else:
            value_str = str(value)
        serialized_rows.append([key, value_str])
    
    # infinite_stock_configs가 JSON 문자열로 직렬화되었는지 확인
    stock_configs_row = [r for r in serialized_rows if r[0] == "infinite_stock_configs"][0]
    parsed_back = json.loads(stock_configs_row[1])
    assert isinstance(parsed_back, dict), "infinite_stock_configs가 dict로 파싱되지 않음"
    assert parsed_back["TQQQ"]["total_budget_usd"] == 5000.0, "TQQQ 예산 오류"
    assert parsed_back["TQQQ"]["division_count"] == 40, "TQQQ 분할 오류"
    assert parsed_back["TQQQ"]["exhaust_action"] == "HOLD", "TQQQ 소진대응 오류"
    assert parsed_back["SOXL"]["total_budget_usd"] == 8000.0, "SOXL 예산 오류"
    assert parsed_back["SOXL"]["division_count"] == 30, "SOXL 분할 오류"
    assert parsed_back["SOXL"]["exhaust_action"] == "LOWER_TARGET", "SOXL 소진대응 오류"
    assert parsed_back["SOXL"]["exhaust_target_roi"] == 0.08, "SOXL 탈출목표 오류"
    
    print(f"  ✅ infinite_stock_configs JSON 직렬화/역직렬화 성공: {list(parsed_back.keys())}")
    
    # 3. read_settings_from_sheet()의 역직렬화 로직 검증 (JSON 문자열 → dict)
    # Google Sheet에서 읽은 레코드 시뮬레이션
    sheet_records = []
    for key, value_str in serialized_rows:
        sheet_records.append({"설정키": key, "설정값": value_str})
    
    # read_settings_from_sheet()의 파싱 로직 시뮬레이션
    parsed_settings = {}
    for rec in sheet_records:
        key = str(rec.get("설정키", "")).strip()
        value = str(rec.get("설정값", "")).strip()
        if not key or not value:
            continue
        
        if key == "infinite_stocks":
            parsed_settings[key] = [s.strip().upper() for s in value.split(",") if s.strip()]
        elif key == "infinite_stock_configs":
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    parsed_settings[key] = parsed
            except (json.JSONDecodeError, ValueError):
                pass
        elif key in ("infinite_total_budget_usd", "infinite_target_roi", "infinite_exhaust_target_roi", "api_call_delay"):
            try:
                parsed_settings[key] = float(value)
            except ValueError:
                parsed_settings[key] = value
        elif key in ("infinite_division_count", "max_stocks_holding"):
            try:
                parsed_settings[key] = int(float(value))
            except ValueError:
                parsed_settings[key] = value
        elif key == "infinite_exhaust_action":
            parsed_settings[key] = str(value).strip().upper()
        else:
            parsed_settings[key] = value
    
    # 4. 역직렬화된 설정이 원본과 일치하는지 검증
    assert parsed_settings["infinite_stocks"] == ["TQQQ", "SOXL"], "infinite_stocks 오류"
    assert parsed_settings["infinite_stock_configs"]["TQQQ"]["total_budget_usd"] == 5000.0, "TQQQ 예산 오류"
    assert parsed_settings["infinite_stock_configs"]["TQQQ"]["division_count"] == 40, "TQQQ 분할 오류"
    assert parsed_settings["infinite_stock_configs"]["TQQQ"]["exhaust_action"] == "HOLD", "TQQQ 소진대응 오류"
    assert parsed_settings["infinite_stock_configs"]["SOXL"]["total_budget_usd"] == 8000.0, "SOXL 예산 오류"
    assert parsed_settings["infinite_stock_configs"]["SOXL"]["division_count"] == 30, "SOXL 분할 오류"
    assert parsed_settings["infinite_stock_configs"]["SOXL"]["exhaust_action"] == "LOWER_TARGET", "SOXL 소진대응 오류"
    assert parsed_settings["infinite_stock_configs"]["SOXL"]["exhaust_target_roi"] == 0.08, "SOXL 탈출목표 오류"
    assert parsed_settings["max_stocks_holding"] == 5, "max_stocks_holding 오류"
    assert parsed_settings["api_call_delay"] == 0.2, "api_call_delay 오류"
    
    print(f"  ✅ Google Sheet 설정 역직렬화 성공: {list(parsed_settings.keys())}")
    print(f"  ✅ infinite_stock_configs: {list(parsed_settings['infinite_stock_configs'].keys())}")
    print("  ✅ PASS")


def test_google_sheet_priority_loading():
    """Google Sheet 설정이 로컬 JSON 설정보다 우선 적용되는지 검증"""
    print("\n=== Test: Google Sheet 설정 최우선 로딩 검증 ===")
    
    # 원본 파일 내용 백업
    original_settings_content = None
    if os.path.exists("infinite_settings.json"):
        with open("infinite_settings.json", "r", encoding="utf-8") as f:
            original_settings_content = f.read()

    try:
        # 1. 가상의 로컬 설정
        local_settings = {
            "infinite_stocks": ["TQQQ"],
            "infinite_stock_configs": {
                "TQQQ": {
                    "total_budget_usd": 3000.0,
                    "division_count": 40,
                    "target_roi": 0.10,
                    "exhaust_action": "HOLD",
                    "exhaust_target_roi": 0.05
                }
            }
        }
        config._apply_settings(local_settings)
        assert config.get_stock_config("TQQQ")["total_budget_usd"] == 3000.0

        # 2. 구글 시트 Mock 객체 생성
        class MockGSS:
            is_connected = True
            def read_settings_from_sheet(self):
                return {
                    "infinite_stocks": ["TQQQ", "SOXL"],
                    "infinite_stock_configs": {
                        "TQQQ": {
                            "total_budget_usd": 7777.0,
                            "division_count": 50,
                            "target_roi": 0.12,
                            "exhaust_action": "REBALANCE_QUARTER",
                            "exhaust_target_roi": 0.06
                        },
                        "SOXL": {
                            "total_budget_usd": 4000.0,
                            "division_count": 30,
                            "target_roi": 0.15,
                            "exhaust_action": "HOLD",
                            "exhaust_target_roi": 0.05
                        }
                    }
                }

        # 3. Google Sheet 우선 로딩 호출
        loaded = config.load_settings_from_google_sheet(gss_instance=MockGSS())
        assert loaded, "Google Sheet 설정 로드 실패"
        
        # 4. config가 로컬 값이 아니라 구글 시트 값으로 완전히 덮어써졌는지 검증
        assert config.INFINITE_STOCKS == ["TQQQ", "SOXL"], f"종목 목록 불일치: {config.INFINITE_STOCKS}"
        tqqq_cfg = config.get_stock_config("TQQQ")
        assert tqqq_cfg["total_budget_usd"] == 7777.0, f"TQQQ 예산 우선 로딩 실패: {tqqq_cfg['total_budget_usd']}"
        assert tqqq_cfg["division_count"] == 50, f"TQQQ 분할 횟수 우선 로딩 실패: {tqqq_cfg['division_count']}"
        assert tqqq_cfg["target_roi"] == 0.12, f"TQQQ 목표수익률 우선 로딩 실패: {tqqq_cfg['target_roi']}"
        assert tqqq_cfg["exhaust_action"] == "REBALANCE_QUARTER", f"TQQQ 소진대응 우선 로딩 실패: {tqqq_cfg['exhaust_action']}"

        soxl_cfg = config.get_stock_config("SOXL")
        assert soxl_cfg["total_budget_usd"] == 4000.0, f"SOXL 예산 우선 로딩 실패: {soxl_cfg['total_budget_usd']}"
        print("  ✅ Google Sheet 설정이 로컬 JSON을 성공적으로 오버라이드함")
        print("  ✅ PASS")
    finally:
        # 원본 파일 복원
        if original_settings_content is not None:
            with open("infinite_settings.json", "w", encoding="utf-8") as f:
                f.write(original_settings_content)


if __name__ == "__main__":
    original_file_content = None
    if os.path.exists("infinite_settings.json"):
        with open("infinite_settings.json", "r", encoding="utf-8") as f:
            original_file_content = f.read()

    try:
        test_auto_execution_flow()
        test_auto_execution_with_multiple_stocks()
        test_google_sheet_settings_sync()
        test_google_sheet_priority_loading()
    finally:
        # 테스트 후 임시 파일 정리
        if os.path.exists(TEST_STATE_FILE):
            os.remove(TEST_STATE_FILE)
        # 설정 파일 및 config 원본 복원
        if original_file_content is not None:
            with open("infinite_settings.json", "w", encoding="utf-8") as f:
                f.write(original_file_content)
            config._load_persistent_settings()
    
    print("\n🎉 자동 실행 시나리오 테스트 전체 통과!")