from PyQt5.QtCore import QObject, pyqtSignal
import logging
import requests
import socket
import subprocess
import time

from core.config_manager import get_server_url # Убедись, что эта функция корректно возвращает URL
from core.utils import is_linux

log = logging.getLogger("NetworkDiagnoser")

class NetworkDiagnoser(QObject):
    # Сигналы для обновления UI (в main_window)
    check_status_update = pyqtSignal(str, str) # (Название проверки, статус-эмодзи)
    detail_output_update = pyqtSignal(str) # Подробный вывод текста
    diagnostic_finished = pyqtSignal(bool, str) # (Общий успех/провал, итоговое сообщение)

    # Сигналы для управления AgentWorker (через main.py)
    request_polling_stop = pyqtSignal()
    request_polling_start = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server_url = None
        self.resolved_server_ip = None
        self._is_running = False
        log.info("NetworkDiagnoser инициализирован.")

    def run_diagnostic(self):
        """
        Запускает полный цикл диагностики сети.
        Вызывается в отдельном потоке.
        """
        if self._is_running:
            log.warning("Диагностика уже запущена. Игнорирую повторный запрос.")
            return

        self._is_running = True
        log.info("Запуск диагностики сети...")
        self.detail_output_update.emit("--- Начинаю диагностику сети ---")
        
        # 1. Запрос на остановку фонового процесса (AgentWorker)
        self.check_status_update.emit("Остановка фоновых процессов", "🔄")
        self.request_polling_stop.emit()
        time.sleep(3) # Даем немного времени на остановку
        self.check_status_update.emit("Остановка фоновых процессов", "🟢")
        self.detail_output_update.emit("Фоновые процессы остановлены.\n")

        overall_success = True
        
        # Переменные для сбора итогового сообщения
        final_summary_messages = []
        
        # Получаем URL сервера
        self.server_url = get_server_url()
        if not self.server_url:
            msg = "Ошибка: URL сервера не указан в конфигурации. Проверьте настройки PLACS Agent."
            self.check_status_update.emit("Проверка URL сервера", "🔴")
            self.detail_output_update.emit(msg + "\n")
            overall_success = False
            final_summary_messages.append("⛔ Проблема с конфигурацией: URL сервера не указан.")
            self._finish_diagnostic(overall_success, final_summary_messages)
            return

        self.detail_output_update.emit(f"Целевой сервер: {self.server_url}\n")

        # 2. Проверка URL сервера (валидность)
        self.check_status_update.emit("Проверка URL сервера", "🔄")
        if not (self.server_url.startswith("http://") or self.server_url.startswith("https://")):
            msg = f"URL сервера '{self.server_url}' некорректен. Должен начинаться с http:// или https://."
            self.check_status_update.emit("Проверка URL сервера", "🔴")
            self.detail_output_update.emit(msg + "\n")
            overall_success = False
            final_summary_messages.append(f"⛔ URL сервера '{self.server_url}' некорректен. Исправьте его в настройках.")
        else:
            self.check_status_update.emit("Проверка URL сервера", "🟢")
            self.detail_output_update.emit(f"URL сервера: {self.server_url} - OK.\n")

        # Если URL некорректен, дальше нет смысла проверять.
        if not overall_success:
            self._finish_diagnostic(overall_success, final_summary_messages)
            return

        # Получаем hostname для DNS и Ping
        hostname = self.server_url.split('://', 1)[-1].split('/')[0].split(':')[0]

        # 3. Проверка DNS
        dns_success, dns_msg = self._perform_dns_check(hostname)
        self.check_status_update.emit("Разрешение DNS имени сервера", "🟢" if dns_success else "🔴")
        self.detail_output_update.emit(f"Разрешение DNS: {dns_msg}\n")
        if not dns_success:
            overall_success = False
            final_summary_messages.append(f"🔴 Не удалось разрешить DNS-имя сервера '{hostname}'. Возможно, нет доступа к DNS-серверам или имя указано неверно.")
        else:
            final_summary_messages.append(f"🟢 DNS-имя сервера '{hostname}' успешно разрешено.")

        # 4. Базовый пинг до сервера (используем resolved_server_ip, если DNS был успешным)
        ping_target = self.resolved_server_ip if dns_success and self.resolved_server_ip else hostname
        ping_success, ping_msg = self._perform_ping_check(ping_target)
        self.check_status_update.emit(f"Пинг до {ping_target}", "🟢" if ping_success else "🔴")
        self.detail_output_update.emit(f"Пинг: {ping_msg}\n")
        if not ping_success:
            overall_success = False
            final_summary_messages.append(f"🔴 Сервер '{ping_target}' недоступен по пингу. Возможно, проблема маршрутизации, фаервола или сервер выключен.")
        else:
            final_summary_messages.append(f"🟢 Сервер '{ping_target}' доступен по пингу.")

        # 5. HTTP/S доступность сервера
        http_success, http_msg = self._perform_http_check(self.server_url)
        self.check_status_update.emit(f"Доступность HTTP/S ({self.server_url})", "🟢" if http_success else "🔴")
        self.detail_output_update.emit(f"HTTP/S доступность: {http_msg}\n")
        if not http_success:
            overall_success = False
            final_summary_messages.append(f"🔴 Не удалось соединиться с сервером PLACS Agent по HTTP/S. Возможно, сервер отключен, неверно настроен или блокируется фаерволом.")
        else:
            final_summary_messages.append(f"🟢 PLACS Agent сервер успешно отвечает на HTTP/S запросы.")

        # 6. Проверка общей доступности интернета (контрольная точка)
        self.detail_output_update.emit("\n--- Проверка общей доступности интернета ---")
        internet_success = True

        internet_dns_success, internet_dns_msg = self._perform_dns_check("google.com")
        self.check_status_update.emit("Разрешение DNS (google.com)", "🟢" if internet_dns_success else "🔴")
        self.detail_output_update.emit(f"Разрешение DNS (google.com): {internet_dns_msg}\n")
        if not internet_dns_success:
            internet_success = False
            final_summary_messages.append("🔴 Не удалось разрешить DNS-имя 'google.com'. Вероятно, проблемы с общим доступом в интернет.")
        
        internet_ping_success, internet_ping_msg = self._perform_ping_check("8.8.8.8")
        self.check_status_update.emit("Пинг до 8.8.8.8 (Google DNS)", "🟢" if internet_ping_success else "🔴")
        self.detail_output_update.emit(f"Пинг 8.8.8.8: {internet_ping_msg}\n")
        if not internet_ping_success:
            internet_success = False
            final_summary_messages.append("🔴 Не удалось пинговать 8.8.8.8. Общие проблемы со связью с интернетом.")

        if not internet_success:
            overall_success = False # Если нет интернета, то общая диагностика провалена
            final_summary_messages.append("⛔ Общие проблемы с интернетом. Проверьте сетевое подключение вашего компьютера.")
        else:
            final_summary_messages.append("🟢 Интернет доступен.")

        # Завершение диагностики
        self._finish_diagnostic(overall_success, final_summary_messages)

    def _finish_diagnostic(self, overall_success: bool, summary_messages: list):
        """Завершает процесс диагностики и сигнализирует о результатах."""
        final_result_message = ""

        if overall_success:
            final_result_message = "<h3 style=\"margin: 0\">✅ Я всё проверил! Сеть в полном порядке, а PLACS Server прямо как швейцарские часы – отвечает без запинки. Отличная работа!</h3>"
        else:
            final_result_message = "<h3 style=\"margin: 0\">❌ О нет! Что-то пошло не так... Кажется, в нашей сети или с моим любимым PLACS Server'ом какие-то неполадки. Давай разберемся!</h3>"
            
        final_result_message += "<hr><h4>Краткий отчет</h4>"
        final_result_message += "<br>".join(summary_messages)

        if not overall_success:
            final_result_message += "<hr><h4>Что будем делать? Советы от меня:</h4>"

            if "Общие проблемы с интернетом" in final_result_message:
                final_result_message += "Пожалуйста, проверьте сетевое подключение вашего компьютера (Wi-Fi/кабель), возможно, просто кабель отошел. Попробуйте перезагрузить роутер – это классика, но часто работает! Или, если вы на Linux, нажмите кнопку 'Попробовать исправить' – я постараюсь сам вернуть вас в онлайн."
            elif "Не удалось соединиться с сервером PLACS Agent" in final_result_message:
                final_result_message += "Возможно, мой сервер сейчас спит или просто недоступен. Свяжитесь, пожалуйста, с администратором сервера или просто подождите, пока он проснется. Как только проблемы исчезнут, я тут же возобновлю свою работу. Я очень ответственный агент!"
            elif "Не удалось разрешить DNS-имя" in final_result_message:
                final_result_message += "Проверьте, пожалуйста, правильность URL сервера в настройках – может, опечатка закралась? Если URL верный, то, скорее всего, загвоздка в DNS-серверах вашего провайдера или в локальных настройках DNS. Тут я, к сожалению, бессилен – это выше моих полномочий... Прости, мой арсенал ограничен."
            elif "недоступен по пингу" in final_result_message:
                final_result_message += "Мой сервер совсем не отвечает! Я пробовал к нему достучаться всеми способами, но он молчит, как партизан на допросе. Пожалуйста, попросите администратора сервера проверить, что там случилось. Или просто подождите – как только он очнется, я сразу же продолжу работу!"


        log.info("\n---Краткий результат проверки---\n".join(summary_messages))

        # Запрос на запуск фонового процесса (AgentWorker)
        self.check_status_update.emit("Запуск фоновых процессов", "🔄")
        self.request_polling_start.emit()
        time.sleep(3) # Даем немного времени на запуск
        self.check_status_update.emit("Запуск фоновых процессов", "🟢")
        self.detail_output_update.emit("Фоновые процессы запущены.\n")

        self.diagnostic_finished.emit(overall_success, final_result_message)
        self._is_running = False

    def _perform_dns_check(self, hostname):
        """Выполняет проверку разрешения DNS."""
        self.check_status_update.emit(f"Разрешение DNS ({hostname})", "🔄")
        try:
            self.resolved_server_ip = socket.gethostbyname(hostname)
            log.info(f"DNS resolved: {hostname} -> {self.resolved_server_ip}")
            return True, f"Успешно: {hostname} разрешен в {self.resolved_server_ip}"
        except socket.gaierror as e:
            msg = f"Не удалось разрешить имя '{hostname}': {e}. Проверьте имя хоста или DNS-серверы."
            log.error(msg)
            return False, msg
        except Exception as e:
            msg = f"Непредвиденная ошибка при DNS-разрешении '{hostname}': {e}"
            log.exception(msg)
            return False, msg

    def _perform_ping_check(self, target):
        """Выполняет проверку пинга с использованием pythonping или subprocess."""
        self.check_status_update.emit(f"Пинг до {target}", "🔄")
        output = ""

        if is_linux():
            # Логика для Linux: используем скрипт-помощник с sudo
            try:
                cmd = ['sudo', '/usr/local/bin/placs-ping-helper.py', target]
                output = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=True)
                
                output_lines = output.stdout.strip().split('\n')
                parsed_results = {}
                for line in output_lines:
                    key, value = line.split(':', 1)
                    parsed_results[key] = value

                if parsed_results.get("success") == "True":
                    log.info(f"Пинг успешен. Потеряно: {parsed_results.get('stats_lost', 'N/A')} пакетов.")
                    return True, f"Успешно: {target} доступен. (Потеряно: {parsed_results.get('stats_lost', 'N/A')} пакетов)"
                else:
                    log.error(f"Пинг не удался. Результат: {parsed_results}")
                    return False, f"Пинг до {target} не удался. Потеряно {parsed_results.get('stats_lost', 'N/A')} из {parsed_results.get('stats_sent', 'N/A')} пакетов."
                    
            except subprocess.CalledProcessError as e:
                log.error(f"Ошибка вызова ping-помощника: {e.stderr}")
                output = "Что-то не так"
                return False, f"Ошибка при выполнении пинга: {e.stderr}"
            except Exception as e:
                log.error(f"Непредвиденная ошибка при обработке пинга: {e}")
                output = "Что-то не так"
                return False, f"Внутренняя ошибка пинга: {e}"
            finally:
                self.detail_output_update.emit(f"--- Пинг {target} ---\n{output}\n")

        else:
            from pythonping import ping
            
            try:            
                # Более чистый способ получить результаты от pythonping:
                result = ping(target, count=4, timeout=2, verbose=False)
                output = f"Пинг до {target} (пакеты отправлены: {result.stats_packets_sent}, получены: {result.stats_packets_returned}, потеряно: {result.stats_packets_lost}, среднее время: {result.rtt_avg_ms:.2f}мс)\n"
                
                if result.success: # pythonping возвращает True/False для общего успеха
                    return True, f"Успешно: {target} доступен. (Потеряно: {result.stats_packets_lost} пакетов)"
                else:
                    return False, f"Пинг до {target} не удался. Потеряно {result.stats_packets_lost} из {result.stats_packets_sent} пакетов."
            except Exception as e:
                msg = f"Ошибка 'pythonping' при пинге {target}: {e}"
                log.exception(msg)
                output = msg
                return False, msg
            finally:
                self.detail_output_update.emit(f"--- Пинг {target} ---\n{output}\n")

    def _perform_http_check(self, url):
        """Выполняет проверку HTTP/S доступности."""
        self.check_status_update.emit(f"HTTP/S доступность ({url})", "🔄")
        try:
            # Делаем HEAD запрос, он быстрее, так как не скачивает тело ответа
            response = requests.head(url, timeout=10, verify=False) # verify=False для самоподписанных сертификатов (если есть)
            response.raise_for_status() # Выбросит исключение для 4xx/5xx ошибок

            return True, f"Успешно: {url} отвечает (HTTP {response.status_code})"
        except requests.exceptions.Timeout:
            msg = f"HTTP/S запрос к {url} превысил таймаут (10 сек). Сервер не отвечает."
            log.error(msg)
            return False, msg
        except requests.exceptions.ConnectionError as e:
            msg = f"Ошибка соединения с {url}: {e}. Сервер недоступен или порт закрыт."
            log.error(msg)
            return False, msg
        except requests.exceptions.HTTPError as e:
            msg = f"HTTP ошибка {e.response.status_code} при доступе к {url}: {e.response.text}"
            log.error(msg)
            return False, msg
        except requests.exceptions.RequestException as e:
            msg = f"Неизвестная ошибка HTTP/S запроса к {url}: {e}"
            log.exception(msg)
            return False, msg
        except Exception as e:
            msg = f"Непредвиденная ошибка при HTTP/S проверке {url}: {e}"
            log.exception(msg)
            return False, msg

    def try_to_fix_network(self):
        """
        Пытается перезапустить сетевые службы на Linux.
        Будет вызван по сигналу из main_window.
        """
        if not is_linux():
            log.warning("Функция 'Попробовать исправить' доступна только на Linux.")
            self.detail_output_update.emit("⚠️ Функция 'Попробовать исправить' доступна только на Linux.\n")
            return

        log.info("Попытка перезапустить сетевые службы на Linux...")
        self.detail_output_update.emit("\n--- Попытка перезапустить сетевые службы (Linux) ---\n")
        self.detail_output_update.emit("⚠️ Для этой операции могут потребоваться права администратора (sudo).\n")

        # Примечание: для запуска команды с sudo из GUI нужен графический запрос пароля.
        # Это сложная тема в PyQt. Проще всего полагаться на то, что агент уже работает с sudo
        # или использовать pkexec/gksudo. Но для простоты я покажу прямой вызов,
        # подразумевая, что пользователь предоставит права или настроит sudoers NOPASSWD.
        
        commands = [
            "sudo systemctl restart NetworkManager",
            "sudo systemctl restart networking", # Для старых систем или Debian-based
        ]
        
        success = False
        for cmd_str in commands:
            self.detail_output_update.emit(f"Выполняю: {cmd_str}\n")
            try:
                # ВНИМАНИЕ: это блокирующий вызов. Если команда потребует ввода пароля,
                # приложение зависнет. Для продакшена лучше использовать QProcess
                # и обрабатывать ввод пароля через stdin, или полагаться на sudoers NOPASSWD.
                # Для демонстрации - простой subprocess.run.
                process = subprocess.run(cmd_str, shell=True, capture_output=True, text=True, timeout=30)
                output = process.stdout + process.stderr
                self.detail_output_update.emit(f"Результат:\n{output}\n")
                if process.returncode == 0:
                    self.detail_output_update.emit(f"✅ Команда '{cmd_str}' выполнена успешно.\n")
                    success = True
                    break # Если одна команда сработала, остальные не нужны
                else:
                    self.detail_output_update.emit(f"❌ Команда '{cmd_str}' завершилась с ошибкой (код {process.returncode}).\n")
            except subprocess.TimeoutExpired:
                self.detail_output_update.emit(f"❌ Команда '{cmd_str}' превысила таймаут (30 сек).\n")
            except Exception as e:
                self.detail_output_update.emit(f"❌ Непредвиденная ошибка при выполнении '{cmd_str}': {e}\n")
        
        if success:
            self.detail_output_update.emit("✨ Попытка исправить сетевые службы завершилась успехом! Перезапустите диагностику для проверки.\n")
        else:
            self.detail_output_update.emit("💔 Попытка исправить сетевые службы не дала результата. Возможно, требуется ручное вмешательство или перезагрузка.\n")
            
        self.detail_output_update.emit("--- Конец попытки исправления ---\n")
        
        # После попытки исправления, можно предложить перезапустить диагностику
        # или просто оставить UI в текущем состоянии, пока пользователь не нажмет кнопку.