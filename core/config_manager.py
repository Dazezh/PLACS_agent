import json
import os
import sys

base_dir = os.path.dirname(os.path.abspath(sys.argv[0])) # Путь к исполняемому файлу
# Формируем полный путь
CONFIG_FILE = os.path.join(base_dir, 'agent_config.json') 

def load_config():
    """Загружает конфигурацию агента из файла."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r') as f:
                conf = json.load(f)

                if isinstance(conf, dict):
                    return conf
        
        except:
            pass
        
    return {}

def save_config(config):
    """Сохраняет конфигурацию агента в файл."""
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=4)

def get_server_url():
    url = load_config().get('server_url')
    if isinstance(url, str):
        return url
    
    return None

def get_agent_token():
    token = load_config().get('auth_token')
    if isinstance(token, str):
        return token
    
    return None

def get_polling_interval():
    interval = load_config().get('polling_interval')
    if isinstance(interval, int):
        return interval
    
    return None

def get_debug_state():
    debug_state = load_config().get('DEBUG')
    if isinstance(debug_state, bool):
        return debug_state
    
    return False

# Вынесено в отдельную функцию просто потому что так удобнее
def set_debug_state(new_debug_state: bool):
    config = load_config()
    config["DEBUG"] = new_debug_state
    save_config(config)

def set_config(server_url: str, auth_token: str, polling_interval: int):
    config = {'server_url': server_url, 'auth_token': auth_token, 'polling_interval': polling_interval, 'DEBUG': get_debug_state()}
    save_config(config)