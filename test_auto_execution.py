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


def test_soxl_exchange_and_execution():
    """SOXL 등 아멕스(AMEX) 상장 종목 거래소 자동 감지 및 주문 실행 검증"""
    print("\n=== Test: SOXL 등 종목별 거래소 자동 감지 및 매수 실행 ===")
    from kis_api import KISApiClient
    from trader import TraderBot

    api = KISApiClient(mock=True)
    
    # 1. 거래소 자동 감지 검증
    assert api.get_symbol_exchange("SOXL") == "AMS", f"SOXL 거래소 오류: {api.get_symbol_exchange('SOXL')}"
    assert api.get_symbol_exchange("TQQQ") == "NAS", f"TQQQ 거래소 오류: {api.get_symbol_exchange('TQQQ')}"
    assert api.get_symbol_exchange("SPXL") == "AMS", f"SPXL 거래소 오류: {api.get_symbol_exchange('SPXL')}"
    print("  ✅ 종목별 거래소 자동 매핑 정상: SOXL->AMS, TQQQ->NAS, SPXL->AMS")

    # 2. TraderBot의 execute_daily_orders(SOXL) 시뮬레이션
    bot = TraderBot(api)
    from infinite_state_manager import InfiniteStateManager
    bot.infinite_state_mgr = InfiniteStateManager(file_path=TEST_STATE_FILE, enable_gss=False)
    bot.fetch_account_balance = lambda: None  # 테스트 중 불필요한 네트워크 API 호출 방지
    bot.holdings["SOXL"] = {"qty": 0, "avg_price": 0.0}
    bot.current_prices["SOXL"] = 25.0

    # 주문 호출 캡처용 mock
    order_calls = []
    def mock_order(symbol, qty, price=0, buy=True, exchange="NAS", ord_type="00", **kwargs):
        eff_exch = api.get_symbol_exchange(symbol) if exchange == "NAS" else exchange
        exchange_map = {"NAS": "NASD", "NYS": "NYSE", "AMS": "AMEX", "NASD": "NASD", "NYSE": "NYSE", "AMEX": "AMEX"}
        ovrs_excg_cd = exchange_map.get(eff_exch.upper(), "NASD")
        order_calls.append({
            "symbol": symbol, "qty": qty, "price": price, "buy": buy,
            "exchange": eff_exch, "ovrs_excg_cd": ovrs_excg_cd, "ord_type": ord_type
        })
        return {"success": True, "msg": "주문 성공", "data": {"ODNO": "MOCK_9999"}}
    api.order_overseas_cash = mock_order

    # SOXL 상태를 IDLE로 시작
    bot.infinite_state_mgr.states["SOXL"] = {
        "symbol": "SOXL",
        "start_date": "2026-09-08",
        "total_budget_usd": 5000.0,
        "division_count": 40,
        "current_round": 0,
        "target_roi": 0.10,
        "exhaust_action": "HOLD",
        "exhaust_target_roi": 0.05,
        "status": "IDLE",
        "peak_qty": 0
    }

    # 매수 실행
    res = bot.execute_daily_orders("SOXL", action_filter="BUY")
    assert res["success"], f"주문 실행 실패: {res}"
    assert res["executed"] == 2, f"0.5회차 매수 2건 미실행: {res['executed']}"
    assert len(order_calls) == 2, f"주문 호출 수 오류: {len(order_calls)}"
    
    # 두 주문 모두 거래소 코드가 AMEX(AMS)로 전달되었는지 검증
    for call in order_calls:
        assert call["exchange"] == "AMS", f"거래소 불일치: {call['exchange']}"
        assert call["ovrs_excg_cd"] == "AMEX", f"OVRS_EXCG_CD 불일치: {call['ovrs_excg_cd']}"
    print(f"  ✅ SOXL 주문 거래소 AMEX(AMS) 매핑 검증 완료: {[c['ovrs_excg_cd'] for c in order_calls]}")

    # IDLE 상태에서 BUYING 상태로 자동 전환되었는지 검증 (held_qty=0임에도 조기 COMPLETED되지 않고 BUYING 유지)
    soxl_st = bot.infinite_state_mgr.get_symbol_state("SOXL")
    assert soxl_st["status"] == "BUYING", f"상태가 BUYING으로 전환되지 않음: {soxl_st['status']}"
    assert soxl_st["current_round"] == 1.0, f"회차가 1.0으로 증가하지 않음: {soxl_st['current_round']}"
    print("  ✅ SOXL IDLE -> BUYING 자동 전환 및 2건 분할 매수 접수 성공 (회차: 1.0, 상태: BUYING 유지)")

    # 3. 체결 후 실제 매수 수량 반영 시뮬레이션 (held_qty: 10주)
    bot.holdings["SOXL"] = {"qty": 10, "avg_price": 25.0}
    bot.sync_holdings_to_state()
    soxl_st = bot.infinite_state_mgr.get_symbol_state("SOXL")
    assert soxl_st["peak_qty"] == 10, f"peak_qty 갱신 실패: {soxl_st.get('peak_qty')}"
    assert soxl_st["status"] == "BUYING", f"체결 보유 중 상태 오류: {soxl_st['status']}"
    print("  ✅ SOXL 실계좌 체결 반영: peak_qty=10 갱신 및 BUYING 유지 확인")

    # 4. 전량 익절 매도 체결 시뮬레이션 (held_qty: 0주)
    bot.holdings["SOXL"] = {"qty": 0, "avg_price": 0.0}
    bot.sync_holdings_to_state()
    soxl_st = bot.infinite_state_mgr.get_symbol_state("SOXL")
    assert soxl_st["status"] == "COMPLETED", f"전량 매도 후 COMPLETED 미전환: {soxl_st['status']}"
    assert soxl_st["current_round"] == 0, f"전량 매도 후 회차 리셋 실패: {soxl_st['current_round']}"
    assert soxl_st["peak_qty"] == 0, f"전량 매도 후 peak_qty 리셋 실패: {soxl_st.get('peak_qty')}"
    print("  ✅ SOXL 전량 매도 체결 감지: COMPLETED 전환 및 회차/peak_qty 리셋 검증 완료")
    print("  ✅ PASS")


def test_pause_and_resume_flow():
    """종목별 투자 일시중지(PAUSED) 및 재개(BUYING), 지정 매도가 매도 검증"""
    print("\n=== Test: 투자 일시중지 / 재개 및 지정 매도가 동작 ===")
    from unittest.mock import MagicMock
    from trader import TraderBot
    from kis_api import KISApiClient
    from infinite_state_manager import InfiniteStateManager

    mgr = InfiniteStateManager(file_path=TEST_STATE_FILE, enable_gss=False)
    api = KISApiClient()
    api.is_overseas_symbol = MagicMock(return_value=True)
    api.get_stock_price = MagicMock(return_value={"success": True, "price": "28.50"})

    order_calls = []
    def mock_order(symbol, qty, price=0.0, buy=True, ord_type="00"):
        order_calls.append({"symbol": symbol, "qty": qty, "price": price, "buy": buy, "ord_type": ord_type})
        return {"success": True, "msg": "주문 성공", "data": {"ODNO": "MOCK_7777"}}
    api.order_overseas_cash = mock_order

    bot = TraderBot(api=api)
    bot.infinite_state_mgr = mgr
    bot.holdings["SOXL"] = {"qty": 10, "avg_price": 25.0}

    # 1. 초기 운용 상태 (BUYING)
    mgr.states["SOXL"] = {
        "symbol": "SOXL",
        "start_date": "2026-09-08",
        "total_budget_usd": 5000.0,
        "division_count": 40,
        "current_round": 2.0,
        "target_roi": 0.10,
        "exhaust_action": "HOLD",
        "exhaust_target_roi": 0.05,
        "status": "BUYING",
        "peak_qty": 10,
        "paused_sell_price": 0.0
    }

    # 2. 투자 일시중지 설정 (지정 매도가 $32.00)
    bot.pause_infinite_buying("SOXL", sell_price=32.0)
    st = mgr.get_symbol_state("SOXL")
    assert st["status"] == "PAUSED", f"상태가 PAUSED가 아님: {st['status']}"
    assert st["paused_sell_price"] == 32.0, f"paused_sell_price 오류: {st['paused_sell_price']}"
    print("  ✅ 1. SOXL 투자 일시중지 설정 완료 (status: PAUSED, paused_sell_price: $32.00)")

    # 3. 일시중지 상태에서 당일 주문 생성 시 매수 주문은 0건, 매도 주문은 지정가 $32.00로 생성되는지 검증
    orders = bot.infinite_strategy.generate_daily_orders("SOXL", 28.50, st, avg_price=25.0, total_qty=10)
    buy_orders = [o for o in orders if o["action"] == "BUY"]
    sell_orders = [o for o in orders if o["action"] == "SELL"]
    assert len(buy_orders) == 0, f"일시중지 상태인데 매수 주문이 생성됨: {buy_orders}"
    assert len(sell_orders) == 1, f"일시중지 상태 지정 매도 주문 누락: {sell_orders}"
    assert sell_orders[0]["price"] == 32.0, f"지정 매도가 불일치: {sell_orders[0]['price']}"
    assert sell_orders[0]["qty"] == 10, f"매도 수량 불일치: {sell_orders[0]['qty']}"
    print("  ✅ 2. 주문 생성 검증: 매수 주문 0건 차단 확인, 전량 매도 주문 $32.00(10주) 확인")

    # 4. 일시중지 상태에서 매수 주문 실행(BUY) 시도 시 즉시 차단 검증
    res_buy = bot.execute_daily_orders("SOXL", action_filter="BUY")
    assert res_buy["executed"] == 0, f"일시중지 중 매수 주문이 실행됨: {res_buy}"
    assert any("차단" in m for m in res_buy["messages"]), f"차단 메시지 누락: {res_buy['messages']}"
    print("  ✅ 3. execute_daily_orders(BUY) 호출 시 매수 발주 차단 검증 완료")

    # 5. 일시중지 상태에서 매도 주문 실행(SELL) 시 지정가 $32.00로 정상 발주 검증
    order_calls.clear()
    res_sell = bot.execute_daily_orders("SOXL", action_filter="SELL")
    assert res_sell["executed"] == 1, f"매도 주문 실행 실패: {res_sell}"
    assert len(order_calls) == 1
    assert order_calls[0]["price"] == 32.0
    assert order_calls[0]["buy"] is False
    print("  ✅ 4. execute_daily_orders(SELL) 호출 시 지정 매도가 $32.00 발주 검증 완료")

    # 6. 실계좌 동기화(sync_holdings_to_state) 시 PAUSED 상태가 BUYING으로 풀리지 않는지 검증
    bot.sync_holdings_to_state()
    st_after_sync = mgr.get_symbol_state("SOXL")
    assert st_after_sync["status"] == "PAUSED", f"sync_holdings_to_state 후 PAUSED 상태 훼손됨: {st_after_sync['status']}"
    print("  ✅ 5. sync_holdings_to_state 실행 후에도 PAUSED 상태 보존 검증 완료")

    # 7. 투자 재개 (resume_infinite_buying) 검증
    bot.resume_infinite_buying("SOXL")
    st_resumed = mgr.get_symbol_state("SOXL")
    assert st_resumed["status"] == "BUYING", f"재개 후 BUYING 미복원: {st_resumed['status']}"
    assert st_resumed["paused_sell_price"] == 0.0, f"재개 후 paused_sell_price 초기화 실패: {st_resumed['paused_sell_price']}"

    # 재개 후 주문 생성 시 분할 매수 주문이 다시 정상 생성되는지 확인
    resumed_orders = bot.infinite_strategy.generate_daily_orders("SOXL", 28.50, st_resumed, avg_price=25.0, total_qty=10)
    resumed_buy_orders = [o for o in resumed_orders if o["action"] == "BUY"]
    assert len(resumed_buy_orders) > 0, f"재개 후 매수 주문 미생성: {resumed_orders}"
    print("  ✅ 6. resume_infinite_buying 후 BUYING 상태 복원 및 매수 주문 재개 검증 완료")
    print("  ✅ PASS")


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
        test_soxl_exchange_and_execution()
        test_pause_and_resume_flow()
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