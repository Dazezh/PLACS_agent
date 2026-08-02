from PyQt6.QtCore import QObject, pyqtSignal, QTimer
import logging
from collections import defaultdict
import datetime
from core.error_types import ErrorType, ErrorState

log = logging.getLogger("ErrorStateManager")

class ErrorStateManager(QObject):
    ui_state_changed = pyqtSignal(ErrorState)
    last_error_message_changed = pyqtSignal(str)

    NETWORK_TRANSIENT_DURATION_MS = 10000 # 10 секунд - длительность желтого фона для сетевых ошибок
    COMMAND_EXECUTION_DURATION_MS = 5000  # 5 секунд - длительность желтого фона для ошибок команд

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_ui_state = ErrorState.START
        self._last_error_message = ""
        self._error_counts = defaultdict(int)

        # Таймеры для временных состояний UI (желтый фон)
        self._network_timer = QTimer(self)
        self._network_timer.setSingleShot(True)
        self._network_timer.timeout.connect(self._check_and_reset_network_error)

        self._command_timer = QTimer(self)
        self._command_timer.setSingleShot(True)
        self._command_timer.timeout.connect(self._check_and_reset_command_error)

        log.info("ErrorStateManager инициализирован.")

    def handle_error(self, error_type: ErrorType, message: str):
        """
        Слот для получения ошибок из других потоков/модулей.
        Обновляет состояние менеджера и эмитирует сигналы UI.
        """
        if not error_type == ErrorType.NORMAL:
            log.warning(f"Получена ошибка: {error_type.value} - {message}")

            self._error_counts[error_type] += 1
            self._last_error_message = message
            self.last_error_message_changed.emit(message)

        if error_type == ErrorType.NETWORK_TRANSIENT:
            self._network_timer.start(self.NETWORK_TRANSIENT_DURATION_MS)

        elif error_type == ErrorType.COMMAND_EXECUTION:
            self._command_timer.start(self.COMMAND_EXECUTION_DURATION_MS)
        
        # Пересчитываем и обновляем общее состояние UI
        self._update_ui_state()

        if error_type == ErrorType.CRITICAL_APPLICATION:
            log.critical(f"Критическая ошибка обнаружена: {message}. Всего критических: {self._error_counts[ErrorType.CRITICAL_APPLICATION]}")

    def _check_and_reset_network_error(self):
        """
        Слот для таймера временной сетевой ошибки (для желтого фона).
        Если этот таймер сработал, и за это время не пришло новых сетевых ошибок,
        значит, "временная" сетевая проблема, возможно, разрешилась.
        """
        log.debug("Таймер временной сетевой ошибки сработал.")
        # Если network_timer сработал, а network_error_active_since не None,
        # это значит, что в течение последних NETWORK_TRANSIENT_DURATION_MS
        # не было новых сетевых ошибок. Можно сбросить состояние.
        # НО: если пришло несколько ошибок подряд, network_timer будет постоянно перезапускаться.
        # Сброс _network_error_active_since происходит только при отсутствии ошибок вообще.
        
        # Если таймер временной ошибки сработал, и *сейчас* нет других активных временных проблем,
        # и сетевая проблема считается разрешенной (т.е. _network_error_active_since не обновлялся)
        # нужно сбросить _network_error_active_since и остановить _diagnostic_check_timer.
        
        # Более корректно:
        # Если network_timer сработал, это значит, что последняя сетевая ошибка была N секунд назад.
        # Если за это время не пришло новых сетевых ошибок, то _network_error_active_since тоже
        # должен быть сброшен.
        # Эту логику лучше вынести в отдельный метод, который будет вызываться при "отсутствии" ошибок.
        # Сейчас мы просто пересчитываем состояние UI.
        self._update_ui_state()

        # Если _network_timer сработал и при этом не пришло новых сетевых ошибок, считаем проблему ушедшей.
        if not self._network_timer.isActive():
            self._update_ui_state()

    def _check_and_reset_command_error(self):
        """Слот для таймера ошибки выполнения команды."""
        log.debug("Таймер ошибки выполнения команды сработал.")
        self._update_ui_state()

    def _update_ui_state(self):
        """
        Определяет текущее общее состояние UI на основе активных ошибок.
        Приоритет: CRITICAL > WARNING (сетевая/командная) > OK.
        """
        new_state = ErrorState.OK

        if self._error_counts[ErrorType.CRITICAL_APPLICATION] > 0:
            new_state = ErrorState.CRITICAL
        elif self._network_timer.isActive() or self._command_timer.isActive():
            new_state = ErrorState.SERVER_CONNECT

        if new_state != self._current_ui_state:
            self._current_ui_state = new_state
            log.info(f"Состояние UI изменено на: {new_state.value}")
            self.ui_state_changed.emit(new_state)

    def get_error_counts(self):
        return dict(self._error_counts)

    def get_current_ui_state(self):
        return self._current_ui_state

    def get_last_error_message(self):
        return self._last_error_message