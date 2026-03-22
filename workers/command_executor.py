# agent_executor.py (или где у тебя execute_command)
import subprocess
import sys
import os
import ctypes
import platform
import logging # Для логирования
from core.utils import get_openvpn_config_path, is_linux

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008
log = logging.getLogger(__name__) # Получаем логгер

def run_elevated_background(command_string):
    """
    Запускает команду в фоновом режиме с повышенными привилегиями.
    Не возвращает stdout/stderr, т.к. процесс отвязывается.
    command_string: строка, представляющая команду.
    Возвращает (True, "Message") при успешной попытке запуска, (False, "Error Message") при ошибке.
    """
    try:
        if platform.system() == "Windows":
            # Проверяем, запущен ли скрипт с правами администратора
            if ctypes.windll.shell32.IsUserAnAdmin():
                log.info(f"Launching command in background (already elevated): {command_string}")
                # Если уже админ, запускаем как отсоединенный процесс
                subprocess.Popen(
                    command_string, 
                    creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS, 
                    shell=True,
                    stdout=subprocess.DEVNULL, # Отправляем вывод в никуда
                    stderr=subprocess.DEVNULL  # чтобы не засорять логи и не висеть
                )
                return True, "Команда: '{}'. Была запущена в фоновом режиме с повышенными привелегиями."
            else:
                log.warning(f"Запрашиваю от пользователя повышения прав для запуска: '{command_string}'")
                # ShellExecuteW запускает новую программу, и она не будет связана с текущей консолью.
                # command_string разбиваем на программу и аргументы для ShellExecuteW
                # (предполагаем, что первое слово - это программа)
                parts = command_string.split(maxsplit=1)
                program = parts[0]
                args = parts[1] if len(parts) > 1 else ""

                ret_val = ctypes.windll.shell32.ShellExecuteW(None, "runas", program, args, None, 0) # 0 = SW_HIDE (скрыть окно)
                if ret_val <= 32: # ShellExecuteW возвращает число > 32 при успехе
                    log.error(f"Что-то не так при повышении прав для: {command_string}. Код ошибки: {ret_val}")
                    return False, f"Не удалось повысить привелегии. КОд ошибки: {ret_val}"
                log.info(f"Команда: '{program}' прошла процесс повышения прав (или не прошла, но запрос выполнен). Ответ получить не получится, это фоновый процесс.")
                return True, "Команда исполнена с повышеными правами. Подробный лог получить не удастся."
        else: # Unix-подобные системы
            log.info(f"Выполняю комманду в фоне от sudo: {command_string}")
            # nohup гарантирует, что процесс переживет закрытие родительского терминала
            # & запускает в фоне
            # preexec_fn=os.setpgrp отвязывает дочерний процесс от группы родителя
            full_command = f"nohup sudo {command_string} &"
            subprocess.Popen(
                full_command, 
                shell=True, 
                preexec_fn=os.setpgrp,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            return True, "Команда запущена в фоне с повышенными привелегиями."
    except Exception as e:
        log.error(f"Не известная ошибка при выполнении комманды '{command_string}' в фоне: {e}")
        return False, f"Что то не так: {e}"

def close_openvpn_connection():
    """
    Завершает все активные OpenVPN соединения.
    Запускается с повышенными привилегиями в фоновом режиме.
    """
    log.info("Попытка закрыть текущие OpenVPN соединения...")
    command_string = ""
    if platform.system() == "Windows":
        # Закрываем все процессы openvpn.exe. /F - принудительно, /IM - по имени образа.
        command_string = "taskkill /F /IM openvpn.exe"
    else: # Unix-подобные системы
        # Завершаем все процессы openvpn. -f - принудительно, -9 - SIGKILL
        command_string = "pkill -9 openvpn" # pkill более современный чем killall и умеет искать по имени
    
    if command_string:
        success, message = run_elevated_background(command_string)
        if success:
            log.info(f"Команда завершения OpenVPN отправлена: {message}")
            return True, message
        else:
            log.error(f"Не удалось отправить команду завершения OpenVPN: {message}")
            return False, message
    return False, "Не удалось определить команду завершения OpenVPN для текущей ОС."

def execute_command(command_data):
    """
    Выполняет команду на основе полученных данных.
    command_data: словарь с информацией о команде (type, command_text, title, message, duration и т.д.)
    Возвращает кортеж (status: str, output: str)
    """
    command_type = command_data.get("type")
    command_text = command_data.get("command_text")
    
    if command_type == 'bash':
        if not command_text:
            return "error", "Не указана команда для типа 'system'."
        
        log.info(f"Выполняю системную команду: {command_text}")
        
        # Защита от непредвиденных команд
        if command_text not in ["reboot", "shutdown", "update"]:
            return "error", f"Неизвестная системная команда: {command_text}. Допустимы только 'reboot', 'shutdown', 'update'."

        if is_linux():
            utils_script = "/usr/local/bin/placs-agent-system.sh"
            try:
                # На Linux используем скрипт-обёртку
                subprocess.Popen(['sudo', utils_script, command_text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "success", f"Системная команда '{command_text}' отправлена на выполнение."
            except Exception as e:
                log.error(f"Не удалось выполнить системную команду '{command_text}': {e}")
                return "error", f"Не удалось выполнить системную команду '{command_text}': {e}"
        
        else: # Windows
            if command_text == "update":
                return "error", "Операционная система не подходит для исполнения команды обновления."
            elif command_text == "reboot":
                command_string = "shutdown /r /t 15"
                success, message = run_elevated_background(command_string)
                return "success" if success else "error", message
            elif command_text == "shutdown":
                command_string = "shutdown /s /t 15"
                success, message = run_elevated_background(command_string)
                return "success" if success else "error", message

    elif command_type == 'network':
        network_name = command_data.get('command_text')
        if not network_name:
            return "error", "Имя сети не указано для команды 'network'."
        
        if network_name == 'close_all':
            status, message = close_openvpn_connection()
            if not status:
                return "error", message
            
            return "success", "Команда закрытия соединений исполнена."
        
        try:
            # --- Шаг 1: Закрываем текущие соединения OpenVPN ---
            log.info(f"Получена команда подключения к сети '{network_name}'. Закрываю предыдущие соединения.")
            close_openvpn_connection() # Вызываем новую функцию

            # --- Шаг 2: Получаем путь к конфигу OpenVPN ---
            openvpn_config_path = get_openvpn_config_path(network_name)
            if not openvpn_config_path:
                return "error", f"Конфигурация OpenVPN не найдена для сети: {network_name}"
            
            # --- Шаг 3: Запускаем OpenVPN с повышенными привилегиями в фоне ---
            # Путь к файлу конфига в кавычках для корректной обработки пробелов
            openvpn_command_string = f"openvpn --config \"{openvpn_config_path}\""
            
            success, message = run_elevated_background(openvpn_command_string)
            
            if success:
                log.info(f"Соединение OpenVPN с '{network_name}' инициировано в фоновом режиме: {message}")
                return "success", f"Соединение OpenVPN с '{network_name}' инициировано. {message}"
            else:
                log.error(f"Не удалось инициировать соединение OpenVPN с '{network_name}': {message}")
                return "error", f"Не удалось инициировать соединение с сетью '{network_name}': {message}"
        except Exception as e:
            log.error(f"Ошибка при обработке сетевой команды для {network_name}: {e}")
            return "error", f"Внутренняя ошибка при обработке сетевой команды: {e}"

    else:
        log.warning(f"Unknown command type received: {command_type}")
        return "error", f"Unknown command type: {command_type}"