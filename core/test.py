import json
import os
import secrets
import socket
import subprocess
import sys
import time
from typing import Dict, Optional, Tuple

from core.utils import is_windows
from core.logger import setup_logger

# === INIT LOGGER ===
temp_log = setup_logger(agent_name="service_manager")
temp_log.warning("Я охуел...")

# === CONSTANTS ===
SERVICE_NAME = "PLACSAgentAdminService"
SERVICE_DISPLAY_NAME = "PLACS Agent Admin Service"
SERVICE_DESCRIPTION = "Executes PLACS privileged Windows operations without repeated UAC prompts."
SERVICE_HOST = "127.0.0.1"
SERVICE_PORT = 48761

SERVICE_STATUS_MISSING = "missing"
SERVICE_STATUS_RUNNING = "running"
SERVICE_STATUS_STOPPED = "stopped"
SERVICE_STATUS_START_PENDING = "start_pending"
SERVICE_STATUS_ERROR = "error"

SERVICE_SETTINGS_KEY = "admin/serviceConfigured"
CONFIRM_SETTINGS_KEY = "admin/confirmPrivilegedRequests"


# === HELPERS ===

def get_runtime_dir() -> str:
    temp_log.debug("[SM001] Определение runtime директории")
    if getattr(sys, "frozen", False):
        path = os.path.dirname(os.path.abspath(sys.executable))
        temp_log.debug(f"[SM002] frozen режим, путь: {path}")
        return path

    path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    temp_log.debug(f"[SM003] обычный режим, путь: {path}")
    return path


def get_service_token_path() -> str:
    path = os.path.join(get_runtime_dir(), ".admin_service_token")
    temp_log.debug(f"[SM004] Путь к токену: {path}")
    return path


def get_or_create_service_token() -> str:
    token_path = get_service_token_path()
    temp_log.info("[SM010] Получение или создание токена службы")

    if os.path.exists(token_path):
        temp_log.debug("[SM011] Токен файл существует")
        with open(token_path, "r", encoding="utf-8") as token_file:
            token = token_file.read().strip()
            if token:
                temp_log.debug("[SM012] Токен успешно прочитан")
                return token

    temp_log.warning("[SM013] Токен отсутствует, создаём новый")
    token = secrets.token_hex(32)

    with open(token_path, "w", encoding="utf-8") as token_file:
        token_file.write(token)

    temp_log.info("[SM014] Новый токен создан")
    return token


def get_service_host_command() -> str:
    temp_log.debug("[SM020] Формирование команды запуска сервиса")

    if getattr(sys, "frozen", False):
        cmd = f'"{os.path.abspath(sys.executable)}" --service-host'
        temp_log.debug(f"[SM021] frozen команда: {cmd}")
        return cmd

    main_script = os.path.join(get_runtime_dir(), "main.py")
    cmd = f'"{os.path.abspath(sys.executable)}" "{os.path.abspath(main_script)}" --service-host'
    temp_log.debug(f"[SM022] python команда: {cmd}")
    return cmd


def _get_control_entry(arguments):
    temp_log.debug(f"[SM030] Подготовка control entry: {arguments}")

    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable), list(arguments)

    main_script = os.path.join(get_runtime_dir(), "main.py")
    return os.path.abspath(sys.executable), [os.path.abspath(main_script)] + list(arguments)


def _run_sc_command(arguments) -> subprocess.CompletedProcess:
    temp_log.info(f"[SM040] Выполнение SC команды: {arguments}")

    result = subprocess.run(
        ["sc.exe"] + list(arguments),
        capture_output=True,
        text=True,
        check=False,
    )

    temp_log.debug(f"[SM041] Код возврата: {result.returncode}")
    temp_log.debug(f"[SM042] stdout: {result.stdout}")
    temp_log.debug(f"[SM043] stderr: {result.stderr}")

    return result


# === SERVICE STATUS ===

def query_service_status() -> Dict[str, str]:
    temp_log.info("[SM100] Запрос статуса службы")

    if not is_windows():
        temp_log.error("[SM101] Не Windows платформа")
        return {"status": SERVICE_STATUS_MISSING, "message": "Windows service is not supported on this platform."}

    result = _run_sc_command(["query", SERVICE_NAME])
    output = f"{result.stdout}\n{result.stderr}".strip()

    if result.returncode != 0:
        lowered = output.lower()
        if "does not exist" in lowered or "1060" in lowered:
            temp_log.warning("[SM102] Служба не установлена")
            return {"status": SERVICE_STATUS_MISSING, "message": output}
        temp_log.error("[SM103] Ошибка получения статуса")
        return {"status": SERVICE_STATUS_ERROR, "message": output}

    normalized = output.upper()

    if "RUNNING" in normalized:
        temp_log.info("[SM104] Служба запущена")
        return {"status": SERVICE_STATUS_RUNNING, "message": output}
    if "START_PENDING" in normalized:
        temp_log.info("[SM105] Служба запускается")
        return {"status": SERVICE_STATUS_START_PENDING, "message": output}
    if "STOPPED" in normalized:
        temp_log.info("[SM106] Служба остановлена")
        return {"status": SERVICE_STATUS_STOPPED, "message": output}

    temp_log.error("[SM107] Неизвестный статус")
    return {"status": SERVICE_STATUS_ERROR, "message": output}


def start_service() -> Tuple[bool, str]:
    temp_log.info("[SM110] Запуск службы")

    result = _run_sc_command(["start", SERVICE_NAME])
    output = f"{result.stdout}\n{result.stderr}".strip()

    if result.returncode == 0:
        temp_log.info("[SM111] Запуск успешен")
        return True, output

    lowered = output.lower()
    if "already running" in lowered or "1056" in lowered:
        temp_log.warning("[SM112] Уже запущена")
        return True, output

    temp_log.error("[SM113] Ошибка запуска")
    return False, output


def wait_for_service(expected_status=SERVICE_STATUS_RUNNING, timeout=20) -> Tuple[bool, str]:
    temp_log.info("[SM120] Ожидание статуса службы")

    deadline = time.time() + timeout
    last_message = ""

    while time.time() < deadline:
        status_info = query_service_status()
        last_message = status_info.get("message", "")

        if status_info.get("status") == expected_status:
            temp_log.info("[SM121] Достигнут нужный статус")
            return True, last_message

        time.sleep(1)

    temp_log.error("[SM122] Таймаут ожидания")
    return False, last_message


def ensure_service_running() -> Tuple[bool, str]:
    temp_log.info("[SM130] Проверка запущенности службы")

    status_info = query_service_status()
    status = status_info.get("status")

    if status == SERVICE_STATUS_RUNNING:
        temp_log.debug("[SM131] Уже работает")
        return True, status_info.get("message", "")

    if status in (SERVICE_STATUS_STOPPED, SERVICE_STATUS_START_PENDING):
        temp_log.warning("[SM132] Пробуем запустить")
        started, message = start_service()

        if not started:
            temp_log.error("[SM133] Не удалось запустить")
            return False, message

        return wait_for_service()

    temp_log.error("[SM134] Служба недоступна")
    return False, status_info.get("message", "")


# === EXECUTION ===

def _powershell_quote(value: str) -> str:
    return value.replace("'", "''")

def run_elevated_helper(arguments) -> Tuple[bool, str]:
    temp_log.info(f"[SM200] Запуск elevated helper: {arguments}")

    executable, args = _get_control_entry(arguments)

    arg_list = ", ".join(f"'{_powershell_quote(arg)}'" for arg in args)

    ps_command = (
        f"$p = Start-Process -FilePath '{executable}' "
        f"-ArgumentList @({arg_list}) -Verb RunAs -Wait -PassThru; "
        "exit $p.ExitCode"
    )

    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_command],
        capture_output=True,
        text=True,
        check=False,
    )

    output = f"{result.stdout}\n{result.stderr}".strip()

    if result.returncode == 0:
        temp_log.info("[SM201] Elevated выполнен успешно")
    else:
        temp_log.error("[SM202] Ошибка elevated запуска")

    return result.returncode == 0, output


def send_service_request(payload: Dict, timeout=30) -> Tuple[bool, Dict]:
    temp_log.info(f"[SM300] Отправка запроса в сервис: {payload}")

    payload = dict(payload)
    payload["token"] = get_or_create_service_token()

    try:
        with socket.create_connection((SERVICE_HOST, SERVICE_PORT), timeout=timeout) as client:
            client.settimeout(timeout)

            client.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))

            response_chunks = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response_chunks.append(chunk)
                if b"\n" in chunk:
                    break

        raw_response = b"".join(response_chunks).decode("utf-8").strip()

        temp_log.debug(f"[SM301] Ответ: {raw_response}")

        return True, json.loads(raw_response) if raw_response else {"ok": False, "message": "Empty response"}

    except Exception as exc:
        temp_log.exception(f"[SM302] Ошибка сокета: {exc}")
        return False, {"ok": False, "message": str(exc)}


def execute_service_request(payload: Dict, timeout=30) -> Tuple[bool, Dict]:
    temp_log.info("[SM400] Выполнение сервисного запроса")

    service_ready, message = ensure_service_running()

    if not service_ready:
        temp_log.error("[SM401] Сервис не готов")
        return False, {"ok": False, "message": message}

    return send_service_request(payload, timeout=timeout)