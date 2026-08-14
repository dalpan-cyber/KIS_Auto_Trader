"""
TTTS3035R / VTTS3035R (inquire-ccnl) 해외주식 주문체결내역 조회 테스트 스크립트
================================================================================
목적: 해외주식 주문체결내역 조회 API(inquire-ccnl)의 request/response를
      상세히 확인할 수 있는 단일 쿼리 테스트 스크립트.
      .env 파일의 key 값들로 request 헤더를 직접 구성한다.
      연속 조회(tr_cont=M) 시 모든 페이지를 자동으로 조회한다.

API 정보:
  - 실전 TR_ID: TTTS3035R
  - 모의 TR_ID: VTTS3035R
  - HTTP Method: GET
  - 실전 Domain: https://openapi.koreainvestment.com:9443
  - 모의 Domain: https://openapivts.koreainvestment.com:29443
  - URL: /uapi/overseas-stock/v1/trading/inquire-ccnl

사용법:
  python test_inquire_ccnl.py                    # 기본 실행 (실전)
  python test_inquire_ccnl.py --mock             # 모의투자 모드로 실행
  python test_inquire_ccnl.py --days 90          # 조회 기간 (일)
  python test_inquire_ccnl.py --pdno TQQQ        # 특정 종목 조회
  python test_inquire_ccnl.py --excg NASD        # 특정 거래소 조회
  python test_inquire_ccnl.py --sll-buy 01       # 매도/매수 구분 (00:전체, 01:매도, 02:매수)
  python test_inquire_ccnl.py --ccld 00          # 체결/미체결 구분 (00:전체, 01:체결, 02:미체결)
  python test_inquire_ccnl.py --sort AS          # 정렬순서 (DS:정순, AS:역순)
  python test_inquire_ccnl.py --debug            # 디버그 모드 (다양한 파라미터 조합 시도)
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
logger = logging.getLogger("INQUIRE_CCNL")


# ============================================================
# .env 파일 직접 로드 (config.py를 거치지 않고 .env 값을 직접 사용)
# ============================================================
def load_env_file(env_path: str = ".env") -> dict:
    """.env 파일을 직접 파싱하여 dict로 반환"""
    env_vars = {}
    if not os.path.exists(env_path):
        logger.warning(f".env 파일이 없습니다: {env_path}")
        return env_vars

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key:
                    env_vars[key] = value
    except Exception as e:
        logger.error(f".env 파일 로드 실패: {e}")

    return env_vars


# .env 파일에서 직접 값 로드
ENV = load_env_file()

# .env에서 직접 읽은 값들
APP_KEY = ENV.get("KIS_APP_KEY", "")
APP_SECRET = ENV.get("KIS_APP_SECRET", "")
CANO = ENV.get("KIS_CANO", "")
ACNT_PRDT_CD = ENV.get("KIS_ACNT_PRDT_CD", "01")
MOCK_TRADING_ONLY = ENV.get("MOCK_TRADING_ONLY", "false").lower() == "true"

# API 서버 Base URL
URL_BASE_MOCK = "https://openapivts.koreainvestment.com:29443"
URL_BASE_REAL = "https://openapi.koreainvestment.com:9443"


# ============================================================
# Access Token 발급 (.env의 appkey/appsecret 사용)
# ============================================================
def get_access_token(url_base: str, app_key: str, app_secret: str) -> str:
    """OAuth 2.0 Access Token 발급 요청"""
    url = f"{url_base}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    body = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }

    print_separator("ACCESS TOKEN 발급")
    print(f"  URL: {url}")
    print(f"  Headers: {headers}")
    print(f"  Body: grant_type=client_credentials, appkey={app_key[:10]}..., appsecret={app_secret[:10]}...")

    try:
        res = requests.post(url, headers=headers, json=body, timeout=10)
        print(f"  HTTP Status: {res.status_code}")
        print(f"  Response: {res.text[:500]}")

        if res.status_code == 200:
            data = res.json()
            token = data.get("access_token", "")
            if token:
                print(f"  ✅ Access Token 발급 성공 (token: {token[:20]}...)")
                return token
            else:
                print(f"  ❌ Access Token 발급 실패: {data}")
                return ""
        else:
            print(f"  ❌ Access Token 발급 실패: HTTP {res.status_code}")
            return ""
    except Exception as e:
        print(f"  ❌ Access Token 발급 예외: {e}")
        return ""


def print_separator(title: str):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print(f"{'='*70}")


def print_request_details(url: str, tr_id: str, headers: dict, params: dict):
    """요청(request) 상세 정보 출력"""
    print_separator("REQUEST (요청 정보)")
    print(f"  HTTP Method : GET")
    print(f"  URL         : {url}")
    print(f"  TR_ID       : {tr_id}")
    print()

    print("  [Headers]")
    for k, v in headers.items():
        # 민감 정보는 일부만 표시
        if k == "authorization":
            print(f"    {k} = Bearer {v[7:27]}... (일부 표시)")
        elif k in ("appkey", "appsecret"):
            print(f"    {k} = {v[:10]}... (일부 표시)")
        else:
            print(f"    {k} = {v}")
    print()

    print("  [Query Params]")
    for k, v in params.items():
        print(f"    {k} = {v}")
    print()


def print_response_details(res: requests.Response, data: dict):
    """응답(response) 상세 정보 출력"""
    print_separator("RESPONSE (응답 정보)")
    print(f"  HTTP Status : {res.status_code}")
    print(f"  Response Headers:")
    for k, v in res.headers.items():
        print(f"    {k} = {v}")
    print()

    print(f"  Raw Response Body (전체):")
    print(f"  {res.text[:8000]}")
    print()

    print(f"  Parsed JSON 최상위 키: {list(data.keys())}")
    print(f"  rt_cd           : {data.get('rt_cd')}")
    print(f"  msg_cd          : {data.get('msg_cd')}")
    print(f"  msg1            : {data.get('msg1')}")
    print(f"  ctx_area_fk200  : {data.get('ctx_area_fk200')}")
    print(f"  ctx_area_nk200  : {data.get('ctx_area_nk200')}")
    print()

    # output 배열 상세 출력
    output = data.get("output", [])
    if isinstance(output, list):
        print(f"  output (array)  : {len(output)}건")
        for i, item in enumerate(output):
            print(f"\n  --- output[{i}] ---")
            if isinstance(item, dict):
                for k, v in item.items():
                    print(f"    {k} = {v}")
            else:
                print(f"    {item}")
    elif isinstance(output, dict):
        print(f"  output (dict)   :")
        for k, v in output.items():
            print(f"    {k} = {v}")
    else:
        print(f"  output          : {output}")
    print()


def print_result_judgment(data: dict):
    """결과 판정 출력"""
    print_separator("결과 판정")
    if data.get("rt_cd") == "0":
        output = data.get("output", [])
        if isinstance(output, list) and output:
            print(f"  ✅ API 호출 성공! {len(output)}건의 주문/체결 내역이 조회되었습니다.")
            print(f"  첫 번째 레코드 키 목록: {list(output[0].keys()) if isinstance(output[0], dict) else 'N/A'}")
            print(f"  첫 번째 레코드 상세:")
            print(f"  {json.dumps(output[0], ensure_ascii=False, indent=2)[:3000]}")
        else:
            print(f"  ⚠️ rt_cd=0 이지만 output이 비어있습니다. (해당 기간에 주문/체결 내역이 없을 수 있음)")
    else:
        print(f"  ❌ API 오류 (rt_cd={data.get('rt_cd')}, msg_cd={data.get('msg_cd')}, msg1={data.get('msg1')})")
        print(f"  ⚠️  참고: msg_cd가 'EGW00123'이면 Access Token 만료, 'EGW00120'이면 유효하지 않은 토큰입니다.")
        print(f"  ⚠️  HTTP 500 오류는 서버 측 오류로, 요청 파라미터가 API 스펙과 일치하지 않을 때 발생할 수 있습니다.")
        print(f"  ⚠️  --debug 옵션으로 다양한 파라미터 조합을 시도해보세요.")


def build_headers(access_token: str, app_key: str, app_secret: str, tr_id: str) -> dict:
    """.env 값으로 request 헤더 직접 구성"""
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "tr_cont": "",  # 초기 조회 (연속 조회 시 "N")
        "custtype": "P"
    }
    return headers


def debug_api_call(url_base: str, access_token: str, params: dict, tr_id: str, url: str, label: str):
    """디버그 모드: API 호출 후 전체 응답을 상세히 출력"""
    print_separator(f"[{label}] API 호출")
    print(f"  URL: {url}")
    print(f"  TR_ID: {tr_id}")
    print(f"  Params:")
    for k, v in params.items():
        print(f"    {k} = {v}")

    headers = build_headers(access_token, APP_KEY, APP_SECRET, tr_id)
    print(f"  Headers (일부):")
    print(f"    authorization = Bearer {access_token[:20]}...")
    print(f"    appkey = {APP_KEY[:10]}...")
    print(f"    appsecret = {APP_SECRET[:10]}...")
    print(f"    tr_id = {tr_id}")
    print(f"    tr_cont = {headers.get('tr_cont')}")
    print(f"    custtype = {headers.get('custtype')}")

    try:
        time.sleep(0.2)  # API 연속 호출 제한
        res = requests.get(url, headers=headers, params=params, timeout=10)
        print(f"\n  HTTP Status: {res.status_code}")
        print(f"  Response Headers: {dict(res.headers)}")
        print(f"  Raw Response Body (전체):")
        print(f"  {res.text[:5000]}")
        print()

        # JSON 파싱
        try:
            data = res.json()
        except json.JSONDecodeError:
            data = {"rt_cd": "1", "msg1": f"JSON 파싱 실패: {res.text[:200]}", "msg_cd": "JSON_DECODE_ERROR"}

        print(f"  Parsed JSON Keys: {list(data.keys())}")
        print(f"  rt_cd: {data.get('rt_cd')}")
        print(f"  msg_cd: {data.get('msg_cd')}")
        print(f"  msg1: {data.get('msg1')}")
        print(f"  output: {json.dumps(data.get('output', []), ensure_ascii=False)[:2000]}")
        print(f"  ctx_area_fk200: {data.get('ctx_area_fk200')}")
        print(f"  ctx_area_nk200: {data.get('ctx_area_nk200')}")

        return data
    except Exception as e:
        print(f"\n  ❌ 예외 발생: {e}")
        import traceback
        traceback.print_exc()
        return None


def run_debug_mode(url_base: str, access_token: str, days_back: int):
    """디버그 모드: 다양한 파라미터 조합으로 API 호출 시도"""
    print_separator("디버그 모드 - 다양한 파라미터 조합 시도")

    today = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    tr_id = "VTTS3035R" if MOCK_TRADING_ONLY else "TTTS3035R"
    url = f"{url_base}/uapi/overseas-stock/v1/trading/inquire-ccnl"

    # 다양한 파라미터 조합 테스트 케이스
    test_cases = [
        {
            "label": "기본 (전체 종목, 전체 거래소, 전체 매도매수, 전체 체결)",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "%" if not MOCK_TRADING_ONLY else "",
                "ORD_STRT_DT": start_date,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "00",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "%" if not MOCK_TRADING_ONLY else "",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "NASD 거래소, 전체 종목",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "%" if not MOCK_TRADING_ONLY else "",
                "ORD_STRT_DT": start_date,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "00",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "NASD",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "NYSE 거래소, 전체 종목",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "%" if not MOCK_TRADING_ONLY else "",
                "ORD_STRT_DT": start_date,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "00",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "NYSE",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "TQQQ 종목, NASD 거래소",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "TQQQ",
                "ORD_STRT_DT": start_date,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "00",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "NASD",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "TQQQ 종목, NASD 거래소, 매수만",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "TQQQ",
                "ORD_STRT_DT": start_date,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "02",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "NASD",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "TQQQ 종목, NASD 거래소, 매수만, 체결만",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "TQQQ",
                "ORD_STRT_DT": start_date,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "02",
                "CCLD_NCCS_DVSN": "01",
                "OVRS_EXCG_CD": "NASD",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "TQQQ 종목, NASD 거래소, 매수만, 미체결만",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "TQQQ",
                "ORD_STRT_DT": start_date,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "02",
                "CCLD_NCCS_DVSN": "02",
                "OVRS_EXCG_CD": "NASD",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "TQQQ 종목, NASD 거래소, 매수만, 역순 정렬",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "TQQQ",
                "ORD_STRT_DT": start_date,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "02",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "NASD",
                "SORT_SQN": "AS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "TQQQ 종목, NASD 거래소, 매수만, 오늘만",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "TQQQ",
                "ORD_STRT_DT": today,
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "02",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "NASD",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
        {
            "label": "TQQQ 종목, NASD 거래소, 매수만, 7일",
            "params": {
                "CANO": CANO,
                "ACNT_PRDT_CD": ACNT_PRDT_CD,
                "PDNO": "TQQQ",
                "ORD_STRT_DT": (datetime.now() - timedelta(days=7)).strftime("%Y%m%d"),
                "ORD_END_DT": today,
                "SLL_BUY_DVSN": "02",
                "CCLD_NCCS_DVSN": "00",
                "OVRS_EXCG_CD": "NASD",
                "SORT_SQN": "DS",
                "ORD_DT": "",
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "CTX_AREA_NK200": "",
                "CTX_AREA_FK200": ""
            }
        },
    ]

    success_count = 0
    for tc in test_cases:
        data = debug_api_call(url_base, access_token, tc["params"], tr_id, url, tc["label"])
        if data and data.get("rt_cd") == "0":
            output = data.get("output", [])
            if isinstance(output, list) and output:
                print(f"\n  ✅ [{tc['label']}] 데이터 발견! {len(output)}건")
                print(f"  첫 번째 레코드 키: {list(output[0].keys())}")
                print(f"  첫 번째 레코드: {json.dumps(output[0], ensure_ascii=False, indent=2)[:2000]}")
                success_count += 1
            else:
                print(f"\n  ⚠️ [{tc['label']}] rt_cd=0 이지만 output 비어있음")
        else:
            print(f"\n  ❌ [{tc['label']}] API 오류")
        time.sleep(0.5)

    print_separator("디버그 모드 결과 요약")
    print(f"  성공한 조합: {success_count} / {len(test_cases)}")
    if success_count == 0:
        print("""
[HTTP 500 오류 진단 가이드]
1. TR_ID 확인: 실전=TTTS3035R, 모의=VTTS3035R (URL과 TR_ID가 일치해야 함)
2. 계좌번호 확인: CANO(8자리) + ACNT_PRDT_CD(2자리)가 올바른지 확인
3. PDNO 값 확인: 실전에서 전종목 조회 시 "%" 사용, 모의에서는 "" 사용
4. OVRS_EXCG_CD 값 확인: 실전에서 전종목 조회 시 "%" 사용, 모의에서는 "" 사용
5. SORT_SQN 값 확인: "DS"(정순) 또는 "AS"(역순)만 허용
6. SLL_BUY_DVSN 값 확인: "00"(전체), "01"(매도), "02"(매수)만 허용
7. CCLD_NCCS_DVSN 값 확인: "00"(전체), "01"(체결), "02"(미체결)만 허용
8. ORD_STRT_DT/ORD_END_DT: YYYYMMDD 형식, 시작일 <= 종료일 확인
9. 모의투자 계좌인데 실전 TR_ID를 사용하거나, 그 반대인 경우 확인
10. API 서버 점검: 한국투자증권 API 서버 일시 장애 가능성
""")


def main():
    # CLI 인자 파싱
    args = sys.argv[1:]
    use_mock = "--mock" in args
    debug_mode = "--debug" in args
    days_back = 30
    pdno = ""          # 상품번호 (전종목: "%", 모의투자: "" 전체 조회)
    excg_cd = ""       # 해외거래소코드 (전종목: "%", 모의투자: "" 전체 조회)
    sll_buy_dvsn = "00"  # 매도매수구분 (00:전체, 01:매도, 02:매수)
    ccld_nccs_dvsn = "00"  # 체결미체결구분 (00:전체, 01:체결, 02:미체결)
    sort_sqn = "DS"    # 정렬순서 (DS:정순, AS:역순)

    for i, a in enumerate(args):
        if a == "--days" and i + 1 < len(args):
            try:
                days_back = int(args[i + 1])
            except ValueError:
                pass
        elif a == "--pdno" and i + 1 < len(args):
            pdno = args[i + 1].upper()
        elif a == "--excg" and i + 1 < len(args):
            excg_cd = args[i + 1].upper()
        elif a == "--sll-buy" and i + 1 < len(args):
            sll_buy_dvsn = args[i + 1]
        elif a == "--ccld" and i + 1 < len(args):
            ccld_nccs_dvsn = args[i + 1]
        elif a == "--sort" and i + 1 < len(args):
            sort_sqn = args[i + 1].upper()

    # 모드 결정: --mock 인자가 있으면 모의, 없으면 .env의 MOCK_TRADING_ONLY 값 사용
    mock_mode = use_mock or MOCK_TRADING_ONLY
    url_base = URL_BASE_MOCK if mock_mode else URL_BASE_REAL

    print_separator("TTTS3035R / VTTS3035R (inquire-ccnl) 해외주식 주문체결내역 조회 테스트")
    print(f"  현재 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  .env 로드: MOCK_TRADING_ONLY={MOCK_TRADING_ONLY}")
    print(f"  실행 모드: {'모의투자' if mock_mode else '실전투자'}")
    print(f"  URL_BASE: {url_base}")
    print(f"  CANO: {CANO}")
    print(f"  ACNT_PRDT_CD: {ACNT_PRDT_CD}")
    print(f"  APP_KEY 설정됨: {bool(APP_KEY)}")
    print(f"  APP_SECRET 설정됨: {bool(APP_SECRET)}")
    print(f"  CLI 인자: mock={use_mock}, debug={debug_mode}, days={days_back}, pdno={pdno or '(전체)'}, "
          f"excg={excg_cd or '(전체)'}, sll_buy={sll_buy_dvsn}, ccld={ccld_nccs_dvsn}, sort={sort_sqn}")

    # 1. .env 값 확인
    if not APP_KEY or not APP_SECRET:
        print("  ❌ .env 파일에 KIS_APP_KEY 또는 KIS_APP_SECRET이 없습니다.")
        print("  ⚠️  .env 파일에 KIS_APP_KEY, KIS_APP_SECRET, KIS_CANO 값을 설정하세요.")
        return

    # 2. Access Token 발급 (.env의 appkey/appsecret 사용)
    access_token = get_access_token(url_base, APP_KEY, APP_SECRET)
    if not access_token:
        print("  ❌ Access Token 발급 실패 - 테스트를 계속할 수 없습니다.")
        return

    # 디버그 모드 실행
    if debug_mode:
        run_debug_mode(url_base, access_token, days_back)
        return

    # 3. 조회 기간 설정
    today = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    # 4. inquire-ccnl API 호출 (단일 쿼리)
    tr_id = "VTTS3035R" if mock_mode else "TTTS3035R"
    url = f"{url_base}/uapi/overseas-stock/v1/trading/inquire-ccnl"

    # 요청 파라미터 구성
    # - PDNO: 전종목일 경우 "%" 입력 (모의투자계좌의 경우 ""(전체 조회)만 가능)
    # - OVRS_EXCG_CD: 전종목일 경우 "%" 입력 (모의투자계좌의 경우 ""(전체 조회)만 가능)
    # - SLL_BUY_DVSN: 00:전체, 01:매도, 02:매수 (모의투자계좌의 경우 "00"만 가능)
    # - CCLD_NCCS_DVSN: 00:전체, 01:체결, 02:미체결 (모의투자계좌의 경우 "00"만 가능)
    # - SORT_SQN: DS:정순, AS:역순 (모의투자계좌의 경우 정렬순서 사용불가, Default: DS)
    # - ORD_DT, ORD_GNO_BRNO, ODNO: Null 값 설정 (주문번호로 검색 불가)
    # - CTX_AREA_NK200, CTX_AREA_FK200: 공란 (최초 조회시)
    params = {
        "CANO": CANO,
        "ACNT_PRDT_CD": ACNT_PRDT_CD,
        "PDNO": pdno if pdno else ("%" if not mock_mode else ""),
        "ORD_STRT_DT": start_date,
        "ORD_END_DT": today,
        "SLL_BUY_DVSN": sll_buy_dvsn,
        "CCLD_NCCS_DVSN": ccld_nccs_dvsn,
        "OVRS_EXCG_CD": excg_cd if excg_cd else ("%" if not mock_mode else ""),
        "SORT_SQN": sort_sqn,
        "ORD_DT": "",
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "CTX_AREA_NK200": "",
        "CTX_AREA_FK200": ""
    }

    # .env 값으로 request 헤더 직접 구성
    headers = build_headers(access_token, APP_KEY, APP_SECRET, tr_id)

    # 요청 정보 출력
    print_request_details(url, tr_id, headers, params)

    try:
        # ============================================================
        # 연속 조회 루프: tr_cont가 "M"이면 계속 다음 페이지 조회
        # ============================================================
        all_output = []          # 모든 페이지의 output 데이터를 누적
        page = 0
        max_pages = 20           # 최대 페이지 수 제한 (무한 루프 방지)
        tr_cont = ""             # 초기 조회

        while page < max_pages:
            page += 1
            is_first_page = (page == 1)

            # 연속 조회 여부에 따라 tr_cont 설정
            # - 최초 조회: "" (공백)
            # - 다음 데이터 조회: "N" (output header의 tr_cont가 M일 경우)
            headers["tr_cont"] = "" if is_first_page else "N"

            print_separator(f"PAGE {page} - API 호출")
            print(f"  URL: {url}")
            print(f"  TR_ID: {tr_id}")
            print(f"  tr_cont: {headers['tr_cont']} ({'최초 조회' if is_first_page else '연속 조회'})")
            print(f"  Params:")
            for k, v in params.items():
                print(f"    {k} = {v}")

            time.sleep(0.2)  # API 연속 호출 제한
            res = requests.get(url, headers=headers, params=params, timeout=10)

            # JSON 파싱
            try:
                data = res.json()
            except json.JSONDecodeError:
                data = {
                    "rt_cd": "1",
                    "msg1": f"JSON 파싱 실패: {res.text[:200]}",
                    "msg_cd": "JSON_DECODE_ERROR",
                    "_http_status": res.status_code,
                    "_raw_body": res.text[:500]
                }

            # 응답 정보 출력
            print_response_details(res, data)

            # 결과 판정
            print_result_judgment(data)

            # HTTP 500 오류 시 진단 정보 출력
            if res.status_code == 500 or data.get("msg_cd") == "HTTP_500":
                print_separator("HTTP 500 오류 진단")
                print("  HTTP 500은 서버 측 오류로, 요청 파라미터가 API 스펙과 일치하지 않을 때 발생할 수 있습니다.")
                print("  다음 사항을 확인해보세요:")
                print("  1. TR_ID: 실전=TTTS3035R, 모의=VTTS3035R (URL과 TR_ID 일치 확인)")
                print("  2. PDNO: 실전 전종목='%', 모의='' (모의에서는 '%' 사용 불가)")
                print("  3. OVRS_EXCG_CD: 실전 전종목='%', 모의='' (모의에서는 '%' 사용 불가)")
                print("  4. SLL_BUY_DVSN: 모의에서는 '00'만 가능")
                print("  5. CCLD_NCCS_DVSN: 모의에서는 '00'만 가능")
                print("  6. SORT_SQN: 모의에서는 정렬순서 사용불가 (Default: DS)")
                print("  7. ORD_STRT_DT/ORD_END_DT: YYYYMMDD 형식, 시작일 <= 종료일")
                print("  8. --debug 옵션으로 다양한 파라미터 조합을 시도해보세요.")
                break

            # API 오류 시 중단
            if data.get("rt_cd") != "0":
                print(f"  ⚠️ API 오류로 조회를 중단합니다. (rt_cd={data.get('rt_cd')}, msg1={data.get('msg1')})")
                break

            # output 데이터 누적
            output = data.get("output", [])
            if isinstance(output, list):
                all_output.extend(output)
                print(f"  📊 이 페이지에서 {len(output)}건, 누적 {len(all_output)}건")
            elif isinstance(output, dict):
                all_output.append(output)
                print(f"  📊 이 페이지에서 1건(dict), 누적 {len(all_output)}건")

            # 연속 조회 여부 확인 (응답 헤더의 tr_cont)
            tr_cont = res.headers.get("tr_cont", "")
            print(f"  🔄 응답 헤더 tr_cont: {tr_cont}")

            if tr_cont != "M":
                print(f"  ✅ 연속 조회 종료 (tr_cont={tr_cont or '(공백)'})")
                break

            # 다음 페이지를 위한 CTX_AREA_NK200/FK200 값 설정
            ctx_nk = data.get("ctx_area_nk200", "")
            ctx_fk = data.get("ctx_area_fk200", "")
            print(f"  🔄 다음 페이지 조회 준비:")
            print(f"    CTX_AREA_NK200 = {ctx_nk}")
            print(f"    CTX_AREA_FK200 = {ctx_fk}")

            if not ctx_nk and not ctx_fk:
                print(f"  ⚠️ tr_cont=M 이지만 CTX_AREA_NK200/FK200이 비어있어 연속 조회를 중단합니다.")
                break

            params["CTX_AREA_NK200"] = ctx_nk
            params["CTX_AREA_FK200"] = ctx_fk

        # ============================================================
        # 전체 결과 요약 (일자/주문번호/종목/수량/체결가(USD)/체결금액(USD))
        # ============================================================
        print_separator("전체 조회 결과 요약")
        print(f"  총 조회 페이지: {page}페이지")
        print(f"  총 데이터 건수: {len(all_output)}건")

        if all_output:
            # --- 필드 추출 헬퍼 함수 ---
            def _get_field(item: dict, *keys) -> str:
                """여러 키 중 첫 번째로 존재하는 값을 반환"""
                for k in keys:
                    if k in item and item[k] is not None:
                        return str(item[k]).strip()
                return ""

            def _fmt_date(raw: str) -> str:
                """YYYYMMDD → YYYY-MM-DD 형식 변환"""
                raw = raw.strip()
                if len(raw) == 8 and raw.isdigit():
                    return f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
                return raw

            def _fmt_num(raw: str) -> str:
                """숫자 문자열을 천 단위 콤마로 포맷"""
                raw = raw.strip()
                if not raw:
                    return "0"
                try:
                    return f"{float(raw):,.2f}"
                except (ValueError, TypeError):
                    return raw

            # --- 레코드 정규화: 각 레코드에서 필요한 필드 추출 ---
            normalized = []
            for item in all_output:
                if not isinstance(item, dict):
                    continue

                # 일자: ord_dt (주문일자) 또는 dmst_ord_dt (국내주문일자)
                ord_dt = _get_field(item, "ord_dt", "dmst_ord_dt", "trad_dt")
                # 주문번호: odno
                odno = _get_field(item, "odno", "ord_no")
                # 종목: pdno (상품번호)
                pdno = _get_field(item, "pdno")
                # 종목명: prdt_name (상품명)
                prdt_name = _get_field(item, "prdt_name")
                # 수량: ft_ccld_qty (FT체결수량) 또는 ft_ord_qty (FT주문수량)
                ccld_qty = _get_field(item, "ft_ccld_qty", "ft_ord_qty", "ccld_qty")
                # 체결가(USD): ft_ccld_unpr3 (FT체결단가3)
                ccld_unpr = _get_field(item, "ft_ccld_unpr3", "ft_ccld_unpr2", "ft_ccld_unpr")
                # 체결금액(USD): ft_ccld_amt3 (FT체결금액3)
                ccld_amt = _get_field(item, "ft_ccld_amt3", "ft_ccld_amt2", "ft_ccld_amt")
                # 매도매수구분
                sll_buy = _get_field(item, "sll_buy_dvsn_cd", "sll_buy_dvsn")
                sll_buy_name = _get_field(item, "sll_buy_dvsn_cd_name", "sll_buy_dvsn_name")
                # 처리상태
                status = _get_field(item, "prcs_stat_name")
                # 미체결수량
                nccs_qty = _get_field(item, "nccs_qty")
                # 거부사유명
                rjct_rson_name = _get_field(item, "rjct_rson_name", "rjct_rson")

                normalized.append({
                    "ord_dt": _fmt_date(ord_dt),
                    "odno": odno,
                    "pdno": pdno,
                    "prdt_name": prdt_name,
                    "ccld_qty": ccld_qty,
                    "ccld_unpr": ccld_unpr,
                    "ccld_amt": ccld_amt,
                    "sll_buy": sll_buy,
                    "sll_buy_name": sll_buy_name,
                    "status": status,
                    "nccs_qty": nccs_qty,
                    "rjct_rson_name": rjct_rson_name,
                })

            # --- 1. 전체 요약 테이블 ---
            print(f"\n  {'='*110}")
            print(f"  [전체 요약] (총 {len(normalized)}건)")
            print(f"  {'='*110}")
            print(f"  {'일자':<12} {'주문번호':<12} {'종목':<8} {'종목명':<20} {'수량':>8} {'체결가(USD)':>14} {'체결금액(USD)':>16} {'매도/매수':<8} {'상태':<8} {'거부사유':<20}")
            print(f"  {'-'*110}")
            for r in normalized:
                symbol_display = r["pdno"] if r["pdno"] else "-"
                name_display = r["prdt_name"] if r["prdt_name"] else "-"
                sll_display = r["sll_buy_name"] if r["sll_buy_name"] else (r["sll_buy"] if r["sll_buy"] else "-")
                status_display = r["status"] if r["status"] else "-"
                rjct_display = r["rjct_rson_name"] if r["rjct_rson_name"] else "-"
                print(f"  {r['ord_dt']:<12} {r['odno']:<12} {symbol_display:<8} {name_display:<20} "
                      f"{r['ccld_qty']:>8} {_fmt_num(r['ccld_unpr']):>14} {_fmt_num(r['ccld_amt']):>16} "
                      f"{sll_display:<8} {status_display:<8} {rjct_display:<20}")
            print(f"  {'-'*110}")

            # --- 2. 날짜별 요약 테이블 ---
            # 날짜별로 그룹핑
            by_date = {}
            for r in normalized:
                date_key = r["ord_dt"] if r["ord_dt"] else "(날짜없음)"
                if date_key not in by_date:
                    by_date[date_key] = []
                by_date[date_key].append(r)

            print(f"\n  {'='*110}")
            print(f"  [날짜별 요약] (총 {len(by_date)}일)")
            print(f"  {'='*110}")

            for date_key in sorted(by_date.keys()):
                records = by_date[date_key]
                print(f"\n  ── {date_key} (총 {len(records)}건) ──")
                print(f"  {'주문번호':<12} {'종목':<8} {'종목명':<20} {'수량':>8} {'체결가(USD)':>14} {'체결금액(USD)':>16} {'매도/매수':<8} {'상태':<8} {'거부사유':<20}")
                print(f"  {'-'*110}")
                for r in records:
                    symbol_display = r["pdno"] if r["pdno"] else "-"
                    name_display = r["prdt_name"] if r["prdt_name"] else "-"
                    sll_display = r["sll_buy_name"] if r["sll_buy_name"] else (r["sll_buy"] if r["sll_buy"] else "-")
                    status_display = r["status"] if r["status"] else "-"
                    rjct_display = r["rjct_rson_name"] if r["rjct_rson_name"] else "-"
                    print(f"  {r['odno']:<12} {symbol_display:<8} {name_display:<20} "
                          f"{r['ccld_qty']:>8} {_fmt_num(r['ccld_unpr']):>14} {_fmt_num(r['ccld_amt']):>16} "
                          f"{sll_display:<8} {status_display:<8} {rjct_display:<20}")

                # 날짜별 합계
                total_qty = sum(float(r["ccld_qty"]) if r["ccld_qty"].replace('.', '').isdigit() else 0 for r in records)
                total_amt = sum(float(r["ccld_amt"]) if r["ccld_amt"].replace('.', '').isdigit() else 0 for r in records)
                print(f"  {'-'*110}")
                print(f"  {'합계':<12} {'':<8} {'':<20} {total_qty:>8,.0f} {'':>14} {total_amt:>16,.2f}")

            # --- 3. 전체 합계 ---
            total_qty_all = sum(float(r["ccld_qty"]) if r["ccld_qty"].replace('.', '').isdigit() else 0 for r in normalized)
            total_amt_all = sum(float(r["ccld_amt"]) if r["ccld_amt"].replace('.', '').isdigit() else 0 for r in normalized)
            print(f"\n  {'='*100}")
            print(f"  [전체 합계]")
            print(f"  {'='*100}")
            print(f"  총 수량: {total_qty_all:,.0f}")
            print(f"  총 체결금액(USD): ${total_amt_all:,.2f}")
            print(f"  {'='*100}")

            # --- 4. 첫 번째 레코드의 키 목록 (참고용) ---
            first = all_output[0]
            if isinstance(first, dict):
                print(f"\n  [첫 번째 레코드 키 목록]")
                print(f"  {list(first.keys())}")

    except Exception as e:
        print(f"\n  ❌ 예외 발생: {e}")
        import traceback
        traceback.print_exc()

    print_separator("테스트 완료")


if __name__ == "__main__":
    main()