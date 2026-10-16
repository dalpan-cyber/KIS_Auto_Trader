@echo off
chcp 65001 > nul
echo [KIS Auto Trader] Streamlit 웹 대시보드를 실행합니다...
py -m streamlit run app.py
pause
