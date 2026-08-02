# workers/agent_worker.py
from PyQt6.QtCore import QObject, pyqtSignal, QTimer,QSettings
import logging
import sys
import os

from core.config_manager import get_polling_interval
from workers.server_communicator import (
    get_commands,
    report_command_output,
    send_log_to_server,
    get_me,
    report_specs,
    report_metrics,
)
from workers.command_executor import execute_command

from core.utils import (
    sanitize_filename,
    clear_folder,
    get_system_specs,
    get_system_metrics,
    is_windows,
)
from core.error_types import ErrorType

from core.config_manager import get_debug_state

log = logging.getLogger("AgentWorker")
sysmon_log = logging.getLogger("SystemMonitor")

class AgentWorker(QObject):
    status_update = pyqtSignal(str)
    command_completed = pyqtSignal(str, str)
    error_occurred = pyqtSignal(ErrorType, str)
    show_display_message_signal = pyqtSignal(str)
    start_update = pyqtSignal(bool, str)
    # --- VPN сигналы ---
    vpn_configs_updated = pyqtSignal(list)  # Эмитим обновленный список конфигов
    vpn_operation_status = pyqtSignal(str, str)  # (status, message)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("PLACS", "Agent")
        self._is_running = False
        self._timer = None
        self._openvpn_configs_downloaded = False
        self.vpn_configs_memory = []  # [{'config_id':..,'network_id':..,'network_name':..,'path':..}]
        self.current_vpn_network = None
        log.info("AgentWorker инициализирован.")

    def start_polling(self):
        """Начинает цикл опроса команд. Создает QTimer в правильном потоке."""
        if not self._is_running:
            self._is_running = True
            log.info("Запуск цикла опроса сервера в отдельном потоке.")

            self._timer = QTimer(self)
            self._timer.timeout.connect(self._perform_polling)
            
            self._timer.start(1000) 
            self.status_update.emit("Фоновые процессы инициализированы!")

    def stop_polling(self):
        """Останавливает цикл опроса команд. Вызывается из главного потока."""
        self._is_running = False
        log.info("Сигнал на остановку цикла опроса отправлен.")
        self.status_update.emit("Агент остановлен.")
    
    def _download_openvpn_configs(self, set_load_completed = True):
        log.info("Скачиваю конфигурационные файлы OpenVPN")
        self.status_update.emit("Скачиваю конфиги OpenVPN")
        try:
            agent, error = get_me()

            if error:
                return error
            
            if not agent:
                return {'type': ErrorType.CRITICAL_APPLICATION, 'message': "Я не знаю что пошло не так, но сервер сказал, что я никто..."}
            
            # Создаём папку для конфигов, а если она есть. Ну на то и суда нет.
            base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
            tmp_dir = os.path.join(base_dir, '.tmp')
            os.makedirs(tmp_dir, exist_ok=True)
            configs = []

            log.info("На всякий случай очищаю временные файлы перед сохранением конфигураций...")
            clear_folder(tmp_dir)

            self.vpn_configs_memory = []
            for network in agent.get("vpn_configs"):
                network_name = network.get('network_name')
                config_path = os.path.join(tmp_dir, f"{sanitize_filename(network_name)}.conf")
                with open(config_path, "w", encoding="utf-8") as config_file:
                    config_file.write(network.get('config_txt'))
                configs.append(network_name)
                self.vpn_configs_memory.append({
                    'config_id': network.get('config_id'),
                    'network_id': network.get('network_id'),
                    'network_name': network_name,
                    'path': config_path
                })
            
            if configs:
                configs = {' '.join(configs)}
                self.status_update.emit(f"Я получил следующие конфигурационные файлы: {configs}")
                log.info(f"Установлены следующие конфигурационные файлы: {configs}")
            
            else:
                self.status_update.emit("Для клиента нет конфигураций!")
                log.info("Для клиента нет конфигураций!")
            self._openvpn_configs_downloaded = True
            self.vpn_configs_updated.emit(self.vpn_configs_memory)

        except Exception as e:
            log.error(f"Ошибка при скачивании конфигов OpenVPN: {e}")
            return  {'type': ErrorType.CRITICAL_APPLICATION, 'message': e} 

    # ---------------- VPN API -----------------
    def refresh_vpn_configs(self):
        """Принудительное обновление списка конфигураций."""
        self._openvpn_configs_downloaded = False
        doc = self._download_openvpn_configs()
        if doc:
            self.vpn_operation_status.emit('error', f"Не удалось обновить конфиги: {doc.get('message')}")
        else:
            self.vpn_operation_status.emit('info', 'Список конфигов обновлён.')

    def connect_to_network(self, network_name: str):
        """Инициирует соединение с указанной сетью."""
        try:
            target = next((c for c in self.vpn_configs_memory if c.get('network_name') == network_name), None)
            if not target:
                self.vpn_operation_status.emit('error', f"Конфиг для сети '{network_name}' не найден")
                return
            status, message = execute_command({"type": "network", "command_text": network_name})
            if status == "success":
                self.current_vpn_network = network_name
                self.vpn_operation_status.emit('success', message)
                send_log_to_server("info", f"Агент самостоятельно инициировал соединение с сетью '{network_name}'.")
            else:
                self.vpn_operation_status.emit('error', f"Не удалось подключиться: {message}")
        except Exception as e:
            log.error(f"Ошибка подключения к сети {network_name}: {e}")
            self.vpn_operation_status.emit('error', f"Внутренняя ошибка подключения: {e}")

    def disconnect_from_network(self):
        """Отключает все активные VPN соединения."""
        try:
            status, message = execute_command({"type": "network", "command_text": "close_all"})
            if status == "success":
                self.current_vpn_network = None
                self.vpn_operation_status.emit('success', message)
            else:
                self.vpn_operation_status.emit('error', f"Не удалось закрыть соединения: {message}")
        except Exception as e:
            log.error(f"Ошибка отключения VPN: {e}")
            self.vpn_operation_status.emit('error', f"Внутренняя ошибка отключения: {e}")

    def _perform_polling(self):
        """Основной цикл опроса команд, выполняющийся в рабочем потоке."""
        if not self._is_running:
            if self._timer:
                self._timer.stop()
            return

        try:
            # Проверка на то, что конфиги скачены. Иначе не пущу выполнять команды!
            if not self._openvpn_configs_downloaded:
                doc = self._download_openvpn_configs()
                if doc:
                    self.error_occurred.emit(doc['type'], doc['message'])
                    doc['message'] = doc['message'] if len(doc['message']) < 30 else doc['message'][:30]
                    self.status_update.emit(f"Ошибка связи: {doc['message']}. Ожидание...")
                    return # Не позволю запуститься если что-то не так с OpenVpn

            log.info("Проверка новых команд...")
            self.status_update.emit("Проверяю новые команды...")

            commands, error_info = get_commands()
            
            if error_info:
                # Если get_commands вернул ошибку, эмитируем ее через наш сигнал
                self.error_occurred.emit(error_info['type'], error_info['message'])
                # Пока оставим, как есть: server_communicator сам логирует и отправляет.
                self.status_update.emit(f"Ошибка связи: {error_info['message']}. Ожидание...")
                return # Прерываем итерацию, если есть ошибка связи
            
            if commands:
                for command_data in commands:
                    command_id = command_data.get("id")
                    command_type = command_data.get("type")

                    if command_id:
                        log.info(f"Обрабатываю поручение ID:{command_id}...")
                        if command_type == 'applet':
                            self.status_update.emit(f"<p>Выполняю апплет ID:<b>{command_id}</b></p>")
                            for command in command_data.get("applet_command"):
                                # Обновляем статус для каждой подкоманды апплета
                                self.status_update.emit(f"""<p>Выполняю команду из апплета ID:<b>{command.get('id')}</b></p><br>
                                            <p>Номер команды|Тип: <b>{command.get('id')}|{command.get('type')}</b></p>
                                            """)
                                
                                if command.get('type') == 'set_on_display': # Исключительная ситуация
                                    message = command.get('command_text', 'Сообщение')
                                    self.show_display_message_signal.emit(message)
                                    status, output = "success", "Сообщение отправлено для отображения" # Не блокируем поток

                                else:
                                    status, output = execute_command(command) # Выполнение подкоманды
                        
                        elif command_type == 'set_on_display': # Исключительная ситуация
                            message = command_data.get('command_text', 'Сообщение')
                            self.show_display_message_signal.emit(message)
                            status, output = "success", "Сообщение отправлено для отображения" # Не блокируем поток
                        
                        elif command_type == 'custom':
                            message = command_data.get('command_text')
                            if message == "upgrade":
                                if get_debug_state():
                                    self.status_update.emit("Получена команда обновления, но так как включён DEBUG режим, я не запущу обновление. Выключи DEBUG в настройках и попробуй снова.")
                                    status, output = "error", "DEBUG режим включён - обновление не запущено."

                                else:
                                    self.start_update.emit(True, "Обновление...")
                                    status, output = "success", "Сигнал обновления отправлен."
                            
                            elif message == "reinstall":
                                if get_debug_state():
                                    self.status_update.emit("Получена команда переустановки, но так как включён DEBUG режим, я не запущу переустановку. Выключи DEBUG в настройках и попробуй снова.")
                                    status, output = "error", "DEBUG режим включён - переустановка не запущена."
                                else:
                                    self.start_update.emit(False, "Переустановка...")
                                    status, output = "success", "Сигнал переустановки отправлен."
                            
                            else:
                                self.status_update.emit(f"<p>Получена неизвестная кастомная команда ID:<b>{command_id}</b></p><br><p>Текст команды:<b>{message}</b></p>")
                                status, output = "error", f"Неизвестная кастомная команда: {message}"
                        
                        else: # Обычная команда (не апплет)
                            self.status_update.emit(f"<p>Выполняю команду ID:<b>{command_id}</b></p><br><p>Тип:<b>{command_type}</b></p>")
                            status, output = execute_command(command_data) # Выполнение одиночной команды

                        # Отправка общего отчета и уведомление GUI после обработки (апплета или одиночной команды)
                        self.status_update.emit(f"<p><b>Отправляю отчёт о выполнении ID:{command_id}</b></p>")
                        report_command_output(command_id, output, status)

                        # Отправка уведомления о завершении команды
                        if status == "success" and self.settings.value("notifications/pushOnCommandFinish", True, type=bool):
                            self.error_occurred.emit(ErrorType.NORMAL, "Всё окей. В логи не вносим!")
                            self.command_completed.emit(str(command_id), status)
                        # Отправка уведомления о ошибке
                        elif status == "error" and self.settings.value("notifications/pushOnError", True, type=bool):
                            self.error_occurred.emit(ErrorType.COMMAND_EXECUTION, f"Команда ID:{str(command_id)}. Привела к ошибке: {output}")
                        # Обновляем статус если появилась ошибка
                        elif status == "error":
                            self.status_update.emit(f"Команда ID:{str(command_id)}<br>Привела к ошибке: {output}")
                    else:
                        log.warning("Получена команда без ID. Пропускаю.")
            else:
                log.info("Нет новых команд. Ожидание...")
                self.error_occurred.emit(ErrorType.NORMAL, "Всё окей. В логи не вносим!")
                self.status_update.emit("Ожидаю новые команды...")

        except Exception as e:
            log.exception(f"Непредвиденная критическая ошибка в основном цикле: {e}")
            self.error_occurred.emit(ErrorType.CRITICAL_APPLICATION, f"Критическая ошибка: {e}")
            send_log_to_server("error", f"Критическая ошибка: {e}")
        
        polling_interval_ms = get_polling_interval() * 1000
        if self._is_running and self._timer:
            self._timer.start(polling_interval_ms)


class SystemMonitor(QObject):
    """Мониторинг системных метрик и отправка их на сервер раз в минуту.

    Логика:
    - При запуске один раз отправляет технические характеристики (идемпотентно).
    - Каждую минуту собирает метрики нагрузки и отправляет их на сервер.
    - В случае ошибок — пишет в логи и, по возможности, отправляет лог на сервер.
    """

    status_update = pyqtSignal(str)
    error_occurred = pyqtSignal(ErrorType, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = QSettings("PLACS", "Agent")
        self._timer = None
        self._started = False

    def start(self):
        """Запуск мониторинга."""
        if self._started:
            return
        self._started = True
        sysmon_log.info("SystemMonitor запускается…")

        # Отправим спецификации один раз при старте
        try:
            specs = get_system_specs()
            if specs:
                resp, err = report_specs(specs)
                if err:
                    # Сообщим о проблеме, но это не блокирует работу мониторинга
                    self.error_occurred.emit(err['type'], f"Не удалось отправить спецификации: {err['message']}")
                    send_log_to_server("error", f"SystemMonitor: ошибка отправки спецификаций: {err['message']}")
                else:
                    self.status_update.emit("Характеристики устройства обновлены на сервере")
                    sysmon_log.info("Спецификации отправлены.")
            else:
                self.status_update.emit("Не удалось собрать спецификации устройства")
                sysmon_log.warning("get_system_specs() вернул пустой результат")
        except Exception as e:
            sysmon_log.exception(f"Исключение при отправке спецификаций: {e}")
            self.error_occurred.emit(ErrorType.CRITICAL_APPLICATION, f"SystemMonitor specs error: {e}")
            send_log_to_server("error", f"SystemMonitor specs exception: {e}")

        # Настраиваем таймер для периодической отправки метрик
        interval_sec = 60
        try:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._send_metrics_tick)
            self._timer.start(interval_sec * 1000)
            # Сделаем первый замер сразу
            self._send_metrics_tick()
            self.status_update.emit("Мониторинг системы запущен")
        except Exception as e:
            sysmon_log.exception(f"Не удалось запустить таймер мониторинга: {e}")
            self.error_occurred.emit(ErrorType.CRITICAL_APPLICATION, f"SystemMonitor start error: {e}")

    def stop(self):
        """Останов мониторинга."""
        if self._timer:
            try:
                self._timer.stop()
            except Exception:
                pass
            self._timer = None
        self._started = False
        sysmon_log.info("SystemMonitor остановлен")

    def _send_metrics_tick(self):
        """Сбор и отправка метрик нагрузки."""
        try:
            # Можно дать пользователю возможность отключить мониторинг через настройки
            if not self.settings.value("monitoring/enabled", True, type=bool):
                sysmon_log.debug("Мониторинг отключён в настройках.")
                return

            metrics = get_system_metrics()
            if not metrics:
                self.status_update.emit("Не удалось собрать метрики системы")
                sysmon_log.warning("get_system_metrics() вернул пустой результат")
                return

            # Если температура недоступна — всё равно отправим -1 и лог
            if metrics.get("cpu_temp_c") is None:
                metrics["cpu_temp_c"] = -1
                #send_log_to_server("warning", "Температура CPU недоступна на этом устройстве. Отправляю -1.")

            resp, err = report_metrics(metrics)
            if err:
                self.error_occurred.emit(err['type'], f"Не удалось отправить метрики: {err['message']}")
                return

            # Успех
            self.status_update.emit("Метрики системы отправлены")
            sysmon_log.debug("Метрики отправлены успешно.")
        except Exception as e:
            sysmon_log.exception(f"Исключение при отправке метрик: {e}")
            self.error_occurred.emit(ErrorType.CRITICAL_APPLICATION, f"SystemMonitor metrics error: {e}")
            #send_log_to_server("error", f"SystemMonitor metrics exception: {e}")
