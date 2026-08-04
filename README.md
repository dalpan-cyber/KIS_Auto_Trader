# 한국투자증권 KIS Open Trading API 자동 투자 프로그램 (Auto Trading Engine)

한국투자증권 **KIS Developers Open Trading API** (REST API / WebSocket) 규격을 준수하여 구현된 **Python 기반 주식 자동 투자 시스템**입니다.

---

## 📌 주요 특징 및 장점

1. **HTS 및 Windows 제약 탈피 (REST API 연동)**
   - 별도의 HTS(e-Friend Expert) 프로그램이나 ActiveX/OCX 설치가 **필요 없습니다**.
   - Windows 뿐만 아니라 **macOS, Linux, Docker, AWS 클라우드 서버**에서 24시간 안정적으로 구동이 가능합니다.
   - OAuth 2.0 토큰 기반 인증 및 초당 API 호출 제한(Rate Limiter)을 안전하게 자동 처리합니다.

2. **모듈화된 매매 전략 엔진 ([`strategy.py`](file:///C:/KIS_Auto_Trader/strategy.py))**
   - **이동평균선 교차 전략 (MA Crossover)**: 5일선-20일선 골든크로스 매수 / 데드크로스 매도.
   - **변동성 돌파 전략 (Volatility Breakout)**: Larry Williams 변동성 K-factor 돌파 매수.
   - 새로운 커스텀 기술 지표 및 알고리즘 전략을 손쉽게 확장 가능.

3. **철저한 리스크 및 자금 관리 ([`risk_manager.py`](file:///C:/KIS_Auto_Trader/risk_manager.py))**
   - **손절매 (Stop Loss)**: 설정한 손실 비율(기본 -3%) 도달 시 즉시 시장가 매도.
   - **익절매 (Take Profit)**: 목표 수익률(기본 +7%) 달성 시 익절 매도.
   - **트레일링 스탑 (Trailing Stop)**: 최고점 대비 설정 비율(기본 -2%) 하락 시 수익 보전 매도.
   - **서킷브레이커**: 연속 주문/API 에러 발생 시 자동 안전 거래 정지.

4. **PyQt5 모던 대시보드 UI ([`gui.py`](file:///C:/KIS_Auto_Trader/gui.py))**
   - 실시간 예수금, 총 자산, 보유 종목 평가손익(PnL %) 시각화.
   - 자동 매매 시작/정지 제어 및 실시간 런타임 이벤트 로그 스트리밍.
   - AppKey 미입력 시에도 안전하게 작동하는 **시뮬레이션 모드** 지원.

---

## 🛠️ 파일 구성

| 파일명 | 역할 |
|---|---|
| [`config.py`](file:///C:/KIS_Auto_Trader/config.py) | KIS AppKey/AppSecret, 계좌번호, 매매 대상 종목, 전략 및 리스크 파라미터 설정 |
| [`kis_api.py`](file:///C:/KIS_Auto_Trader/kis_api.py) | 한국투자증권 REST API 연동 (OAuth2 토큰, 시세/일봉 조회, 잔고 조회, 현금 주문) |
| [`strategy.py`](file:///C:/KIS_Auto_Trader/strategy.py) | 매매 전략 알고리즘 (이동평균 교차, 변동성 돌파 등) |
| [`risk_manager.py`](file:///C:/KIS_Auto_Trader/risk_manager.py) | 손절/익절/트레일링 스탑, 자금 관리 및 서킷브레이커 |
| [`trader.py`](file:///C:/KIS_Auto_Trader/trader.py) | 시세 수신, 전략 평가, 주문 발주를 총괄하는 메인 트레이딩 엔진 |
| [`gui.py`](file:///C:/KIS_Auto_Trader/gui.py) | PyQt5 기반 트레이딩 대시보드 UI 및 실행 스크립트 |
| [`test_strategy.py`](file:///C:/KIS_Auto_Trader/test_strategy.py) | 매매 전략 단위 테스트 |
| [`test_risk_manager.py`](file:///C:/KIS_Auto_Trader/test_risk_manager.py) | 리스크 관리 및 자금 계산 단위 테스트 |

---

## 🚀 시작 가이드

### 1. KIS Developers AppKey / AppSecret 발급

1. [한국투자증권 KIS Developers 포털](https://apiportal.koreainvestment.com/)에 가입합니다.
2. **오픈API 신청** 메뉴에서 계좌 연동 및 **앱 등록(AppKey & AppSecret 발급)**을 진행합니다.
   - **모의투자용**: 테스트용 계좌번호(8자리)와 AppKey/AppSecret 발급
   - **실전투자용**: 실제 종합계좌(8자리)와 AppKey/AppSecret 발급

### 2. 의존성 패키지 설치

필요한 파이썬 패키지를 설치합니다:

```cmd
pip install requests pandas numpy pyqt5
```

---

### 3. 환경 설정 ([`config.py`](file:///C:/KIS_Auto_Trader/config.py))

[`config.py`](file:///C:/KIS_Auto_Trader/config.py) 파일에 발급받은 KIS API 정보를 입력하거나 환경변수로 설정합니다:

```python
# KIS API 인증 및 계좌 정보
APP_KEY = "발급받은_AppKey"
APP_SECRET = "발급받은_AppSecret"
CANO = "12345678"          # 계좌번호 앞 8자리
ACNT_PRDT_CD = "01"        # 계좌상품코드 (주식 기본 01)

# 안전 모드 설정 (True: 모의투자 서버, False: 실전투자 서버)
MOCK_TRADING_ONLY = True

# 매매 대상 종목 (6자리 주식코드)
TARGET_STOCKS = ["005930", "000660", "035420"]
```

---

### 4. 프로그램 실행

다음 명령어로 PyQt5 트레이딩 대시보드를 실행합니다:

```cmd
python gui.py
```

* AppKey가 비어있어도 **안전한 시뮬레이션 모드**로 구동되어 UI 및 매매 루프 동작을 바로 테스트할 수 있습니다.
* `▶ 자동매매 시작` 버튼 클릭 시 5초 주기로 종목 시세 조회 및 매매 전략 평가가 실행됩니다.
