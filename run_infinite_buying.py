"""
GitHub Actions 및 스케줄러 전용 라오어 무한매수 실행 스크립트 (run_infinite_buying.py)
"""
import os
import sys
import time
import logging

# Linux / GitHub Actions 서버 타임존을 한국 표준시(KST)로 설정
if hasattr(time, "tzset"):
    os.environ["TZ"] = "Asia/Seoul"
    time.tzset()

# Windows 콘솔 인코딩 방어
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import config
from kis_api import KISApiClient
from trader import TraderBot

# 로깅 기본 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

logger = logging.getLogger("InfiniteBuyingCLI")

def main():
    logger.info("===== GitHub Actions 라오어 무한매수 무인 자동 실행 시작 =====")

    # CLI 실행 시 항상 무인 자동 주문 제출 모드로 세팅
    config.REQUIRE_USER_APPROVAL = False
    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    if is_github_actions:
        logger.info("🤖 GitHub Actions 환경 감지: 무인 자동 주문 모드(REQUIRE_USER_APPROVAL=False)로 가동됩니다.")

    api_client = KISApiClient()
    bot = TraderBot(api_client)
    bot.require_approval = False  # 무인 자동 매수 모드 강제

    # 1. 계좌 및 토큰 초기화
    init_success = bot.initialize_account()
    if not init_success:
        logger.error("❌ KIS 계좌 및 토큰 초기화 실패! 실행을 중단합니다.")
        sys.exit(1)

    # 실전 매매 모드에서 토큰 발급 실패 시 시뮬레이션으로 우회하지 않고 명시적 오류 종료
    if not api_client.mock and not api_client.is_token_valid():
        logger.error("🚨 [치명적 오류] KIS 실전 API Access Token이 발급되지 않았습니다! GitHub Secrets(KIS_APP_KEY, KIS_APP_SECRET)를 확인하세요.")
        sys.exit(1)

    logger.info(f"💰 [잔고 정보] 원화예수금: ₩{bot.available_cash:,.0f} | 외화예수금: ${bot.available_usd_cash:,.2f} | 총자산: ₩{bot.total_eval_amount:,.0f}")

    # 2. IDLE 상태인 대상 종목이 있다면 BUYING 상태로 자동 활성화
    for symbol in getattr(config, "INFINITE_STOCKS", ["TQQQ"]):
        st_data = bot.infinite_state_mgr.get_symbol_state(symbol)
        if st_data.get("status") == "IDLE":
            logger.info(f"▶ [{symbol}] 무한매수 상태가 IDLE입니다. 자동 매수 진행(BUYING) 상태로 전환합니다.")
            bot.infinite_state_mgr.start_buying(symbol)

    # Google Sheet 연결 상태 점검
    gss_connected = bot.infinite_state_mgr.gss_mgr.is_connected if hasattr(bot.infinite_state_mgr, "gss_mgr") and bot.infinite_state_mgr.gss_mgr else False
    gss_status_str = "🟢 연동 성공" if gss_connected else "🔴 미연동 (gcp_key.json 키 및 시트 공유 설정 필요)"
    logger.info(f"📊 [Google Sheets 동기화 상태] {gss_status_str}")

    # 3. 라오어 무한매수법 당일 매매 루틴 실행
    logger.info("🚀 무한매수 당일 LOC 매수 & 익절 매도 주문 생성/제출 실행...")
    bot.run_infinite_buying_cycle()

    # 4. 승인 대기 중인 제안이 남아있는 경우 일괄 승인 및 주문 제출
    if bot.pending_proposals:
        logger.info(f"⚡ 생성된 {len(bot.pending_proposals)}건의 대기 주문을 KIS API로 즉시 전송합니다...")
        for prop_id in list(bot.pending_proposals.keys()):
            bot.approve_proposal(prop_id)

    # 5. 최종 무한매수 상태 저장 및 구글 시트 동기화 강제 실행
    bot.infinite_state_mgr.save_state()

    logger.info("🎉 ===== 무한매수 당일 루틴 실행 완료 =====")

if __name__ == "__main__":
    main()
