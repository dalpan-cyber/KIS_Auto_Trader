# 🚀 KIS 라오어 무한매수법 무인 자동매매 & Streamlit 대시보드 구축 가이드

본 문서는 **한국투자증권(KIS) Open API**와 **GitHub Actions**, **Streamlit Cloud**, **Google Sheets**를 연동하여 컴퓨터를 켜두지 않고도 24시간 365일 무인으로 운영되는 **라오어 무한매수법 v2.0 자동투자 시스템**을 구축하는 전체 매뉴얼입니다.

---

## 📋 전체 구축 순서 요약

```mermaid
graph TD
    A[1. GitHub 저장소 Fork/Clone] --> B[2. 한국투자증권 Open API 신청]
    B --> C[3. 구글 스프레드시트 & GCP 서비스 계정 생성]
    C --> D[4. GitHub Secrets & Actions 권한 설정]
    D --> E[5. Streamlit Cloud 웹 대시보드 배포]
    E --> F[6. 동작 검증 및 운영]
```

---

## 1단계: GitHub 저장소 가져오기 (Fork)

1. 본 GitHub 저장소 우측 상단의 **`Fork`** 버튼을 클릭하여 본인의 GitHub 계정으로 저장소를 복제합니다.
2. 본인 계정의 저장소명(예: `https://github.com/<본인-아이디>/KIS_Auto_Trader`)으로 생성된 것을 확인합니다.

---

## 2단계: 한국투자증권 KIS Open API 및 해외주식 거래 준비

### 1) KIS Developers 오픈API 신청 및 키 발급
1. [한국투자증권 KIS Developers 포털](https://apiportal.koreainvestment.com/)에 접속하여 로그인합니다.
2. 상단 메뉴의 **[오픈API 신청]** > **[앱 등록/관리]**로 이동합니다.
3. 실전투자 계좌를 선택하고 앱을 등록하여 **`AppKey`**와 **`AppSecret`**을 발급받아 안전한 곳에 복사해 둡니다.

### 2) 해외주식 및 3배 레버리지 ETF 거래 신청 필수 사항 (MTS/HTS)
> [!IMPORTANT]
> 무한매수법 대상 종목(TQQQ, SOXL 등)을 매매하려면 증권사 계좌에 다음 설정이 완료되어 있어야 주문 거절이 발생하지 않습니다.
1. **해외주식 거래 신청**: MTS > 해외주식 거래 서비스 신청
2. **해외 ETF 거래 신청 & 기본예탁금 등록**: MTS > 해외 ETF 거래 신청
3. **레버리지 ETF 교육 이수**: [금융투자교육원](https://www.kifin.or.kr) '레버리지 ETP(ETF/ETN) 가이드' 이수 후 수료증 번호를 한국투자증권에 등록

---

## 3단계: 구글 스프레드시트 & GCP 서비스 계정 생성

매매 일지 자동 기록 및 설정값 동기화를 위해 Google Sheets API를 연동합니다.

### 1) 구글 스프레드시트 생성
1. [Google Drive](https://drive.google.com/)에 접속하여 새 스프레드시트를 생성합니다.
2. 스프레드시트 제목을 반드시 **`KIS_무한매수_매매일지`**로 설정합니다.
3. 하단 탭에 다음 **2개 시트(탭)**를 준비합니다:
   - `CompletedTrades` (익절 완료 매매 기록용)
   - `Settings` (설정 동기화용)

### 2) Google Cloud Platform(GCP) 서비스 계정 키 발급
1. [Google Cloud Console](https://console.cloud.google.com/)에 접속하여 새 프로젝트를 생성합니다.
2. **[API 및 서비스] > [라이브러리]**에서 다음 2개 API를 검색하여 **사용(활성화)**을 누릅니다:
   - **Google Drive API**
   - **Google Sheets API**
3. **[API 및 서비스] > [사용자 인증 정보]** > **[사용자 인증 정보 만들기]** > **[서비스 계정]**을 클릭합니다.
4. 서비스 계정 이름(예: `kis-sheets-bot`)을 입력하고 생성을 완료합니다.
5. 생성된 서비스 계정을 클릭 > **[키(Keys)] 탭** > **[키 추가]** > **[새 키 만들기]** > **JSON** 선택 후 다운로드합니다.
   - *다운로드된 JSON 파일의 전체 텍스트를 메모장 등으로 열어 보관합니다.*
6. JSON 파일 내의 `client_email` 값 (예: `kis-sheets-bot@xxxx.iam.gserviceaccount.com`)을 복사합니다.
7. 앞서 만든 **구글 스프레드시트(`KIS_무한매수_매매일지`)**의 우측 상단 **[공유]** 버튼을 누르고, 복사한 서비스 계정 이메일을 **`편집자`** 권한으로 추가합니다.

---

## 4단계: GitHub Actions 무인 자동매매 설정 (GitHub Secrets)

GitHub Actions가 자동으로 매일 밤 주문을 넣을 수 있도록 비밀키와 권한을 등록합니다.

### 1) GitHub Actions Workflow 권한 설정 (필수)
진행 회차 상태(`infinite_trader_state.json`)를 GitHub에 자동 커밋하기 위해 필요합니다.
1. 본인의 GitHub 저장소 > **[Settings]** > **[Actions]** > **[General]**로 이동합니다.
2. 화면 하단의 **`Workflow permissions`** 섹션에서 **`Read and write permissions`**를 선택하고 **Save**를 클릭합니다.

### 2) Repository Secrets 등록
본인의 GitHub 저장소 > **[Settings]** > **[Secrets and variables]** > **[Actions]** > **[New repository secret]**을 클릭하여 아래 항목들을 각각 추가합니다:

| Secret 이름 | 설명 | 예시 값 |
|---|---|---|
| `KIS_APP_KEY` | 한국투자증권에서 발급받은 AppKey | `PSxxxx...` |
| `KIS_APP_SECRET` | 한국투자증권에서 발급받은 AppSecret | `xxxx...` |
| `KIS_CANO` | 종합계좌번호 앞 8자리 | `12345678` |
| `KIS_ACNT_PRDT_CD` | 계좌상품코드 2자리 (주식 보통 01) | `01` |
| `KIS_ACCOUNT_PWD` | 계좌 비밀번호 (4자리) | `1234` |
| `GCP_SERVICE_ACCOUNT_JSON` | GCP 서비스 계정 JSON 파일의 전체 내용 | `{"type": "service_account", ...}` |

> [!TIP]
> `GCP_SERVICE_ACCOUNT_JSON`에는 다운로드받은 JSON 파일의 내용을 첫 글자 `{`부터 마지막 `}`까지 그대로 복사해서 붙여넣으시면 됩니다.

---

## 5단계: Streamlit Cloud 웹 대시보드 배포 (모바일/PC 관제)

핸드폰이나 PC 브라우저에서 실시간 잔고와 차트를 확인하고 파라미터를 변경할 수 있는 대시보드를 무료로 배포합니다.

### 1) Streamlit Community Cloud 배포
1. [share.streamlit.io](https://share.streamlit.io/)에 접속하여 GitHub 계정으로 로그인합니다.
2. 우측 상단의 **[Create app]** 버튼을 클릭합니다.
3. 다음 정보를 선택/입력합니다:
   - **Repository**: 본인의 Fork 저장소 (예: `<본인아이디>/KIS_Auto_Trader`)
   - **Branch**: `main`
   - **Main file path**: `app.py`
4. **[Advanced settings...]**를 클릭합니다.

### 2) Streamlit Secrets (환경변수) 등록
Advanced settings의 **Secrets** 텍스트 상자에 아래 형식(`TOML` 형식)으로 값을 입력합니다:

```toml
KIS_APP_KEY = "발급받은_AppKey"
KIS_APP_SECRET = "발급받은_AppSecret"
KIS_CANO = "12345678"
KIS_ACNT_PRDT_CD = "01"
KIS_ACCOUNT_PWD = "계좌비밀번호4자리"
MOCK_TRADING_ONLY = "false"

# GCP 서비스 계정 JSON (문자열 또는 인라인 JSON)
GCP_SERVICE_ACCOUNT_JSON = '''
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n",
  "client_email": "kis-sheets-bot@your-project-id.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
'''
```

5. **[Deploy!]** 버튼을 클릭합니다. 1~2분 내에 대시보드가 정상 빌드되고 URL이 생성됩니다.

---

## 6단계: 무인 자동매매 스케줄 및 동작 검증

### 1) 자동 실행 스케줄 (KST 기준)
* **21:59 (월~금)**: 미국 장 개장 전 당일 **LOC 매수 2건 + 지정가 익절 매도 1건** 자동 발주
* **05:12 (화~토)**: 장 마감 후 체결 내역 조회 및 회차 진행/익절 완료 판정 후 상태 갱신

### 2) 수동 즉시 실행 테스트 (GitHub Actions)
설정이 올바른지 즉시 확인해볼 수 있습니다:
1. 본인 GitHub 저장소 > **[Actions]** 탭으로 이동합니다.
2. 좌측 목록에서 **`🇺🇸 KIS 라오어 무한매수법 무인 자동매매`** 워크플로우를 선택합니다.
3. 우측의 **[Run workflow]** 드롭다운 버튼을 누르고 **[Run workflow]**를 클릭합니다.
4. 실행 로그를 클릭하여 `run_infinite_buying.py`가 에러 없이 잔고 조회 및 주문 생성을 완료하는지 확인합니다.

---

## ⚙️ 대시보드 주요 기능 활용법

1. **📊 무한매수 현황 & 당일 주문**
   - 현재 진행 회차, 평단가, 평가 손익, 당일 주문 제안을 한눈에 확인
   - 장중에 원할 경우 수동 즉시 주문 실행 가능
2. **⚙️ 무한매수 설정**
   - 대상 종목(TQQQ, SOXL 등), 예산, 분할 횟수, 익절 목표 수익률(+10%) 변경
   - **40회차 소진 시 대응 모드 선택**:
     - `1. 무한 대기 (HOLD)`: 추가 매수 중단, +10% 익절 매도 유지
     - `2. 쿼터 순환 (REBALANCE_QUARTER)`: 1회차 매도 + LOC 재매수로 평단가 인하
     - `3. 목표가 하향 (LOWER_TARGET)`: 탈출 목표 수익률(+5%)로 자동 하향
   - 변경 후 **[설정 적용]**을 누르면 구글 시트와 GitHub 저장소에 자동 동기화됩니다.
