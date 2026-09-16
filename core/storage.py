"""
KIS Auto Trading - Safe Storage Module
다중 스레드 및 프로세스 환경에서 JSON 상태 파일의 동시성 안전 및 Atomic Write 보장
"""
import os
import json
import time
import logging
import tempfile
import threading
from typing import Any, Dict, Optional

logger = logging.getLogger("Storage")

# 프로세스 내 파일별 쓰기 락 관리
_file_locks: Dict[str, threading.Lock] = {}
_global_lock = threading.Lock()

def _get_lock_for_file(file_path: str) -> threading.Lock:
    norm_path = os.path.abspath(file_path)
    with _global_lock:
        if norm_path not in _file_locks:
            _file_locks[norm_path] = threading.Lock()
        return _file_locks[norm_path]

def safe_load_json(file_path: str, default: Any = None) -> Any:
    """
    JSON 파일을 안전하게 읽어옵니다. 파일이 손상되었거나 없는 경우 default를 반환합니다.
    """
    if not os.path.exists(file_path):
        return default if default is not None else {}

    lock = _get_lock_for_file(file_path)
    with lock:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    return default if default is not None else {}
                return json.loads(content)
        except Exception as e:
            logger.warning(f"JSON 파일 로드 실패 ({file_path}): {e}")
            return default if default is not None else {}

def atomic_save_json(file_path: str, data: Any, indent: int = 2, max_retries: int = 5) -> bool:
    """
    임시 파일에 먼저 기록한 후 os.replace()로 원자적(Atomic)으로 교체하여
    쓰기 도중 크래시나 읽기 충돌로 인한 JSON 손상을 방지합니다.
    Windows 파일 핸들 잠금 충돌 방지를 위한 지수 백오프 재시도 포함.
    """
    lock = _get_lock_for_file(file_path)
    dir_name = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(dir_name, exist_ok=True)

    with lock:
        temp_file_path = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=dir_name,
                delete=False,
                encoding="utf-8",
                suffix=".tmp"
            ) as tf:
                json.dump(data, tf, ensure_ascii=False, indent=indent)
                temp_file_path = tf.name

            # Windows에서 일시적 파일 잠금 시 재시도
            last_err = None
            for attempt in range(max_retries):
                try:
                    os.replace(temp_file_path, file_path)
                    return True
                except PermissionError as pe:
                    last_err = pe
                    time.sleep(0.01 * (attempt + 1))
                except Exception as e:
                    last_err = e
                    time.sleep(0.01 * (attempt + 1))

            if last_err:
                raise last_err
            return True
        except Exception as e:
            logger.error(f"Atomic JSON 저장 실패 ({file_path}): {e}")
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except Exception:
                    pass
            return False
