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

        # 저장된 기존 토큰 파일 로드 시도
        self._load_token_file()

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
            data = res.json()

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
                data = res.json()
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
            data = res.json()

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
            data = res.json()

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
            data = res.json()

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
            data = res.json()

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
                data = res.json()

                if res.status_code == 200 and data.get("rt_cd") == "0":
                    output = data.get("output", {})
                    last_str = str(output.get("last", "")).strip()
                    if last_str and last_str != "0":
                        last_price = float(last_str)
                        diff_val = float(output.get("diff", 0) or 0)
                        rate_val = float(output.get("rate", 0) or 0)
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
                data = res.json()

                if res.status_code == 200 and data.get("rt_cd") == "0":
                    raw_output = data.get("output2", data.get("output", []))
                    if raw_output:
                        results = []
                        for item in raw_output[:count]:
                            c_val = float(item.get("clos", item.get("last", 0)) or 0)
                            if c_val > 0:
                                results.append({
                                    "date": item.get("ksam_date", item.get("date", "")),
                                    "close": c_val,
                                    "open": float(item.get("open", 0) or 0),
                                    "high": float(item.get("high", 0) or 0),
                                    "low": float(item.get("low", 0) or 0),
                                    "volume": int(item.get("tvol", item.get("voum", 0)) or 0)
                                })
                        if results:
                            return results
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
            data = res.json()

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

        # 여러 거래소(NAS/NYS/AMS)를 순회하며 보유 종목 통합 조회
        # KIS API 거래소 코드: NAS=나스닥, NYS=뉴욕, AMS=아멕스
        # (NMS/NYQ는 NAS/NYS의 대체 코드로, 별도 조회 시 중복 데이터만 발생하므로 제외)
        exchanges = ["NAS", "NYS", "AMS"]
        all_holdings = []
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
                    data = res.json()

                    logger.info(f"[해외잔고] [{exch}] HTTP {res.status_code} | rt_cd={data.get('rt_cd')} | msg1={data.get('msg1')} | msg_cd={data.get('msg_cd')}")

                    if res.status_code == 200 and data.get("rt_cd") == "0":
                        output1 = data.get("output1", [])
                        logger.info(f"[해외잔고] [{exch}] output1 항목 수: {len(output1)}")
                        if output1:
                            logger.info(f"[해외잔고] [{exch}] output1 첫 항목 원본: {json.dumps(output1[0], ensure_ascii=False)[:500]}")
                            logger.info(f"[해외잔고] [{exch}] output1 전체 키 목록: {list(output1[0].keys()) if output1 else []}")

                        for item in output1:
                            # 디버깅: 원본 아이템의 모든 키와 값 로깅
                            logger.info(f"[해외잔고] [{exch}] 원본 아이템: {json.dumps(item, ensure_ascii=False)[:500]}")

                            # 수량 필드 디버깅 - 여러 가능한 필드명 확인
                            qty_raw = item.get("ovrs_cblc_qty", item.get("ovrs_ccls_qty", item.get("ccls_qty", item.get("hldg_qty", item.get("ovrs_hldg_qty", 0)))))
                            logger.info(f"[해외잔고] [{exch}] 수량 필드 확인: ovrs_cblc_qty={item.get('ovrs_cblc_qty')}, ovrs_ccls_qty={item.get('ovrs_ccls_qty')}, ccls_qty={item.get('ccls_qty')}, hldg_qty={item.get('hldg_qty')}, ovrs_hldg_qty={item.get('ovrs_hldg_qty')}")

                            qty = int(float(qty_raw or 0))
                            if qty <= 0:
                                logger.info(f"[해외잔고] [{exch}] 수량 0 이하로 스킵: pdno={item.get('pdno')}, ovrs_pdno={item.get('ovrs_pdno')}, symb={item.get('symb')}, qty_raw={qty_raw}")
                                continue

                            code = item.get("ovrs_pdno", item.get("pdno", item.get("symb", ""))).strip().upper()
                            if not code:
                                logger.info(f"[해외잔고] [{exch}] 종목코드 없음으로 스킵: item={json.dumps(item, ensure_ascii=False)[:300]}")
                                continue

                            name = item.get("ovrs_item_name", item.get("item_name", item.get("prdt_name", code)))
                            avg_p = float(item.get("pchs_avg_pric", item.get("avg_pric", 0.0)) or 0.0)
                            cur_p = float(item.get("now_pric2", item.get("last_prik", 0.0)) or 0.0)
                            pnl_rate = float(item.get("evlu_pfls_rt", item.get("pfls_rt", 0.0)) or 0.0)

                            logger.info(f"[해외잔고] [{exch}] 보유 종목 파싱: code={code}, name={name}, qty={qty}, avg_p={avg_p}, cur_p={cur_p}, pnl_rate={pnl_rate}")

                            holding_item = {
                                "code": code,
                                "name": name,
                                "qty": qty,
                                "avg_price": avg_p,
                                "current_price": cur_p,
                                "pnl_rate": pnl_rate
                            }
                            all_holdings.append(holding_item)
                            exch_holdings.append(holding_item)

                        # 다음 페이지 확인
                        ctx_fk = (data.get("ctx_area_fk200", "") or "").strip()
                        ctx_nk = (data.get("ctx_area_nk200", "") or "").strip()
                        logger.info(f"[해외잔고] [{exch}] 페이지 컨텍스트: ctx_fk={ctx_fk}, ctx_nk={ctx_nk}")
                        if not ctx_fk and not ctx_nk:
                            logger.info(f"[해외잔고] [{exch}] 페이지 컨텍스트가 비어있어 페이지네이션 종료")
                            break
                    else:
                        msg1 = data.get("msg1", "")
                        logger.warning(f"[해외잔고] [{exch}] API 오류: rt_cd={data.get('rt_cd')}, msg1={msg1}, msg_cd={data.get('msg_cd')}, 전체 응답: {json.dumps(data, ensure_ascii=False)[:500]}")
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

        # 시세 조회 코드를 해외주식 주문 전용 거래소 코드로 자동 변환 (NAS->NASD, NYS->NYSE, AMS->AMEX)
        exchange_map = {
            "NAS": "NASD",
            "NYS": "NYSE",
            "AMS": "AMEX",
            "NASD": "NASD",
            "NYSE": "NYSE",
            "AMEX": "AMEX"
        }
        ovrs_excg_cd = exchange_map.get(exchange.upper(), "NASD")

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
            data = res.json()

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
        해외주식 체결/미체결 이력 조회 (VTTS3035R: 모의 / TTTS3035R: 실전)
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
        params = {
            "CANO": self.cano,
            "ACNT_PRDT_CD": self.acnt_prdt_cd,
            "PDNO": symbol.upper() if symbol else "%",
            "ORD_STRT_DT": start_date,
            "ORD_END_DT": end_date,
            "SVR_DVSN_CD": "0",
            "CCNL_DVSN": "00",
            "ORD_GDS_DVSN": "00",
            "CTX_AREA_FK200": "",
            "CTX_AREA_NK200": ""
        }

        try:
            results = []
            ctx_fk = ""
            ctx_nk = ""
            max_pages = 5  # 최대 5페이지까지 조회 (안전장치)

            logger.info(f"[체결이력] API 호출: tr_id={tr_id}, start_date={start_date}, end_date={end_date}, symbol={symbol or '%'}")

            for _ in range(max_pages):
                params["CTX_AREA_FK200"] = ctx_fk
                params["CTX_AREA_NK200"] = ctx_nk

                self._rate_limit()
                res = requests.get(url, headers=headers, params=params, timeout=10)
                data = res.json()

                logger.info(f"[체결이력] HTTP {res.status_code} | rt_cd={data.get('rt_cd')} | msg1={data.get('msg1')} | msg_cd={data.get('msg_cd')}")

                if res.status_code == 200 and data.get("rt_cd") == "0":
                    output = data.get("output", [])
                    logger.info(f"[체결이력] output 항목 수: {len(output)}")
                    if output:
                        logger.info(f"[체결이력] output 첫 항목 원본: {json.dumps(output[0], ensure_ascii=False)[:500]}")
                        logger.info(f"[체결이력] output 전체 키 목록: {list(output[0].keys()) if output else []}")

                    for item in output:
                        logger.info(f"[체결이력] 원본 아이템: {json.dumps(item, ensure_ascii=False)[:500]}")
                        results.append({
                            "order_no": item.get("odno", ""),
                            "symbol": item.get("pdno", ""),
                            "order_type": item.get("sll_buy_dvsn_cd_name", ""),
                            "qty": int(item.get("ft_ord_qty", 0) or 0),
                            "price": float(item.get("ft_ord_unpr3", 0.0) or 0.0),
                            "executed_qty": int(item.get("ft_ccnl_qty", 0) or 0),
                            "executed_price": float(item.get("ft_ccnl_unpr3", 0.0) or 0.0),
                            "status": item.get("prcs_stat_name", ""),
                            "order_time": item.get("ord_dt", "") + " " + item.get("ord_tmd", "")
                        })

                    # 다음 페이지 여부 확인
                    ctx_fk = (data.get("ctx_area_fk200", "") or "").strip()
                    ctx_nk = (data.get("ctx_area_nk200", "") or "").strip()
                    logger.info(f"[체결이력] 페이지 컨텍스트: ctx_fk={ctx_fk}, ctx_nk={ctx_nk}")
                    if not ctx_fk and not ctx_nk:
                        logger.info(f"[체결이력] 페이지 컨텍스트가 비어있어 페이지네이션 종료")
                        break
                else:
                    msg1 = data.get("msg1", "")
                    logger.warning(f"[체결이력] API 오류: rt_cd={data.get('rt_cd')}, msg1={msg1}, msg_cd={data.get('msg_cd')}, 전체 응답: {json.dumps(data, ensure_ascii=False)[:500]}")
                    if "만료된" in msg1 or data.get("msg_cd") == "EGW00123":
                        logger.warning("Token 만료 감지: 해외 체결내역 재조회 시도...")
                        self.access_token = None
                        self.token_issued_at = 0
                        if self.get_access_token():
                            return self.get_overseas_execution_history(symbol=symbol, start_date=start_date, end_date=end_date)
                    logger.debug(f"해외주식 체결내역 조회 실패: {msg1}")
                    break

            logger.info(f"[체결이력] 최종 결과: {len(results)}건")
            return results
        except Exception as e:
            logger.error(f"해외주식 체결내역 조회 예외 발생: {e}")
            return []

