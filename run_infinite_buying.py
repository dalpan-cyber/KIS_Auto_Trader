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

import argparse
from datetime import datetime

def main():
    parser = argparse.ArgumentParser(description="GitHub Actions 및 스케줄러 전용 무한매수 실행 스크립트")
    parser.add_argument("--mode", choices=["auto", "order", "check"], default="auto", help="order: 주문발주, check: 체결확인만, auto: 시간대자동")
    args = parser.parse_args()

    # KST 시간대 기준 모드 자동 판별 (04시~09시 사이면 check 체결확인 모드, 그 외 order 주문발주 모드)
    current_hour = datetime.now().hour
    if args.mode == "auto":
        mode = "check" if (4 <= current_hour <= 9) else "order"
    else:
        mode = args.mode

    logger.info(f"===== GitHub Actions 라오어 무한매수 무인 자동 실행 시작 (모드: {mode.upper()}) =====")

    # CLI 실행 시 항상 무인 자동 주문 제출 모드로 세팅
    config.REQUIRE_USER_APPROVAL = False
    is_github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    if is_github_actions:
        logger.info("🤖 GitHub Actions 환경 감지: 무인 자동 실행 모드로 가동됩니다.")

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

    # Google Sheet 연결 상태 점검
    gss_connected = bot.infinite_state_mgr.gss_mgr.is_connected if hasattr(bot.infinite_state_mgr, "gss_mgr") and bot.infinite_state_mgr.gss_mgr else False
    gss_status_str = "🟢 연동 성공" if gss_connected else "🔴 미연동 (gcp_key.json 키 및 시트 공유 설정 필요)"
    logger.info(f"📊 [Google Sheets 동기화 상태] {gss_status_str}")

    # 2. 체결 확인(CHECK) 모드: 장 마감 후 체결 내역 조회 및 구글 시트 동기화만 수행 (신규 주문 발주 안 함)
    if mode == "check":
        logger.info("🔍 [체결 확인 모드] 장 마감 후 체결 내역 조회 및 Google Sheets 동기화를 진행합니다. (신규 주문은 발주하지 않음)")
        bot.sync_holdings_to_state()
        bot.infinite_state_mgr.save_state()
        logger.info("🎉 ===== 무한매수 장 마감 체결 확인 및 구글 시트 동기화 완료 =====")
        return

    # 3. 주문 발주(ORDER) 모드: IDLE 상태인 대상 종목 활성화 및 당일 LOC 주문 발주
    for symbol in getattr(config, "INFINITE_STOCKS", ["TQQQ", "SOXL"]):
        stock_cfg = config.get_stock_config(symbol)
        st_data = bot.infinite_state_mgr.get_symbol_state(
            symbol,
            default_budget_usd=stock_cfg["total_budget_usd"],
            division_count=stock_cfg["division_count"],
            target_roi=stock_cfg["target_roi"],
            exhaust_action=stock_cfg["exhaust_action"],
            exhaust_target_roi=stock_cfg["exhaust_target_roi"]
        )
        if st_data.get("status") in ("IDLE", "COMPLETED"):
            logger.info(f"▶ [{symbol}] 무한매수 상태가 {st_data.get('status')}입니다. 자동 매수 진행(BUYING) 상태로 전환하여 새 사이클을 시작합니다.")
            bot.infinite_state_mgr.start_buying(symbol)

    logger.info("🚀 [주문 발주 모드] 무한매수 당일 LOC 매수 & 익절 매도 주문 생성/제출 실행...")
    bot.run_infinite_buying_cycle()

    # 4. 승인 대기 중인 제안이 남아있는 경우 일괄 승인 및 주문 제출
    if bot.pending_proposals:
        logger.info(f"⚡ 생성된 {len(bot.pending_proposals)}건의 대기 주문을 KIS API로 즉시 전송합니다...")
        for prop_id in list(bot.pending_proposals.keys()):
            bot.approve_proposal(prop_id)

    # 5. 최종 무한매수 상태 저장 및 구글 시트 동기화 강제 실행
    bot.infinite_state_mgr.save_state()
    bot.sync_holdings_to_state()

    logger.info("🎉 ===== 무한매수 당일 주문 발주 루틴 완료 =====")

if __name__ == "__main__":
    main()
