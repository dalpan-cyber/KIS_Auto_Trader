# 🇺🇸 한국투자증권 KIS 라오어 무한매수법 무인 자동투자 시스템

한국투자증권 **KIS Developers Open Trading API**와 **GitHub Actions**, **Streamlit Cloud**, **Google Sheets**를 연동하여 컴퓨터를 켜둘 필요 없이 24시간 365일 무인으로 운영되는 **라오어 무한매수법 v2.0 전담 자동 매매 시스템**입니다.

> 📖 **처음 시작하시나요?**  
> GitHub Actions 무인 자동매매 및 Streamlit 웹 대시보드 구축 방법은 **[👉 무인 자동매매 구축 상세 가이드 (SETUP_GUIDE.md)](./SETUP_GUIDE.md)**를 참고하세요!

---

## 📌 주요 특징 및 장점

1. **HTS 및 Windows 제약 탈피 (REST API 연동)**
   - 별도의 HTS(e-Friend Expert) 프로그램이나 ActiveX/OCX 설치가 **필요 없습니다**.
   - Windows 뿐만 아니라 **macOS, Linux, Docker, AWS 클라우드 서버**에서 24시간 안정적으로 구동이 가능합니다.
   - OAuth 2.0 토큰 기반 인증 및 초당 API 호출 제한(Rate Limiter)을 안전하게 자동 처리합니다.

2. **모듈화된 매매 전략 엔진 ([`strategy.py`](./strategy.py))**
   - **이동평균선 교차 전략 (MA Crossover)**: 5일선-20일선 골든크로스 매수 / 데드크로스 매도.
   - **변동성 돌파 전략 (Volatility Breakout)**: Larry Williams 변동성 K-factor 돌파 매수.
   - 새로운 커스텀 기술 지표 및 알고리즘 전략을 손쉽게 확장 가능.

3. **철저한 리스크 및 자금 관리 ([`risk_manager.py`](./risk_manager.py))**
   - **손절매 (Stop Loss)**: 설정한 손실 비율(기본 -3%) 도달 시 즉시 시장가 매도.
   - **익절매 (Take Profit)**: 목표 수익률(기본 +7%) 달성 시 익절 매도.
   - **트레일링 스탑 (Trailing Stop)**: 최고점 대비 설정 비율(기본 -2%) 하락 시 수익 보전 매도.
   - **서킷브레이커**: 연속 주문/API 에러 발생 시 자동 안전 거래 정지.

4. **Streamlit 통합 웹 대시보드 ([`app.py`](./app.py))**
   - 국내 자산/포트폴리오, 포지션·리스크 관리, 종가 스크리닝, 백테스트, 무한매수(미국) 관제 화면.
   - 앱 실행 시 백그라운드 스케줄러(09:00 손절 감시 / 장중 5분 감시 / 15:10 스크리닝 / 15:15 매수 / 15:30 정산)가 함께 구동됩니다.
   - AppKey 미입력 + 모의투자 모드에서는 안전하게 작동하는 **시뮬레이션 모드** 지원.

---

## 🛠️ 파일 구성

| 파일명 | 역할 |
|---|---|
| [`app.py`](./app.py) | Streamlit 통합 웹 대시보드 (국내 퀀트 + 미국 무한매수) 및 백그라운드 스케줄러 구동 |
| [`config.py`](./config.py) | 무한매수(해외) 설정 입구 — `core/config/common.py` + `core/config/infinite.py` (`infinite_settings.json`) |
| [`app_config.py`](./app_config.py) | 국내 퀀트 설정 입구 — `core/config/common.py` + `core/config/domestic.py` (`settings.json`) |
| [`kis_api.py`](./kis_api.py) | 한국투자증권 REST API 연동 (OAuth2 토큰, 국내/해외 시세·잔고·주문·체결내역) |
| [`screener.py`](./screener.py) / [`scheduler.py`](./scheduler.py) | 국내 종가 매수 스크리닝·매도 신호 엔진 / 5단계 일일 타임라인 스케줄러 |
| [`core/strategy/`](./core/strategy/) | 국내 매매 전략 (모멘텀, 52주 신저가 반등, 월봉 GTAA, 컵앤핸들) |
| [`strategy.py`](./strategy.py) / [`trader.py`](./trader.py) | 라오어 무한매수 전략 / 무한매수 트레이딩 엔진 |
| [`run_infinite_buying.py`](./run_infinite_buying.py) | GitHub Actions 무인 실행용 무한매수 CLI |
| [`risk_manager.py`](./risk_manager.py) | 손절/익절/트레일링 스탑, 자금 관리 및 서킷브레이커 |
| [`tests/`](./tests/) | 단위 테스트 (pytest, 외부 연동 자동 차단) |
| [`scripts/`](./scripts/) | 실제 KIS API를 호출하는 수동 점검 스크립트 (CI에서 실행하지 않음) |
| [`docs/`](./docs/) | 무한매수 구축 가이드 (PDF/HTML) |

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
pip install -r requirements.txt
```

---

### 3. 환경 설정 (`.env` / 환경변수 / Streamlit Secrets)

KIS API 인증 정보는 코드에 직접 쓰지 않고 **환경변수 → Streamlit Secrets → 프로젝트 루트 `.env`** 순으로 읽습니다 ([`core/config/common.py`](./core/config/common.py)). `.env`는 `.gitignore`에 포함되어 커밋되지 않습니다.

```ini
# .env
KIS_APP_KEY=발급받은_AppKey
KIS_APP_SECRET=발급받은_AppSecret
KIS_CANO=12345678          # 계좌번호 앞 8자리
KIS_ACNT_PRDT_CD=01        # 계좌상품코드 (주식 기본 01)

# (선택) 지정 시 settings.json의 mock_trading보다 우선 (true: 모의투자 서버)
# MOCK_TRADING_ONLY=true

# (선택) 텔레그램 알림
# TELEGRAM_BOT_TOKEN=...
# TELEGRAM_CHAT_ID=...
```

매매 대상·전략·리스크 파라미터는 대시보드 설정 화면에서 변경하며 `settings.json`(국내) / `infinite_settings.json`(무한매수)과 구글 시트에 저장됩니다.

---

### 4. 프로그램 실행

다음 명령어로 Streamlit 대시보드를 실행합니다:

```cmd
streamlit run app.py
```

* 모의/실전 모드는 설정 화면의 "모의투자 모드" 토글(`settings.json`의 `mock_trading`)을 따르며, 환경변수 `MOCK_TRADING_ONLY`가 지정되면 그 값이 우선합니다. 사이드바 배지에 실제 주문이 나가는 모드가 표시됩니다.
* 로그는 콘솔과 `logs/kis_auto_trader.log`(UTF-8, 5MB x 5개 회전)에 기록됩니다. `LOG_TO_FILE=false`로 파일 기록을 끌 수 있습니다.

---

### 5. 테스트 실행

```cmd
pip install -r requirements-dev.txt
pytest
```

* `tests/conftest.py`가 KIS API 키·구글 시트·텔레그램 연동을 차단하고, 상태 JSON 파일을 임시 디렉터리로 격리하므로 실제 계좌나 시트에 영향을 주지 않습니다.
* `scripts/`의 점검 스크립트는 실제 API를 호출하므로 필요할 때만 수동으로 실행하세요 (예: `python scripts/check_ctos4001r_single.py`).
