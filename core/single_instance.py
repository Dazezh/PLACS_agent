import atexit
import ctypes
import json
import os
import tempfile
from typing import Optional, Tuple


PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _is_windows() -> bool:
    return os.name == "nt"


def _process_exists(pid: int) -> bool:
    if pid <= 0:
        return False

    if _is_windows():
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        kernel32.CloseHandle(handle)
        return True

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _default_lock_path(app_name: str) -> str:
    safe_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in app_name)
    return os.path.join(tempfile.gettempdir(), f"{safe_name}.lock")


class SingleInstanceLock:
    def __init__(self, app_name: str, lock_path: Optional[str] = None):
        self.app_name = app_name
        self.lock_path = lock_path or _default_lock_path(app_name)
        self._acquired = False

    def acquire(self) -> Tuple[bool, Optional[int]]:
        current_pid = os.getpid()

        while True:
            payload = {"pid": current_pid}
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

            try:
                fd = os.open(self.lock_path, flags)
            except FileExistsError:
                existing_pid = self._read_pid()
                if existing_pid and _process_exists(existing_pid):
                    return False, existing_pid

                self._remove_stale_lock()
                continue

            with os.fdopen(fd, "w", encoding="utf-8") as lock_file:
                json.dump(payload, lock_file, ensure_ascii=False)

            self._acquired = True
            atexit.register(self.release)
            return True, None

    def release(self):
        if not self._acquired:
            return

        try:
            existing_pid = self._read_pid()
            if existing_pid == os.getpid() and os.path.exists(self.lock_path):
                os.remove(self.lock_path)
        except OSError:
            pass
        finally:
            self._acquired = False

    def _read_pid(self) -> Optional[int]:
        try:
            with open(self.lock_path, "r", encoding="utf-8") as lock_file:
                payload = json.load(lock_file)
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            return None

        pid = payload.get("pid")
        return pid if isinstance(pid, int) else None

    def _remove_stale_lock(self):
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass
        except OSError:
            pass
