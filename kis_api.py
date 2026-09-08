"""
한국투자증권 Open Trading API (KIS Developers REST API) Client Wrapper
"""
import os
import json
import time
import logging
import requests
from typing import Dict, Any, List, Optional
import config

logger = logging.getLogger("KISApiClient")

class KISApiClient:
    """한국투자증권 Open API (REST API) 통신 클래스"""

    def __init__(
        self,
        app_key: Optional[str] = None,
        app_secret: Optional[str] = None,
        cano: Optional[str] = None,
        acnt_prdt_cd: Optional[str] = None,
        mock: Optional[bool] = None
    ):
        self.app_key = app_key or config.APP_KEY
        self.app_secret = app_secret or config.APP_SECRET
        self.cano = cano or config.CANO
        self.acnt_prdt_cd = acnt_prdt_cd or config.ACNT_PRDT_CD
        self.mock = mock if mock is not None else config.MOCK_TRADING_ONLY

        self.url_base = config.URL_BASE_MOCK if self.mock else config.URL_BASE_REAL
        self.access_token: Optional[str] = None
        self.token_issued_at: float = 0
        self.token_expires_in: int = 86400

        self.last_call_time: float = 0
        self.last_token_attempt_time: float = 0
        self._token_file_path = "token_kis_mock.json" if self.mock else "token_kis_real.json"
        
        self._mock_balance_deposit = 10000000  # 키가 없을 때 테스트용 가상 예수금 (1천만원)
        self._mock_usd_deposit = 5000.0       # 가상 외화(USD) 예수금 ($5,000)
        self._mock_holdings: Dict[str, Dict[str, Any]] = {}

        # 해외 주요 ETF/주식 거래소 매핑 및 런타임 캐시 (SOXL/SPXL 등 아멕스 종목 오주문 방지)
        self._symbol_exchange_cache: Dict[str, str] = {
            "TQQQ": "NAS", "QQQ": "NAS", "SQQQ": "NAS", "AAPL": "NAS", "MSFT": "NAS",
            "NVDA": "NAS", "TSLA": "NAS", "GOOGL": "NAS", "AMZN": "NAS", "TSLL": "NAS", "NVDL": "NAS",
            "SOXL": "AMS", "SOXS": "AMS", "SPY": "AMS", "SPXL": "AMS", "UPRO": "AMS",
            "TECL": "AMS", "FNGU": "AMS", "BULZ": "AMS", "LABU": "AMS", "LABD": "AMS",
            "TNA": "AMS", "TZA": "AMS", "FAS": "AMS", "FAZ": "AMS", "DPST": "AMS",
            "BNKU": "AMS", "YINN": "AMS", "YANG": "AMS", "CWEB": "AMS"
        }

        # 저장된 기존 토큰 파일 로드 시도
        self._load_token_file()

    def get_symbol_exchange(self, symbol: str) -> str:
        """
        해외 종목의 상장 거래소 코드 반환 (NAS: 나스닥, AMS: 아멕스/NYSE Arca, NYS: 뉴욕)
        - SOXL, SPXL 등은 아멕스(AMS/AMEX) 상장으로, 나스닥(NASD)으로 주문 시 API 거부됨
        """
        sym_upper = str(symbol).strip().upper()
        if sym_upper in self._symbol_exchange_cache:
            return self._symbol_exchange_cache[sym_upper]

        # 캐시에 없으면 시세 조회를 통해 거래소 자동 감지
        try:
            price_res = self.get_overseas_stock_price(sym_upper)
            if price_res.get("success") and price_res.get("exchange"):
                self._symbol_exchange_cache[sym_upper] = price_res["exchange"]
                return price_res["exchange"]
        except Exception:
            pass

        return "NAS"

    def _rate_limit(self):
        """API 연쇄 호출 제한 안전 딜레이"""
        elapsed = time.time() - self.last_call_time
        if elapsed < config.API_CALL_DELAY:
            time.sleep(config.API_CALL_DELAY - elapsed)
        self.last_call_time = time.time()

    def _load_token_file(self):
        """로컬 파일에 저장된 유효한 Access Token이 있는지 로드"""
        if not os.path.exists(self._token_file_path):
            return

        try:
            with open(self._token_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                token = data.get("access_token")
                issued_at = data.get("issued_at", 0)
                expires_in = data.get("expires_in", 86400)

                # 토큰 만료 여부 확인 (만료 60초 전까지 유효)
                if token and (time.time() - issued_at) < (expires_in - 60):
                    self.access_token = token
                    self.token_issued_at = issued_at
                    self.token_expires_in = expires_in
                    logger.info(f"기존 저장된 KIS Access Token 로드 성공 ({self._token_file_path})")
        except Exception as e:
            logger.warning(f"토큰 파일 로드 실패: {e}")

    def _save_token_file(self):
        """발급받은 Access Token을 로컬 파일로 저장"""
        try:
            data = {
                "access_token": self.access_token,
                "issued_at": self.token_issued_at,
                "expires_in": self.token_expires_in
            }
            with open(self._token_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"새 KIS Access Token 로컬 파일 저장 완료 ({self._token_file_path})")
        except Exception as e:
            logger.warning(f"토큰 파일 저장 실패: {e}")

    def get_access_token(self) -> bool:
        """OAuth 2.0 Access Token 발급 요청"""
        if self.is_token_valid():
            return True

        if not self.app_key or not self.app_secret:
            logger.warning("AppKey 또는 AppSecret이 설정되지 않았습니다. 시뮬레이션 모드로 작동합니다.")
            return False

        # 1분(60초) 재발급 쿨다운 제한 체크 (한국투자증권 API 1분당 1회 제한 보호)
        now = time.time()
        elapsed_since_attempt = now - self.last_token_attempt_time
        if elapsed_since_attempt < 60:
            logger.warning(f"Access Token 재발급 요청 쿨타임 적용 중 (남은시간: {60 - elapsed_since_attempt:.0f}초)")
            return False

        self.last_token_attempt_time = now
        url = f"{self.url_base}/oauth2/tokenP"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }

        try:
            self._rate_limit()
            res = requests.post(url, headers=headers, json=body, timeout=10)
            data = self._safe_json_response(res, context="AccessToken발급")

            if res.status_code == 200 and "access_token" in data:
                self.access_token = data["access_token"]
                self.token_issued_at = time.time()
                self.token_expires_in = data.get("expires_in", 86400)
                self._save_token_file()
                logger.info("KIS Open API Access Token 발급 성공")
                return True
            else:
                msg = data.get("error_description", data.get("msg1", "Unknown Error"))
                logger.error(f"Access Token 발급 실패: {msg}")
                return False
        except Exception as e:
            logger.error(f"Access Token 발급 중 예외 발생: {e}")
            return False

    def is_token_valid(self) -> bool:
        """접속 토큰 유효성 확인"""
        if not self.access_token:
            return False
        return (time.time() - self.token_issued_at) < (self.token_expires_in - 60)

    def _ensure_token(self):
        """토큰 미발급 시 자동 발급 시도"""
        if not self.is_token_valid():
            self.get_access_token()

    def _get_headers(self, tr_id: str, hashkey: Optional[str] = None) -> Dict[str, str]:
        """기본 API 요청 헤더 생성"""
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {self.access_token}",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P"
        }
        if hashkey:
            headers["hashkey"] = hashkey
        return headers
    def _safe_json_response(self, res: requests.Response, context: str = "") -> Dict[str, Any]:
        """
        API 응답을 안전하게 JSON으로 파싱한다.
        - HTTP 상태 코드가 200이 아니거나, 응답 본문이 비어있거나, JSON이 아닌 경우
          (HTML 에러 페이지, 게이트웨이 오류 등) JSONDecodeError가 발생하지 않도록 처리한다.
        - 파싱 실패 시 {"rt_cd": "1", "msg1": "...", "msg_cd": "..."} 형태의 오류 dict를 반환한다.
        """
        try:
            if res.status_code != 200:
                # KIS API는 에러 시(장외 시간, 권한 부족 등) HTTP 400/500과 함께 JSON 본문으로 상세 사유 전달
                try:
                    err_json = res.json()
                    if isinstance(err_json, dict):
                        if "rt_cd" not in err_json:
                            err_json["rt_cd"] = "1"
                        if "msg_cd" not in err_json:
                            err_json["msg_cd"] = f"HTTP_{res.status_code}"
                        err_json["_http_status"] = res.status_code
                        logger.warning(f"[{context}] HTTP {res.status_code} KIS API 에러 응답: {err_json.get('msg1', '')} (코드: {err_json.get('msg_cd')})")
                        return err_json
                except Exception:
                    pass

                body_preview = res.text[:300] if res.text else "(empty body)"
                logger.warning(f"[{context}] HTTP {res.status_code} 응답 (JSON 아님): {body_preview}")
                return {
                    "rt_cd": "1",
                    "msg1": f"HTTP {res.status_code} 응답",
                    "msg_cd": f"HTTP_{res.status_code}",
                    "_http_status": res.status_code,
                    "_raw_body": res.text[:500]
                }

            if not res.text or not res.text.strip():
                logger.warning(f"[{context}] 빈 응답 본문 (HTTP {res.status_code})")
                return {
                    "rt_cd": "1",
                    "msg1": "빈 응답 본문",
                    "msg_cd": "EMPTY_BODY",
                    "_http_status": res.status_code,
                    "_raw_body": ""
                }

            data = res.json()
            if not isinstance(data, dict):
                logger.warning(f"[{context}] JSON 응답이 dict가 아님: {type(data).__name__}")
                return {
                    "rt_cd": "1",
                    "msg1": f"JSON 응답 형식 오류: {type(data).__name__}",
                    "msg_cd": "INVALID_JSON_TYPE",
                    "_http_status": res.status_code,
                    "_raw_body": res.text[:500]
                }
            return data
        except json.JSONDecodeError as e:
            body_preview = res.text[:300] if res.text else "(empty body)"
            logger.error(f"[{context}] JSON 파싱 실패: {e} | HTTP {res.status_code} | body={body_preview}")
            return {
                "rt_cd": "1",
                "msg1": f"JSON 파싱 실패: {e}",
                "msg_cd": "JSON_DECODE_ERROR",
                "_http_status": res.status_code,
                "_raw_body": res.text[:500]
            }
        except Exception as e:
            logger.error(f"[{context}] 응답 파싱 중 예외 발생: {e}")
            return {
                "rt_cd": "1",
                "msg1": f"응답 파싱 예외: {e}",
                "msg_cd": "PARSE_EXCEPTION",
                "_http_status": getattr(res, "status_code", 0),
                "_raw_body": getattr(res, "text", "")[:500]
            }

    def get_hashkey(self, body: Dict[str, Any]) -> Optional[str]:
        """
        POST 주문 시 요청 바디(Body) 무결성 검증용 Hashkey 발급 (/uapi/hashkey)
        """
        url = f"{self.url_base}/uapi/hashkey"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "appkey": self.app_key,
            "appsecret": self.app_secret
        }
        try:
            res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
            if res.status_code == 200:
                data = self._safe_json_response(res, context="Hashkey발급")
                return data.get("HASH")
            else:
                logger.warning(f"Hashkey 발급 실패: status={res.status_code}, response={res.text}")
                return None
        except Exception as e:
            logger.error(f"Hashkey 발급 예외 발생: {e}")
            return None

    @staticmethod
    def is_overseas_symbol(symbol: str) -> bool:
        """종목 코드가 해외 주식(티커 알파벳)인지 여부 확인 (예: TSLA, AAPL, NVDA)"""
        if not symbol:
            return False
        return symbol.strip().replace(".", "").isalpha()

    def get_stock_price(self, stock_code: str, exchange: str = "NAS") -> Dict[str, Any]:
        """
        주식 현재가 시세 조회 (국내: FHKST01010100 / 해외: HHDFS76200200)
        """
        if self.is_overseas_symbol(stock_code):
            return self.get_overseas_stock_price(stock_code, exchange=exchange)

        self._ensure_token()
        if not self.access_token:
            # API키 없을 시 가상 테스트 시세 반환
            return {
                "success": True,
                "code": stock_code,
                "name": f"종목_{stock_code}",
                "price": 70000 if stock_code == "005930" else 120000,
                "diff": 500,
                "rate": 0.71,
                "volume": 1000000,
                "high": 71000,
                "low": 69500,
                "open": 69800
            }

        url = f"{self.url_base}/uapi/domestic-stock/v1/quotations/inquire-price"
        headers = self._get_headers("FHKST01010100")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code
        }

        try:
            self._rate_limit()
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = self._safe_json_response(res, context=f"국내시세[{stock_code}]")

            if res.status_code == 200 and data.get("rt_cd") == "0":
                output = data.get("output", {})
                return {
                    "success": True,
                    "code": stock_code,
                    "name": output.get("hts_kor_isnm", f"종목_{stock_code}"),
                    "price": int(output.get("stck_prpr", 0)),
                    "diff": int(output.get("prdy_vrss", 0)),
                    "rate": float(output.get("prdy_ctrt", 0.0)),
                    "volume": int(output.get("acml_vol", 0)),
                    "high": int(output.get("stck_hgpr", 0)),
                    "low": int(output.get("stck_lwpr", 0)),
                    "open": int(output.get("stck_oprc", 0))
                }
            else:
                logger.error(f"[{stock_code}] 시세 조회 실패: {data.get('msg1')}")
                return {"success": False, "msg": data.get("msg1", "시세 조회 실패")}
        except Exception as e:
            logger.error(f"[{stock_code}] 시세 조회 예외 발생: {e}")
            return {"success": False, "msg": str(e)}

    def get_daily_chart(self, stock_code: str, period: str = "D", count: int = 30, exchange: str = "NAS") -> List[Dict[str, Any]]:
        """
        주식 일별 차트 시세 조회 (국내: FHKST01010400 / 해외: HHDFS76240000)
        """
        if self.is_overseas_symbol(stock_code):
            return self.get_overseas_daily_chart(stock_code, exchange=exchange, count=count)

        self._ensure_token()
        if not self.access_token:
            # API키 없을 시 가상 테스트 일봉 차트 데이터 반환
            chart_data = []
            base_p = 70000 if stock_code == "005930" else 120000
            for i in range(count):
                chart_data.append({
                    "date": f"202608{30-i:02d}",
                    "close": base_p + (i % 5) * 200 - (i % 3) * 150,
                    "open": base_p,
                    "high": base_p + 1000,
                    "low": base_p - 1000,
                    "volume": 500000 + i * 1000
                })
            return chart_data

        url = f"{self.url_base}/uapi/domestic-stock/v1/quotations/inquire-daily-price"
        headers = self._get_headers("FHKST01010400")
        params = {
            "FID_COND_MRKT_DIV_CODE": "J",
            "FID_INPUT_ISCD": stock_code,
            "FID_PERIOD_DIV_CODE": period,
            "FID_ORG_ADJ_PRC": "0"
        }

        try:
            self._rate_limit()
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = self._safe_json_response(res, context=f"국내일봉[{stock_code}]")

            if res.status_code == 200 and data.get("rt_cd") == "0":
                results = []
                for item in data.get("output", [])[:count]:
                    results.append({
                        "date": item.get("stck_bsop_date", ""),
                        "close": int(item.get("stck_clpr", 0)),
                        "open": int(item.get("stck_oprc", 0)),
                        "high": int(item.get("stck_hgpr", 0)),
                        "low": int(item.get("stck_lwpr", 0)),
                        "volume": int(item.get("acml_vol", 0))
                    })
                return results
            else:
                logger.error(f"[{stock_code}] 일봉 조회 실패: {data.get('msg1')}")
                return []
        except Exception as e:
            logger.error(f"[{stock_code}] 일봉 조회 예외 발생: {e}")
            return []

    def get_account_balance(self) -> Dict[str, Any]:
        """
        계좌 잔고 및 예수금 조회 (VTTC8434R: 모의 / TTTC8434R: 실전)
        """
        self._ensure_token()
        if not self.access_token or not self.cano:
            # API 키/계좌 미설정 시 가상 계좌 잔고 반환
            holdings_list = []
            total_eval_holdings = 0
            for code, h in self._mock_holdings.items():
                cur_price = self.get_stock_price(code).get("price", h["avg_price"])
                eval_amt = cur_price * h["qty"]
                pnl = eval_amt - (h["avg_price"] * h["qty"])
                pnl_rate = (pnl / (h["avg_price"] * h["qty"])) * 100 if h["avg_price"] > 0 else 0.0
                total_eval_holdings += eval_amt

                holdings_list.append({
                    "code": code,
                    "name": h.get("name", f"종목_{code}"),
                    "qty": h["qty"],
                    "avg_price": h["avg_price"],
                    "current_price": cur_price,
                    "eval_amount": eval_amt,
                    "pnl": pnl,
                    "pnl_rate": round(pnl_rate, 2)
                })

            total_asset = self._mock_balance_deposit + total_eval_holdings
            return {
                "success": True,
                "deposit": self._mock_balance_deposit,
                "total_asset": total_asset,
                "holdings": holdings_list
            }

        tr_id = "VTTC8434R" if self.mock else "TTTC8434R"
        url = f"{self.url_base}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = self._get_headers(tr_id)
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "01",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        try:
            self._rate_limit()
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = self._safe_json_response(res, context="국내계좌잔고")

            if res.status_code == 200 and data.get("rt_cd") == "0":
                output1 = data.get("output1", [])
                output2 = data.get("output2", [{}])[0]

                deposit = int(output2.get("dnca_tot_amt", 0))
                total_asset = int(output2.get("tot_evlu_amt", 0))

                holdings_list = []
                for item in output1:
                    qty = int(item.get("hldg_qty", 0))
                    if qty <= 0:
                        continue
                    code = item.get("pdno", "")
                    avg_p = float(item.get("prma_evlu_amt", 0)) / qty if qty > 0 else 0.0
                    cur_p = int(item.get("prpr", 0))
                    eval_amt = int(item.get("evlu_amt", 0))
                    pnl = int(item.get("evlu_pfls_amt", 0))
                    pnl_rate = float(item.get("evlu_pfls_rt", 0.0))

                    holdings_list.append({
                        "code": code,
                        "name": item.get("prdt_name", f"종목_{code}"),
                        "qty": qty,
                        "avg_price": avg_p,
                        "current_price": cur_p,
                        "eval_amount": eval_amt,
                        "pnl": pnl,
                        "pnl_rate": pnl_rate
                    })

                return {
                    "success": True,
                    "deposit": deposit,
                    "total_asset": total_asset,
                    "holdings": holdings_list
                }
            else:
                msg1 = data.get("msg1", "")
                if "만료된" in msg1 or data.get("msg_cd") == "EGW00123":
                    logger.warning("Access Token 만료 감지: 자동 토큰 재발급 후 계좌 잔고 재조회...")
                    self.access_token = None
                    self.token_issued_at = 0
                    if self.get_access_token():
                        return self.get_account_balance()
                logger.error(f"계좌 잔고 조회 실패: {msg1}")
                return {"success": False, "msg": msg1}
        except Exception as e:
            logger.error(f"계좌 잔고 조회 예외 발생: {e}")
            return {"success": False, "msg": str(e)}

    def order_cash(
        self,
        stock_code: str,
        qty: int,
        price: float = 0,
        buy: bool = True,
        exchange: str = "NAS"
    ) -> Dict[str, Any]:
        """
        현금 주문 발주 (국내/해외 자동 분기)
        """
        if self.is_overseas_symbol(stock_code):
            return self.order_overseas_cash(stock_code, qty=qty, price=price, buy=buy, exchange=exchange)

        if qty <= 0:
            return {"success": False, "msg": "주문 수량이 0 이하입니다."}

        self._ensure_token()
        if not self.access_token or not self.cano:
            # API 키/계좌 미설정 시 가상 주문 처리
            cur_price = price if price > 0 else self.get_stock_price(stock_code).get("price", 70000)
            total_cost = cur_price * qty

            if buy:
                if self._mock_balance_deposit < total_cost:
                    return {"success": False, "msg": "가상 예수금 부족"}
                self._mock_balance_deposit -= total_cost
                if stock_code in self._mock_holdings:
                    prev_q = self._mock_holdings[stock_code]["qty"]
                    prev_p = self._mock_holdings[stock_code]["avg_price"]
                    new_q = prev_q + qty
                    new_p = ((prev_q * prev_p) + total_cost) / new_q
                    self._mock_holdings[stock_code] = {"qty": new_q, "avg_price": new_p, "name": f"종목_{stock_code}"}
                else:
                    self._mock_holdings[stock_code] = {"qty": qty, "avg_price": cur_price, "name": f"종목_{stock_code}"}
            else:
                if stock_code not in self._mock_holdings or self._mock_holdings[stock_code]["qty"] < qty:
                    return {"success": False, "msg": "매도할 보유 수량이 부족합니다."}
                self._mock_balance_deposit += total_cost
                self._mock_holdings[stock_code]["qty"] -= qty
                if self._mock_holdings[stock_code]["qty"] <= 0:
                    del self._mock_holdings[stock_code]

            order_type_str = "매수" if buy else "매도"
            logger.info(f"[시뮬레이션 주문] {stock_code} {order_type_str} {qty}주 완료 (체결가: {cur_price:,.0f}원)")
            return {
                "success": True,
                "order_no": f"SIM_{int(time.time())}",
                "code": stock_code,
                "qty": qty,
                "price": cur_price,
                "msg": f"시뮬레이션 {order_type_str} 완료"
            }

        tr_id = ("VTTC0802U" if self.mock else "TTTC0802U") if buy else ("VTTC0801U" if self.mock else "TTTC0801U")
        url = f"{self.url_base}/uapi/domestic-stock/v1/trading/order-cash"
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": stock_code,
            "ORD_DVSN": "01" if price == 0 else "00",
            "ORD_QTY": str(qty),
            "ORD_UNPR": str(int(price))
        }
        hashkey = self.get_hashkey(body)
        headers = self._get_headers(tr_id, hashkey=hashkey)

        try:
            self._rate_limit()
            res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
            data = self._safe_json_response(res, context=f"국내주문[{stock_code}]")

            if res.status_code == 200 and data.get("rt_cd") == "0":
                output = data.get("output", {})
                order_no = output.get("KRX_FWDG_ORD_ORGNO", "") + output.get("ODNO", "")
                logger.info(f"주문 성공: [{stock_code}] 수량 {qty} (주문번호: {order_no})")
                return {
                    "success": True,
                    "order_no": order_no,
                    "code": stock_code,
                    "qty": qty,
                    "msg": data.get("msg1", "주문 성공")
                }
            else:
                logger.error(f"주문 실패: [{stock_code}] {data.get('msg1')}")
                return {"success": False, "msg": data.get("msg1", "주문 실패")}
        except Exception as e:
            logger.error(f"주문 발주 예외 발생: {e}")
            return {"success": False, "msg": str(e)}

    # -------------------------------------------------------------------------
    # 해외주식 (미국 등) 전용 REST API 메서드
    # -------------------------------------------------------------------------
    def get_overseas_stock_price(self, symbol: str, exchange: str = "NAS") -> Dict[str, Any]:
        """
        해외주식(미국 등) 현재가 시세 조회 (HHDFS76200200)
        나스닥(NAS), 뉴욕(NYS), 아멕스(AMS) 거래소 자동 검색 지원
        """
        self._ensure_token()
        symbol_upper = symbol.upper()
        if not self.access_token:
            mock_prices = {"GOOGL": 175.5, "PFE": 25.03, "PLTR": 27.2, "TSLA": 220.5, "AAPL": 215.0, "NVDA": 130.0}
            base_p = mock_prices.get(symbol_upper, 100.0)
            return {
                "success": True,
                "code": symbol_upper,
                "name": f"해외({symbol_upper})",
                "price": base_p,
                "diff": 0.5,
                "rate": 0.55,
                "volume": 5000000,
                "high": base_p * 1.02,
                "low": base_p * 0.98,
                "open": base_p * 0.99,
                "currency": "USD"
            }

        url = f"{self.url_base}/uapi/overseas-price/v1/quotations/price"
        exchanges = [exchange] + [ex for ex in ["NAS", "NYS", "AMS"] if ex != exchange]

        for ex in exchanges:
            headers = self._get_headers("HHDFS76200200")
            params = {"AUTH": "", "EXCD": ex, "SYMB": symbol_upper}

            try:
                self._rate_limit()
                res = requests.get(url, headers=headers, params=params, timeout=10)
                data = self._safe_json_response(res, context=f"해외시세[{symbol_upper}]")

                if res.status_code == 200 and data.get("rt_cd") == "0":
                    output = data.get("output", {})
                    last_str = str(output.get("last", "")).strip()
                    if last_str and last_str != "0":
                        last_price = float(last_str)
                        diff_val = float(output.get("diff", 0) or 0)
                        rate_val = float(output.get("rate", 0) or 0)
                        self._symbol_exchange_cache[symbol_upper] = ex
                        return {
                            "success": True,
                            "code": symbol_upper,
                            "name": output.get("rsym", symbol_upper),
                            "price": last_price,
                            "diff": diff_val,
                            "rate": rate_val,
                            "volume": int(output.get("tvol", 0) or 0),
                            "high": float(output.get("high", last_price) or last_price),
                            "low": float(output.get("low", last_price) or last_price),
                            "open": float(output.get("open", last_price) or last_price),
                            "exchange": ex,
                            "currency": "USD"
                        }
            except Exception as e:
                logger.debug(f"[{symbol_upper}] {ex} 거래소 시세 조회 시도 예외: {e}")

        logger.error(f"[{symbol_upper}] 모든 해외 거래소(NAS/NYS/AMS) 시세 조회 실패")
        return {"success": False, "msg": "해외 시세 조회 실패"}

    def get_overseas_daily_chart(self, symbol: str, exchange: str = "NAS", count: int = 30) -> List[Dict[str, Any]]:
        """
        해외주식(미국 등) 일별 차트 시세 조회 (HHDFS76240000)
        나스닥(NAS), 뉴욕(NYS), 아멕스(AMS) 거래소 자동 검색 지원
        """
        self._ensure_token()
        symbol_upper = symbol.upper()
        if not self.access_token:
            chart_data = []
            mock_prices = {"GOOGL": 175.5, "PFE": 25.03, "PLTR": 27.2, "TSLA": 220.5, "AAPL": 215.0, "NVDA": 130.0}
            base_p = mock_prices.get(symbol_upper, 100.0)
            for i in range(count):
                chart_data.append({
                    "date": f"202608{30-i:02d}",
                    "close": base_p + (i % 5) * 0.5 - (i % 3) * 0.3,
                    "open": base_p,
                    "high": base_p * 1.02,
                    "low": base_p * 0.98,
                    "volume": 1000000 + i * 10000
                })
            return chart_data

        url = f"{self.url_base}/uapi/overseas-price/v1/quotations/dailyprice"
        exchanges = [exchange] + [ex for ex in ["NAS", "NYS", "AMS"] if ex != exchange]

        for ex in exchanges:
            headers = self._get_headers("HHDFS76240000")
            params = {"AUTH": "", "EXCD": ex, "SYMB": symbol_upper, "GUBN": "0", "BYMD": "", "MODP": "1"}

            try:
                self._rate_limit()
                res = requests.get(url, headers=headers, params=params, timeout=10)
                data = self._safe_json_response(res, context=f"해외일봉[{symbol_upper}]")

                logger.info(f"[{symbol_upper}] 일봉 차트 [{ex}] HTTP {res.status_code} | rt_cd={data.get('rt_cd')} | msg1={data.get('msg1')}")

                if res.status_code == 200 and data.get("rt_cd") == "0":
                    raw_output = data.get("output2", data.get("output", []))
                    if raw_output:
                        results = []
                        for item in raw_output[:count]:
                            c_val = float(item.get("clos", item.get("last", 0)) or 0)
                            if c_val > 0:
                                results.append({
                                    "date": item.get("xymd", item.get("ksam_date", item.get("date", ""))),
                                    "close": c_val,
                                    "open": float(item.get("open", 0) or 0),
                                    "high": float(item.get("high", 0) or 0),
                                    "low": float(item.get("low", 0) or 0),
                                    "volume": int(item.get("tvol", item.get("voum", 0)) or 0)
                                })
                        if results:
                            logger.info(f"[{symbol_upper}] 일봉 차트 [{ex}] 결과 {len(results)}건 반환")
                            return results
                        else:
                            logger.warning(f"[{symbol_upper}] 일봉 차트 [{ex}] 결과가 모두 0이거나 파싱 실패")
                    else:
                        logger.warning(f"[{symbol_upper}] 일봉 차트 [{ex}] output2가 비어있음, 전체 응답: {json.dumps(data, ensure_ascii=False)[:500]}")
                else:
                    logger.warning(f"[{symbol_upper}] 일봉 차트 [{ex}] API 오류: {data.get('msg1', '')}")
            except Exception as e:
                logger.debug(f"[{symbol_upper}] {ex} 일봉 차트 조회 시도 예외: {e}")

        logger.error(f"[{symbol_upper}] 해외 일봉 차트 조회 실패")
        return []

    def get_overseas_account_balance(self) -> Dict[str, Any]:
        """
        해외주식 계좌 외화(USD) 예수금 및 주문가능금액 조회 (VTTS3007R: 모의 / TTTS3007R: 실전)
        """
        self._ensure_token()
        if not self.access_token or not self.cano:
            return {
                "success": True,
                "usd_deposit": getattr(self, "_mock_usd_deposit", 5000.0),
                "is_simulated": True
            }

        tr_id = "VTTS3007R" if self.mock else "TTTS3007R"
        url = f"{self.url_base}/uapi/overseas-stock/v1/trading/inquire-psamount"
        headers = self._get_headers(tr_id)
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": "NAS",
            "ITEM_CD": "TQQQ",
            "OVRS_ORD_UNPR": "0"
        }

        try:
            self._rate_limit()
            res = requests.get(url, headers=headers, params=params, timeout=10)
            data = self._safe_json_response(res, context="해외계좌잔고")

            if res.status_code == 200 and data.get("rt_cd") == "0":
                output = data.get("output", {})
                usd_dep = float(output.get("ord_psbl_frcr_amt", output.get("ovrs_ord_psbl_amt", 0.0)))
                ex_rate = float(output.get("exrt", 1428.20))
                return {"success": True, "usd_deposit": usd_dep, "exchange_rate": ex_rate, "is_simulated": False, "data": output}
            else:
                msg1 = data.get("msg1", "")
                if "만료된" in msg1 or data.get("msg_cd") == "EGW00123":
                    logger.warning("Token 만료 감시: 새로운 Access Token 재발급 시도...")
                    self.access_token = None
                    self.token_issued_at = 0
                    if self.get_access_token():
                        return self.get_overseas_account_balance()
                return {"success": True, "usd_deposit": getattr(self, "_mock_usd_deposit", 5000.0), "exchange_rate": 1428.20, "is_simulated": True}
        except Exception as e:
            logger.error(f"해외 계좌 잔고 조회 실패 예외: {e}")
            return {"success": True, "usd_deposit": getattr(self, "_mock_usd_deposit", 5000.0), "is_simulated": True}

    def get_overseas_stock_balance(self) -> Dict[str, Any]:
        """
        해외주식 잔고 보유 종목 및 수량 조회 (VTTS3012R: 모의 / TTTS3012R: 실전)
        """
        self._ensure_token()
        if not self.access_token or not self.cano:
            # 시뮬레이션 모드 시 가상 보유 종목 변환 리턴
            mock_holdings = []
            for code, item in getattr(self, "_mock_holdings", {}).items():
                if self.is_overseas_symbol(code):
                    mock_holdings.append({
                        "code": code,
                        "name": item.get("name", f"해외({code})"),
                        "qty": int(item.get("qty", 0)),
                        "avg_price": float(item.get("avg_price", 0.0)),
                        "current_price": float(item.get("current_price", 0.0)),
                        "pnl_rate": float(item.get("pnl_rate", 0.0))
                    })
            logger.info(f"[해외잔고] 시뮬레이션 모드: 가상 해외 보유 종목 {len(mock_holdings)}개 반환")
            return {"success": True, "holdings": mock_holdings, "is_simulated": True}

        tr_id = "VTTS3012R" if self.mock else "TTTS3012R"
        url = f"{self.url_base}/uapi/overseas-stock/v1/trading/inquire-balance"
        headers = self._get_headers(tr_id)
        logger.info(f"[해외잔고] API 호출 시작: tr_id={tr_id}, url={url}, mock={self.mock}")

        # 해외 거래소 순회하며 보유 종목 통합 조회 (NASD는 미국 전역 통합 조회, AMEX/NYSE로 추가 보완)
        exchanges = ["NASD", "AMEX", "NYSE"]
        all_holdings = []
        seen_codes = set()
        last_error = ""
        exchange_results: Dict[str, Dict[str, Any]] = {}

        for exch in exchanges:
            params = {
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.acnt_prdt_cd,
                "OVRS_EXCG_CD": exch,
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": ""
            }

            exch_holdings = []
            try:
                ctx_fk = ""
                ctx_nk = ""
                max_pages = 5

                for _ in range(max_pages):
                    params["CTX_AREA_FK200"] = ctx_fk
                    params["CTX_AREA_NK200"] = ctx_nk

                    self._rate_limit()
                    res = requests.get(url, headers=headers, params=params, timeout=10)
                    data = self._safe_json_response(res, context=f"해외잔고[{exch}]")

                    logger.info(f"[해외잔고] [{exch}] HTTP {res.status_code} | rt_cd={data.get('rt_cd')} | msg1={data.get('msg1')}")

                    if res.status_code == 200 and data.get("rt_cd") == "0":
                        output1 = data.get("output1", [])
                        logger.info(f"[해외잔고] [{exch}] output1 항목 수: {len(output1)}")

                        for item in output1:
                            # 수량 필드 - 여러 가능한 필드명 확인
                            qty_raw = item.get("ovrs_cblc_qty", item.get("ovrs_ccls_qty", item.get("ccls_qty", item.get("hldg_qty", item.get("ovrs_hldg_qty", 0)))))

                            qty = int(float(qty_raw or 0))
                            if qty <= 0:
                                logger.debug(f"[해외잔고] [{exch}] 수량 0 이하로 스킵: pdno={item.get('pdno')}, ovrs_pdno={item.get('ovrs_pdno')}, symb={item.get('symb')}, qty_raw={qty_raw}")
                                continue

                            code = item.get("ovrs_pdno", item.get("pdno", item.get("symb", ""))).strip().upper()
                            if not code:
                                logger.debug(f"[해외잔고] [{exch}] 종목코드 없음으로 스킵: item={json.dumps(item, ensure_ascii=False)[:300]}")
                                continue

                            name = item.get("ovrs_item_name", item.get("item_name", item.get("prdt_name", code)))
                            avg_p = float(item.get("pchs_avg_pric", item.get("avg_pric", 0.0)) or 0.0)
                            cur_p = float(item.get("now_pric2", item.get("last_prik", 0.0)) or 0.0)
                            pnl_rate = float(item.get("evlu_pfls_rt", item.get("pfls_rt", 0.0)) or 0.0)

                            logger.debug(f"[해외잔고] [{exch}] 보유 종목 파싱: code={code}, name={name}, qty={qty}, avg_p={avg_p}, cur_p={cur_p}, pnl_rate={pnl_rate}")

                            holding_item = {
                                "code": code,
                                "name": name,
                                "qty": qty,
                                "avg_price": avg_p,
                                "current_price": cur_p,
                                "pnl_rate": pnl_rate
                            }
                            exch_holdings.append(holding_item)
                            if code not in seen_codes:
                                seen_codes.add(code)
                                all_holdings.append(holding_item)

                        # 다음 페이지 확인
                        ctx_fk = (data.get("ctx_area_fk200", "") or "").strip()
                        ctx_nk = (data.get("ctx_area_nk200", "") or "").strip()
                        if not ctx_fk and not ctx_nk:
                            break
                    else:
                        msg1 = data.get("msg1", "")
                        logger.warning(f"[해외잔고] [{exch}] API 오류: rt_cd={data.get('rt_cd')}, msg1={msg1}, msg_cd={data.get('msg_cd')}")
                        if "만료된" in msg1 or data.get("msg_cd") == "EGW00123":
                            logger.warning("Token 만료 감지: 해외 잔고 재조회 시도...")
                            self.access_token = None
                            self.token_issued_at = 0
                            if self.get_access_token():
                                return self.get_overseas_stock_balance()
                        last_error = f"[{exch}] {msg1}"
                        break
            except Exception as e:
                last_error = str(e)
                logger.error(f"해외주식 잔고 조회 예외 발생 ({exch}): {e}")

            exchange_results[exch] = {
                "holdings_count": len(exch_holdings),
                "holdings": exch_holdings,
                "error": last_error if last_error and f"[{exch}]" in last_error else ""
            }
            logger.info(f"[해외잔고] [{exch}] 거래소 조회 완료: 보유 종목 {len(exch_holdings)}개 | last_error={last_error}")

        logger.info(f"[해외잔고] 전체 거래소 조회 결과: NAS={exchange_results.get('NAS', {}).get('holdings_count', 0)}개, NYS={exchange_results.get('NYS', {}).get('holdings_count', 0)}개, AMS={exchange_results.get('AMS', {}).get('holdings_count', 0)}개 | 총 {len(all_holdings)}개")

        if all_holdings:
            holdings_summary = ", ".join([f"{h['code']}({h['qty']}주)" for h in all_holdings])
            logger.info(f"[해외잔고] 해외 보유 종목 {len(all_holdings)}개 반환: {holdings_summary}")
            return {"success": True, "holdings": all_holdings, "is_simulated": False}
        elif last_error:
            logger.error(f"해외주식 잔고 조회 실패: {last_error}")
            return {"success": False, "msg": last_error, "holdings": []}
        else:
            logger.warning("[해외잔고] 해외주식 잔고 API가 성공했지만 보유 종목이 0개입니다. (실제 보유 종목이 없거나, API 응답 파싱 문제일 수 있음)")
            return {"success": True, "holdings": [], "is_simulated": False}

    def get_overseas_execution_balance(
        self,
        symbol: str = "",
        start_date: str = "",
        end_date: str = "",
        cblc_dvsn: str = "00"
    ) -> Dict[str, Any]:
        """
        해외주식 체결기준 현물 잔고 조회 (TTTS3012R: 실전 / VTTS3012R: 모의)
        - 체결(Execution) 기준으로 보유 종목의 체결수량/체결단가/미체결수량을 조회
        - TTTS3012R(해외주식 잔고) API를 사용하여 실제 체결된 수량과 단가를 기준으로 잔고를 계산
        - 매수/매도 & 체결/실패 이력을 Google Sheets에 기록할 때 사용
        - cblc_dvsn: 체결구분 (00: 전체, 01: 미체결, 02: 체결) - TTTS3012R에서는 사용하지 않음 (호환용 파라미터)
        - NOTE: TTTC1006R(체결기준 현물 잔고) API는 KIS OpenAPI에서 제공하지 않아 OPSQ0002(없는 서비스 코드) 오류가 발생한다.
                따라서 TTTS3012R(해외주식 잔고) API로 대체하여 사용한다. TTTS3012R은 ovrs_cblc_qty(보유수량),
                ft_ccld_qty(체결수량), nccs_qty(미체결수량) 필드를 제공하여 동일한 데이터를 얻을 수 있다.
        """
        self._ensure_token()
        if not self.access_token or not self.cano:
            # 시뮬레이션 모드 시 가상 보유 종목 변환 리턴
            mock_holdings = []
            for code, item in getattr(self, "_mock_holdings", {}).items():
                if self.is_overseas_symbol(code):
                    mock_holdings.append({
                        "code": code,
                        "name": item.get("name", f"해외({code})"),
                        "qty": int(item.get("qty", 0)),
                        "avg_price": float(item.get("avg_price", 0.0)),
                        "current_price": float(item.get("current_price", 0.0)),
                        "executed_qty": int(item.get("qty", 0)),
                        "executed_price": float(item.get("avg_price", 0.0)),
                        "unexecuted_qty": 0,
                        "pnl_rate": float(item.get("pnl_rate", 0.0))
                    })
            logger.info(f"[해외체결잔고] 시뮬레이션 모드: 가상 해외 보유 종목 {len(mock_holdings)}개 반환")
            return {"success": True, "holdings": mock_holdings, "is_simulated": True}

        if not start_date:
            start_date = time.strftime("%Y%m%d")
        if not end_date:
            end_date = time.strftime("%Y%m%d")

        # NOTE: TTTC1006R(체결기준 현물 잔고) API는 KIS OpenAPI에서 제공하지 않아 OPSQ0002(없는 서비스 코드) 오류가 발생한다.
        #       TTTS3012R(해외주식 잔고) API로 대체하여 사용한다. TTTS3012R은 ovrs_cblc_qty(보유수량),
        #       ft_ccld_qty(체결수량), nccs_qty(미체결수량) 필드를 제공하여 동일한 데이터를 얻을 수 있다.
        tr_id = "VTTS3012R" if self.mock else "TTTS3012R"
        url = f"{self.url_base}/uapi/overseas-stock/v1/trading/inquire-balance"
        headers = self._get_headers(tr_id)
        logger.info(f"[해외체결잔고] API 호출 시작: tr_id={tr_id}, url={url}, mock={self.mock}, 기간={start_date}~{end_date}")

        # 여러 거래소 순회하며 체결기준 보유 종목 통합 조회 (NASD는 미국 전역 통합 조회, AMEX/NYSE로 추가 보완)
        exchanges = ["NASD", "AMEX", "NYSE"]
        all_holdings = []
        seen_codes = set()
        last_error = ""
        exchange_results: Dict[str, Dict[str, Any]] = {}

        for exch in exchanges:
            params = {
                "CANO": self.cano,
                "ACNT_PRDT_CD": self.acnt_prdt_cd,
                "OVRS_EXCG_CD": exch,
                "TR_CRCY_CD": "USD",
                "CTX_AREA_FK200": "",
                "CTX_AREA_NK200": ""
            }

            exch_holdings = []
            try:
                ctx_fk = ""
                ctx_nk = ""
                max_pages = 5

                for _ in range(max_pages):
                    params["CTX_AREA_FK200"] = ctx_fk
                    params["CTX_AREA_NK200"] = ctx_nk

                    self._rate_limit()
                    res = requests.get(url, headers=headers, params=params, timeout=10)
                    data = self._safe_json_response(res, context=f"해외체결잔고[{exch}]")

                    logger.info(f"[해외체결잔고] [{exch}] HTTP {res.status_code} | rt_cd={data.get('rt_cd')} | msg1={data.get('msg1')}")

                    if res.status_code == 200 and data.get("rt_cd") == "0":
                        output1 = data.get("output1", [])
                        logger.info(f"[해외체결잔고] [{exch}] output1 항목 수: {len(output1)}")

                        for item in output1:
                            # 체결기준 수량 필드 (TTTS3012R 응답 필드)
                            # - ovrs_cblc_qty: 체결기준 보유수량
                            # - ft_ccld_qty: 체결수량
                            # - nccs_qty: 미체결수량
                            qty_raw = item.get("ovrs_cblc_qty", item.get("ft_ccld_qty", item.get("cblc_qty", item.get("hldg_qty", 0))))
                            exec_qty_raw = item.get("ft_ccld_qty", item.get("ovrs_cblc_qty", 0))
                            unexec_qty_raw = item.get("nccs_qty", 0)

                            qty = int(float(qty_raw or 0))
                            exec_qty = int(float(exec_qty_raw or 0))
                            unexec_qty = int(float(unexec_qty_raw or 0))
                            if qty <= 0 and exec_qty <= 0:
                                logger.debug(f"[해외체결잔고] [{exch}] 수량 0 이하로 스킵: pdno={item.get('pdno')}, ovrs_pdno={item.get('ovrs_pdno')}, symb={item.get('symb')}, qty_raw={qty_raw}")
                                continue

                            code = item.get("ovrs_pdno", item.get("pdno", item.get("symb", ""))).strip().upper()
                            if not code:
                                logger.debug(f"[해외체결잔고] [{exch}] 종목코드 없음으로 스킵: item={json.dumps(item, ensure_ascii=False)[:300]}")
                                continue

                            # 종목 필터
                            if symbol and code != symbol.upper():
                                logger.debug(f"[해외체결잔고] [{exch}] 종목 필터 스킵: code={code}, symbol={symbol.upper()}")
                                continue

                            name = item.get("ovrs_item_name", item.get("item_name", item.get("prdt_name", code)))
                            # 체결기준 평균단가/체결단가
                            avg_p = float(item.get("pchs_avg_pric", item.get("ft_ccld_unpr", item.get("avg_pric", 0.0))) or 0.0)
                            exec_p = float(item.get("ft_ccld_unpr", item.get("ft_ccld_unpr3", 0.0)) or 0.0)
                            cur_p = float(item.get("now_pric2", item.get("last_prik", 0.0)) or 0.0)
                            pnl_rate = float(item.get("evlu_pfls_rt", item.get("pfls_rt", 0.0)) or 0.0)

                            logger.debug(f"[해외체결잔고] [{exch}] 체결기준 보유 종목 파싱: code={code}, name={name}, qty={qty}, exec_qty={exec_qty}, unexec_qty={unexec_qty}, avg_p={avg_p}, exec_p={exec_p}, cur_p={cur_p}, pnl_rate={pnl_rate}")

                            holding_item = {
                                "code": code,
                                "name": name,
                                "qty": qty,
                                "executed_qty": exec_qty,
                                "unexecuted_qty": unexec_qty,
                                "avg_price": avg_p,
                                "executed_price": exec_p,
                                "current_price": cur_p,
                                "pnl_rate": pnl_rate
                            }
                            exch_holdings.append(holding_item)
                            if code not in seen_codes:
                                seen_codes.add(code)
                                all_holdings.append(holding_item)

                        # 다음 페이지 확인
                        ctx_fk = (data.get("ctx_area_fk200", "") or "").strip()
                        ctx_nk = (data.get("ctx_area_nk200", "") or "").strip()
                        if not ctx_fk and not ctx_nk:
                            break
                    else:
                        msg1 = data.get("msg1", "")
                        logger.warning(f"[해외체결잔고] [{exch}] API 오류: rt_cd={data.get('rt_cd')}, msg1={msg1}, msg_cd={data.get('msg_cd')}")
                        if "만료된" in msg1 or data.get("msg_cd") == "EGW00123":
                            logger.warning("Token 만료 감지: 해외 체결기준 잔고 재조회 시도...")
                            self.access_token = None
                            self.token_issued_at = 0
                            if self.get_access_token():
                                return self.get_overseas_execution_balance(symbol=symbol, start_date=start_date, end_date=end_date, cblc_dvsn=cblc_dvsn)
                        last_error = f"[{exch}] {msg1}"
                        break
            except Exception as e:
                last_error = str(e)
                logger.error(f"해외주식 체결기준 잔고 조회 예외 발생 ({exch}): {e}")

            exchange_results[exch] = {
                "holdings_count": len(exch_holdings),
                "holdings": exch_holdings,
                "error": last_error if last_error and f"[{exch}]" in last_error else ""
            }
            logger.info(f"[해외체결잔고] [{exch}] 거래소 조회 완료: 체결기준 보유 종목 {len(exch_holdings)}개 | last_error={last_error}")

        logger.info(f"[해외체결잔고] 전체 거래소 조회 결과: NAS={exchange_results.get('NAS', {}).get('holdings_count', 0)}개, NYS={exchange_results.get('NYS', {}).get('holdings_count', 0)}개, AMS={exchange_results.get('AMS', {}).get('holdings_count', 0)}개 | 총 {len(all_holdings)}개")

        if all_holdings:
            holdings_summary = ", ".join([f"{h['code']}(체결{h['executed_qty']}주/미체결{h['unexecuted_qty']}주)" for h in all_holdings])
            logger.info(f"[해외체결잔고] 해외 체결기준 보유 종목 {len(all_holdings)}개 반환: {holdings_summary}")
            return {"success": True, "holdings": all_holdings, "is_simulated": False}
        elif last_error:
            logger.error(f"해외주식 체결기준 잔고 조회 실패: {last_error}")
            return {"success": False, "msg": last_error, "holdings": []}
        else:
            logger.warning("[해외체결잔고] 해외주식 체결기준 잔고 API가 성공했지만 보유 종목이 0개입니다. (실제 보유 종목이 없거나, API 응답 파싱 문제일 수 있음)")
            return {"success": True, "holdings": [], "is_simulated": False}

    def order_overseas_cash(
        self,
        symbol: str,
        qty: int,
        price: float = 0,
        buy: bool = True,
        exchange: str = "NAS",
        ord_type: str = "00"
    ) -> Dict[str, Any]:
        """
        해외주식 현금 매수/매도 주문 (TTBL1002U / TTBL1006U)
        ord_type: "00"(지정가), "34"(LOC - Limit On Close), "33"(LOO - Limit On Open), "01"(시장가)
        """
        self._ensure_token()
        symbol_upper = symbol.upper()
        if not self.access_token:
            # 실전매매 환경(self.mock=False)인데 토큰 발급이 안된 경우 가상 성공 처리 방지
            if not self.mock and (self.app_key and self.app_secret):
                logger.error(f"[{symbol_upper}] KIS Access Token이 유효하지 않아 실전 해외 주문을 발주할 수 없습니다.")
                return {"success": False, "msg": "Access Token이 유효하지 않아 실전 주문을 발주할 수 없습니다."}

            action_str = "매수" if buy else "매도"
            ord_name = "LOC " if ord_type == "34" else ""
            total_cost = qty * price if price > 0 else 0.0
            if buy and total_cost > 0:
                self._mock_usd_deposit = max(0.0, self._mock_usd_deposit - total_cost)
            elif not buy and total_cost > 0:
                self._mock_usd_deposit += total_cost

            logger.info(f"[시뮬레이션] 해외주식 {symbol_upper} {ord_name}{action_str} {qty}주 완료 (가격: ${price:.2f}, 외화잔고: ${self._mock_usd_deposit:.2f})")
            return {"success": True, "msg": f"[시뮬레이션] 해외 {symbol_upper} {ord_name}{action_str} 성공"}

        # 종목별 상장 거래소 자동 판별 (exchange가 미지정이거나 NAS 기본값일 때 자동 보정)
        target_exchange = exchange
        if not target_exchange or target_exchange.upper() == "NAS":
            auto_exch = self.get_symbol_exchange(symbol_upper)
            if auto_exch:
                target_exchange = auto_exch

        # 시세 조회 코드를 해외주식 주문 전용 거래소 코드로 자동 변환 (NAS->NASD, NYS->NYSE, AMS->AMEX)
        exchange_map = {
            "NAS": "NASD",
            "NYS": "NYSE",
            "AMS": "AMEX",
            "NASD": "NASD",
            "NYSE": "NYSE",
            "AMEX": "AMEX"
        }
        ovrs_excg_cd = exchange_map.get(target_exchange.upper() if target_exchange else "NAS", "NASD")
        logger.info(f"[{symbol_upper}] 해외주식 주문 거래소 결정: {target_exchange} -> {ovrs_excg_cd}")

        url = f"{self.url_base}/uapi/overseas-stock/v1/trading/order"
        tr_id = ("TTTT1002U" if buy else "TTTT1006U") if not self.mock else ("VTTT1002U" if buy else "VTTT1006U")
        
        body = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "OVRS_EXCG_CD": ovrs_excg_cd,
            "PDNO": symbol_upper,
            "ORD_QTY": str(qty),
            "OVRS_ORD_UNPR": f"{price:.2f}" if price > 0 else "0",
            "ORD_DVSN": ord_type if price > 0 else "01",
            "ORD_SVR_DVSN_CD": "0"
        }
        hashkey = self.get_hashkey(body)
        headers = self._get_headers(tr_id, hashkey=hashkey)

        try:
            self._rate_limit()
            res = requests.post(url, headers=headers, data=json.dumps(body), timeout=10)
            data = self._safe_json_response(res, context=f"해외주문[{symbol_upper}]")

            if res.status_code == 200 and data.get("rt_cd") == "0":
                logger.info(f"★ [{symbol_upper}] 해외주식 {'매수' if buy else '매도'} 주문 성공! (주문번호: {data.get('output', {}).get('ODNO')})")
                return {"success": True, "msg": "주문 성공", "data": data.get("output")}
            else:
                msg = data.get("msg1", "주문 실패")
                msg_cd = data.get("msg_cd", "")
                logger.error(f"[{symbol_upper}] 해외주식 주문 실패 (tr_id={tr_id}, rt_cd={data.get('rt_cd')}, msg_cd={msg_cd}): {msg}")
                if msg_cd == "APBK1681" or "기본예탁금" in msg:
                    logger.warning(f"⚠️ [{symbol_upper}] 레버리지 ETF 매수 조건 미충족 (기본예탁금 등록 및 레버리지 사전교육 이수 필요)")
                return {"success": False, "msg": f"{msg} (코드: {msg_cd})", "msg_cd": msg_cd}
        except Exception as e:
            logger.error(f"[{symbol_upper}] 해외주식 주문 예외 발생: {e}")
            return {"success": False, "msg": str(e)}

    def get_overseas_execution_history(
        self,
        symbol: str = "",
        start_date: str = "",
        end_date: str = ""
    ) -> List[Dict[str, Any]]:
        """
        해외주식 체결/미체결 이력 조회 (CTOS4001R 기간별거래)
        - CTOS4001R(기간별거래)로 주문/체결 이력을 조회하며, 주문번호(odno) 기준으로 중복을 제거한다.
        - NOTE: 야간원장(JTTT3001R)은 한국 시간 낮에 데이터가 매칭되지 않아 제거,
                TTTS3035R(주간원장)은 현재 주(week) 데이터만 반환하므로 제거,
                CTOS4001R(기간별거래)만 사용하여 기간 전체 이력을 조회한다.
        """
        self._ensure_token()
        if not self.access_token or not self.cano:
            return []

        if not start_date:
            start_date = time.strftime("%Y%m%d")
        if not end_date:
            end_date = time.strftime("%Y%m%d")

        results = []
        total_fetched = 0
        total_skipped_symbol = 0

        # NOTE: OVRS_EXCG_CD를 공백("")으로 설정하여 모든 거래소의 해외주식 주문체결 이력을 조회한다.
        #       (KIS API에서 OVRS_EXCG_CD를 비우면 전체 거래소를 조회할 수 있음)
        ovrs_excg = ""

        # 해외주식 주문/체결 이력 조회 (CTOS4001R 기간별거래)
        tr_id_day = "VCTS4001R" if self.mock else "CTOS4001R"
        url_day = f"{self.url_base}/uapi/overseas-stock/v1/trading/inquire-period-trans"
        ep_name = "기간별거래(CTOS4001R)"
        headers_day = self._get_headers(tr_id_day)
        headers_day["tr_cont"] = ""  # 초기 조회 (연속 조회 시 "N")
        logger.info(f"[체결이력] {ep_name} API 호출 시작: tr_id={tr_id_day}, url={url_day}")

        # NOTE: CTOS4001R 요청 파라미터 (등록일자 기준 조회)
        #       - ERLM_STRT_DT/ERLM_END_DT: 등록시작/종료일자
        #       - LOAN_DVSN_CD: 대출구분코드 (00: 전체)
        #       - SLL_BUY_DVSN_CD: 매도매수구분코드 (00: 전체)
        #       - 일부 API 버전에서는 ORD_STRT_DT/ORD_END_DT(주문일자)를 사용할 수 있음
        params_day = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "ERLM_STRT_DT": start_date,
            "ERLM_END_DT": end_date,
            "OVRS_EXCG_CD": ovrs_excg,
            "PDNO": symbol.upper() if symbol else "",
            "SLL_BUY_DVSN_CD": "00",
            "LOAN_DVSN_CD": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }

        try:
            ctx_fk = ""
            ctx_nk = ""
            for _ in range(5):
                params_day["CTX_AREA_FK100"] = ctx_fk
                params_day["CTX_AREA_NK100"] = ctx_nk
                # 연속 조회 여부: 응답 헤더 tr_cont가 "M"이면 다음 페이지 조회 시 "N"으로 설정
                headers_day["tr_cont"] = "N" if _ > 0 else ""
                time.sleep(0.05)
                res = requests.get(url_day, headers=headers_day, params=params_day, timeout=8)
                data = self._safe_json_response(res, context=f"체결이력[{ep_name}]")

                # DEBUG: CTOS4001R 전체 응답 원문 로그 (디버깅용)
                logger.debug(f"[체결이력] {ep_name} page={_+1} HTTP {res.status_code} | rt_cd={data.get('rt_cd')} | msg_cd={data.get('msg_cd')} | msg1={data.get('msg1')} | raw={json.dumps(data, ensure_ascii=False)[:3000]}")

                if res.status_code == 200 and data.get("rt_cd") == "0":
                    output = data.get("output1", []) or data.get("output", [])
                    if not output:
                        # 빈 응답 진단 로그 (디버깅용)
                        logger.warning(f"[체결이력] {ep_name} page={_+1} output이 비어있음 (rt_cd=0, output1/output 없음)")
                        logger.warning(f"[체결이력] {ep_name} 빈 응답 진단:")
                        logger.warning(f"  - 요청 파라미터: ERLM_STRT_DT={params_day.get('ERLM_STRT_DT')}, ERLM_END_DT={params_day.get('ERLM_END_DT')}, OVRS_EXCG_CD={params_day.get('OVRS_EXCG_CD')}, PDNO={params_day.get('PDNO')}, SLL_BUY_DVSN_CD={params_day.get('SLL_BUY_DVSN_CD')}")
                        logger.warning(f"  - 가능 원인 1: 해당 기간에 거래 내역이 없음 (정상적인 경우, 오류 아님)")
                        logger.warning(f"  - 가능 원인 2: 등록일자(ERLM_STRT_DT/ERLM_END_DT) 기준이 거래일자와 다를 수 있음 - 날짜 범위 확장 필요")
                        logger.warning(f"  - 가능 원인 3: 거래소 코드가 공백이어서 API가 전체 거래소를 조회하지 못할 수 있음 - NAS/NYS/AMS 명시 필요")
                        logger.warning(f"  - 가능 원인 4: 계좌(CANO={self.cano})에 해당 기간 거래가 없음")
                        logger.warning(f"  - 가능 원인 5: 권한 부족 또는 계좌 유형 불일치 (custtype=P는 개인 전용)")
                        logger.warning(f"  - 원본 응답: {json.dumps(data, ensure_ascii=False)[:1000]}")
                        break
                    logger.info(f"[체결이력] {ep_name} 조회 성공 (건수={len(output)}, page={_ + 1})")

                    # DEBUG: CTOS4001R 응답 원문 로그 (디버깅용)
                    logger.debug(f"[체결이력] {ep_name} page={_+1} output1 raw: {json.dumps(output, ensure_ascii=False)[:2000]}")
                    logger.debug(f"[체결이력] {ep_name} page={_+1} output2 raw: {json.dumps(data.get('output2', {}), ensure_ascii=False)[:1000]}")
                    logger.debug(f"[체결이력] {ep_name} page={_+1} ctx_area_fk100={ctx_fk} ctx_area_nk100={ctx_nk}")

                    for item in output:
                            total_fetched += 1
                            # CTOS4001R 응답 필드 매핑
                            # - trad_dt: 매매일자
                            # - sttl_dt: 결제일자
                            # - sll_buy_dvsn_cd: 매도매수구분코드
                            # - sll_buy_dvsn_name: 매도매수구분명
                            # - pdno: 상품번호
                            # - ovrs_item_name: 해외종목명
                            # - ccld_qty: 체결수량
                            # - ft_ccld_unpr2: FT체결단가2
                            # - ovrs_stck_ccld_unpr: 해외주식체결단가
                            # - tr_frcr_amt2: 거래외화금액2
                            # - tr_amt: 거래금액
                            # - crcy_cd: 통화코드
                            # - loan_dvsn_cd: 대출구분코드
                            # - loan_dvsn_name: 대출구분명
                            order_no = str(item.get("odno", item.get("ord_no", ""))).strip()
                            item_symbol = str(item.get("pdno", item.get("symb", item.get("symbol", "")))).strip().upper()
                            sll_buy_cd = str(item.get("sll_buy_dvsn_cd", "")).strip()
                            order_type = str(item.get("sll_buy_dvsn_name", "")).strip()
                            if not order_type or order_type == "-":
                                if sll_buy_cd in ("01", "1"):
                                    order_type = "매도"
                                elif sll_buy_cd in ("02", "2"):
                                    order_type = "매수"
                            qty = int(item.get("ccld_qty", item.get("ft_ccld_qty", item.get("qty", 0))) or 0)
                            exec_qty = int(item.get("ccld_qty", item.get("ft_ccld_qty", item.get("exec_qty", 0))) or 0)
                            exec_price = float(item.get("ft_ccld_unpr2") or item.get("ft_ccld_unpr") or item.get("ovrs_stck_ccld_unpr") or item.get("exec_price") or 0.0)
                            ord_price = float(item.get("ft_ord_unpr3") or item.get("ft_ord_unpr") or item.get("ft_ccld_unpr2") or item.get("ft_ccld_unpr") or item.get("ovrs_stck_ord_unpr") or item.get("ovrs_stck_ccld_unpr") or item.get("price") or 0.0)
                            ord_dt_raw = str(item.get("trad_dt", item.get("ord_dt", item.get("order_dt", "")))).strip()
                            ord_tmd_raw = str(item.get("ord_tmd", item.get("order_tmd", ""))).strip()
                            fmt_dt = f"{ord_dt_raw[:4]}-{ord_dt_raw[4:6]}-{ord_dt_raw[6:8]}" if len(ord_dt_raw) == 8 and ord_dt_raw.isdigit() else ord_dt_raw
                            fmt_tmd = f"{ord_tmd_raw[:2]}:{ord_tmd_raw[2:4]}:{ord_tmd_raw[4:6]}" if len(ord_tmd_raw) == 6 and ord_tmd_raw.isdigit() else ord_tmd_raw
                            order_time = f"{fmt_dt} {fmt_tmd}".strip()
                            status = str(item.get("prcs_stat_name", item.get("stat_name", item.get("status", "")))).strip()
                            orgn_odno = str(item.get("orgn_odno", "")).strip()
                            ord_gno_brno = str(item.get("ord_gno_brno", "")).strip()

                            if symbol and item_symbol and item_symbol != symbol.upper():
                                total_skipped_symbol += 1
                                continue

                            results.append({
                                "order_no": order_no,
                                "symbol": item_symbol,
                                "order_type": order_type,
                                "qty": qty,
                                "price": ord_price,
                                "executed_qty": exec_qty,
                                "executed_price": exec_price,
                                "status": status,
                                "order_time": order_time,
                                "ord_dt": ord_dt_raw,
                                "ord_tmd": ord_tmd_raw,
                                "ord_gno_brno": ord_gno_brno,
                                "orgn_odno": orgn_odno,
                                "prdt_name": str(item.get("ovrs_item_name", item.get("prdt_name", ""))).strip(),
                                "sll_buy_dvsn_cd": str(item.get("sll_buy_dvsn_cd", "")).strip(),
                                "rvse_cncl_dvsn": str(item.get("rvse_cncl_dvsn", "")).strip(),
                                "rvse_cncl_dvsn_name": str(item.get("rvse_cncl_dvsn_name", "")).strip(),
                                "ft_ccld_amt3": str(item.get("ft_ccld_amt3", item.get("tr_frcr_amt2", item.get("tr_amt", "")))).strip(),
                                "nccs_qty": str(item.get("nccs_qty", "")).strip(),
                                "rjct_rson": str(item.get("rjct_rson", "")).strip(),
                                "rjct_rson_name": str(item.get("rjct_rson_name", "")).strip(),
                                "tr_mket_name": str(item.get("tr_mket_name", "")).strip(),
                                "tr_natn_name": str(item.get("tr_natn_name", "")).strip(),
                                "ovrs_excg_cd": str(item.get("ovrs_excg_cd", "")).strip(),
                                "tr_crcy_cd": str(item.get("crcy_cd", item.get("tr_crcy_cd", ""))).strip(),
                                "dmst_ord_dt": str(item.get("dmst_ord_dt", "")).strip(),
                                "thco_ord_tmd": str(item.get("thco_ord_tmd", "")).strip(),
                                "loan_type_cd": str(item.get("loan_dvsn_cd", item.get("loan_type_cd", ""))).strip(),
                                "loan_dt": str(item.get("loan_dt", "")).strip(),
                                "mdia_dvsn_name": str(item.get("mdia_dvsn_name", "")).strip(),
                                "usa_amk_exts_rqst_yn": str(item.get("usa_amk_exts_rqst_yn", "")).strip()
                            })

                            # DEBUG: 파싱된 레코드 로그 (디버깅용)
                            logger.debug(f"[체결이력] {ep_name} 파싱 레코드: order_no={order_no}, symbol={item_symbol}, order_type={order_type}, qty={qty}, exec_qty={exec_qty}, exec_price={exec_price}, ord_price={ord_price}, trad_dt={ord_dt_raw}, status={status}")

                    ctx_fk = (data.get("ctx_area_fk100", "") or "").strip()
                    ctx_nk = (data.get("ctx_area_nk100", "") or "").strip()
                    if not ctx_fk and not ctx_nk:
                        break
                else:
                    msg1 = data.get("msg1", "")
                    msg_cd = data.get("msg_cd", "")
                    logger.warning(f"[체결이력] {ep_name} API 오류: rt_cd={data.get('rt_cd')}, msg_cd={msg_cd}, msg1={msg1}")
                    if "만료된" in msg1 or data.get("msg_cd") == "EGW00123":
                        logger.warning("Token 만료 감지: 해외 체결내역 재조회 시도...")
                        self.access_token = None
                        self.token_issued_at = 0
                        if self.get_access_token():
                            return self.get_overseas_execution_history(symbol=symbol, start_date=start_date, end_date=end_date)
                    break
            logger.info(f"[체결이력] {ep_name} 조회 완료: {total_fetched}건")
        except Exception as e:
            logger.warning(f"[체결이력] {ep_name} 조회 예외: {e}")

        # NOTE: 주문번호(odno) 기준으로 중복 제거 (페이지네이션 중복 포함)
        #       중복이 발견되더라도 최대 5페이지까지 모두 조회한 후, 메모리단에서 한 번에 제거한다.
        seen_odno = set()
        deduped_results = []
        for r in results:
            odno = r.get("order_no", "")
            if odno and odno in seen_odno:
                continue
            if odno:
                seen_odno.add(odno)
            deduped_results.append(r)
        results = deduped_results

        logger.info(f"[체결이력] 최종 결과: {len(results)}건 (symbol={symbol or '전체'}, 기간={start_date}~{end_date})")
        logger.info(f"[체결이력] 진단: 총 조회={total_fetched}건, 종목필터 스킵={total_skipped_symbol}건, 중복 제거={total_fetched - len(results)}건, 최종={len(results)}건")
        for r in results:
            logger.info(f"  → {r.get('order_time', '')} | {r.get('symbol', '')} | {r.get('order_type', '')} | "
                        f"주문수량={r.get('qty', 0)} | 체결수량={r.get('executed_qty', 0)} | "
                        f"체결가={r.get('executed_price', 0)} | 상태={r.get('status', '')} | 주문번호={r.get('order_no', '')}")
        return results

    def get_overseas_order_ccnl(
        self,
        symbol: str = "",
        start_date: str = "",
        end_date: str = "",
        sll_buy_dvsn: str = "00",
        ccld_nccs_dvsn: str = "00",
        sort_sqn: str = "DS"
    ) -> List[Dict[str, Any]]:
        """
        해외주식 주문체결내역 조회 (inquire-ccnl, TTTS3035R/VTTS3035R)
        - 실전 TR_ID: TTTS3035R
        - 모의 TR_ID: VTTS3035R
        - URL: /uapi/overseas-stock/v1/trading/inquire-ccnl
        - 연속 조회(tr_cont=M) 시 모든 페이지를 자동으로 조회한다.

        Args:
            symbol: 상품번호 (예: "TQQQ"). 비어있으면 전체 종목 조회.
            start_date: 조회 시작일 (YYYYMMDD). 비어있으면 오늘.
            end_date: 조회 종료일 (YYYYMMDD). 비어있으면 오늘.
            sll_buy_dvsn: 매도매수구분 (00:전체, 01:매도, 02:매수)
            ccld_nccs_dvsn: 체결미체결구분 (00:전체, 01:체결, 02:미체결)
            sort_sqn: 정렬순서 (DS:정순, AS:역순)

        Returns:
            List[Dict]: 정규화된 주문/체결 내역 리스트
        """
        self._ensure_token()
        if not self.access_token or not self.cano:
            return []

        if not start_date:
            start_date = time.strftime("%Y%m%d")
        if not end_date:
            end_date = time.strftime("%Y%m%d")

        tr_id = "VTTS3035R" if self.mock else "TTTS3035R"
        url = f"{self.url_base}/uapi/overseas-stock/v1/trading/inquire-ccnl"
        headers = self._get_headers(tr_id)
        headers["tr_cont"] = ""  # 초기 조회 (연속 조회 시 "N")

        # 요청 파라미터 구성
        # - PDNO: 전종목일 경우 "%" 입력 (모의투자계좌의 경우 ""(전체 조회)만 가능)
        # - OVRS_EXCG_CD: 전종목일 경우 "%" 입력 (모의투자계좌의 경우 ""(전체 조회)만 가능)
        # - SLL_BUY_DVSN: 00:전체, 01:매도, 02:매수 (모의투자계좌의 경우 "00"만 가능)
        # - CCLD_NCCS_DVSN: 00:전체, 01:체결, 02:미체결 (모의투자계좌의 경우 "00"만 가능)
        # - SORT_SQN: DS:정순, AS:역순 (모의투자계좌의 경우 정렬순서 사용불가, Default: DS)
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": symbol.upper() if symbol else ("%" if not self.mock else ""),
            "ORD_STRT_DT": start_date,
            "ORD_END_DT": end_date,
            "SLL_BUY_DVSN": sll_buy_dvsn,
            "CCLD_NCCS_DVSN": ccld_nccs_dvsn,
            "OVRS_EXCG_CD": "%" if not self.mock else "",
            "SORT_SQN": sort_sqn,
            "ORD_DT": "",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "CTX_AREA_NK200": "",
            "CTX_AREA_FK200": ""
        }

        all_output = []
        page = 0
        max_pages = 20  # 최대 페이지 수 제한 (무한 루프 방지)

        try:
            ctx_nk = ""
            ctx_fk = ""
            for page in range(1, max_pages + 1):
                # 연속 조회 여부에 따라 tr_cont 설정
                # - 최초 조회: "" (공백)
                # - 다음 데이터 조회: "N" (output header의 tr_cont가 M일 경우)
                headers["tr_cont"] = "" if page == 1 else "N"
                params["CTX_AREA_NK200"] = ctx_nk
                params["CTX_AREA_FK200"] = ctx_fk

                time.sleep(0.05)
                res = requests.get(url, headers=headers, params=params, timeout=8)
                data = self._safe_json_response(res, context=f"주문체결내역[inquire-ccnl]")

                logger.debug(f"[주문체결내역] inquire-ccnl page={page} HTTP {res.status_code} | rt_cd={data.get('rt_cd')} | msg_cd={data.get('msg_cd')} | msg1={data.get('msg1')} | raw={json.dumps(data, ensure_ascii=False)[:3000]}")

                if res.status_code == 200 and data.get("rt_cd") == "0":
                    output = data.get("output", [])
                    if isinstance(output, list):
                        all_output.extend(output)
                    elif isinstance(output, dict):
                        all_output.append(output)

                    # 연속 조회 여부 확인 (응답 헤더의 tr_cont)
                    tr_cont = res.headers.get("tr_cont", "")
                    if tr_cont != "M":
                        break

                    # 다음 페이지를 위한 CTX_AREA_NK200/FK200 값 설정
                    ctx_nk = (data.get("ctx_area_nk200", "") or "").strip()
                    ctx_fk = (data.get("ctx_area_fk200", "") or "").strip()
                    if not ctx_nk and not ctx_fk:
                        break
                else:
                    msg1 = data.get("msg1", "")
                    msg_cd = data.get("msg_cd", "")
                    logger.warning(f"[주문체결내역] inquire-ccnl API 오류: rt_cd={data.get('rt_cd')}, msg_cd={msg_cd}, msg1={msg1}")
                    if "만료된" in msg1 or data.get("msg_cd") == "EGW00123":
                        logger.warning("Token 만료 감지: 주문체결내역 재조회 시도...")
                        self.access_token = None
                        self.token_issued_at = 0
                        if self.get_access_token():
                            return self.get_overseas_order_ccnl(
                                symbol=symbol, start_date=start_date, end_date=end_date,
                                sll_buy_dvsn=sll_buy_dvsn, ccld_nccs_dvsn=ccld_nccs_dvsn, sort_sqn=sort_sqn
                            )
                    break
        except Exception as e:
            logger.warning(f"[주문체결내역] inquire-ccnl 조회 예외: {e}")

        # --- 레코드 정규화 ---
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
            # 주문시각
            ord_tmd = _get_field(item, "ord_tmd", "thco_ord_tmd")
            # 정정/취소구분
            rvse_cncl_dvsn = _get_field(item, "rvse_cncl_dvsn")
            rvse_cncl_dvsn_name = _get_field(item, "rvse_cncl_dvsn_name")
            # 거래시장/국가/거래소/통화
            tr_mket_name = _get_field(item, "tr_mket_name")
            tr_natn_name = _get_field(item, "tr_natn_name")
            ovrs_excg_cd = _get_field(item, "ovrs_excg_cd")
            tr_crcy_cd = _get_field(item, "tr_crcy_cd")
            # 주문지점
            ord_gno_brno = _get_field(item, "ord_gno_brno")
            # 원주문번호
            orgn_odno = _get_field(item, "orgn_odno")
            # 주문수량
            ord_qty = _get_field(item, "ft_ord_qty", "ord_qty")
            # 주문단가
            ord_unpr = _get_field(item, "ft_ord_unpr3", "ft_ord_unpr2", "ft_ord_unpr")
            # 대출유형/일자
            loan_type_cd = _get_field(item, "loan_type_cd")
            loan_dt = _get_field(item, "loan_dt")
            # 매체구분
            mdia_dvsn_name = _get_field(item, "mdia_dvsn_name")
            # 장외연장요청
            usa_amk_exts_rqst_yn = _get_field(item, "usa_amk_exts_rqst_yn")

            # order_type 결정 (매수/매도)
            order_type = sll_buy_name
            if not order_type or order_type == "-":
                if sll_buy in ("01", "1"):
                    order_type = "매도"
                elif sll_buy in ("02", "2"):
                    order_type = "매수"

            # order_time 구성 (ord_dt + ord_tmd)
            fmt_dt = _fmt_date(ord_dt)
            fmt_tmd = ord_tmd
            if len(ord_tmd) == 6 and ord_tmd.isdigit():
                fmt_tmd = f"{ord_tmd[:2]}:{ord_tmd[2:4]}:{ord_tmd[4:6]}"
            order_time = f"{fmt_dt} {fmt_tmd}".strip()

            normalized.append({
                "order_no": odno,
                "symbol": pdno,
                "order_type": order_type,
                "qty": int(float(ord_qty)) if ord_qty and ord_qty.replace('.', '').isdigit() else 0,
                "price": float(ord_unpr) if ord_unpr and ord_unpr.replace('.', '').isdigit() else 0.0,
                "executed_qty": int(float(ccld_qty)) if ccld_qty and ccld_qty.replace('.', '').isdigit() else 0,
                "executed_price": float(ccld_unpr) if ccld_unpr and ccld_unpr.replace('.', '').isdigit() else 0.0,
                "status": status,
                "order_time": order_time,
                "ord_dt": ord_dt,
                "ord_tmd": ord_tmd,
                "ord_gno_brno": ord_gno_brno,
                "orgn_odno": orgn_odno,
                "prdt_name": prdt_name,
                "sll_buy_dvsn_cd": sll_buy,
                "rvse_cncl_dvsn": rvse_cncl_dvsn,
                "rvse_cncl_dvsn_name": rvse_cncl_dvsn_name,
                "ft_ccld_amt3": ccld_amt,
                "nccs_qty": nccs_qty,
                "rjct_rson": rjct_rson_name,
                "rjct_rson_name": rjct_rson_name,
                "tr_mket_name": tr_mket_name,
                "tr_natn_name": tr_natn_name,
                "ovrs_excg_cd": ovrs_excg_cd,
                "tr_crcy_cd": tr_crcy_cd,
                "dmst_ord_dt": ord_dt,
                "thco_ord_tmd": ord_tmd,
                "loan_type_cd": loan_type_cd,
                "loan_dt": loan_dt,
                "mdia_dvsn_name": mdia_dvsn_name,
                "usa_amk_exts_rqst_yn": usa_amk_exts_rqst_yn
            })

        logger.info(f"[주문체결내역] inquire-ccnl 조회 완료: {len(normalized)}건 (symbol={symbol or '전체'}, 기간={start_date}~{end_date})")
        return normalized
