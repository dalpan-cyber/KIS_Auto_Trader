"""
Scheduler Module
5단계 일일 운영 타임라인 스케줄러 (월~금 KST 기준)
1. 09:00 : 시초가 갭하락 및 보유 종목 긴급 손절 감시 (Force Stop-loss)
2. 09:05 ~ 15:05 (5분 주기) : 장중 실시간 익절/손절 조건 모니터링
3. 15:10 : 일봉 데이터 수집 + 거래량 보정 + 종가 매수 점수 산출
4. 15:15 : 매수 추천 종목 확정 및 시장가 주문 발주
5. 15:30 : 장마감 체결 확인, 보유 잔고 및 D+Day 정산
"""
import os
import sys
import time
import logging
import datetime
import threading

import app_config as config
from screener import StockScreener
from time_utils import now

logger = logging.getLogger("Scheduler")

_scheduler = None
_thread_running = False
_worker_thread = None

# =============================================================================
# 5단계 정기 스케줄 작업 함수 정의
# =============================================================================

def job_market_open_stop_loss():
    """[09:00] 시초가 갭하락 및 보유 종목 긴급 손절 감시"""
    logger.info(f"⏰ [09:00] 시초가 갭하락 및 긴급 손절 감시 작업 시작 ({now()})")
    try:
        screener = StockScreener()
        urgent_sells = screener.check_market_open_stop_loss()
        logger.info(f"✅ [09:00] 시초가 감시 완료: 긴급 손절 {len(urgent_sells)}건 감지")
    except Exception as e:
        logger.error(f"❌ [09:00] 시초가 감시 작업 실패: {e}")

def job_intraday_monitoring():
    """[09:05~15:05] 장중 5분 주기 실시간 익절/손절 모니터링"""
    now_dt = now()
    # 장 운영 시간 (09:05 ~ 15:05) 체크
    if now_dt.hour < 9 or (now_dt.hour == 9 and now_dt.minute < 5) or (now_dt.hour == 15 and now_dt.minute > 5) or now_dt.hour > 15:
        return

    logger.info(f"🔄 [장중 감시] 실시간 매도/익절 신호 체크 ({now_dt.strftime('%H:%M:%S')})")
    try:
        screener = StockScreener()
        proposals = screener.check_sell_signals_now()
        sell_count = len(proposals.get("sell_proposals", []))
        if sell_count > 0:
            logger.warning(f"⚠️ [장중 감시] 매도 신호 {sell_count}건 감지됨")
    except Exception as e:
        logger.error(f"❌ [장중 감시] 실시간 모니터링 실패: {e}")

def job_closing_price_screening():
    """[15:10] 일봉 수집 + 거래량 보정 + 종가 매수 점수 산출"""
    logger.info(f"⏰ [15:10] 종가 매수 후보 발굴 및 스크리닝 시작 ({now()})")
    try:
        screener = StockScreener()
        proposals = screener.run_closing_price_screening()
        buy_count = len(proposals.get("buy_proposals", []))
        sell_count = len(proposals.get("sell_proposals", []))
        logger.info(f"✅ [15:10] 종가 스크리닝 완료: 매수 추천 {buy_count}건, 매도 추천 {sell_count}건")
    except Exception as e:
        logger.error(f"❌ [15:10] 종가 스크리닝 작업 실패: {e}")

def job_execute_buy_orders():
    """[15:15] 매수 추천 종목 주문 집행"""
    logger.info(f"⏰ [15:15] 종가 매수 주문 집행 작업 시작 ({now()})")
    try:
        screener = StockScreener()
        executed = screener.execute_top_buy_orders()
        logger.info(f"✅ [15:15] 매수 주문 집행 완료: {len(executed)}건 처리")
    except Exception as e:
        logger.error(f"❌ [15:15] 매수 주문 집행 실패: {e}")

def job_market_close_settlement():
    """[15:30] 장마감 체결 확인, 보유 잔고 및 D+Day 정산"""
    logger.info(f"⏰ [15:30] 장마감 잔고 및 일일 정산 시작 ({now()})")
    try:
        screener = StockScreener()
        screener.check_sell_signals_now()
        logger.info("✅ [15:30] 장마감 정산 완료")
    except Exception as e:
        logger.error(f"❌ [15:30] 장마감 정산 실패: {e}")

# 하위 호환성을 위한 alias
job_premarket_screening = job_closing_price_screening

# =============================================================================
# Fallback 스레드 기반 스케줄러 (APScheduler 부재 시 동작)
# =============================================================================

class SimpleFallbackScheduler:
    def __init__(self):
        self.running = False
        self._thread = None

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("내장 스레드 스케줄러가 백그라운드에서 동작합니다.")

    def shutdown(self, wait=False):
        self.running = False

    def _loop(self):
        last_executed = {}
        while self.running:
            now_dt = now()
            # 월~금(0~4) 주식 개장일만 실행
            if now_dt.weekday() < 5:
                today_str = now_dt.strftime("%Y%m%d")
                hm = (now_dt.hour, now_dt.minute)

                # 1. 09:00 긴급 손절 감시
                if hm == (9, 0) and last_executed.get("0900") != today_str:
                    last_executed["0900"] = today_str
                    job_market_open_stop_loss()

                # 2. 09:05 ~ 15:05 5분 간격 장중 감시
                if 9 <= now_dt.hour <= 15:
                    if (now_dt.hour == 9 and now_dt.minute >= 5) or (9 < now_dt.hour < 15) or (now_dt.hour == 15 and now_dt.minute <= 5):
                        if now_dt.minute % 5 == 0:
                            key = f"intraday_{today_str}_{now_dt.hour}_{now_dt.minute}"
                            if last_executed.get("intraday") != key:
                                last_executed["intraday"] = key
                                job_intraday_monitoring()

                # 3. 15:10 종가 매수 스크리닝
                if hm == (15, 10) and last_executed.get("1510") != today_str:
                    last_executed["1510"] = today_str
                    job_closing_price_screening()

                # 4. 15:15 주문 발주
                if hm == (15, 15) and last_executed.get("1515") != today_str:
                    last_executed["1515"] = today_str
                    job_execute_buy_orders()

                # 5. 15:30 장마감 정산
                if hm == (15, 30) and last_executed.get("1530") != today_str:
                    last_executed["1530"] = today_str
                    job_market_close_settlement()

            time.sleep(20)

# =============================================================================
# 스케줄러 시작/중지 인터페이스
# =============================================================================

def start_scheduler():
    """백그라운드 스케줄러 시작 (APScheduler 또는 내장 스케줄러 사용)"""
    global _scheduler
    if _scheduler is not None and getattr(_scheduler, "running", False):
        logger.info("스케줄러가 이미 실행 중입니다.")
        return _scheduler

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger

        _scheduler = BackgroundScheduler(timezone="Asia/Seoul")

        # 1. 09:00 시초가 갭하락 및 긴급 손절 감시
        _scheduler.add_job(
            job_market_open_stop_loss,
            CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone="Asia/Seoul"),
            id="job_0900_market_open",
            replace_existing=True
        )

        # 2. 09:05 ~ 15:05 5분 주기 장중 모니터링
        _scheduler.add_job(
            job_intraday_monitoring,
            CronTrigger(day_of_week="mon-fri", hour="9-14", minute="*/5", timezone="Asia/Seoul"),
            id="job_intraday_monitoring_morning",
            replace_existing=True
        )
        _scheduler.add_job(
            job_intraday_monitoring,
            CronTrigger(day_of_week="mon-fri", hour=15, minute="0,5", timezone="Asia/Seoul"),
            id="job_intraday_monitoring_afternoon",
            replace_existing=True
        )

        # 3. 15:10 종가 매수 스크리닝
        _scheduler.add_job(
            job_closing_price_screening,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=10, timezone="Asia/Seoul"),
            id="job_1510_closing_screening",
            replace_existing=True
        )

        # 4. 15:15 주문 발주
        _scheduler.add_job(
            job_execute_buy_orders,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=15, timezone="Asia/Seoul"),
            id="job_1515_buy_orders",
            replace_existing=True
        )

        # 5. 15:30 장마감 정산
        _scheduler.add_job(
            job_market_close_settlement,
            CronTrigger(day_of_week="mon-fri", hour=15, minute=30, timezone="Asia/Seoul"),
            id="job_1530_settlement",
            replace_existing=True
        )

        _scheduler.start()
        logger.info("APScheduler 5단계 일일 타임라인 스케줄러 구동 완료 (09:00 / 장중5분 / 15:10 / 15:15 / 15:30 KST)")
    except ImportError:
        logger.warning("APScheduler 미설치로 내장 Fallback 스케줄러를 구동합니다.")
        _scheduler = SimpleFallbackScheduler()
        _scheduler.start()

    return _scheduler

def stop_scheduler():
    """스케줄러 중지"""
    global _scheduler
    if _scheduler and getattr(_scheduler, "running", False):
        _scheduler.shutdown(wait=False)
        logger.info("스케줄러 중지됨")

if __name__ == "__main__":
    print("Starting standalone scheduler runner with 5-stage timeline...")
    s = start_scheduler()
    try:
        while True:
            time.sleep(1)
    except (KeyboardInterrupt, SystemExit):
        stop_scheduler()
