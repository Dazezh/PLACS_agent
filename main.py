import sys
import os

# PyQt5 UI библиотеки
from PyQt5.QtWidgets import QApplication, QDialog, QMessageBox
from PyQt5.QtGui import QIcon
from PyQt5.QtCore import QThread, QSettings, QTimer

# Мои модули из разных папок
from core.logger import setup_logger
from core.config_manager import load_config, set_config, get_agent_token, get_server_url, get_debug_state
from ui.config_dialog import ConfigDialog
from ui.main_window import MainWindow
from ui.tray_icon import SystemTrayApp

from workers.agent_worker import AgentWorker, SystemMonitor
from workers.network_diagnoser import NetworkDiagnoser
from workers.hotkey_listener import GlobalHotkeyListener

from core.error_state_manager import ErrorStateManager
from core.single_instance import SingleInstanceLock
from core.windows_service_manager import (
    SERVICE_SETTINGS_KEY,
    SERVICE_STATUS_MISSING,
    SERVICE_STATUS_RUNNING,
    disable_service_cli,
    install_or_repair_service_elevated,
    install_service_cli,
    query_service_status,
    start_service,
)

from core.utils import is_windows, clear_folder
from core.ver import __assets_packet_version__, __version__

from urllib.parse import urlparse

# Глобальные переменные для логгера и UI элементов
log = None 
main_window = None
tray_icon = None
agent_thread = None # Переменная для потока
agent_worker = None # Переменная для рабочего объекта
error_state_manager = None
debug_pult_dialog = None
debug_pult_thread = None
hotkey_listener = None
system_monitor_thread = None
system_monitor = None

# Глобальный флаг для управления процессом выхода
_is_shutting_down_gracefully = False

DEBUG_MODE = get_debug_state()

def apply_qss_style(app, qss_file_path):
    """Загружает и применяет QSS стили ко всему приложению."""
    try:
        with open(qss_file_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
        if log:
            log.info(f"QSS стили загружены из {qss_file_path}")
        else:
            print(f"QSS стили загружены из {qss_file_path}")
    except FileNotFoundError:
        if log:
            log.error(f"Файл QSS стилей не найден: {qss_file_path}")
        else:
            print(f"Ошибка: Файл QSS стилей не найден: {qss_file_path}")
    except Exception as e:
        if log:
            log.error(f"Ошибка при загрузке QSS стилей: {e}")
        else:
            print(f"Ошибка при загрузке QSS стилей: {e}")

def start_update(app=None, reinstall=False, hide_process=True):
    """Запускает процесс обновления или переустановки."""
    
    executable_name = "update_placs.exe" if is_windows() else "./update_placs"
    update_args = []

    if reinstall:
        update_args.append('--reinstall')
    else:
        update_args.extend(['--agent-version', __version__])
        update_args.extend(['--assets-version', __assets_packet_version__])

    if hide_process:
        update_args.append('--hide-process')

    try:
        if not DEBUG_MODE:
            command = [executable_name] + update_args
            subprocess.Popen(command, shell=False) # shell=False безопаснее, если возможно
            print(f"Команда '{' '.join(command)}' запущена. Выход.")
        
        else:
            print("Приложение находится в режиме отладки. Обновление не будет запущено!")
        
        if app:
            app.quit() # Корректно завершаем Qt приложение, если оно было передано
        else:
            sys.exit(0) # Стандартный выход, если Qt-контура нет
            
    except Exception as e:
        print(f"Не удалось запустить обновление: {e}. Запускаю приложение.")
        pass

def _shutdown_core(final_action, app, main_window, power_off_title="Отключение...", power_off_reason="Требование пользователя.", delay_ms=2500):
    """
    Централизованно управляет процессом корректного завершения работы приложения.
    Останавливает все потоки и воркеры, после чего выполняет финальное действие.
    """
    global _is_shutting_down_gracefully
    if _is_shutting_down_gracefully:
        return

    _is_shutting_down_gracefully = True
    log.info(f"Запускаю последовательность завершения. Причина: {power_off_reason}")

    # 1. Показываем прощальный экран
    main_window.power_off(power_off_title, power_off_reason)
    
    # 2. Останавливаем все фоновые процессы
    log.debug("Останавливаю фоновые процессы и потоки...")
    agent_worker.stop_polling()
    agent_thread.quit()
    network_diagnoser_thread.quit()
    if system_monitor:
        try:
            system_monitor.stop()
        except Exception:
            pass
    if system_monitor_thread:
        system_monitor_thread.quit()
    
    if hotkey_listener:
        hotkey_listener.stop()
    
    base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    tmp_dir = os.path.join(base_dir, '.tmp')

    # 3. Очистка временных файлов
    log.info("Очистка временных файлов...")
    clear_folder(tmp_dir)
    
    # 4. Устанавливаем таймер для финального действия
    log.info(f"Финальное действие будет выполнено через {delay_ms / 1000:.1f} сек.")
    QTimer.singleShot(delay_ms, final_action)

def ensure_windows_admin_service_ready(app, window):
    if not is_windows():
        return True

    settings = QSettings("PLACS", "Agent")
    configured_before = settings.value(SERVICE_SETTINGS_KEY, False, type=bool)
    status_info = query_service_status()
    status = status_info.get("status")

    if status not in (SERVICE_STATUS_MISSING, SERVICE_STATUS_RUNNING):
        start_service()
        status_info = query_service_status()
        status = status_info.get("status")

    if status == SERVICE_STATUS_RUNNING:
        settings.setValue(SERVICE_SETTINGS_KEY, True)
        return True

    dialog_result, accepted_setup = window.show_service_setup_window(retry_mode=configured_before)
    if dialog_result != QDialog.Accepted or not accepted_setup:
        app.quit()
        return False

    setup_ok, setup_message = install_or_repair_service_elevated()
    if not setup_ok:
        QMessageBox.critical(
            window,
            "Служба не настроена",
            f"Не удалось завершить настройку службы.\n\n{setup_message}",
        )
        app.quit()
        return False

    settings.setValue(SERVICE_SETTINGS_KEY, True)
    return True


def initialize_agent_ui_and_config():
    """Инициализирует QApplication, загружает конфиг и настраивает UI."""
    global log, main_window, tray_icon, agent_thread, agent_worker, error_state_manager
    global network_diagnoser_thread, network_diagnoser, hotkey_listener
    global system_monitor_thread, system_monitor

    app = QApplication(sys.argv)

    settings = QSettings("PLACS", "Agent")

    app.setQuitOnLastWindowClosed(False) 

    icon_path = 'ui/media/img/PLACS_ICON.ico'
    
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    else:
        print("Внимание: Файл 'PLACS_ICON.ico' не найден. Иконка приложения не установлена.")

    qss_file_path = 'ui/media/style.qss'
    apply_qss_style(app, qss_file_path)

    # Загружаем конфигурацию клиента для проверки
    config = load_config()
    server_url = config.get('server_url')
    auth_token = config.get('auth_token')

    # Перепроверяем URL (мало-ли пользователь мудак)
    parsed_url = urlparse(server_url)
    is_valid_hypertext_url = parsed_url.scheme.lower() in ['http', 'https'] and parsed_url.netloc

    if not is_valid_hypertext_url:
        QMessageBox.critical(app, "Ошибка", "Введён некорректный адрес сервера. Пожалуйста, убедитесь, что это полная ссылка (например, https://example.com).")
        return

    if not server_url or not auth_token:
        temp_log, log_path = setup_logger(agent_name="initial_setup") 
        temp_log.warning("Конфигурация агента отсутствует или неполна. Запускаю UI для настройки.")
        
        dialog = ConfigDialog()
        if dialog.exec_() == QDialog.Accepted:
            server_url = dialog.server_url
            auth_token = dialog.auth_token
            polling_interval = dialog.polling_interval
            set_config(server_url, auth_token, polling_interval)
            temp_log.info("Настройки агента сохранены.")
        else:
            temp_log.error("Настройка агента отменена. Агент не будет запущен.")
            sys.exit(1)
    
    # Настройка логирования с учётом настроек из GUI
    agent_id_from_token = get_agent_token()[:8] if get_agent_token() else "unknown"
    logging_level = settings.value("logging/level", "INFO", type=str)
    max_log_folder_size_mb = settings.value("logging/maxLogFolderSizeMB", 100, type=int)
    log, log_path = setup_logger(agent_name=agent_id_from_token, initial_level=logging_level, max_log_folder_size_mb=max_log_folder_size_mb)
    log.info("UI и конфигурация агента инициализированы.")

    error_state_manager = ErrorStateManager()

    main_window = MainWindow(DEBUG_MODE, log_path)
    if not ensure_windows_admin_service_ready(app, main_window):
        log.error("Служба Windows Admin Service не готова. Завершение работы приложения.")
        return False
    tray_icon = SystemTrayApp(icon_path, app, main_window)

    agent_thread = QThread() # Создаем экземпляр потока
    agent_worker = AgentWorker() # Создаем экземпляр рабочего объекта

    # Перемещаем рабочий объект в поток
    agent_worker.moveToThread(agent_thread)

    # --- Создание и инициализация NetworkDiagnoser ---
    network_diagnoser_thread = QThread()
    network_diagnoser = NetworkDiagnoser()
    network_diagnoser.moveToThread(network_diagnoser_thread)

    # --- Создание и инициализация SystemMonitor ---
    system_monitor_thread = QThread()
    system_monitor = SystemMonitor()
    system_monitor.moveToThread(system_monitor_thread)

    # Соединяем сигналы рабочего объекта со слотами UI
    agent_worker.status_update.connect(main_window.update_status)
    agent_worker.command_completed.connect(lambda cmd_id, status: tray_icon.show_message("PLACS Agent", f"Команда {cmd_id} завершена: {status}"))
    agent_worker.error_occurred.connect(error_state_manager.handle_error)
    agent_worker.show_display_message_signal.connect(main_window.handle_display_message)

    error_state_manager.ui_state_changed.connect(main_window.update_ui_for_error_state)
    error_state_manager.last_error_message_changed.connect(main_window.update_last_error_display)
    error_state_manager.trigger_diagnostic.connect(main_window.run_network_diagnostic)

    # Сигналы SystemMonitor в UI
    system_monitor.status_update.connect(main_window.update_status)
    system_monitor.error_occurred.connect(error_state_manager.handle_error)

    # ОТ MainWindow (кнопка "Перезапустить диагностику") К NetworkDiagnoser
    main_window.start_diagnostic_signal.connect(network_diagnoser.run_diagnostic)
    
    # ОТ MainWindow (кнопка "Попробовать исправить") К NetworkDiagnoser
    main_window.try_fix_network_signal.connect(network_diagnoser.try_to_fix_network)

    # ОТ NetworkDiagnoser К MainWindow для обновления UI диагностики
    network_diagnoser.check_status_update.connect(main_window.update_diagnostic_checklist)
    network_diagnoser.detail_output_update.connect(main_window.append_diagnostic_details)
    network_diagnoser.diagnostic_finished.connect(main_window.handle_diagnostic_finish)

    # ОТ NetworkDiagnoser К AgentWorker для управления циклом опроса
    network_diagnoser.request_polling_stop.connect(agent_worker.stop_polling)
    network_diagnoser.request_polling_start.connect(agent_worker.start_polling)

    # --- VPN сигналы ---
    main_window.request_vpn_refresh.connect(agent_worker.refresh_vpn_configs)
    main_window.request_vpn_connect.connect(agent_worker.connect_to_network)
    main_window.request_vpn_disconnect.connect(agent_worker.disconnect_from_network)
    agent_worker.vpn_configs_updated.connect(main_window.update_vpn_configs_view)
    agent_worker.vpn_operation_status.connect(main_window.handle_vpn_operation_status)
    
    def handle_app_quit_sequence(fast=False):
        shutdown_delay_ms = 100 if fast else 2500
        # Просто вызываем ядро завершения и передаем ему действие "выйти из приложения"
        _shutdown_core(app.quit, app, main_window, delay_ms=shutdown_delay_ms)
    
    def handle_app_restart(just_restart=False, reason="Обновление конфигурации."):
        if just_restart:
            tray_icon.show_message("PLASC Agent", reason)
            title = "Перезапуск..."
            # Готовим действие "запустить обновление"
            update_action = lambda: start_update(app=app, reinstall=False, hide_process=False)
        else:
            tray_icon.show_message("PLASC Agent", "Переустановка агента...")
            title = "Переустановка..."
            reason = "Полная переустановка..."
            # Готовим действие "запустить переустановку"
            update_action = lambda: start_update(app=app, reinstall=True, hide_process=False)

        # Вызываем ядро и передаем ему подготовленное действие
        _shutdown_core(update_action, app, main_window, power_off_title=title, power_off_reason=reason)
    
    main_window.restart_app = handle_app_restart

    # Привязываем сигнал запуска обновления
    agent_worker.start_update.connect(handle_app_restart)
    # Запускаем метод start_polling рабочего объекта, когда поток стартует
    agent_thread.started.connect(agent_worker.start_polling)
    # Запуск мониторинга при старте его потока
    system_monitor_thread.started.connect(system_monitor.start)

    # Подключаем наш управляющий слот к сигналу aboutToQuit
    app.setQuitOnLastWindowClosed(False)
    app.aboutToQuit.connect(handle_app_quit_sequence)
    tray_icon.exit_action.triggered.connect(handle_app_quit_sequence) 

    # Слушатель сочетаний клавиш запускаются только если пользователь хочет
    if settings.value("shortcuts/Enabled", True, type=bool) and is_windows():
        hotkey_listener = GlobalHotkeyListener()
        hotkey_listener.start()

    # --- DEBUG PULT ---
    if DEBUG_MODE:
        try:
            from ui.debug_pult import create_debug_pult_with_thread
            global debug_pult_dialog, debug_pult_thread
            debug_pult_dialog, debug_pult_thread, _worker = create_debug_pult_with_thread(main_window)

            # Прямые сигналы в главное окно
            debug_pult_dialog.request_state_change.connect(main_window.update_ui_for_error_state)
            debug_pult_dialog.request_exit.connect(lambda: handle_app_quit_sequence(fast=True))
            debug_pult_dialog.request_layout_by_id.connect(main_window.switch_layout)
            debug_pult_dialog.request_show_diagnostic.connect(main_window.switch_to_diagnostic_layout_and_start)
            debug_pult_dialog.request_status_text.connect(main_window.update_status)
            debug_pult_dialog.request_display_message.connect(main_window.handle_display_message)

            # Запускаем поток воркера
            debug_pult_thread.start()

            # Показываем «тоталитарный» пульт
            debug_pult_dialog.show()
        except Exception as e:
            if log:
                log.exception(f"Не удалось инициализировать Debug Пульт: {e}")
            else:
                print(f"Не удалось инициализировать Debug Пульт: {e}")

    return app

if __name__ == "__main__":
    import argparse
    import subprocess

    if "--service-install" in sys.argv:
        sys.exit(install_service_cli())

    if "--service-disable" in sys.argv:
        sys.exit(disable_service_cli())

    if "--service-host" in sys.argv:
        import servicemanager
        from workers.windows_admin_service import PLACSAgentWindowsService

        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(PLACSAgentWindowsService)
        servicemanager.StartServiceCtrlDispatcher()
        sys.exit(0)

    parser = argparse.ArgumentParser(description='PLACS Агент - ПО для удалённого доступа и отслежвания состяния устройства клиента.')
    parser.add_argument('skip_update', type=str, nargs='?', default='.',
                        help='Пропустить проверку обновлений. Если аргумент отсутствует, будет запущено обновление.')

    args = parser.parse_args()

    instance_lock = SingleInstanceLock("PLACSAgent")
    lock_acquired, running_pid = instance_lock.acquire()
    if not lock_acquired:
        duplicate_app = QApplication.instance() or QApplication(sys.argv)
        QMessageBox.information(
            None,
            "PLACS Agent",
            f"PLACS Agent уже запущен.\n\nPID активного экземпляра: {running_pid}",
        )
        sys.exit(0)

    if args.skip_update == '.' and get_server_url() and not DEBUG_MODE:
        start_update()

    # Если мы дошли до сюда, значит, либо был аргумент skip_update,
    # либо произошла ошибка при запуске обновления, и мы решили продолжить.
    app = initialize_agent_ui_and_config()

    if not app:
        print("Не удалось инициализировать приложение. Завершение.")
        sys.exit(1)

    # Запускаем потоки, если они определены
    if agent_thread and agent_worker:
        agent_thread.start() # Запуск потока обработчика
        network_diagnoser_thread.start() # Запуск потока диагностики.
        system_monitor_thread.start() # Запуск потока мониторинга.

    sys.exit(app.exec_())
