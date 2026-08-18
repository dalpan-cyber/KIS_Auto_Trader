"""
종목별 무한매수 설정 테스트 스크립트
- config.get_stock_config()가 종목별 설정을 올바르게 반환하는지 검증
- InfiniteStateManager가 종목별 exhaust 설정을 저장/조회하는지 검증
- InfiniteBuyingStrategy가 종목별 exhaust 설정을 사용하는지 검증
"""
import os
import sys
import json
import tempfile

# 테스트용 임시 상태 파일 경로
TEST_STATE_FILE = os.path.join(tempfile.gettempdir(), "test_infinite_state.json")
if os.path.exists(TEST_STATE_FILE):
    os.remove(TEST_STATE_FILE)

import config

def test_get_stock_config():
    """config.get_stock_config()가 종목별 설정을 올바르게 반환하는지 검증"""
    print("=== Test 1: config.get_stock_config() ===")
    
    # 종목별 설정 시뮬레이션
    config.INFINITE_STOCK_CONFIGS = {
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
    }
    
    tqqq_cfg = config.get_stock_config("TQQQ")
    soxl_cfg = config.get_stock_config("SOXL")
    unknown_cfg = config.get_stock_config("SPXL")
    
    assert tqqq_cfg["total_budget_usd"] == 5000.0, f"TQQQ 예산 오류: {tqqq_cfg['total_budget_usd']}"
    assert tqqq_cfg["division_count"] == 40, f"TQQQ 분할 오류: {tqqq_cfg['division_count']}"
    assert tqqq_cfg["target_roi"] == 0.10, f"TQQQ 목표수익률 오류: {tqqq_cfg['target_roi']}"
    assert tqqq_cfg["exhaust_action"] == "HOLD", f"TQQQ 소진대응 오류: {tqqq_cfg['exhaust_action']}"
    
    assert soxl_cfg["total_budget_usd"] == 8000.0, f"SOXL 예산 오류: {soxl_cfg['total_budget_usd']}"
    assert soxl_cfg["division_count"] == 30, f"SOXL 분할 오류: {soxl_cfg['division_count']}"
    assert soxl_cfg["target_roi"] == 0.15, f"SOXL 목표수익률 오류: {soxl_cfg['target_roi']}"
    assert soxl_cfg["exhaust_action"] == "LOWER_TARGET", f"SOXL 소진대응 오류: {soxl_cfg['exhaust_action']}"
    assert soxl_cfg["exhaust_target_roi"] == 0.08, f"SOXL 탈출목표 오류: {soxl_cfg['exhaust_target_roi']}"
    
    # 미등록 종목은 전역 기본값 사용
    assert unknown_cfg["total_budget_usd"] == config.INFINITE_TOTAL_BUDGET_USD, f"미등록 종목 예산 오류"
    assert unknown_cfg["division_count"] == config.INFINITE_DIVISION_COUNT, f"미등록 종목 분할 오류"
    assert unknown_cfg["exhaust_action"] == config.INFINITE_EXHAUST_ACTION, f"미등록 종목 소진대응 오류"
    
    print("  ✅ TQQQ:", tqqq_cfg)
    print("  ✅ SOXL:", soxl_cfg)
    print("  ✅ SPXL(미등록, 기본값):", unknown_cfg)
    print("  ✅ PASS")


def test_state_manager_per_stock():
    """InfiniteStateManager가 종목별 exhaust 설정을 저장/조회하는지 검증"""
    print("\n=== Test 2: InfiniteStateManager 종목별 설정 ===")
    
    from infinite_state_manager import InfiniteStateManager
    
    mgr = InfiniteStateManager(file_path=TEST_STATE_FILE, enable_gss=False)
    
    # TQQQ 상태 생성 (HOLD)
    tqqq_state = mgr.get_symbol_state(
        "TQQQ",
        default_budget_usd=5000.0,
        division_count=40,
        target_roi=0.10,
        exhaust_action="HOLD",
        exhaust_target_roi=0.05
    )
    assert tqqq_state["exhaust_action"] == "HOLD", f"TQQQ exhaust_action 오류: {tqqq_state['exhaust_action']}"
    assert tqqq_state["exhaust_target_roi"] == 0.05, f"TQQQ exhaust_target_roi 오류: {tqqq_state['exhaust_target_roi']}"
    
    # SOXL 상태 생성 (LOWER_TARGET)
    soxl_state = mgr.get_symbol_state(
        "SOXL",
        default_budget_usd=8000.0,
        division_count=30,
        target_roi=0.15,
        exhaust_action="LOWER_TARGET",
        exhaust_target_roi=0.08
    )
    assert soxl_state["exhaust_action"] == "LOWER_TARGET", f"SOXL exhaust_action 오류: {soxl_state['exhaust_action']}"
    assert soxl_state["exhaust_target_roi"] == 0.08, f"SOXL exhaust_target_roi 오류: {soxl_state['exhaust_target_roi']}"
    
    # 상태 파일에 저장되었는지 확인
    with open(TEST_STATE_FILE, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["TQQQ"]["exhaust_action"] == "HOLD", "TQQQ 상태 파일 저장 오류"
    assert saved["SOXL"]["exhaust_action"] == "LOWER_TARGET", "SOXL 상태 파일 저장 오류"
    assert saved["SOXL"]["exhaust_target_roi"] == 0.08, "SOXL 탈출목표 상태 파일 저장 오류"
    
    print("  ✅ TQQQ state:", {k: tqqq_state[k] for k in ["exhaust_action", "exhaust_target_roi", "division_count", "total_budget_usd"]})
    print("  ✅ SOXL state:", {k: soxl_state[k] for k in ["exhaust_action", "exhaust_target_roi", "division_count", "total_budget_usd"]})
    print("  ✅ PASS")


def test_strategy_per_stock():
    """InfiniteBuyingStrategy가 종목별 exhaust 설정을 사용하는지 검증"""
    print("\n=== Test 3: InfiniteBuyingStrategy 종목별 설정 ===")
    
    from strategy import InfiniteBuyingStrategy
    
    strategy = InfiniteBuyingStrategy()
    
    # TQQQ: HOLD 모드, 40회차 소진
    tqqq_state = {
        "current_round": 40,
        "division_count": 40,
        "total_budget_usd": 5000.0,
        "target_roi": 0.10,
        "exhaust_action": "HOLD",
        "exhaust_target_roi": 0.05,
        "status": "BUYING"
    }
    tqqq_orders = strategy.generate_daily_orders("TQQQ", 50.0, tqqq_state, avg_price=45.0, total_qty=100)
    tqqq_sells = [o for o in tqqq_orders if o["action"] == "SELL"]
    tqqq_buys = [o for o in tqqq_orders if o["action"] == "BUY"]
    # HOLD 모드: 매수 없음, 익절 매도만 (원래 목표수익률 +10%)
    assert len(tqqq_buys) == 0, f"TQQQ HOLD 모드에서 매수 주문이 생성됨: {tqqq_buys}"
    assert len(tqqq_sells) == 1, f"TQQQ HOLD 모드에서 익절 매도가 없음"
    assert tqqq_sells[0]["price"] == round(45.0 * 1.10, 2), f"TQQQ HOLD 익절가 오류: {tqqq_sells[0]['price']}"
    
    # SOXL: LOWER_TARGET 모드, 30회차 소진
    soxl_state = {
        "current_round": 30,
        "division_count": 30,
        "total_budget_usd": 8000.0,
        "target_roi": 0.15,
        "exhaust_action": "LOWER_TARGET",
        "exhaust_target_roi": 0.08,
        "status": "BUYING"
    }
    soxl_orders = strategy.generate_daily_orders("SOXL", 20.0, soxl_state, avg_price=18.0, total_qty=200)
    soxl_sells = [o for o in soxl_orders if o["action"] == "SELL"]
    soxl_buys = [o for o in soxl_orders if o["action"] == "BUY"]
    # LOWER_TARGET 모드: 매수 없음, 하향 목표수익률(+8%) 익절 매도
    assert len(soxl_buys) == 0, f"SOXL LOWER_TARGET 모드에서 매수 주문이 생성됨: {soxl_buys}"
    assert len(soxl_sells) == 1, f"SOXL LOWER_TARGET 모드에서 익절 매도가 없음"
    assert soxl_sells[0]["price"] == round(18.0 * 1.08, 2), f"SOXL LOWER_TARGET 익절가 오류: {soxl_sells[0]['price']}"
    
    # SOXL: REBALANCE_QUARTER 모드, 30회차 소진
    soxl_state2 = dict(soxl_state)
    soxl_state2["exhaust_action"] = "REBALANCE_QUARTER"
    soxl_orders2 = strategy.generate_daily_orders("SOXL", 20.0, soxl_state2, avg_price=18.0, total_qty=200)
    soxl_sells2 = [o for o in soxl_orders2 if o["action"] == "SELL"]
    soxl_buys2 = [o for o in soxl_orders2 if o["action"] == "BUY"]
    # REBALANCE_QUARTER 모드: 순환 매도 + LOC 재매수
    assert len(soxl_sells2) >= 1, f"SOXL REBALANCE_QUARTER 모드에서 순환 매도가 없음"
    assert len(soxl_buys2) >= 1, f"SOXL REBALANCE_QUARTER 모드에서 LOC 재매수가 없음"
    
    print("  ✅ TQQQ(HOLD) 주문:", [(o['action'], o['price']) for o in tqqq_orders])
    print("  ✅ SOXL(LOWER_TARGET) 주문:", [(o['action'], o['price']) for o in soxl_orders])
    print("  ✅ SOXL(REBALANCE_QUARTER) 주문:", [(o['action'], o['price']) for o in soxl_orders2])
    print("  ✅ PASS")


def test_update_settings_preserves_state():
    """update_settings()가 설정값만 업데이트하고 전략 진행 상태는 유지하는지 검증"""
    print("\n=== Test 5: update_settings() 전략 상태 유지 ===")
    
    from infinite_state_manager import InfiniteStateManager
    
    mgr = InfiniteStateManager(file_path=TEST_STATE_FILE, enable_gss=False)
    
    # TQQQ 상태 생성 (진행 회차 10, 상태 BUYING)
    tqqq_state = mgr.get_symbol_state(
        "TQQQ",
        default_budget_usd=5000.0,
        division_count=40,
        target_roi=0.10,
        exhaust_action="HOLD",
        exhaust_target_roi=0.05
    )
    tqqq_state["current_round"] = 10
    tqqq_state["status"] = "BUYING"
    tqqq_state["start_date"] = "2026-01-15"
    mgr.save_state()
    
    # 설정값만 업데이트 (전략 상태는 유지)
    mgr.update_settings(
        "TQQQ",
        total_budget_usd=7000.0,
        division_count=50,
        target_roi=0.12,
        exhaust_action="LOWER_TARGET",
        exhaust_target_roi=0.06
    )
    
    updated = mgr.get_symbol_state("TQQQ")
    assert updated["total_budget_usd"] == 7000.0, f"예산 업데이트 오류: {updated['total_budget_usd']}"
    assert updated["division_count"] == 50, f"분할 업데이트 오류: {updated['division_count']}"
    assert updated["target_roi"] == 0.12, f"목표수익률 업데이트 오류: {updated['target_roi']}"
    assert updated["exhaust_action"] == "LOWER_TARGET", f"소진대응 업데이트 오류: {updated['exhaust_action']}"
    assert updated["exhaust_target_roi"] == 0.06, f"탈출목표 업데이트 오류: {updated['exhaust_target_roi']}"
    
    # 전략 진행 상태는 유지되어야 함
    assert updated["current_round"] == 10, f"진행 회차가 초기화됨: {updated['current_round']}"
    assert updated["status"] == "BUYING", f"상태가 초기화됨: {updated['status']}"
    assert updated["start_date"] == "2026-01-15", f"시작일이 초기화됨: {updated['start_date']}"
    
    print(f"  ✅ 설정값 업데이트: 예산=${updated['total_budget_usd']:,.0f}, 분할={updated['division_count']}회, 목표=+{updated['target_roi']*100:.1f}%, 소진대응={updated['exhaust_action']}")
    print(f"  ✅ 전략 상태 유지: 회차={updated['current_round']}, 상태={updated['status']}, 시작일={updated['start_date']}")
    print("  ✅ PASS")


def test_apply_settings():
    """_apply_settings가 infinite_stock_configs를 올바르게 반영하는지 검증"""
    print("\n=== Test 4: _apply_settings ===")
    
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
        "max_stocks_holding": 5,
        "api_call_delay": 0.2,
    }
    
    config._apply_settings(test_settings)
    
    assert config.INFINITE_STOCKS == ["TQQQ", "SOXL"], f"INFINITE_STOCKS 오류: {config.INFINITE_STOCKS}"
    assert config.TARGET_STOCKS == ["TQQQ", "SOXL"], f"TARGET_STOCKS 오류: {config.TARGET_STOCKS}"
    assert "TQQQ" in config.INFINITE_STOCK_CONFIGS, "TQQQ 설정 누락"
    assert "SOXL" in config.INFINITE_STOCK_CONFIGS, "SOXL 설정 누락"
    assert config.INFINITE_STOCK_CONFIGS["SOXL"]["exhaust_action"] == "LOWER_TARGET", "SOXL exhaust_action 오류"
    assert config.INFINITE_STOCK_CONFIGS["SOXL"]["exhaust_target_roi"] == 0.08, "SOXL exhaust_target_roi 오류"
    
    print("  ✅ INFINITE_STOCKS:", config.INFINITE_STOCKS)
    print("  ✅ INFINITE_STOCK_CONFIGS:", config.INFINITE_STOCK_CONFIGS)
    print("  ✅ PASS")


if __name__ == "__main__":
    test_get_stock_config()
    test_state_manager_per_stock()
    test_strategy_per_stock()
    test_update_settings_preserves_state()
    test_apply_settings()
    
    # 테스트 후 임시 파일 정리
    if os.path.exists(TEST_STATE_FILE):
        os.remove(TEST_STATE_FILE)
    
    print("\n🎉 모든 종목별 설정 테스트 통과!")