"""
CTOS4001R (기간별거래) 빈 응답 디버깅 스크립트
================================================
목적: 해외주식 체결이력 조회 시 output1/output이 비어있는 문제를 진단한다.

디버깅 포인트:
1. API 응답 원문 (rt_cd, msg_cd, msg1, output1, output2, ctx_area_fk100, ctx_area_nk100)
2. 요청 파라미터 검증 (CANO, ACNT_PRDT_CD, ERLM_STRT_DT, ERLM_END_DT, OVRS_EXCG_CD, PDNO)
3. 다양한 파라미터 조합 시도 (거래소 변경, 매도/매수 구분 변경, 기간 확장)
4. 응답 키 구조 확인 (output1 vs output vs output2)

사용법:
  python debug_ctos4001r.py                    # 기본 실행
  python debug_ctos4001r.py --mock             # 모의투자 모드로 실행
  python debug_ctos4001r.py --symbol TQQQ      # 특정 종목 필터
  python debug_ctos4001r.py --days 90          # 조회 기간 (일)
"""
import os
import sys
import json
import time
import logging
import requests
from datetime import datetime, timedelta

# 로깅 설정 - DEBUG 레벨로 모든 로그 출력
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("CTOS4001R_DEBUG")

import config
from kis_api import KISApiClient

def print_separator(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")

def debug_api_call(client: KISApiClient, params: dict, tr_id: str, url: str, label: str):
    """API 호출 후 전체 응답을 상세히 출력"""
    print_separator(f"[{label}] API 호출")
    print(f"  URL: {url}")
    print(f"  TR_ID: {tr_id}")
    print(f"  Params:")
    for k, v in params.items():
        print(f"    {k} = {v}")

    headers = client._get_headers(tr_id)
    headers["tr_cont"] = ""  # 초기 조회 (연속 조회 시 "N")
    print(f"  Headers (일부):")
    print(f"    authorization = Bearer {client.access_token[:20]}...")
    print(f"    appkey = {client.app_key[:10]}...")
    print(f"    appsecret = {client.app_secret[:10]}...")
    print(f"    tr_id = {tr_id}")
    print(f"    tr_cont = {headers.get('tr_cont')}")
    print(f"    custtype = {headers.get('custtype')}")

    try:
        client._rate_limit()
        res = requests.get(url, headers=headers, params=params, timeout=10)
        print(f"\n  HTTP Status: {res.status_code}")
        print(f"  Response Headers: {dict(res.headers)}")
        print(f"  Raw Response Body (전체):")
        print(f"  {res.text[:5000]}")
        print()

        data = client._safe_json_response(res, context=f"DEBUG[{label}]")
        print(f"  Parsed JSON Keys: {list(data.keys())}")
        print(f"  rt_cd: {data.get('rt_cd')}")
        print(f"  msg_cd: {data.get('msg_cd')}")
        print(f"  msg1: {data.get('msg1')}")
        print(f"  output1: {json.dumps(data.get('output1', []), ensure_ascii=False)[:2000]}")
        print(f"  output2: {json.dumps(data.get('output2', []), ensure_ascii=False)[:2000]}")
        print(f"  output: {json.dumps(data.get('output', []), ensure_ascii=False)[:2000]}")
        print(f"  ctx_area_fk100: {data.get('ctx_area_fk100')}")
        print(f"  ctx_area_nk100: {data.get('ctx_area_nk100')}")

        # 응답에 있는 모든 키 출력
        print(f"\n  응답의 모든 최상위 키:")
        for key in data.keys():
            val = data[key]
            if isinstance(val, list):
                print(f"    {key}: list[{len(val)}]")
            elif isinstance(val, dict):
                print(f"    {key}: dict{list(val.keys())}")
            else:
                print(f"    {key}: {val}")

        return data
    except Exception as e:
        print(f"\n  ❌ 예외 발생: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    # CLI 인자 파싱
    args = sys.argv[1:]
    use_mock = "--mock" in args
    symbol_filter = ""
    days_back = 30

    for i, a in enumerate(args):
        if a == "--symbol" and i + 1 < len(args):
            symbol_filter = args[i + 1].upper()
        elif a == "--days" and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                pass

    print_separator("CTOS4001R 빈 응답 디버깅 시작")
    print(f"  현재 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  MOCK_TRADING_ONLY: {config.MOCK_TRADING_ONLY}")
    print(f"  URL_BASE: {config.URL_BASE}")
    print(f"  CANO: {config.CANO}")
    print(f"  ACNT_PRDT_CD: {config.ACNT_PRDT_CD}")
    print(f"  APP_KEY 설정됨: {bool(config.APP_KEY)}")
    print(f"  APP_SECRET 설정됨: {bool(config.APP_SECRET)}")
    print(f"  CLI 인자: mock={use_mock}, symbol={symbol_filter or '전체'}, days={days_back}")

    # 1. 클라이언트 초기화 및 토큰 확인
    client = KISApiClient(mock=use_mock) if use_mock else KISApiClient()
    print(f"\n  Access Token 유효: {client.is_token_valid()}")
    if not client.is_token_valid():
        print("  토큰 발급 시도...")
        ok = client.get_access_token()
        print(f"  토큰 발급 결과: {ok}")
        if not ok:
            print("  ❌ 토큰 발급 실패")
            print("  ⚠️  환경변수(KIS_APP_KEY, KIS_APP_SECRET, KIS_CANO)가 설정되어 있는지 확인하세요.")
            print("  ⚠️  .env 파일이 있는지, 또는 실행 환경에서 환경변수가 주입되는지 확인하세요.")
            print("  ⚠️  GitHub Actions 등 CI 환경에서는 Secrets가 주입되는지 확인하세요.")
            return

    # 2. 기본 파라미터 (현재 코드와 동일)
    today = datetime.now().strftime("%Y%m%d")
    week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    month_ago = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    tr_id = "VCTS4001R" if client.mock else "CTOS4001R"
    url = f"{client.url_base}/uapi/overseas-stock/v1/trading/inquire-period-trans"

    # 3. 다양한 파라미터 조합으로 테스트
    test_cases = [
        {
            "label": "기본 (오늘~오늘, 전체 거래소, 전체)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ERLM_STRT_DT": today,
                "ERLM_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": "7일 기간 (전체 거래소, 전체)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ERLM_STRT_DT": week_ago,
                "ERLM_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": f"{days_back}일 기간 (전체 거래소, 전체)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ERLM_STRT_DT": month_ago,
                "ERLM_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": f"{days_back}일 기간 (전체 거래소, 전체)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ERLM_STRT_DT": month_ago,
                "ERLM_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": f"{days_back}일 기간 (전체 거래소, 매수만)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ERLM_STRT_DT": month_ago,
                "ERLM_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": f"{days_back}일 기간 (전체 거래소, 매도만)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ERLM_STRT_DT": month_ago,
                "ERLM_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": f"{days_back}일 기간 (전체 거래소, 전체 - NYS 테스트)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ERLM_STRT_DT": month_ago,
                "ERLM_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": f"{days_back}일 기간 (전체 거래소, 전체 - AMS 테스트)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ERLM_STRT_DT": month_ago,
                "ERLM_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": f"{days_back}일 기간 (전체 거래소, ORD_STRT_DT/ORD_END_DT 사용)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "ORD_STRT_DT": month_ago,
                "ORD_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
        {
            "label": f"{days_back}일 기간 (전체 거래소, TRD_STRT_DT/TRD_END_DT 사용)",
            "params": {
                "CANO": client.cano,
                "ACNT_PRDT_CD": client.acnt_prdt_cd,
                "TRD_STRT_DT": month_ago,
                "TRD_END_DT": today,
                "OVRS_EXCG_CD": "NAS",
                "PDNO": "TQQQ",
                "SLL_BUY_DVSN_CD": "02",
                "LOAN_DVSN_CD": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
        },
    ]

    # 4. 각 테스트 케이스 실행
    for tc in test_cases:
        data = debug_api_call(client, tc["params"], tr_id, url, tc["label"])
        if data and data.get("rt_cd") == "0":
            output1 = data.get("output1", []) or data.get("output", [])
            if output1:
                print(f"\n  ✅ [{tc['label']}] 데이터 발견! {len(output1)}건")
                # 첫 번째 레코드의 키 구조 출력
                print(f"  첫 번째 레코드 키: {list(output1[0].keys())}")
                print(f"  첫 번째 레코드: {json.dumps(output1[0], ensure_ascii=False, indent=2)[:2000]}")
            else:
                print(f"\n  ⚠️ [{tc['label']}] rt_cd=0 이지만 output1/output 비어있음")
        else:
            print(f"\n  ❌ [{tc['label']}] API 오류")
        time.sleep(0.5)

    # 5. 계좌 잔고도 확인 (계좌에 실제 거래가 있는지)
    print_separator("계좌 잔고 확인 (해외)")
    try:
        bal = client.get_overseas_stock_balance()
        print(f"  해외 잔고: {json.dumps(bal, ensure_ascii=False, indent=2)[:2000]}")
    except Exception as e:
        print(f"  해외 잔고 조회 실패: {e}")

    print_separator("디버깅 완료")
    print("""
[결론 해석 가이드]
1. 모든 테스트에서 output1이 비어있음 → 계좌에 해당 기간 거래가 없거나, 
   등록일자(ERLM_STRT_DT/ERLM_END_DT) 기준이 아닌 다른 기준으로 조회해야 함
2. 특정 거래소에서만 데이터가 있음 → OVRS_EXCG_CD를 해당 거래소로 변경 필요
3. 특정 매수/매도 구분에서만 데이터가 있음 → SLL_BUY_DVSN_CD 조정 필요
4. rt_cd가 0이 아닌 오류 → msg1/msg_cd 확인 필요
5. 계좌 잔고도 비어있음 → 계좌 자체에 문제가 있을 수 있음 (CANO/ACNT_PRDT_CD 확인)
""")

if __name__ == "__main__":
    main()