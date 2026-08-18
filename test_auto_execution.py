"""
자동 실행(GitHub Actions / run_infinite_buying.py) 시나리오 테스트
- 종목별 설정이 자동 실행 경로에서도 올바르게 적용되는지 검증
"""
import os
import sys
import json
import tempfile

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


if __name__ == "__main__":
    test_auto_execution_flow()
    test_auto_execution_with_multiple_stocks()
    
    # 테스트 후 임시 파일 정리
    if os.path.exists(TEST_STATE_FILE):
        os.remove(TEST_STATE_FILE)
    
    print("\n🎉 자동 실행 시나리오 테스트 통과!")