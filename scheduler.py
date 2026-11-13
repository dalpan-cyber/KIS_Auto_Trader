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

# 프로세스 간 스케줄러 단일 실행 보장용 락 파일 (Streamlit 핫리로드 / scheduler.py 동시 실행 시 잡 중복 방지)
SCHEDULER_LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scheduler.lock")
_lock_handle = None
_lock_held_elsewhere = False


def _acquire_process_lock() -> bool:
    """OS 파일 락으로 머신 내 단 하나의 스케줄러만 동작하도록 보장 (프로세스 종료 시 자동 해제)"""
    global _lock_handle
    if _lock_handle is not None:
        return True
    handle = open(SCHEDULER_LOCK_FILE, "a+")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    handle.seek(0)
    handle.truncate()
    handle.write(f"pid={os.getpid()} started={now()}\n")
    handle.flush()
    _lock_handle = handle
    return True



def _parse_time_str(time_str: str, default_hour: int = 15, default_minute: int = 10) -> tuple:
    """'HH:MM' 형태의 문자열을 (hour, minute) 정수 튜플로 변환"""
    try:
        if time_str and ":" in str(time_str):
            parts = str(time_str).strip().split(":")
            h = int(parts[0])
            m = int(parts[1]) if len(parts) > 1 else 0
            if 0 <= h <= 23 and 0 <= m <= 59:
                return h, m
    except Exception:
        pass
    return default_hour, default_minute


def get_screening_and_order_times() -> tuple:
    """설정에서 스크리닝 시각(HH:MM)과 그에 따른 매수 주문 발주 시각(+5분) 반환"""
    premarket_time = config.get_setting("premarket_time", "15:10")
    s_hour, s_minute = _parse_time_str(premarket_time, 15, 10)

    # 주문 발주는 스크리닝 완료 후 5분 뒤 (최대 15:25로 제한하여 장마감 15:30 전 보장)
    order_total_min = s_hour * 60 + s_minute + 5
    if order_total_min > 15 * 60 + 25:
        order_total_min = 15 * 60 + 25
    o_hour = order_total_min // 60
    o_minute = order_total_min % 60

    return (s_hour, s_minute), (o_hour, o_minute)


def reschedule_screening_jobs(new_time: str = None) -> bool:
    """
    설정 변경 시 백그라운드 스케줄러의 종가 스크리닝 및 매수 주문 발주 시간을 실시간 갱신합니다.
    """
    global _scheduler
    if new_time:
        s_hour, s_minute = _parse_time_str(new_time, 15, 10)
        order_total_min = min(s_hour * 60 + s_minute + 5, 15 * 60 + 25)
        o_hour, o_minute = order_total_min // 60, order_total_min % 60
    else:
        (s_hour, s_minute), (o_hour, o_minute) = get_screening_and_order_times()

    logger.info(f"🔄 스케줄러 시간 재설정 요청: 종가 스크리닝={s_hour:02d}:{s_minute:02d}, 주문 발주={o_hour:02d}:{o_minute:02d}")

    if _scheduler is None:
        logger.info("스케줄러가 아직 구동되지 않았습니다. 시작 시 최신 설정이 자동 반영됩니다.")
        return True

    # 1. APScheduler 인스턴스인 경우 실시간 reschedule
    if hasattr(_scheduler, "reschedule_job") or hasattr(_scheduler, "add_job"):
        try:
            from apscheduler.triggers.cron import CronTrigger
            trigger_s = CronTrigger(day_of_week="mon-fri", hour=s_hour, minute=s_minute, timezone="Asia/Seoul")
            try:
                _scheduler.reschedule_job("job_1510_closing_screening", trigger=trigger_s)
                logger.info(f"✅ [APScheduler] 종가 스크리닝 작업 시간 변경 완료: {s_hour:02d}:{s_minute:02d}")
            except Exception:
                _scheduler.add_job(
                    job_closing_price_screening,
                    trigger_s,
                    id="job_1510_closing_screening",
                    replace_existing=True
                )
                logger.info(f"✅ [APScheduler] 종가 스크리닝 작업 등록 완료: {s_hour:02d}:{s_minute:02d}")

            trigger_o = CronTrigger(day_of_week="mon-fri", hour=o_hour, minute=o_minute, timezone="Asia/Seoul")
            try:
                _scheduler.reschedule_job("job_1515_buy_orders", trigger=trigger_o)
                logger.info(f"✅ [APScheduler] 매수 주문 발주 작업 시간 변경 완료: {o_hour:02d}:{o_minute:02d}")
            except Exception:
                _scheduler.add_job(
                    job_execute_buy_orders,
                    trigger_o,
                    id="job_1515_buy_orders",
                    replace_existing=True
                )
                logger.info(f"✅ [APScheduler] 매수 주문 발주 작업 등록 완료: {o_hour:02d}:{o_minute:02d}")
            return True
        except Exception as e:
            logger.error(f"❌ [APScheduler] 스케줄러 시간 재설정 실패: {e}")
            return False

    # 2. SimpleFallbackScheduler인 경우 매 루프마다 get_screening_and_order_times()를 확인하므로 자동 적용됨
    logger.info(f"✅ [내장 스케줄러] 변경된 시간({s_hour:02d}:{s_minute:02d} / {o_hour:02d}:{o_minute:02d})이 다음 루프부터 자동 적용됩니다.")
    return True


def get_scheduled_jobs_info() -> list:
    """현재 스케줄러에 등록된 잡들의 ID, 트리거, 다음 실행 시각 반환"""
    global _scheduler
    jobs_info = []
    if _scheduler and hasattr(_scheduler, "get_jobs"):
        try:
            for job in _scheduler.get_jobs():
                next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if getattr(job, "next_run_time", None) else "-"
                jobs_info.append({
                    "id": job.id,
                    "name": getattr(job, "name", job.id),
                    "next_run": next_run,
                    "trigger": str(job.trigger)
                })
        except Exception:
            pass
    return jobs_info


def is_scheduler_active() -> bool:
    """이 프로세스 또는 다른 프로세스에서 스케줄러가 동작 중인지 여부"""
    return _lock_held_elsewhere or (_scheduler is not None and getattr(_scheduler, "running", False))

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
        proposals = screener.check_sell_signals_now(fast_mode=True)
        sell_count = len(proposals.get("sell_proposals", []))
        if sell_count > 0:
            logger.warning(f"⚠️ [장중 감시] 매도 신호 {sell_count}건 감지됨")
    except Exception as e:
        logger.error(f"❌ [장중 감시] 실시간 모니터링 실패: {e}")

def job_closing_price_screening():
    """설정된 시각(기본 15:10)에 일봉 수집 + 거래량 보정 + 종가 매수 점수 산출"""
    cur_time = config.get_setting("premarket_time", "15:10")
    logger.info(f"⏰ [{cur_time}] 종가 매수 후보 발굴 및 스크리닝 시작 ({now()})")
    try:
        screener = StockScreener()
        proposals = screener.run_closing_price_screening()
        buy_count = len(proposals.get("buy_proposals", []))
        sell_count = len(proposals.get("sell_proposals", []))
        logger.info(f"✅ [{cur_time}] 종가 스크리닝 완료: 매수 추천 {buy_count}건, 매도 추천 {sell_count}건")
    except Exception as e:
        logger.error(f"❌ [{cur_time}] 종가 스크리닝 작업 실패: {e}")

def job_execute_buy_orders():
    """매수 추천 종목 주문 집행 (스크리닝 5분 후)"""
    cur_time = config.get_setting("premarket_time", "15:10")
    (s_h, s_m), (o_h, o_m) = get_screening_and_order_times()
    order_time_str = f"{o_h:02d}:{o_m:02d}"
    logger.info(f"⏰ [{order_time_str} 주문 집행] 종가 매수 주문 집행 작업 시작 ({now()})")
    try:
        screener = StockScreener()
        executed = screener.execute_top_buy_orders()
        logger.info(f"✅ [{order_time_str} 주문 집행] 매수 주문 집행 완료: {len(executed)}건 처리")
    except Exception as e:
        logger.error(f"❌ [{order_time_str} 주문 집행] 매수 주문 집행 실패: {e}")

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

                # 동적으로 설정에서 스크리닝 및 주문 발주 시각 조회
                (s_h, s_m), (o_h, o_m) = get_screening_and_order_times()

                # 3. 종가 매수 스크리닝 (설정 시각)
                if hm == (s_h, s_m) and last_executed.get(f"screen_{s_h}_{s_m}") != today_str:
                    last_executed[f"screen_{s_h}_{s_m}"] = today_str
                    job_closing_price_screening()

                # 4. 주문 발주 (스크리닝 5분 뒤)
                if hm == (o_h, o_m) and last_executed.get(f"orders_{o_h}_{o_m}") != today_str:
                    last_executed[f"orders_{o_h}_{o_m}"] = today_str
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
    global _scheduler, _lock_held_elsewhere
    if _scheduler is not None and getattr(_scheduler, "running", False):
        logger.info("스케줄러가 이미 실행 중입니다.")
        return _scheduler

    if not _acquire_process_lock():
        _lock_held_elsewhere = True
        logger.warning(f"다른 프로세스(또는 이전 로드된 모듈)에서 스케줄러가 이미 실행 중이어서 시작하지 않습니다. ({SCHEDULER_LOCK_FILE})")
        return None
    _lock_held_elsewhere = False

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
            replace_existing=True,
            misfire_grace_time=60,
            coalesce=True
        )
        _scheduler.add_job(
            job_intraday_monitoring,
            CronTrigger(day_of_week="mon-fri", hour=15, minute="0,5", timezone="Asia/Seoul"),
            id="job_intraday_monitoring_afternoon",
            replace_existing=True,
            misfire_grace_time=60,
            coalesce=True
        )

        # 설정에서 스크리닝 및 주문 발주 시각 동적 로드
        (s_h, s_m), (o_h, o_m) = get_screening_and_order_times()

        # 3. 종가 매수 스크리닝 (설정 시각, 기본 15:10)
        _scheduler.add_job(
            job_closing_price_screening,
            CronTrigger(day_of_week="mon-fri", hour=s_h, minute=s_m, timezone="Asia/Seoul"),
            id="job_1510_closing_screening",
            replace_existing=True
        )

        # 4. 주문 발주 (스크리닝 5분 뒤, 기본 15:15)
        _scheduler.add_job(
            job_execute_buy_orders,
            CronTrigger(day_of_week="mon-fri", hour=o_h, minute=o_m, timezone="Asia/Seoul"),
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
        logger.info(f"APScheduler 5단계 일일 타임라인 스케줄러 구동 완료 (09:00 / 장중5분 / {s_h:02d}:{s_m:02d} / {o_h:02d}:{o_m:02d} / 15:30 KST)")
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
