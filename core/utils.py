import logging
import getpass
import random
import shutil
import sys
import os

from datetime import datetime
import pytz
import platform

import psutil

# Явные platform-specific импорты. Не оборачиваем в try/except —
# это намеренно: при сборке в exe зависимость должна быть явной.
# На Windows требуется пакет WMI (имя пакета в pip: WMI).
wmi = None
if sys.platform.startswith('win'):
    import wmi  # type: ignore


log = logging.getLogger("Utilits")

def get_username():
    """
    Пытается получить имя пользователя (логин) системы.
    """
    try:
        # getpass.getuser() более надёжен в некоторых средах
        # (например, в cron-заданиях)
        username = getpass.getuser()
    except Exception:
        # Fallback на os.getlogin()
        try:
            username = os.getlogin()
        except OSError:
            # os.getlogin() может упасть, если скрипт запущен
            # без TTY, поэтому проверяем окружение
            username = os.environ.get('USER') or os.environ.get('USERNAME')
    
    if username:
        return username
    else:
        return "user"

def clear_folder(folder_path):
    """
    Очищает указанную папку, удаляя все файлы и подпапки.
    Пропускает файлы, которые не могут быть удалены (например, заблокированные).
    """
    log.info(f"Начало очистки папки: {folder_path}")
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)
                log.info(f"Удален файл: {file_path}")
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
                log.info(f"Удалена директория: {file_path}")
        except Exception as e:
            log.error(f"Не удалось удалить {file_path}. Причина: {e}")
    log.info(f"Очистка папки {folder_path} завершена.")

def get_random_file_path(directory, file_extension):
    # Добавляем точку к расширению, если её нет
    if not file_extension.startswith('.'):
        file_extension = '.' + file_extension
    
    # Проверяем существование директории
    if not os.path.isdir(directory):
        raise ValueError(f"Директория '{directory}' не существует или не является папкой")
    
    # Получаем список файлов с нужным расширением
    matching_files = [
        os.path.join(directory, f) for f in os.listdir(directory)
        if (os.path.isfile(os.path.join(directory, f)) and 
            f.lower().endswith(file_extension.lower()))
    ]
    
    # Выбираем случайный файл из списка
    if not matching_files:
        return None
    
    random_file = random.choice(matching_files)
    return os.path.abspath(random_file)

def sanitize_filename(name):
    """
    Преобразует строку в безопасное имя файла/путь:
    1. Переводит в нижний регистр.
    2. Удаляет акценты и не-ASCII символы (например, кириллицу преобразует в латиницу).
    3. Заменяет пробелы и другие небезопасные символы на подчеркивания или дефисы.
    4. Удаляет повторяющиеся дефисы/подчеркивания.
    5. Обрезает по краям.
    """
    if not isinstance(name, str):
        log.warning(f"Попытка санировать не-строковое значение: {type(name)}. Преобразую в строку.")
        name = str(name)

    from slugify import slugify
    sanitized_name = slugify(name, separator='_')
    log.debug(f"Имя '{name}' санировано с slugify до '{sanitized_name}'")
    return sanitized_name

def get_openvpn_config_path(network_name):
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0])) # sys.argv[0] - путь к запускаемому скрипту/exe
    tmp_dir = os.path.join(base_dir, '.tmp')
    config_filename = f"{sanitize_filename(network_name)}.conf"
    
    # Формируем полный путь к файлу конфигурации
    full_config_path = os.path.join(tmp_dir, config_filename)
    
    log.debug(f"Поиск конфига OpenVPN: '{full_config_path}'")

    if os.path.exists(full_config_path):
        return full_config_path
    else:
        return None

def get_current_time(time_only = False):
    # Получаем текущее время
    now_utc = datetime.utcnow()

    # Определяем часовой пояс машины
    try:
        from tzlocal import get_localzone
        local_tz = get_localzone()
    except ImportError:
        # Если tzlocal не установлен, можно попробовать pytz.reference.LocalTimezone(),
        local_tz = pytz.reference.LocalTimezone()

    # Приводим UTC время к локальному часовому поясу
    current_local_time = now_utc.replace(tzinfo=pytz.utc).astimezone(local_tz)

    # Форматируем время в нужный вид
    if time_only:
        formatted_time = current_local_time.strftime("<b>[%H:%M:%S]</b> ")
    
    else:
        formatted_time = current_local_time.strftime("<b>[%d.%m.%Y %H:%M:%S]</b> ")

    return formatted_time

def is_linux():
    """Проверяет, является ли текущая ОС Linux."""
    return sys.platform.startswith('linux')

def is_windows():
    """Проверяет, является ли текущая ОС Windows."""
    return sys.platform.startswith('win')

def is_mac():
    """Проверяет, является ли текущая ОС macOS."""
    return sys.platform.startswith('darwin')

def get_os_string():
    if sys.platform.startswith('linux'): return 'linux'
    elif sys.platform.startswith('win'): return 'windows'
    elif sys.platform.startswith('darwin'): return 'macos'
    else: return 'unknown'
    

def get_system_specs():
    """Собирает технические характеристики устройства.

    Возвращает словарь совместимый с /api/report_specs.
    Значения могут отсутствовать (None) — сервер их проигнорирует.
    """
    specs = {}
    try:
        # CPU модель
        cpu_model = platform.processor() or None
        # На Windows попробуем уточнить через WMI (если доступен).
        # Импорт wmi выполняется вверху модуля — это даёт сборщикам exe
        # явную зависимость и позволяет быстрее обнаруживать ошибки.
        if not cpu_model and is_windows() and wmi is not None:
            try:
                c = wmi.WMI()
                for cpu in c.Win32_Processor():
                    cpu_model = cpu.Name
                    break
            except Exception as e:
                log.debug(f"WMI: ошибка при чтении модели CPU: {e}")
        specs['cpu_model'] = cpu_model

        # Количество ядер и потоков
        if psutil:
            specs['cpu_cores'] = psutil.cpu_count(logical=False)
            specs['cpu_threads'] = psutil.cpu_count(logical=True)
        else:
            specs['cpu_cores'] = None
            specs['cpu_threads'] = None

        # RAM total MB
        if psutil:
            try:
                vm = psutil.virtual_memory()
                specs['ram_total_mb'] = int(vm.total / (1024 * 1024))
            except Exception:
                specs['ram_total_mb'] = None
        else:
            specs['ram_total_mb'] = None

        specs['os_name'] = platform.system() or None
        specs['os_version'] = platform.version() or None
        specs['machine'] = platform.machine() or None
    except Exception as e:
        log.exception(f"Ошибка при сборе системных характеристик: {e}")
    return specs


def _get_cpu_temperature():
    """Пытается получить температуру CPU.
    Возвращает float или None, если недоступно.
    На Windows пробует WMI, на остальных — psutil.sensors_temperatures.
    """
    # Пытаемся получить температуру через WMI на Windows (если модуль доступен).
    try:
        if is_windows() and wmi is not None:
            try:
                c = wmi.WMI(namespace="root\\wmi")
                temps = []
                # MSAcpi_ThermalZoneTemperature возвращает CurrentTemperature в десятых долях Кельвина
                for sensor in c.MSAcpi_ThermalZoneTemperature():
                    try:
                        kelvin = sensor.CurrentTemperature / 10.0
                        celsius = kelvin - 273.15
                        if -20 < celsius < 120:  # sanity-check
                            temps.append(celsius)
                    except Exception:
                        # Пропускаем сенсоры с некорректными данными
                        continue
                if temps:
                    return round(sum(temps) / len(temps), 1)
            except Exception as e:
                log.debug(f"WMI: ошибка при чтении температуры CPU: {e}")

        # Универсальный метод через psutil (должен работать на Linux/macOS и там, где есть сенсоры)
        if psutil and hasattr(psutil, 'sensors_temperatures'):
            try:
                data = psutil.sensors_temperatures()
                if not data:
                    return None
                # Предпочитаем coretemp, иначе берем первый набор сенсоров
                if 'coretemp' in data:
                    entries = data['coretemp']
                else:
                    entries = next(iter(data.values()))
                temps = [getattr(e, 'current', None) for e in entries if getattr(e, 'current', None) is not None]
                if temps:
                    return round(sum(temps) / len(temps), 1)
            except Exception as e:
                log.debug(f"psutil: ошибка при получении температуры: {e}")
    except Exception as e:
        # Логируем неожиданные ошибки на уровне debug — функция не должна ломать остальную логику
        log.debug(f"Ошибка получения температуры CPU: {e}")

    return None


def get_system_metrics():
    """Собирает текущие метрики нагрузки.

    Возвращает словарь для /api/report_metrics. Некоторые поля опциональны.
    Обязательные: cpu_temp_c (может быть -1 если недоступно), cpu_usage_pct, mem_used_mb.
    """
    metrics = {}
    try:
        # Использование CPU (короткий интервал для усреднения).
        if psutil:
            try:
                metrics['cpu_usage_pct'] = psutil.cpu_percent(interval=0.5)
            except Exception:
                metrics['cpu_usage_pct'] = None
        else:
            metrics['cpu_usage_pct'] = None

        # Температура CPU
        metrics['cpu_temp_c'] = _get_cpu_temperature()

        # Память
        if psutil:
            try:
                vm = psutil.virtual_memory()
                metrics['mem_total_mb'] = int(vm.total / (1024 * 1024))
                metrics['mem_used_mb'] = int((vm.total - vm.available) / (1024 * 1024))
                # Процент можем вычислить, но он опционален
                metrics['mem_usage_pct'] = round(vm.percent, 2)
            except Exception:
                metrics['mem_total_mb'] = None
                metrics['mem_used_mb'] = None
                metrics['mem_usage_pct'] = None
        else:
            metrics['mem_total_mb'] = None
            metrics['mem_used_mb'] = None
            metrics['mem_usage_pct'] = None

        # Диск (основной системный)
        if psutil:
            try:
                if is_windows():
                    system_drive = os.getenv('SystemDrive', 'C:') + '\\'
                    du = psutil.disk_usage(system_drive)
                else:
                    du = psutil.disk_usage('/')
                metrics['disk_total_mb'] = int(du.total / (1024 * 1024))
                metrics['disk_used_mb'] = int(du.used / (1024 * 1024))
                metrics['disk_usage_pct'] = round(du.percent, 2)
            except Exception:
                metrics['disk_total_mb'] = None
                metrics['disk_used_mb'] = None
                metrics['disk_usage_pct'] = None
        else:
            metrics['disk_total_mb'] = None
            metrics['disk_used_mb'] = None
            metrics['disk_usage_pct'] = None

        # Временная метка ISO 8601 (UTC)
        metrics['timestamp'] = datetime.utcnow().isoformat(timespec='seconds')
    except Exception as e:
        log.exception(f"Ошибка при сборе метрик системы: {e}")
    return metrics