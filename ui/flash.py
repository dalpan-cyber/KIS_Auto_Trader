"""
KIS Auto Trading - UI Flash Message Helper
st.rerun() 직후에도 사용자에게 결과 메시지를 보여주기 위한 1회성 토스트 큐
(time.sleep()으로 화면을 멈춰 메시지를 보여주던 방식 대체)
"""
import streamlit as st

_FLASH_KEY = "_flash_messages"


def flash(message: str, icon: str = "✅") -> None:
    """다음 렌더링 시 토스트로 표시할 메시지 등록"""
    message = message.removeprefix(icon).lstrip()
    st.session_state.setdefault(_FLASH_KEY, []).append((message, icon))


def render_flash() -> None:
    """등록된 메시지를 토스트로 표시하고 큐 비우기 (앱 상단에서 1회 호출)"""
    for message, icon in st.session_state.pop(_FLASH_KEY, []):
        st.toast(message, icon=icon)
