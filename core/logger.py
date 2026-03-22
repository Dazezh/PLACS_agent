import logging
import os
import sys
import datetime

# --- Константы и пути ---
# BASE_DIR - путь к директории, где находится исполняемый файл агента.
# Это важно для корректного размещения логов, особенно при сборке в exe (PyInstaller).
try:
    if getattr(sys, 'frozen', False): # Проверка, если приложение "заморожено" (например, PyInstaller)
        BASE_DIR = os.path.dirname(sys.executable)
    else:
        # В режиме разработки это будет директория, где лежит logger_config.py
        BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except Exception:
    BASE_DIR = os.getcwd() # Запасной вариант - текущая рабочая директория

LOG_FOLDER = os.path.join(BASE_DIR, 'logs')
DEFAULT_MAX_LOG_FOLDER_SIZE_MB = 100 

def _clean_old_logs(max_log_folder_size_mb):
    """
    Удаляет старые файлы логов в папке LOG_FOLDER, чтобы общий размер
    не превышал max_log_folder_size_mb.
    """
    if not os.path.exists(LOG_FOLDER):
        return

    # Получаем список всех лог-файлов с расширением .log
    # Игнорируем файлы, к которым нет доступа
    log_files_info = []
    for f_name in os.listdir(LOG_FOLDER):
        if f_name.endswith('.log'):
            file_path = os.path.join(LOG_FOLDER, f_name)
            try:
                log_files_info.append({
                    'path': file_path,
                    'size': os.path.getsize(file_path),
                    'mtime': os.path.getmtime(file_path) # Время последней модификации
                })
            except OSError:
                logging.warning(f"Не удалось получить информацию о файле: '{file_path}'")
                continue # Пропускаем файл, если нет доступа или он поврежден

    # Сортируем файлы от старых к новым по времени модификации
    log_files_info.sort(key=lambda x: x['mtime'])

    total_size_bytes = sum(f['size'] for f in log_files_info)
    max_size_bytes = max_log_folder_size_mb * 1024 * 1024 # Конвертируем МБ в байты

    # Начинаем логирование до того, как основной логгер будет полностью настроен.
    # Это временное сообщение, которое может пойти в консоль.
    print(f"[LogCleanup] Текущий размер папки логов: {total_size_bytes / (1024*1024):.2f} МБ / Макс: {max_log_folder_size_mb} МБ")

    while total_size_bytes > max_size_bytes and len(log_files_info) > 0:
        oldest_file = log_files_info.pop(0) # Берем самый старый файл из списка
        try:
            os.remove(oldest_file['path'])
            total_size_bytes -= oldest_file['size']
            print(f"[LogCleanup] Удален старый лог-файл: '{os.path.basename(oldest_file['path'])}' для уменьшения размера папки.")
        except OSError as e:
            print(f"[LogCleanup ERROR] Не удалось удалить старый лог-файл '{oldest_file['path']}': {e}")
            break # Останавливаем, если не можем удалить файл (например, из-за блокировки)

def setup_logger(agent_name="UNKNOWN_AGENT", initial_level="INFO", max_log_folder_size_mb=DEFAULT_MAX_LOG_FOLDER_SIZE_MB):
    """
    Настраивает корневой логгер для приложения.
    - Создает новый лог-файл для каждого запуска с именем агента и меткой времени.
    - Управляет общим размером папки логов.
    - Принимает имя агента, начальный уровень логирования и максимальный размер папки логов.
    """
    os.makedirs(LOG_FOLDER, exist_ok=True)

    _clean_old_logs(max_log_folder_size_mb)

    timestamp = datetime.datetime.now().strftime("%d-%m-%Y_%H-%M-%S")

    log_filename = f"agent_{agent_name}_{timestamp}.log"
    current_log_file_path = os.path.join(LOG_FOLDER, log_filename)

    # --- 3. Настройка корневого логгера ---
    root_logger = logging.getLogger()
    
    # Очищаем все существующие обработчики. Это критично,
    # чтобы избежать дублирования логов и перенастроить handler-ы.
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
        handler.close() # Важно закрыть хэндлеры, особенно файловые

    # Устанавливаем уровень логирования для корневого логгера
    numeric_level = getattr(logging, initial_level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    # Форматтер для всех обработчиков (консоль и файл)
    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(name)s - %(filename)s:%(lineno)d - %(message)s'
    )
    
    # Консольный обработчик (выводит в стандартный вывод/ошибки)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Файловый обработчик (пишет в новый уникальный файл для каждого запуска)
    # Используем FileHandler, так как ротация по размеру файла будет не нужна
    # (мы создаем новый файл каждый раз, а ротацию папки делаем сами)
    try:
        file_handler = logging.FileHandler(current_log_file_path, mode='a', encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    except Exception as e:
        # Если не можем создать лог-файл (например, из-за прав), продолжаем без него
        logging.error(f"Не удалось создать лог-файл '{current_log_file_path}': {e}. Логи будут только в консоли.")

    logging.info(f"Логирование настроено. Уровень: {initial_level}. Новый лог-файл: '{log_filename}'")
    logging.info(f"Максимальный размер папки логов: {max_log_folder_size_mb} МБ.")

    return root_logger, current_log_file_path


def set_global_log_level(level_str):
    """
    Устанавливает глобальный уровень логирования для всего приложения.
    Эта функция предназначена для изменения уровня логирования "на лету"
    без пересоздания файловых обработчиков.
    
    Args:
        level_str (str): Строковое представление уровня логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL).
    """
    numeric_level = getattr(logging, level_str.upper(), None)
    if not isinstance(numeric_level, int):
        # Если этот лог не виден, значит, уровень уже установлен слишком высоко
        logging.error(f"Неизвестный уровень логирования: '{level_str}'. Устанавливаю INFO по умолчанию.")
        numeric_level = logging.INFO
    
    # Устанавливаем уровень для корневого логгера
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Также обновляем уровень для всех существующих обработчиков, чтобы они
    # корректно фильтровали сообщения
    for handler in root_logger.handlers:
        handler.setLevel(numeric_level)

    logging.info(f"Глобальный уровень логирования изменен на: {level_str}")