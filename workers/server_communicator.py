import requests
import json
import logging

from core.config_manager import get_server_url, get_agent_token, get_debug_state
from core.error_types import ErrorType
from core.ver import __version__
from core.utils import get_os_string

from urllib.parse import urljoin

# Получаем настроенный логгер
log = logging.getLogger('ServerCommunicator')
os = get_os_string()
run_type = "Standalone"
if get_debug_state():
    run_type = "Development"

log.info(f"Инициализация ServerCommunicator для ОС: {os}, версии агента: {__version__} ({run_type})")

def _get_headers(config_for_test={}):
    """Формирует заголовки с токеном аутентификации."""
    token = get_agent_token() if not config_for_test else config_for_test.get('auth_token')
    if not token:
        log.error("Токен агента не найден в конфигурации.")
        return {} # Возвращаем пустые заголовки, если токена нет
    return {"X-Auth-Token": token, "X-Agent-Version": __version__, "X-Agent-OS": os, "X-Agent-Run-Type": run_type, "Content-Type": "application/json"}

def get_commands():
    """Запрашивает список команд у сервера.
    Возвращает (список_команд, None) в случае успеха,
    или (None, {'type': ErrorType, 'message': str}) в случае ошибки.
    """
    server_url = get_server_url()
    if not server_url:
        log.error("URL сервера не указан в конфигурации.")
        # Возвращаем информацию об ошибке, так как это проблема конфигурации, влияющая на связь
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': "URL сервера не указан."}

    try:
        response = requests.get(urljoin(server_url, "/api/get_command"), headers=_get_headers())
        response.raise_for_status() # Выбросит исключение для HTTP ошибок (4xx, 5xx)
        commands_data = response.json()
        if not isinstance(commands_data, list):
            log.warning(f"Сервер вернул неожиданный формат команд (не список): {commands_data}")
            return None,  {'type': ErrorType.CRITICAL_APPLICATION, 'message': f"СЕРВЕР ВЕРНУЛ ЧТО ТО СТРАННОЕ: {commands_data if len(commands_data) < 10 else str(commands_data)[:10]}"}
        log.info(f"Получено {len(commands_data)} команд(ы) от сервера.")
        return commands_data, None # Успех, нет ошибки
    except requests.exceptions.ConnectionError as e:
        msg = f"Ошибка соединения с сервером: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg} # Сетевая ошибка
    except requests.exceptions.HTTPError as e:
        msg = f"HTTP ошибка {e.response.status_code} при получении команд: {e.response.text}"
        log.error(msg)
        # Если 401/403, это может быть критическая проблема с токеном
        if e.response.status_code in [401, 403]:
            return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': f"Ошибка авторизации: {e.response.status_code} - {e.response.text}"}
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg} # Другие HTTP ошибки как временные сетевые
    except requests.exceptions.RequestException as e:
        msg = f"Неизвестная сетевая ошибка при получении команд: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg} # Общие ошибки запросов как временные сетевые
    except json.JSONDecodeError as e:
        msg = f"Ошибка декодирования JSON ответа сервера при получении команд: {e}"
        log.error(msg)
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': msg} # Проблема с форматом ответа
    except Exception as e:
        msg = f"Непредвиденная критическая ошибка в get_commands: {e}"
        log.exception(msg) # Используем exception для вывода стека
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': msg} # Любая другая непредвиденная ошибка

def get_me(config_for_test={}):
    """Запрашивает информацию об агенте с сервера
    - config_for_test - опциональный аргумент, чтобы протестировать новую конфигурацию
    """
    if config_for_test:
        log.debug(f"Проводится проверка следующей конфигурации: {config_for_test}")

    server_url = get_server_url() if not config_for_test else config_for_test.get('server_url')

    if not server_url:
        log.error("URL сервера не указан в конфигурации.")
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': "URL сервера не указан."}

    try:
        response = requests.get(urljoin(server_url, "/api/get_me"), headers=_get_headers(config_for_test))
        response.raise_for_status() # Выбросит исключение для HTTP ошибок (4xx, 5xx)
        user_info = response.json()
        if not isinstance(user_info, dict):
            log.warning(f"Сервер вернул неожиданный формат ответа (не словарь): {user_info}")
            return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': f"СЕРВЕР ВЕРНУЛ ЧТО ТО СТРАННОЕ: {user_info  if len(user_info) < 10 else str(user_info)[:10]}"}
        return user_info, None
    except requests.exceptions.ConnectionError as e:
        msg = f"Ошибка соединения с сервером: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg} # Сетевая ошибка
    except requests.exceptions.HTTPError as e:
        msg = f"HTTP ошибка {e.response.status_code} при получении команд: {e.response.text}"
        log.error(msg)
        # Если 401/403, это может быть критическая проблема с токеном
        if e.response.status_code in [401, 403]:
            return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': f"Ошибка авторизации: {e.response.status_code} - {e.response.text}"}
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg} # Другие HTTP ошибки как временные сетевые
    except requests.exceptions.RequestException as e:
        msg = f"Неизвестная сетевая ошибка при получении информации о агенте: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg} # Общие ошибки запросов как временные сетевые
    except json.JSONDecodeError as e:
        msg = f"Ошибка декодирования JSON ответа сервера при получении информации о агенте: {e}"
        log.error(msg)
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': msg} # Проблема с форматом ответа
    except Exception as e:
        msg = f"Непредвиденная критическая ошибка в get_me: {e}"
        log.exception(msg) # Используем exception для вывода стека
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': msg} # Любая другая непредвиденная ошибка

def report_command_output(command_id, output, status="success"):
    """Отправляет отчет о выполнении команды на сервер."""
    server_url = get_server_url()
    if not server_url:
        log.error("URL сервера не указан в конфигурации.")
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': "URL сервера не указан."}

    report_data = {
        "command_id": command_id,
        "output": output,
        "status": status # Не используется в routes.py, но полезно для будущего
    }
    try:
        response = requests.post(urljoin(server_url, "/api/report_output"), json=report_data, headers=_get_headers())
        response.raise_for_status()
        log.info(f"Отчет о команде {command_id} отправлен. Статус: {status}")
        return response.json(), None
    except requests.exceptions.ConnectionError as e:
        msg = f"Ошибка соединения при отправке отчета для команды {command_id}: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except requests.exceptions.HTTPError as e:
        msg = f"HTTP ошибка {e.response.status_code} при отправке отчета для команды {command_id}: {e.response.text}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except requests.exceptions.RequestException as e:
        msg = f"Неизвестная сетевая ошибка при отправке отчета для команды {command_id}: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except Exception as e:
        msg = f"Непредвиденная критическая ошибка в report_command_output для команды {command_id}: {e}"
        log.exception(msg)
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': msg}

def send_log_to_server(log_type, message):
    """Отправляет лог на сервер."""
    server_url = get_server_url()
    if not server_url:
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': "URL сервера не указан."}

    log_data = {
        "log_type": log_type,
        "message": message
    }
    try:
        response = requests.post(urljoin(server_url, "/api/send_log"), json=log_data, headers=_get_headers())
        response.raise_for_status()
        log.debug(f"Лог '{log_type}' отправлен на сервер.")
    except requests.exceptions.ConnectionError as e:
        msg = f"Ошибка соединения при отправке лога '{log_type}': {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except requests.exceptions.HTTPError as e:
        msg = f"HTTP ошибка {e.response.status_code} при отправке лога '{log_type}': {e.response.text}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except requests.exceptions.RequestException as e:
        msg = f"Неизвестная сетевая ошибка при отправке лога '{log_type}': {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except Exception as e:
        msg = f"Непредвиденная критическая ошибка в send_log_to_server для типа '{log_type}': {e}"
        log.exception(msg)
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': msg}
    
    return None, None


def report_specs(specs_data):
    """Отправляет технические характеристики агента (идемпотентно).

    Возвращает (response_json, None) при успехе,
    или (None, {'type': ErrorType, 'message': str}) при ошибке.
    """
    server_url = get_server_url()
    if not server_url:
        log.error("URL сервера не указан в конфигурации.")
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': "URL сервера не указан."}

    try:
        response = requests.post(urljoin(server_url, "/api/report_specs"), json=specs_data, headers=_get_headers())
        response.raise_for_status()
        log.info("Спецификации устройства отправлены на сервер.")
        return response.json(), None
    except requests.exceptions.ConnectionError as e:
        msg = f"Ошибка соединения при отправке спецификаций: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except requests.exceptions.HTTPError as e:
        msg = f"HTTP ошибка {e.response.status_code} при отправке спецификаций: {e.response.text}"
        log.error(msg)
        if e.response.status_code in [401, 403]:
            return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': f"Ошибка авторизации: {e.response.status_code} - {e.response.text}"}
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except requests.exceptions.RequestException as e:
        msg = f"Неизвестная сетевая ошибка при отправке спецификаций: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except Exception as e:
        msg = f"Непредвиденная критическая ошибка в report_specs: {e}"
        log.exception(msg)
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': msg}


def report_metrics(metrics_data):
    """Отправляет текущие метрики нагрузки агента.

    Возвращает (response_json, None) при успехе,
    или (None, {'type': ErrorType, 'message': str}) при ошибке.
    Требуемые поля см. в API.md: cpu_temp_c, cpu_usage_pct, mem_used_mb.
    """
    server_url = get_server_url()
    if not server_url:
        log.error("URL сервера не указан в конфигурации.")
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': "URL сервера не указан."}

    try:
        response = requests.post(urljoin(server_url, "/api/report_metrics"), json=metrics_data, headers=_get_headers())
        response.raise_for_status()
        log.debug("Метрики системы отправлены на сервер.")
        return response.json(), None if response.text else ({"status": "ok"}, None)
    except requests.exceptions.ConnectionError as e:
        msg = f"Ошибка соединения при отправке метрик: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except requests.exceptions.HTTPError as e:
        msg = f"HTTP ошибка {e.response.status_code} при отправке метрик: {e.response.text}"
        log.error(msg)
        if e.response.status_code in [401, 403]:
            return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': f"Ошибка авторизации: {e.response.status_code} - {e.response.text}"}
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except requests.exceptions.RequestException as e:
        msg = f"Неизвестная сетевая ошибка при отправке метрик: {e}"
        log.error(msg)
        return None, {'type': ErrorType.NETWORK_TRANSIENT, 'message': msg}
    except Exception as e:
        msg = f"Непредвиденная критическая ошибка в report_metrics: {e}"
        log.exception(msg)
        return None, {'type': ErrorType.CRITICAL_APPLICATION, 'message': msg}