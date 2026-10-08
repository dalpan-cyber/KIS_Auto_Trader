# 🌐 KIS 라오어 무한매수 자동매매 시스템 아키텍처 & 동작 원리

본 문서는 **Local PC, GitHub (Actions & Repo), cron-job.org, Streamlit Cloud (share.streamlit.io), Google Sheets**로 구성된 24시간 365일 무인 자동매매 에코시스템의 세부 역할과 데이터 흐름을 설명합니다.

---

## 1. 시스템 전체 구성도 (High-Level Architecture)

```mermaid
flowchart TD
    subgraph Schedulers ["⏰ 정밀 스케줄링"]
        CJ["cron-job.org<br/>(외부 정밀 웹 크론)"]
    end

    subgraph GitHubEnv ["🐙 GitHub 클라우드"]
        Repo["GitHub Repository<br/>(코드 + infinite_trader_state.json)"]
        GHA["GitHub Actions Runner<br/>(run_infinite_buying.py)"]
    end

    subgraph Brokerage ["🏛️ 증권사 서버"]
        KIS["한국투자증권 (KIS Open API)<br/>실전 계좌 주문 & 체결"]
    end

    subgraph Monitoring ["📱 관제 및 데이터 싱크"]
        ST["Streamlit Community Cloud<br/>(share.streamlit.io - app.py)"]
        GS["Google Sheets<br/>(KIS_무한매수_매매일지)"]
    end

    subgraph Developer ["💻 개발자 / 로컬"]
        PC["Local PC<br/>(코드 개발 & Git push)"]
    end

    %% 연결 관계
    PC -->|"코드 및 설정 push"| Repo
    CJ -->|"1. 정시 Webhook 트리거 (22:35 / 06:05)"| GHA
    Repo <-->|"2. 코드 checkout & State 자동 커밋/push"| GHA
    GHA -->|"3. LOC 매수 / 지정가 매도 / 체결조회"| KIS
    GHA -->|"4. 체결이력 & 회차 백업"| GS

    Repo -->|"코드 자동 배포"| ST
    ST <-->|"실시간 계좌 잔고 및 호가 조회"| KIS
    ST <-->|"설정값 및 완료일지 동기화"| GS
```

---

## 2. 5대 핵심 구성 요소별 역할 및 책임 (R&R)

| 구성 요소 | 위치 / 인프라 | 주요 역할 및 담당 업무 |
| :--- | :--- | :--- |
| **1. Local PC** | 사용자 개인 컴퓨터 | - 소스코드 개발, 디버깅, 백테스트 및 알고리즘 유지보수<br>- Git을 통한 GitHub 원격 저장소로 코드 `git push`<br>- 평상시에는 전원을 꺼두어도 전체 시스템 운영에 아무런 영향 없음 |
| **2. cron-job.org** | 무료 외부 웹 크론 서비스 | - **초 단위 정밀 스케줄링 트리거 담당**<br>- **밤 22:35** (장 개장 직후 주문 발주) 및 **아침 06:05** (장 마감 직후 정산)에 GitHub API(`workflow_dispatch`)를 정확한 시간에 호출<br>- GitHub 내장 cron의 지연(5분~30분 딜레이)을 원천 차단 |
| **3. GitHub (Repo & Actions)** | GitHub 클라우드 | - **중앙 소스 저장소**: 최신 코드 및 상태 파일(`infinite_trader_state.json`, `infinite_settings.json`) 저장<br>- **무인 실행 엔진 (Actions)**: `run_infinite_buying.py`를 실행하여 증권사로 주문 전송<br>- **상태 자동 영속화**: 주문/정산 완료 후 변경된 회차를 Git 저장소로 자동 커밋 & 푸시 |
| **4. Streamlit Cloud** | `share.streamlit.io` | - **24시간 웹/모바일 실시간 관제탑 (Dashboard)**<br>- 모바일 브라우저로 실시간 KIS 잔고, 보유 종목, 현재 진행 회차, 평단가 확인<br>- 종목별 예산, 40분할 회차, 목표 수익률, 40회차 소진 시 옵션 실시간 설정 |
| **5. Google Sheets** | Google Cloud (Drive/Sheets) | - **영구 매매일지 및 데이터 백업 센터**<br>- `CompletedTrades`(익절 완료 일지), `Holdings`(실시간 잔고), `ExecutionHistory`(주문체결 이력) 자동 기록<br>- 스프레드시트 앱으로 언제 어디서나 엑셀 형태로 자산 추이 열람 가능 |

---

## 3. 일일 운영 프로세스 및 동작 시퀀스

시스템은 하루 동안 다음 3단계 사이클로 전자동 운영됩니다.

```mermaid
sequenceDiagram
    autonumber
    actor User as 👤 사용자
    participant CJ as ⏰ cron-job.org
    participant GHA as 🐙 GitHub Actions
    participant KIS as 🏛️ 한국투자증권 KIS
    participant Repo as 📁 Git Repo
    participant GS as 📊 Google Sheets
    participant ST as 📱 Streamlit Cloud

    Note over CJ, GS: [1단계: 밤 22:35 KST] 미국 정규장 개장 직후 당일 주문 발주
    CJ->>GHA: POST /actions/workflows/infinite_trader.yml/dispatches
    activate GHA
    GHA->>Repo: git checkout & 상태 파일 로드
    GHA->>KIS: 평단가 LOC 매수 + 상향 LOC 매수 + +10% 지정가 익절 매도 발주
    GHA->>Repo: 당일 주문 키/회차 기록 후 git auto-commit & push
    GHA->>GS: 당일 주문 내역 및 Holdings 동기화
    deactivate GHA

    Note over User, ST: [2단계: 밤~새벽 정규장 진행 중] 실시간 모바일 관제
    User->>ST: 스마트폰 웹 브라우저 접속 (share.streamlit.io)
    ST->>KIS: 실시간 체결 현황 및 계좌 평가손익 조회 표시
    User->>ST: (필요 시) 종목별 목표 수익률이나 예산 설정 변경
    ST->>GS: 변경된 설정값 동기화

    Note over CJ, GS: [3단계: 아침 06:05 KST] 미국 정규장 마감 직후 정산 & 동기화
    CJ->>GHA: POST /actions/workflows/infinite_trader.yml/dispatches
    activate GHA
    GHA->>KIS: 당일 체결 내역 조회 (sync_holdings_to_state)
    alt 전량 익절 완료 시
        GHA->>GS: CompletedTrades 시트에 실현수익/수익률 영구 기록 & 회차 1.0 리셋
    else 일반 체결 시
        GHA->>Repo: 체결 수량 반영하여 회차 전진 (예: 6.0 -> 7.0회차) 저장
    end
    GHA->>Repo: git auto-commit & push (최종 회차 상태 백업)
    GHA->>GS: 최근 7일 체결 이력 및 최종 상태 백업
    deactivate GHA
```

---

## 4. 왜 이러한 아키텍처로 설계되었는가? (핵심 설계 의도)

### ① 왜 GitHub Actions 내장 cron 대신 `cron-job.org`를 쓰는가?
GitHub Actions의 `schedule: - cron: '...'`은 전 세계 수많은 프로젝트가 공유하는 무료 리소스이므로, 큐 대기열에 따라 **최소 5분에서 길게는 30분 이상 실행이 지연(delay)**될 수 있습니다.
- 미국 정규장은 현지 시간 09:30에 개장하므로, 개장 직후 안전하게 호가를 확인하고 주문을 넣거나 장 마감 원장 확정 시점에 정확히 체결을 대조해야 합니다.
- **cron-job.org**는 독립된 상시 웹 크론 서버로서, 정해진 시간(**22:35 / 06:05**)에 GitHub API의 `workflow_dispatch` 엔드포인트를 1초의 오차 없이 즉시 호출해주므로 **지연 없는 정시 실행**을 보장합니다.

### ② 삼중 데이터 정합성 (Triple Consistency) 보장
자동매매 시스템에서 가장 위험한 것은 "내가 몇 회차까지 샀는지"를 잃어버리는 것입니다.
1. **1차 저장소 (Git Repo)**: `infinite_trader_state.json` 파일에 커밋되어 형상 관리
2. **2차 저장소 (Google Sheets)**: 클라우드 스프레드시트의 `State` 및 `CompletedTrades` 탭에 실시간 기록
3. **3차 검증 (KIS 증권사 원장)**: 장 마감 후 KIS API를 통해 실제 보유 주식 수량과 평단가를 직접 대조하여 회차를 보정(`sync_holdings_to_state`)

### ③ 서버 비용 0원 & 24시간 무중단 환경
- 로컬 PC를 밤새 켜둘 필요가 없습니다. (전기세, 절전 모드 진입 위험, 인터넷 끊김 위험 배제)
- GitHub Actions (매월 2,000분 무료), Streamlit Cloud (무료 호스팅), Google Sheets API (무료 티어), cron-job.org (무료)를 조합하여 **고정 서버 비용 0원**으로 완벽한 엔터프라이즈급 자동화 환경을 유지합니다.
