"""
한국투자증권 Open Trading API (KIS Developers) PyQt5 GUI 대시보드 (gui.py)
"""
import sys
import os
import logging
from typing import Dict, Any

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QTextEdit, QGroupBox, QSplitter, QStatusBar, QMessageBox
)
from PyQt5.QtCore import QTimer, Qt, pyqtSignal, QObject
from PyQt5.QtGui import QFont, QColor

import config
from kis_api import KISApiClient
from trader import TraderBot


class QTextEditLogger(logging.Handler, QObject):
    """QTextEdit 위젯으로 로그를 스트리밍하는 커스텀 로깅 핸들러"""
    log_signal = pyqtSignal(str)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)

    def emit(self, record):
        msg = self.format(record)
        self.log_signal.emit(msg)


class TradingDashboard(QMainWindow):
    """KIS Open API 자동 매매 대시보드 메인 윈도우"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("한국투자증권 KIS Open Trading API 자동 투자 시스템")
        self.resize(1200, 800)

        # 1. KIS API 및 봇 초기화
        self.api = KISApiClient()
        self.bot = TraderBot(self.api)

        # 2. UI 테마 및 레이아웃 구성
        self._apply_dark_theme()
        self._init_ui()

        # 3. 로깅 핸들러 연결 (중복 등록 방지)
        root_logger = logging.getLogger()
        for h in list(root_logger.handlers):
            if isinstance(h, QTextEditLogger):
                root_logger.removeHandler(h)
        self.log_handler = QTextEditLogger()
        self.log_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S"))
        self.log_handler.log_signal.connect(self._append_log)
        root_logger.addHandler(self.log_handler)

        # 4. 주기적 자동매매 타이머 (5초 간격)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer_tick)

        # 초기 계좌 및 토큰 설정 실행
        QTimer.singleShot(500, self._initial_setup)

    def _apply_dark_theme(self):
        """프리미엄 다크 모드 스타일시트 적용"""
        dark_stylesheet = """
        QMainWindow, QWidget {
            background-color: #121826;
            color: #E2E8F0;
            font-family: 'Malgun Gothic', 'Segoe UI', sans-serif;
            font-size: 10pt;
        }
        QGroupBox {
            font-weight: bold;
            border: 1px solid #2D3748;
            border-radius: 8px;
            margin-top: 10px;
            padding-top: 10px;
            background-color: #1A202C;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 8px;
            color: #38BDF8;
        }
        QPushButton {
            background-color: #2563EB;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 8px 16px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #1D4ED8;
        }
        QPushButton:pressed {
            background-color: #1E40AF;
        }
        QPushButton#btnStop {
            background-color: #DC2626;
        }
        QPushButton#btnStop:hover {
            background-color: #B91C1C;
        }
        QPushButton#btnRefresh {
            background-color: #0D9488;
        }
        QPushButton#btnRefresh:hover {
            background-color: #0F766E;
        }
        QTableWidget {
            background-color: #0F172A;
            gridline-color: #1E293B;
            border: 1px solid #1E293B;
            border-radius: 6px;
        }
        QHeaderView::section {
            background-color: #1E293B;
            color: #94A3B8;
            font-weight: bold;
            border: none;
            padding: 6px;
        }
        QTextEdit {
            background-color: #0F172A;
            border: 1px solid #1E293B;
            border-radius: 6px;
            color: #A7F3D0;
            font-family: 'Consolas', monospace;
        }
        QLabel#lblStatus {
            font-size: 11pt;
            font-weight: bold;
        }
        """
        self.setStyleSheet(dark_stylesheet)

    def _init_ui(self):
        """UI 컴포넌트 생성 및 배치"""
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)

        # ----------------------------------------------------
        # 상단: 헤더 및 계좌/서버 정보 요약 카드
        # ----------------------------------------------------
        top_group = QGroupBox("KIS Developers Open API 접속 정보")
        top_layout = QHBoxLayout(top_group)

        self.lbl_env = QLabel("접속 환경: 확인 중...")
        self.lbl_env.setObjectName("lblStatus")
        self.lbl_account = QLabel("계좌번호: -")
        self.lbl_cash = QLabel("예수금: 0 원")
        self.lbl_eval = QLabel("총 자산: 0 원")
        self.lbl_strategy = QLabel(f"전략: {config.STRATEGY_NAME}")

        top_layout.addWidget(self.lbl_env)
        top_layout.addWidget(self.lbl_account)
        top_layout.addWidget(self.lbl_cash)
        top_layout.addWidget(self.lbl_eval)
        top_layout.addWidget(self.lbl_strategy)

        main_layout.addWidget(top_group)

        # ----------------------------------------------------
        # 중단: 테이블 (보유 종목 현황 & 감시 종목 시세)
        # ----------------------------------------------------
        splitter = QSplitter(Qt.Horizontal)

        # 좌측: 보유 종목 현황
        holdings_group = QGroupBox("현재 계좌 보유 종목")
        holdings_layout = QVBoxLayout(holdings_group)
        self.tbl_holdings = QTableWidget(0, 5)
        self.tbl_holdings.setHorizontalHeaderLabels(["종목명", "보유수량", "평단가", "현재가", "수익률"])
        self.tbl_holdings.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        holdings_layout.addWidget(self.tbl_holdings)
        splitter.addWidget(holdings_group)

        # 우측: 매매 감시 대상 종목
        targets_group = QGroupBox("매매 감시 대상 종목")
        targets_layout = QVBoxLayout(targets_group)
        self.tbl_targets = QTableWidget(len(config.TARGET_STOCKS), 3)
        self.tbl_targets.setHorizontalHeaderLabels(["종목코드", "현재가", "상태"])
        self.tbl_targets.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

        for row, code in enumerate(config.TARGET_STOCKS):
            self.tbl_targets.setItem(row, 0, QTableWidgetItem(code))
            self.tbl_targets.setItem(row, 1, QTableWidgetItem("-"))
            self.tbl_targets.setItem(row, 2, QTableWidgetItem("대기 중"))

        targets_layout.addWidget(self.tbl_targets)
        splitter.addWidget(targets_group)

        # 우측2: 무한매수 현황
        infinite_group = QGroupBox("🇺🇸 라오어 무한매수 현황")
        infinite_layout = QVBoxLayout(infinite_group)
        infinite_stocks = getattr(config, "INFINITE_STOCKS", ["TQQQ", "SOXL"])
        self.tbl_infinite = QTableWidget(len(infinite_stocks), 8)
        self.tbl_infinite.setHorizontalHeaderLabels(["종목코드", "진행회차", "총예산($)", "평단가($)", "보유수량", "매도주문(수량/목표가)", "매수주문(수량/금액)", "상태"])
        self.tbl_infinite.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        infinite_layout.addWidget(self.tbl_infinite)
        splitter.addWidget(infinite_group)

        main_layout.addWidget(splitter, stretch=2)

        # ----------------------------------------------------
        # 하단: 제어 버튼 및 실시간 로그 창
        # ----------------------------------------------------
        ctrl_layout = QHBoxLayout()

        self.btn_start = QPushButton("▶ 자동매매 시작")
        self.btn_start.clicked.connect(self._start_auto_trading)

        self.btn_stop = QPushButton("⏹ 자동매매 정지")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.clicked.connect(self._stop_auto_trading)
        self.btn_stop.setEnabled(False)

        self.btn_refresh = QPushButton("🔄 잔고/시세 갱신")
        self.btn_refresh.setObjectName("btnRefresh")
        self.btn_refresh.clicked.connect(self._refresh_data)

        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        ctrl_layout.addWidget(self.btn_refresh)

        main_layout.addLayout(ctrl_layout)

        # 로그 창
        log_group = QGroupBox("실시간 이벤트 & 실행 로그")
        log_layout = QVBoxLayout(log_group)
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        log_layout.addWidget(self.txt_log)

        main_layout.addWidget(log_group, stretch=1)

        self.setCentralWidget(main_widget)

        # 상태바
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("준비 완료. KIS Open Trading API 연결됨.")

    def _initial_setup(self):
        """초기 계좌 정보 로드 및 환경 검증"""
        success = self.bot.initialize_account()
        is_mock = self.api.mock
        env_str = "<font color='#34D399'>🟢 모의투자 (VTS)</font>" if is_mock else "<font color='#F87171'>🔴 실전투자 (LIVE)</font>"
        
        acc_text = f"{self.api.cano}-{self.api.acnt_prdt_cd}" if self.api.cano else "설정필요(CANO)"
        self.lbl_env.setText(f"접속 환경: {env_str}")
        self.lbl_account.setText(f"계좌번호: {acc_text}")
        self._refresh_data()

    def _start_auto_trading(self):
        """자동 매매 루프 시작"""
        if self.bot.is_running:
            return
        self.bot.is_running = True
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.statusBar.showMessage("🚀 자동 매매가 시작되었습니다. (5초 간격 REST API 감시 중)")
        logging.info("===== KIS Open API 자동 매매 루프 시작 =====")
        self.timer.start(5000)

    def _stop_auto_trading(self):
        """자동 매매 루프 정지"""
        self.bot.is_running = False
        self.timer.stop()
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.statusBar.showMessage("⏹ 자동 매매가 정지되었습니다.")
        logging.info("===== KIS Open API 자동 매매 루프 정지 =====")

    def _refresh_data(self):
        """잔고 및 시세 즉시 갱신"""
        logging.info("계좌 잔고 및 종목 정보 갱신 중...")
        self.bot.fetch_account_balance()
        self.bot.sync_holdings_to_state()
        self._update_ui_tables()

    def _on_timer_tick(self):
        """주기적 매매 감시 실행 (타이머)"""
        if not self.bot.is_running:
            return

        self.bot.run_trading_cycle()
        self._update_ui_tables()

        # 승인 대기 중인 제안이 있을 경우 팝업창으로 사용자 승인 요청
        if self.bot.pending_proposals:
            for prop_id, prop in list(self.bot.pending_proposals.items()):
                msg = (
                    f"[{prop['stock_name']} ({prop['symbol']})] {prop['action_kr']} 제안이 발생했습니다!\n\n"
                    f"• 수량: {prop['qty']:,}주\n"
                    f"• 현재가: ₩{prop['price']:,.0f}\n"
                    f"• 예상 총액: ₩{prop['total_price']:,.0f}\n"
                    f"• 제안 사유: {prop['reason']}\n\n"
                    f"이 주문을 승인하고 한국투자증권에 제출하시겠습니까?"
                )
                reply = QMessageBox.question(
                    self,
                    f"💡 매매 제안 승인 요청 ({prop['action_kr']})",
                    msg,
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.Yes
                )
                if reply == QMessageBox.Yes:
                    self.bot.approve_proposal(prop_id)
                else:
                    self.bot.reject_proposal(prop_id)
            self._update_ui_tables()

    def _update_ui_tables(self):
        """UI 데이터 갱신 (예수금, 보유종목 테이블 등)"""
        self.lbl_cash.setText(f"예수금: {self.bot.available_cash:,.0f} 원")
        self.lbl_eval.setText(f"총 자산: {self.bot.total_eval_amount:,.0f} 원")

        # 1. 보유 종목 테이블 갱신
        self.tbl_holdings.setRowCount(len(self.bot.holdings))
        for row, (sym, h) in enumerate(self.bot.holdings.items()):
            self.tbl_holdings.setItem(row, 0, QTableWidgetItem(f"{h['name']}({sym})"))
            self.tbl_holdings.setItem(row, 1, QTableWidgetItem(str(h['qty'])))
            self.tbl_holdings.setItem(row, 2, QTableWidgetItem(f"{h['avg_price']:,.0f}"))
            self.tbl_holdings.setItem(row, 3, QTableWidgetItem(f"{h['current_price']:,.0f}"))

            pnl_rate = h.get("pnl_rate", 0.0)
            if pnl_rate == 0.0 and h['avg_price'] > 0 and h['current_price'] > 0:
                pnl_rate = ((h['current_price'] - h['avg_price']) / h['avg_price']) * 100

            item_pnl = QTableWidgetItem(f"{pnl_rate:+.2f}%")
            if pnl_rate > 0:
                item_pnl.setForeground(QColor("#F87171"))  # 빨간색 (상승)
            elif pnl_rate < 0:
                item_pnl.setForeground(QColor("#60A5FA"))  # 파란색 (하락)

            self.tbl_holdings.setItem(row, 4, item_pnl)

        # 2. 감시 종목 테이블 갱신
        for row, code in enumerate(config.TARGET_STOCKS):
            price = self.bot.current_prices.get(code, 0.0)
            price_text = f"{price:,.0f}원" if price > 0 else "-"
            self.tbl_targets.setItem(row, 1, QTableWidgetItem(price_text))

            status = "보유 중" if code in self.bot.holdings else "감시 중"
            self.tbl_targets.setItem(row, 2, QTableWidgetItem(status))

        # 3. 무한매수 현황 테이블 갱신
        if hasattr(self, "tbl_infinite"):
            infinite_stocks = getattr(config, "INFINITE_STOCKS", ["TQQQ", "SOXL"])
            self.tbl_infinite.setRowCount(len(infinite_stocks))
            for row, sym in enumerate(infinite_stocks):
                st = self.bot.infinite_state_mgr.get_symbol_state(sym)
                curr_round = st.get("current_round", 0)
                div_count = st.get("division_count", 40)
                budget = st.get("total_budget_usd", 10000.0)
                # 보유 수량/평단가는 KIS API 실계좌가 Source of Truth
                hld = self.bot.holdings.get(sym, {})
                avg_p = hld.get("avg_price", 0.0)
                qty = hld.get("qty", 0)
                roi = st.get("target_roi", 0.10)
                status = st.get("status", "IDLE")

                cur_p = self.bot.current_prices.get(sym, 0.0)
                calc_p = cur_p if cur_p > 0 else (avg_p if avg_p > 0 else 50.0)
                sample_orders = self.bot.infinite_strategy.generate_daily_orders(
                    sym, calc_p, st,
                    avg_price=avg_p, total_qty=qty
                )

                sell_orders = [o for o in sample_orders if o['action'] == 'SELL']
                buy_orders = [o for o in sample_orders if o['action'] == 'BUY']

                sell_str = f"{sell_orders[0]['qty']:,}주 @ ${sell_orders[0]['price']:.2f}" if sell_orders else "-"
                if buy_orders:
                    b_qty_sum = sum(b['qty'] for b in buy_orders)
                    b_amt_sum = sum(b['qty'] * b['price'] for b in buy_orders)
                    buy_str = f"{b_qty_sum:,}주 (${b_amt_sum:,.2f})"
                else:
                    buy_str = "매수중지" if status in ["STOPPED", "PAUSED"] else "-"

                self.tbl_infinite.setItem(row, 0, QTableWidgetItem(sym))
                self.tbl_infinite.setItem(row, 1, QTableWidgetItem(f"{curr_round}/{div_count} 회차"))
                self.tbl_infinite.setItem(row, 2, QTableWidgetItem(f"${budget:,.0f}"))
                self.tbl_infinite.setItem(row, 3, QTableWidgetItem(f"${avg_p:.2f}" if avg_p > 0 else "-"))
                self.tbl_infinite.setItem(row, 4, QTableWidgetItem(f"{qty}주"))
                self.tbl_infinite.setItem(row, 5, QTableWidgetItem(sell_str))
                self.tbl_infinite.setItem(row, 6, QTableWidgetItem(buy_str))
                self.tbl_infinite.setItem(row, 7, QTableWidgetItem(status))

    def _append_log(self, text: str):
        """로그 텍스트 추가"""
        self.txt_log.append(text)


def main():
    app = QApplication(sys.argv)
    window = TradingDashboard()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
