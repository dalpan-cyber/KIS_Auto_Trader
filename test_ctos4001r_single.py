"""
CTOS4001R (기간별거래) 단일 쿼리 테스트 스크립트
================================================
목적: 해외주식 체결이력 조회 API(CTOS4001R) 하나만 단일 쿼리로 시험한다.

사용법:
  python test_ctos4001r_single.py                    # 기본 실행 (실거래)
  python test_ctos4001r_single.py --mock             # 모의투자 모드로 실행
  python test_ctos4001r_single.py --days 90          # 조회 기간 (일)
"""
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
logger = logging.getLogger("CTOS4001R_SINGLE")

import config
from kis_api import KISApiClient


def print_separator(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def main():
    # CLI 인자 파싱
    args = sys.argv[1:]
    use_mock = "--mock" in args
    days_back = 30

    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                pass

    print_separator("CTOS4001R 단일 쿼리 테스트")
    print(f"  현재 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  MOCK_TRADING_ONLY: {config.MOCK_TRADING_ONLY}")
    print(f"  URL_BASE: {config.URL_BASE}")
    print(f"  CANO: {config.CANO}")
    print(f"  ACNT_PRDT_CD: {config.ACNT_PRDT_CD}")
    print(f"  APP_KEY 설정됨: {bool(config.APP_KEY)}")
    print(f"  APP_SECRET 설정됨: {bool(config.APP_SECRET)}")
    print(f"  CLI 인자: mock={use_mock}, days={days_back}")

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
            return

    # 2. 조회 기간 설정
    today = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    # 3. CTOS4001R API 호출 (단일 쿼리)
    tr_id = "VCTS4001R" if client.mock else "CTOS4001R"
    url = f"{client.url_base}/uapi/overseas-stock/v1/trading/inquire-period-trans"

    params = {
        "CANO": client.cano,
        "ACNT_PRDT_CD": client.acnt_prdt_cd,
        "ERLM_STRT_DT": start_date,
        "ERLM_END_DT": today,
        "OVRS_EXCG_CD": "NAS",
        "PDNO": "TQQQ",
        "SLL_BUY_DVSN_CD": "00",
        "LOAN_DVSN_CD": "",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }

    print_separator("CTOS4001R API 호출")
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

        data = client._safe_json_response(res, context="CTOS4001R_SINGLE")
        print(f"  Parsed JSON Keys: {list(data.keys())}")
        print(f"  rt_cd: {data.get('rt_cd')}")
        print(f"  msg_cd: {data.get('msg_cd')}")
        print(f"  msg1: {data.get('msg1')}")
        print(f"  output1: {json.dumps(data.get('output1', []), ensure_ascii=False)[:2000]}")
        print(f"  output2: {json.dumps(data.get('output2', []), ensure_ascii=False)[:2000]}")
        print(f"  output: {json.dumps(data.get('output', []), ensure_ascii=False)[:2000]}")
        print(f"  ctx_area_fk100: {data.get('ctx_area_fk100')}")
        print(f"  ctx_area_nk100: {data.get('ctx_area_nk100')}")
        print(f"  tr_cont: {res.headers.get('tr_cont', '(없음)')}")

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

        # 결과 판정
        print_separator("결과 판정")
        if data.get("rt_cd") == "0":
            output1 = data.get("output1", []) or data.get("output", [])
            if output1:
                print(f"  ✅ 데이터 발견! {len(output1)}건")
                print(f"  첫 번째 레코드 키: {list(output1[0].keys())}")
                print(f"  첫 번째 레코드: {json.dumps(output1[0], ensure_ascii=False, indent=2)[:2000]}")
            else:
                print(f"  ⚠️ rt_cd=0 이지만 output1/output 비어있음")
        else:
            print(f"  ❌ API 오류 (rt_cd={data.get('rt_cd')}, msg1={data.get('msg1')})")

    except Exception as e:
        print(f"\n  ❌ 예외 발생: {e}")
        import traceback
        traceback.print_exc()

    print_separator("테스트 완료")


if __name__ == "__main__":
    main()