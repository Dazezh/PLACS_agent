import json
import os
import sys
import secrets

import keyring

try:
    from core.constant import PLACS_SERVER_URL
except ImportError:
    PLACS_SERVER_URL = None  # Значение по умолчанию, если импорт не удался

try:
    from core.constant import POOLING_INTERVAL
except ImportError:
    POOLING_INTERVAL = None

try:
    from core.constant import AUTH_TOKEN
except ImportError:
    AUTH_TOKEN = None

base_dir = os.path.dirname(os.path.abspath(sys.argv[0])) # Путь к исполняемому файлу
# Формируем полный путь
CONFIG_FILE = os.path.join(base_dir, 'agent_config.json')

# Имя сервиса для хранения токенов в keyring
SERVICE_NAME = "PLACSAgentCredentials"

# ЛЕГАСИ: путь к файлу токена администрирования (для миграции)
ADMIN_TOKEN_FILE = os.path.join(base_dir, '.admin_service_token')


def _kr_get(key: str):
    """Получение значения из keyring. Возвращает None, если ключ не найден."""
    try:
        return keyring.get_password(SERVICE_NAME, key)
    except Exception:
        return None


def _kr_set(key: str, value: str):
    """Установка значения в keyring."""
    try:
        keyring.set_password(SERVICE_NAME, key, value)
    except Exception:
        pass


def _kr_delete(key: str):
    """Удаление значения из keyring."""
    try:
        keyring.delete_password(SERVICE_NAME, key)
    except Exception:
        pass


def load_config():
    """Загружает конфигурацию агента из keyring."""
    config = {}

    for key in ('server_url', 'auth_token', 'polling_interval', 'DEBUG'):
        if key == 'server_url' and PLACS_SERVER_URL is not None:
            config[key] = PLACS_SERVER_URL
            continue
        if key == 'auth_token' and AUTH_TOKEN is not None:
            config[key] = AUTH_TOKEN
            continue
        if key == 'polling_interval' and POOLING_INTERVAL is not None:
            config[key] = POOLING_INTERVAL
            continue
        
        val = _kr_get(key)
        if val is not None:
            if key == 'polling_interval':
                try:
                    val = int(val)
                except (ValueError, TypeError):
                    continue
            elif key == 'DEBUG':
                val = val.lower() == 'true'
            config[key] = val

    return config

def save_config(config):
    """Сохраняет конфигурацию агента в keyring."""
    for key, value in config.items():
        _kr_set(key, str(value))

def get_server_url():
    if PLACS_SERVER_URL is not None:
        return PLACS_SERVER_URL

    url = _kr_get('server_url')
    if url:
        return url

    return None

def server_url_is_constant():
    """Проверяет, задан ли URL сервера в коде (константа)."""
    return PLACS_SERVER_URL is not None

def get_agent_token():
    if AUTH_TOKEN is not None:
        return AUTH_TOKEN

    token = _kr_get('auth_token')
    if token:
        return token

    return None

def agent_token_is_constant():
    """Проверяет, задан ли токен агента в коде (константа)."""
    return AUTH_TOKEN is not None

def get_polling_interval():
    if POOLING_INTERVAL is not None:
        return POOLING_INTERVAL

    interval = _kr_get('polling_interval')
    if interval is not None:
        try:
            return int(interval)
        except (ValueError, TypeError):
            pass

    return None

def polling_interval_is_constant():
    """Проверяет, задан ли интервал опроса в коде (константа)."""
    return POOLING_INTERVAL is not None

def get_debug_state():
    debug_state = _kr_get('DEBUG')
    if debug_state is not None:
        return debug_state.lower() == 'true'

    return False

# Вынесено в отдельную функцию просто потому что так удобнее
def set_debug_state(new_debug_state: bool):
    _kr_set('DEBUG', str(new_debug_state))


def get_service_token_path() -> str:
    """Возвращает путь к legacy-файлу токена администрирования (для миграции)."""
    return ADMIN_TOKEN_FILE


def get_or_create_service_token() -> str:
    """Получение или создание токена администрирования (keyring)."""
    token = _kr_get('admin_service_token')
    if token:
        return token

    # Проверяем legacy-файл
    token_path = get_service_token_path()
    if os.path.exists(token_path):
        try:
            with open(token_path, "r", encoding="utf-8") as token_file:
                token = token_file.read().strip()
                if token:
                    _kr_set('admin_service_token', token)
                    return token
        except Exception:
            pass

    # Генерируем новый токен
    token = secrets.token_hex(32)
    _kr_set('admin_service_token', token)
    return token


def set_config(server_url: str, auth_token: str, polling_interval: int):
    _kr_set('server_url', server_url)
    _kr_set('auth_token', auth_token)
    _kr_set('polling_interval', str(polling_interval))
    _kr_set('DEBUG', str(get_debug_state()))


# ============================================================
# LEGACY MIGRATION: переносит старые файлы в keyring и удаляет их
# ============================================================
def _migrate_legacy_files():
    """Переносит конфигурацию из старых файлов в keyring и удаляет их."""
    # 1. Миграция agent_config.json
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                conf = json.load(f)
            if isinstance(conf, dict):
                for key, value in conf.items():
                    if value is not None:
                        _kr_set(key, str(value))
            os.remove(CONFIG_FILE)
        except Exception:
            pass

    # 2. Миграция .admin_service_token
    token_path = get_service_token_path()
    if os.path.exists(token_path):
        try:
            with open(token_path, 'r', encoding='utf-8') as f:
                token = f.read().strip()
            if token:
                _kr_set('admin_service_token', token)
            os.remove(token_path)
        except Exception:
            pass


# Запускаем миграцию при импорте модуля
_migrate_legacy_files()