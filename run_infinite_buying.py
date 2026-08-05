"""
GitHub Actions 및 스케줄러 전용 라오어 무한매수 실행 스크립트 (run_infinite_buying.py)
"""
import os
import sys
import logging

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

    # GitHub Actions 환경에서는 무인 자동 주문 제출 모드로 세팅
    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    if is_github_actions:
        config.REQUIRE_USER_APPROVAL = False
        logger.info("🤖 GitHub Actions 환경 감지: 무인 자동 주문 모드(REQUIRE_USER_APPROVAL=False)로 가동됩니다.")

    api_client = KISApiClient()
    bot = TraderBot(api_client)

    # 1. 계좌 및 토큰 초기화
    init_success = bot.initialize_account()
    if not init_success:
        logger.error("❌ KIS 계좌 및 토큰 초기화 실패! 실행을 중단합니다.")
        sys.exit(1)

    logger.info(f"💰 [잔고 정보] 원화예수금: ₩{bot.available_cash:,.0f} | 외화예수금: ${bot.available_usd_cash:,.2f} | 총자산: ₩{bot.total_eval_amount:,.0f}")

    # 2. 라오어 무한매수법 당일 매매 루틴 실행
    logger.info("🚀 무한매수 당일 LOC 매수 & 익절 매도 주문 생성/제출 실행...")
    bot.run_infinite_buying_cycle()

    # 3. 승인 대기 중인 제안이 자동 모드일 때 일괄 실행
    if not bot.require_approval and bot.pending_proposals:
        logger.info(f"⚡ 생성된 {len(bot.pending_proposals)}건의 주문을 KIS API로 즉시 전송합니다...")
        for prop_id in list(bot.pending_proposals.keys()):
            bot.approve_proposal(prop_id)

    logger.info("🎉 ===== 무한매수 당일 루틴 실행 완료 =====")

if __name__ == "__main__":
    main()
