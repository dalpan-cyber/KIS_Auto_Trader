import os
import subprocess

html_content = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<title>KIS 라오어 무한매수법 무인 자동매매 구축 완벽 가이드</title>
<style>
  @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

  @page {
    size: A4;
    margin: 20mm 15mm 20mm 15mm;
  }

  body {
    font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, 'Malgun Gothic', sans-serif;
    color: #1e293b;
    line-height: 1.65;
    font-size: 13.5px;
    background-color: #ffffff;
    margin: 0;
    padding: 0;
  }

  /* Cover Section */
  .cover {
    text-align: center;
    padding: 40px 20px 30px 20px;
    border-bottom: 2px solid #e2e8f0;
    margin-bottom: 30px;
    page-break-after: always;
  }

  .cover-badge {
    display: inline-block;
    background: #eff6ff;
    color: #1d4ed8;
    padding: 6px 14px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 700;
    margin-bottom: 15px;
    border: 1px solid #bfdbfe;
  }

  .cover-title {
    font-size: 26px;
    font-weight: 800;
    color: #0f172a;
    margin: 10px 0;
    letter-spacing: -0.5px;
    line-height: 1.35;
  }

  .cover-subtitle {
    font-size: 15px;
    color: #475569;
    margin-bottom: 25px;
  }

  .cover-meta {
    font-size: 12px;
    color: #94a3b8;
    margin-top: 30px;
  }

  .summary-card {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 20px;
    text-align: left;
    margin: 20px auto;
    max-width: 600px;
  }

  .summary-card h4 {
    margin-top: 0;
    color: #1e293b;
    font-size: 15px;
  }

  .summary-card ul {
    margin: 0;
    padding-left: 20px;
    color: #334155;
    font-size: 13px;
  }

  .summary-card li {
    margin-bottom: 6px;
  }

  /* Headings */
  h1 {
    font-size: 18px;
    font-weight: 800;
    color: #0f172a;
    border-left: 5px solid #2563eb;
    padding-left: 10px;
    margin-top: 35px;
    margin-bottom: 15px;
    page-break-after: avoid;
  }

  h2 {
    font-size: 15px;
    font-weight: 700;
    color: #1e293b;
    margin-top: 22px;
    margin-bottom: 10px;
    page-break-after: avoid;
  }

  h3 {
    font-size: 13.5px;
    font-weight: 700;
    color: #334155;
    margin-top: 14px;
    margin-bottom: 8px;
    page-break-after: avoid;
  }

  p, li {
    color: #334155;
  }

  /* Step box */
  .step-box {
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    page-break-inside: avoid;
  }

  .step-header {
    display: flex;
    align-items: center;
    font-size: 14.5px;
    font-weight: 700;
    color: #1e293b;
    margin-bottom: 8px;
  }

  .step-num {
    display: inline-block;
    background: #2563eb;
    color: #ffffff;
    width: 22px;
    height: 22px;
    line-height: 22px;
    text-align: center;
    border-radius: 50%;
    margin-right: 8px;
    font-size: 12px;
    font-weight: 700;
  }

  /* Alerts */
  .alert {
    border-radius: 8px;
    padding: 12px 14px;
    margin: 12px 0;
    font-size: 12.5px;
    page-break-inside: avoid;
  }

  .alert-info {
    background: #eff6ff;
    border: 1px solid #bfdbfe;
    color: #1e40af;
  }

  .alert-warn {
    background: #fefce8;
    border: 1px solid #fef08a;
    color: #854d0e;
  }

  .alert-important {
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #991b1b;
  }

  /* Table */
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 12px 0 16px 0;
    font-size: 12.5px;
    page-break-inside: avoid;
  }

  th, td {
    border: 1px solid #cbd5e1;
    padding: 8px 10px;
    text-align: left;
  }

  th {
    background-color: #f1f5f9;
    color: #0f172a;
    font-weight: 700;
  }

  tr:nth-child(even) {
    background-color: #f8fafc;
  }

  /* Code block */
  code {
    font-family: 'Consolas', 'Courier New', monospace;
    background: #f1f5f9;
    color: #0f172a;
    padding: 2px 5px;
    border-radius: 4px;
    font-size: 12px;
  }

  pre {
    background: #0f172a;
    color: #f8fafc;
    padding: 12px;
    border-radius: 6px;
    font-size: 11.5px;
    line-height: 1.45;
    overflow-x: auto;
    page-break-inside: avoid;
    font-family: 'Consolas', 'Courier New', monospace;
  }

  .page-break {
    page-break-before: always;
  }

  .footer {
    text-align: center;
    font-size: 11px;
    color: #94a3b8;
    margin-top: 30px;
    border-top: 1px solid #e2e8f0;
    padding-top: 10px;
  }
</style>
</head>
<body>

<!-- COVER PAGE -->
<div class="cover">
  <div class="cover-badge">초보자용 100% 실전 구축 매뉴얼</div>
  <div class="cover-title">🇺🇸 한국투자증권 KIS 라오어 무한매수법<br>무인 자동매매 & 웹 대시보드 완벽 가이드</div>
  <div class="cover-subtitle">내 컴퓨터를 켜두지 않아도 24시간 365일 클라우드에서 자동으로 매매되는 무한매수 시스템</div>

  <div class="summary-card">
    <h4>💡 본 시스템의 핵심 특징</h4>
    <ul>
      <li><strong>완전 무인 자동화</strong>: GitHub Actions가 매일 밤(21:59) 정해진 시간에 자동 매수/매도 주문 발주</li>
      <li><strong>모바일/PC 실시간 관제</strong>: Streamlit Cloud 무료 대시보드로 잔고/수익률/차트 실시간 확인</li>
      <li><strong>자동 매매일지 기록</strong>: Google Sheets에 체결 이력 및 설정값 자동 동기화</li>
      <li><strong>서버 비용 0원</strong>: GitHub Actions + Streamlit Cloud + Google Cloud 무료 티어 100% 활용</li>
    </ul>
  </div>

  <div class="cover-meta">
    작성 버전: v2.0 (2026년 최신) | 대상: 비개발자 및 주식 자동매매 초보자
  </div>
</div>

<!-- PAGE 1: PREPARATION & STEP 1 -->
<h1>📌 시작 전 준비물 체크리스트</h1>
<div class="step-box">
  <ul>
    <li><strong>GitHub 계정</strong> (<a href="https://github.com">github.com</a> 가입)</li>
    <li><strong>한국투자증권 실전 계좌</strong> (해외주식 거래 가능 종합계좌)</li>
    <li><strong>Google 계정</strong> (구글 드라이브 및 스프레드시트 이용)</li>
  </ul>
</div>

<h1>1단계: GitHub 저장소 복제하기 (Fork)</h1>
<div class="step-box">
  <div class="step-header"><span class="step-num">1</span>저장소 접속 및 Fork 클릭</div>
  <p>1. 인터넷 브라우저로 원본 저장소 주소에 접속합니다.</p>
  <p>2. 화면 우측 상단에 있는 <strong>[Fork]</strong> 버튼을 클릭합니다.</p>
  <p>3. <strong>Create fork</strong> 버튼을 누르면 본인 계정에 <code>https://github.com/&lt;본인ID&gt;/KIS_Auto_Trader</code> 저장소가 자동으로 복제됩니다.</p>
</div>

<div class="alert alert-info">
  💡 <strong>Fork란?</strong> 원본 코드를 본인의 깃허브 계정으로 그대로 복사해 와서, 본인만의 설정과 계좌 키를 등록해 독립적으로 구동시키는 기능입니다.
</div>

<!-- PAGE 2: STEP 2 KIS DEVELOPERS & MTS -->
<h1>2단계: 한국투자증권 Open API 키 발급 & MTS 필수 설정</h1>

<div class="step-box">
  <div class="step-header"><span class="step-num">1</span>KIS Developers 포털 가입 및 앱 등록</div>
  <p>1. <strong>한국투자증권 KIS Developers</strong> (<a href="https://apiportal.koreainvestment.com">apiportal.koreainvestment.com</a>)에 접속하여 로그인합니다.</p>
  <p>2. 상단 메뉴에서 <strong>[오픈API 신청] &gt; [앱 등록/관리]</strong>를 클릭합니다.</p>
  <p>3. 본인의 실전투자 계좌를 선택하고 앱을 등록합니다.</p>
  <p>4. 발급된 <strong>AppKey</strong>와 <strong>AppSecret</strong>을 안전한 곳(메모장)에 복사해 둡니다.</p>
</div>

<div class="step-box">
  <div class="step-header"><span class="step-num">2</span>MTS(스마트폰 앱) 필수 거래 신청 (매우 중요!)</div>
  <p>무한매수 대상인 미국 3배 레버리지 ETF(TQQQ, SOXL 등)를 매매하기 위해 증권사에 다음 3가지 신청이 필수로 등록되어 있어야 주문 오류가 발생하지 않습니다.</p>
  <ul>
    <li><strong>해외주식 거래 신청</strong>: MTS &gt; 메뉴 &gt; 안내/신청 &gt; 해외주식 거래 서비스 신청</li>
    <li><strong>해외 ETF 거래 신청 및 기본예탁금 등록</strong>: MTS &gt; 메뉴 &gt; 안내/신청 &gt; 해외 ETF 거래 신청 (기본예탁금 면제/등록)</li>
    <li><strong>레버리지 ETF 교육 이수 등록</strong>:
      <ol>
        <li><a href="https://www.kifin.or.kr">금융투자교육원</a> 접속 후 <em>'레버리지 ETP(ETF/ETN) 가이드'</em> (1시간 온라인 교육) 수료</li>
        <li>한국투자증권 MTS &gt; 메뉴 &gt; 안내/신청 &gt; <em>'레버리지 ETF 교육이수 등록'</em>에 수료 번호 입력</li>
      </ol>
    </li>
  </ul>
</div>

<div class="page-break"></div>

<!-- PAGE 3: STEP 3 GOOGLE SHEETS & GCP -->
<h1>3단계: Google Sheets & 서비스 계정 생성</h1>

<div class="step-box">
  <div class="step-header"><span class="step-num">1</span>구글 스프레드시트 생성</div>
  <p>1. <a href="https://drive.google.com">Google Drive</a>에 접속하여 새 스프레드시트를 생성합니다.</p>
  <p>2. 스프레드시트 제목을 반드시 <strong><code>KIS_무한매수_매매일지</code></strong>로 입력합니다.</p>
  <p>3. 하단 탭에 다음 2개의 시트(탭)를 생성합니다:
    <ul>
      <li><code>CompletedTrades</code> (익절 완료된 매매 기록 저장용)</li>
      <li><code>Settings</code> (대시보드 설정값 동기화용)</li>
    </ul>
  </p>
</div>

<div class="step-box">
  <div class="step-header"><span class="step-num">2</span>Google Cloud Platform(GCP) 서비스 계정 키 발급</div>
  <p>1. <a href="https://console.cloud.google.com">Google Cloud Console</a>에 접속하여 새 프로젝트를 생성합니다.</p>
  <p>2. <strong>[API 및 서비스] &gt; [라이브러리]</strong>에서 다음 2개 API를 검색하여 <strong>[사용(활성화)]</strong>을 클릭합니다:
    <ul>
      <li><strong>Google Drive API</strong></li>
      <li><strong>Google Sheets API</strong></li>
    </ul>
  </p>
  <p>3. <strong>[API 및 서비스] &gt; [사용자 인증 정보]</strong> &gt; <strong>[사용자 인증 정보 만들기] &gt; [서비스 계정]</strong>을 클릭합니다.</p>
  <p>4. 이름(예: <code>kis-sheets-bot</code>)을 넣고 생성을 완료합니다.</p>
  <p>5. 생성된 서비스 계정을 클릭 &gt; <strong>[키(Keys)] 탭</strong> &gt; <strong>[키 추가] &gt; [새 키 만들기] &gt; JSON</strong>을 선택하여 키 파일을 다운로드합니다.</p>
  <p>6. 다운로드된 JSON 파일을 메모장으로 열어 <code>client_email</code> 값(예: <code>kis-sheets-bot@xxxx.iam.gserviceaccount.com</code>)을 복사합니다.</p>
  <p>7. 앞서 만든 <strong>구글 스프레드시트(<code>KIS_무한매수_매매일지</code>)</strong>의 <strong>[공유]</strong> 버튼을 누르고, 복사한 서비스 계정 이메일을 <strong><code>편집자</code></strong> 권한으로 초대합니다.</p>
</div>

<!-- PAGE 4: STEP 4 GITHUB SECRETS -->
<h1>4단계: GitHub Actions Secrets 등록 & 권한 설정</h1>

<div class="step-box">
  <div class="step-header"><span class="step-num">1</span>GitHub Actions 쓰기 권한 활성화 (필수)</div>
  <p>자동매매가 끝난 후 진행 회차(예: 6.0회차)를 Git에 자동 저장하기 위해 권한이 필요합니다.</p>
  <p>1. 본인 GitHub 저장소 &gt; <strong>[Settings] &gt; [Actions] &gt; [General]</strong>로 이동합니다.</p>
  <p>2. 화면 맨 아래 <strong>Workflow permissions</strong> 섹션에서 <strong>[Read and write permissions]</strong>를 체크하고 <strong>Save</strong>를 클릭합니다.</p>
</div>

<div class="step-box">
  <div class="step-header"><span class="step-num">2</span>GitHub Repository Secrets 6개 등록</div>
  <p>본인 저장소 &gt; <strong>[Settings] &gt; [Secrets and variables] &gt; [Actions] &gt; [New repository secret]</strong>을 눌러 다음 6개 항목을 등록합니다.</p>

  <table>
    <tr>
      <th>Secret 이름 (정확히 입력)</th>
      <th>설명</th>
      <th>입력 값 예시</th>
    </tr>
    <tr>
      <td><code>KIS_APP_KEY</code></td>
      <td>한국투자증권 AppKey</td>
      <td><code>PSxxxxxxxxxxxxxx</code></td>
    </tr>
    <tr>
      <td><code>KIS_APP_SECRET</code></td>
      <td>한국투자증권 AppSecret</td>
      <td><code>xxxxxxxxxxxxxxxxxxxxxxxx</code></td>
    </tr>
    <tr>
      <td><code>KIS_CANO</code></td>
      <td>계좌번호 앞 8자리</td>
      <td><code>12345678</code></td>
    </tr>
    <tr>
      <td><code>KIS_ACNT_PRDT_CD</code></td>
      <td>계좌상품코드 2자리</td>
      <td><code>01</code></td>
    </tr>
    <tr>
      <td><code>KIS_ACCOUNT_PWD</code></td>
      <td>계좌 비밀번호 4자리</td>
      <td><code>1234</code></td>
    </tr>
    <tr>
      <td><code>GCP_SERVICE_ACCOUNT_JSON</code></td>
      <td>GCP 서비스 계정 JSON 전체 내용</td>
      <td>JSON 파일 내용을 <code>{</code>부터 <code>}</code>까지 전체 복사해서 붙여넣기</td>
    </tr>
  </table>
</div>

<div class="page-break"></div>

<!-- PAGE 5: STEP 5 STREAMLIT CLOUD -->
<h1>5단계: Streamlit Cloud 무료 웹 대시보드 배포</h1>

<div class="step-box">
  <div class="step-header"><span class="step-num">1</span>Streamlit Cloud 앱 생성</div>
  <p>1. <a href="https://share.streamlit.io">share.streamlit.io</a>에 접속하여 GitHub 계정으로 로그인합니다.</p>
  <p>2. 우측 상단의 <strong>[Create app]</strong>을 클릭합니다.</p>
  <p>3. 저장소 정보를 입력합니다:
    <ul>
      <li><strong>Repository</strong>: 본인의 Fork 저장소 (예: <code>&lt;본인ID&gt;/KIS_Auto_Trader</code>)</li>
      <li><strong>Branch</strong>: <code>main</code></li>
      <li><strong>Main file path</strong>: <code>app.py</code></li>
    </ul>
  </p>
  <p>4. <strong>[Advanced settings...]</strong> 버튼을 클릭합니다.</p>
</div>

<div class="step-box">
  <div class="step-header"><span class="step-num">2</span>Streamlit Secrets 환경변수 입력</div>
  <p>Advanced settings 창의 <strong>Secrets</strong> 입력창에 아래 내용을 그대로 복사하고 본인의 정보로 채워 넣습니다:</p>

<pre>
KIS_APP_KEY = "발급받은_AppKey"
KIS_APP_SECRET = "발급받은_AppSecret"
KIS_CANO = "계좌번호앞8자리"
KIS_ACNT_PRDT_CD = "01"
KIS_ACCOUNT_PWD = "계좌비밀번호4자리"
MOCK_TRADING_ONLY = "false"

# GCP 서비스 계정 키 JSON
GCP_SERVICE_ACCOUNT_JSON = '''
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "...",
  "private_key": "-----BEGIN PRIVATE KEY-----\\n...\\n-----END PRIVATE KEY-----\\n",
  "client_email": "kis-sheets-bot@your-project-id.iam.gserviceaccount.com",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
'''
</pre>
  <p>5. <strong>[Save]</strong> 후 <strong>[Deploy!]</strong> 버튼을 누르면 1~2분 뒤 나만의 모바일/웹 대시보드가 오픈됩니다!</p>
</div>

<!-- PAGE 6: OPERATION & FAQS -->
<h1>6단계: 자동매매 스케줄 및 동작 검증</h1>

<div class="step-box">
  <div class="step-header"><span class="step-num">1</span>자동 실행 시간표 (한국 시간 기준)</div>
  <ul>
    <li><strong>밤 21:59 (월~금)</strong>: 미국 정규장 개장 전 당일 <strong>평단가 LOC 매수 + 상향 LOC 매수 + +10% 지정가 익절 매도</strong> 발주</li>
    <li><strong>아침 05:12 (화~토)</strong>: 미국 장 마감 후 체결 내역 확인 및 회차 진행, 익절 시 자동 리셋 및 구글 시트 매매일지 기록</li>
  </ul>
</div>

<div class="step-box">
  <div class="step-header"><span class="step-num">2</span>수동 즉시 실행 테스트 (정상 작동 확인)</div>
  <p>GitHub Actions가 잘 작동하는지 지금 바로 테스트해 볼 수 있습니다:</p>
  <p>1. 본인 GitHub 저장소 &gt; <strong>[Actions]</strong> 탭으로 이동합니다.</p>
  <p>2. 좌측에서 <strong>`🇺🇸 KIS 라오어 무한매수법 무인 자동매매`</strong> 워크플로우를 선택합니다.</p>
  <p>3. 우측 <strong>[Run workflow]</strong> 드롭다운을 누르고 초록색 <strong>[Run workflow]</strong> 버튼을 클릭합니다.</p>
  <p>4. 1분 후 초록색 체크(✔)가 뜨고 실행 로그에 잔고와 주문 제안이 정상 출력되면 모든 세팅이 완벽하게 끝난 것입니다!</p>
</div>

<div class="alert alert-warn">
  🛡️ <strong>40회차 소진 시 대응 옵션 안내 (대시보드에서 설정 가능)</strong><br>
  주가가 계속 하락하여 40회차까지 모두 매수되었을 때 대시보드의 [설정] 메뉴에서 다음 3가지 전략 중 원하는 방식을 선택할 수 있습니다:
  <ol style="margin-bottom:0; padding-left:18px;">
    <li><strong>1. 무한 대기 (기본)</strong>: 추가 매수를 중단하고 원금을 지키며 +10% 익절 매도만 유지</li>
    <li><strong>2. 쿼터 순환 매매</strong>: 매일 1회차 분량을 매도하고 LOC 재매수하여 평단가를 강제로 인하</li>
    <li><strong>3. 목표수익률 하향</strong>: 40회차 도달 시 목표 수익률을 +5%로 자동 낮춰 빠른 조기 탈출 유도</li>
  </ol>
</div>

<div class="footer">
  🎉 축하합니다! 이제 컴퓨터를 끄셔도 깃허브 클라우드가 매일 밤 자동으로 당신의 무한매수를 실행합니다.
</div>

</body>
</html>
"""

html_path = "KIS_무한매수_구축가이드_초보자용.html"
pdf_path = "KIS_무한매수_구축가이드_초보자용.pdf"

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"HTML 파일 생성 완료: {html_path}")

edge_path = r'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
if not os.path.exists(edge_path):
    edge_path = r'C:\Program Files\Microsoft\Edge\Application\msedge.exe'

cmd = [
    edge_path,
    "--headless",
    "--disable-gpu",
    "--run-all-compositor-stages-before-draw",
    f"--print-to-pdf={os.path.abspath(pdf_path)}",
    "--no-pdf-header-footer",
    os.path.abspath(html_path)
]

print("PDF 변환 중...")
res = subprocess.run(cmd, capture_output=True, text=True)
print("PDF 생성 완료:", os.path.exists(pdf_path), "파일 크기:", os.path.getsize(pdf_path) if os.path.exists(pdf_path) else 0)
