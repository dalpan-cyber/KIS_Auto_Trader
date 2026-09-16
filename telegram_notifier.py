"""
Telegram Notification Module
매수 성공 및 매도 추천 알림을 텔레그램 봇으로 전송
"""
import os
import logging
import threading
import requests
from html import escape as html_escape
from typing import Optional, Dict, Any, List

import app_config as config
from core.storage import safe_load_json, atomic_save_json
from time_utils import today

logger = logging.getLogger("TelegramNotifier")

# 매도 알림 중복 방지 기록 파일 (같은 날짜 + 같은 종목 + 같은 유형 중복 전송 방지)
SELL_NOTIFY_HISTORY_FILE = os.path.join(os.path.dirname(__file__), "sell_notify_history.json")


class TelegramNotifier:
    """텔레그램 봇을 통한 주문/신호 알림 전송 클래스"""

    _history_lock = threading.Lock()

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or config.TELEGRAM_BOT_TOKEN
        self.chat_id = chat_id or config.TELEGRAM_CHAT_ID
        self.api_base = f"https://api.telegram.org/bot{self.bot_token}" if self.bot_token else None

    @property
    def is_enabled(self) -> bool:
        """봇 토큰과 채팅 ID가 모두 설정되었는지 확인"""
        return bool(self.bot_token and self.chat_id)

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """
        텔레그램 메시지 전송

        Args:
            text: 전송할 메시지 본문
            parse_mode: HTML 또는 Markdown (기본: HTML)

        Returns:
            bool: 전송 성공 여부
        """
        # 설정에서 텔레그램 알림 활성화 여부 확인
        if not config.get_setting("telegram_enabled", False):
            logger.info("텔레그램 알림이 비활성화되어 있습니다. (설정 > 텔레그램 알림 활성화 필요)")
            return False

        if not self.is_enabled:
            logger.warning("텔레그램 봇 토큰 또는 채팅 ID가 설정되지 않아 알림을 전송하지 않습니다.")
            return False

        if not text:
            return False

        # 텔레그램 메시지 최대 길이 (4096자) 제한
        if len(text) > 4000:
            text = text[:4000] + "\n\n... (메시지가 길어 일부만 표시됩니다)"

        url = f"{self.api_base}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                logger.info("텔레그램 알림 전송 성공")
                return True
            else:
                logger.error(f"텔레그램 알림 전송 실패: HTTP {resp.status_code} - {data.get('description', '알 수 없는 오류')}")
                return False
        except requests.exceptions.SSLError as e:
            logger.error(f"텔레그램 SSL 인증 오류: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.error(f"텔레그램 연결 실패: {e}")
            return False
        except Exception as e:
            logger.error(f"텔레그램 알림 전송 중 예외 발생: {e}")
            return False

    def send_buy_success(
        self,
        name: str,
        code: str,
        qty: int,
        price: float,
        order_no: str = "",
        order_type: str = "시장가"
    ) -> bool:
        """매수 주문 성공 알림 전송"""
        total_amount = qty * price
        text = (
            "🟢 <b>종가 매수 주문 성공</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>종목:</b> {html_escape(name)} ({html_escape(code)})\n"
            f"🔢 <b>수량:</b> {qty:,}주\n"
            f"💰 <b>주문가:</b> {price:,.0f}원\n"
            f"💵 <b>총 주문액:</b> {total_amount:,.0f}원\n"
            f"📋 <b>주문 유형:</b> {html_escape(order_type)}\n"
        )
        if order_no:
            text += f"🆔 <b>주문 번호:</b> {html_escape(order_no)}\n"
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += f"⏰ {self._now_str()}"

        return self.send_message(text)

    def _load_sell_notify_history(self) -> Dict[str, List[str]]:
        """매도 알림 전송 이력 로드 (날짜 -> [code|sell_type] 목록)"""
        return safe_load_json(SELL_NOTIFY_HISTORY_FILE, default={})

    def _save_sell_notify_history(self, history: Dict[str, List[str]]) -> bool:
        """매도 알림 전송 이력 저장"""
        return atomic_save_json(SELL_NOTIFY_HISTORY_FILE, history)

    def _is_sell_notified(self, code: str, sell_type: str) -> bool:
        """
        같은 날짜 + 같은 종목 + 같은 유형의 매도 알림이 이미 전송되었는지 확인
        """
        date_str = today().strftime("%Y-%m-%d")
        key = f"{code}|{sell_type}"
        with self._history_lock:
            history = self._load_sell_notify_history()
            sent_keys = history.get(date_str, [])
            return key in sent_keys

    def _mark_sell_notified(self, code: str, sell_type: str) -> bool:
        """
        매도 알림 전송 이력에 기록 (같은 날짜 + 같은 종목 + 같은 유형 중복 방지)
        """
        date_str = today().strftime("%Y-%m-%d")
        key = f"{code}|{sell_type}"
        with self._history_lock:
            history = self._load_sell_notify_history()
            sent_keys = history.get(date_str, [])
            if key not in sent_keys:
                sent_keys.append(key)
                history[date_str] = sent_keys
                return self._save_sell_notify_history(history)
            return True

    def send_sell_recommendation(
        self,
        name: str,
        code: str,
        holding_qty: int,
        avg_buy_price: float,
        current_price: float,
        profit_rate: float,
        profit_loss: float,
        reasons: List[str],
        is_urgent: bool = False,
        sell_type: str = "매도"
    ) -> bool:
        """매도 추천 알림 전송 (같은 날짜 + 같은 종목 + 같은 유형 중복 전송 방지)"""
        # 중복 전송 방지: 같은 날짜 + 같은 종목 + 같은 유형이 이미 전송된 경우 스킵
        if self._is_sell_notified(code, sell_type):
            logger.info(f"[{name}({code})] 같은 날짜/종목/유형({sell_type}) 매도 알림이 이미 전송되어 중복 전송을 건너뜁니다.")
            return False

        icon = "🚨" if is_urgent else "⚠️"
        title = "긴급 손절 알림" if is_urgent else "매도 추천 신호"
        text = (
            f"{icon} <b>{title}</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>종목:</b> {html_escape(name)} ({html_escape(code)})\n"
            f"📋 <b>유형:</b> {html_escape(sell_type)}\n"
            f"📦 <b>보유 수량:</b> {holding_qty:,}주\n"
            f"💹 <b>평균 매입가:</b> {avg_buy_price:,.0f}원\n"
            f"📊 <b>현재가:</b> {current_price:,.0f}원\n"
            f"📈 <b>수익률:</b> {profit_rate:+.2f}%\n"
            f"💵 <b>평가 손익:</b> {profit_loss:+,.0f}원\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📝 <b>매도 사유:</b>\n"
        )
        for reason in reasons:
            text += f"• {html_escape(reason)}\n"
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += f"⏰ {self._now_str()}"

        sent = self.send_message(text)
        if sent:
            # 전송 성공 시 이력 기록 (다음 중복 전송 방지)
            self._mark_sell_notified(code, sell_type)
        return sent

    def send_sell_success(
        self,
        name: str,
        code: str,
        qty: int,
        price: float,
        order_no: str = "",
        order_type: str = "시장가"
    ) -> bool:
        """매도 주문 성공 알림 전송"""
        total_amount = qty * price
        text = (
            "🔴 <b>매도 주문 성공</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"📌 <b>종목:</b> {html_escape(name)} ({html_escape(code)})\n"
            f"🔢 <b>수량:</b> {qty:,}주\n"
            f"💰 <b>주문가:</b> {price:,.0f}원\n"
            f"💵 <b>총 매도액:</b> {total_amount:,.0f}원\n"
            f"📋 <b>주문 유형:</b> {html_escape(order_type)}\n"
        )
        if order_no:
            text += f"🆔 <b>주문 번호:</b> {html_escape(order_no)}\n"
        text += "━━━━━━━━━━━━━━━━━━\n"
        text += f"⏰ {self._now_str()}"

        return self.send_message(text)

    def send_daily_summary(
        self,
        buy_count: int,
        sell_count: int,
        holdings_count: int,
        buy_list: Optional[List[Dict[str, Any]]] = None,
        sell_list: Optional[List[Dict[str, Any]]] = None,
        top_candidates: Optional[List[Dict[str, Any]]] = None
    ) -> bool:
        """일일 스크리닝 요약 알림 전송 (15:10 종가 매수 및 매도 현황)"""
        text = (
            "📊 <b>15:10 종가 스크리닝 요약</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"🟢 <b>종가 매수 추천:</b> {buy_count}건\n"
            f"🔴 <b>매도 신호 감지:</b> {sell_count}건\n"
            f"📦 <b>현재 보유 종목:</b> {holdings_count}개\n"
        )

        if buy_list:
            text += "\n<b>🟢 종가 매수 추천 종목:</b>\n"
            for item in buy_list[:5]:
                buy_tag = "🔄 추가매수" if item.get("is_additional_buy") else "🆕 신규매수"
                score = item.get("score", 0)
                t_score = item.get("trend_score", 0)
                s_score = item.get("supply_score", 0)
                m_score = item.get("momentum_score", 0)
                f_score = item.get("futures_score")
                f_str = f"/선물 {f_score}" if f_score is not None else ""
                text += (
                    f"• {buy_tag} <b>{html_escape(item.get('name', ''))}</b> ({html_escape(item.get('code', ''))})\n"
                    f"  💰 {item.get('current_price', 0):,.0f}원 | 🎯 총 {score}점 (추세 {t_score}/수급 {s_score}/모멘텀 {m_score}{f_str})\n"
                )
        elif top_candidates:
            text += "\n<b>👀 [관망 후보 Top 3 (매수 추천 아님)]</b>\n"
            for item in top_candidates[:3]:
                score = item.get("score", 0)
                reason = item.get("disqualify_reason", "기준 미달")
                text += (
                    f"• <b>{html_escape(item.get('name', ''))}</b> ({html_escape(item.get('code', ''))})\n"
                    f"  💰 {item.get('current_price', 0):,.0f}원 | 📊 {score}점 ({html_escape(str(reason))})\n"
                )

        if sell_list:
            text += "\n<b>🔴 매도 추천 종목:</b>\n"
            for item in sell_list[:5]:
                urgent_tag = "🚨 [긴급]" if item.get("is_urgent") else "⚠️"
                sell_type = item.get("sell_type", "매도")
                text += (
                    f"• {urgent_tag} <b>{html_escape(item.get('name', ''))}</b> ({html_escape(item.get('code', ''))}) "
                    f"| {html_escape(sell_type)} | 수익률 {item.get('profit_rate', 0):+.2f}%\n"
                )

        text += "━━━━━━━━━━━━━━━━━━\n"
        text += f"⏰ {self._now_str()}"

        return self.send_message(text)

    def send_test_message(self) -> bool:
        """테스트 메시지 전송 (연결 확인용)"""
        text = (
            "✅ <b>텔레그램 알림 테스트</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "KIS Auto Trader 시스템에서 보낸 테스트 메시지입니다.\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"⏰ {self._now_str()}"
        )
        return self.send_message(text)

    @staticmethod
    def _now_str() -> str:
        """현재 시각 문자열 반환 (KST)"""
        from time_utils import now_str
        return now_str()


# 모듈 레벨 싱글톤 인스턴스
notifier = TelegramNotifier()