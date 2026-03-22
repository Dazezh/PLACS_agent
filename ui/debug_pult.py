import sys
from PyQt5.QtCore import Qt, pyqtSignal, QObject, QThread
from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QLineEdit, QSpinBox, QGroupBox

from core.error_types import ErrorState


class DebugPultWorker(QObject):
    """Пустой воркер для соответствия требованию: отдельный поток под пульт."""
    pass


class DebugPultDialog(QDialog):
    # Сигналы для прямого управления главным окном
    request_state_change = pyqtSignal(ErrorState)
    request_exit = pyqtSignal()
    request_layout_by_id = pyqtSignal(int)
    request_show_diagnostic = pyqtSignal()
    request_status_text = pyqtSignal(str)
    request_display_message = pyqtSignal(str, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PLACS Debug Пульт — ТЫ ЗДЕСЬ ГЛАВНЫЙ (временно)")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.setFixedSize(590, 630)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Блок управления состояниями
        state_group = QGroupBox("РЕЖИМЫ СТАТУСА — ПОДЧИНИТЕСЬ!")
        state_layout = QVBoxLayout()

        self.state_combo = QComboBox()
        self.state_combo.addItems([
            "START - Запуск", "OK - Хорошо", "WARNING - Предупреждение", 
            "SERVER_CONNECT - Ошибка соединения", "NETWORK - Интернет барахлит", 
            "CRITICAL - Критическая ошибка"
        ])
        state_layout.addWidget(QLabel("Выбери судьбу интерфейса:"))
        state_layout.addWidget(self.state_combo)

        force_btn = QPushButton("Принудительно применить статус")
        force_btn.clicked.connect(self._emit_state_by_name)
        state_layout.addWidget(force_btn)

        state_group.setLayout(state_layout)
        root.addWidget(state_group)

        # Блок управления слоем виджета
        index_group = QGroupBox("НОМЕР СЛОЯ - СМЕНИСЬ!")
        index_layout = QVBoxLayout()

        self.layout_combo = QComboBox()
        self.layout_combo.addItems([
            "0 - Запуск", "1 - Статус", "2 - Диагностический",
            "3 - О PLACS", "4 - Выход", "5 - Сервисный режим"
        ])
        index_layout.addWidget(QLabel("Выбери судьбу виджета:"))
        index_layout.addWidget(self.layout_combo)

        force_layout_btn = QPushButton("Принудительно применить статус")
        force_layout_btn.clicked.connect(self._emit_layout_by_name)
        index_layout.addWidget(force_layout_btn)

        index_group.setLayout(index_layout)
        root.addWidget(index_group)

        # Блок управления сообщениями статуса
        status_group = QGroupBox("Сообщение агента — ЗАСТАВИТЬ ГОВОРИТЬ")
        status_layout = QVBoxLayout()
        self.status_edit = QLineEdit()
        self.status_edit.setPlaceholderText("Например: Проверяю доступ к серверу…")
        send_status_btn = QPushButton("Отправить как статус")
        send_status_btn.clicked.connect(lambda: self.request_status_text.emit(self.status_edit.text()))
        status_layout.addWidget(self.status_edit)
        status_layout.addWidget(send_status_btn)
        status_group.setLayout(status_layout)
        root.addWidget(status_group)

        # Блок всплывающего сообщения на экран
        display_group = QGroupBox("Сообщение на экран — СМОТРИ НА МЕНЯ")
        display_layout = QHBoxLayout()
        self.display_edit = QLineEdit()
        self.display_edit.setPlaceholderText("Текст для вывода на дисплей…")
        self.duration_spin = QSpinBox()
        self.duration_spin.setRange(1, 120)
        self.duration_spin.setValue(5)
        self.duration_spin.setSuffix(" сек")
        show_btn = QPushButton("Показать")
        show_btn.clicked.connect(lambda: self.request_display_message.emit(self.display_edit.text(), self.duration_spin.value()))
        display_layout.addWidget(self.display_edit)
        display_layout.addWidget(self.duration_spin)
        display_layout.addWidget(show_btn)
        display_group.setLayout(display_layout)
        root.addWidget(display_group)

        # Отступ от навигации
        root.addStretch()

        # Навигация
        nav_layout = QHBoxLayout()
        exit_btn = QPushButton("Быстрое отключение")
        to_diag_btn = QPushButton("Диагностика")
        exit_btn.clicked.connect(self.request_exit.emit)
        to_diag_btn.clicked.connect(self.request_show_diagnostic.emit)
        nav_layout.addWidget(exit_btn)
        nav_layout.addWidget(to_diag_btn)
        root.addLayout(nav_layout)

        # Немного тоталитарного шарма
        root.addWidget(QLabel("<i>Власть развращает. Используй ответственно, командир~</i>"))

        self.setLayout(root)

    def _emit_state_by_name(self, name: str):
        name = self.state_combo.currentText()

        mapping = {
            "START - Запуск": ErrorState.START,
            "OK - Хорошо": ErrorState.OK,
            "WARNING - Предупреждение": ErrorState.WARNING,
            "SERVER_CONNECT - Ошибка соединения": ErrorState.SERVER_CONNECT,
            "NETWORK - Интернет барахлит": ErrorState.NETWORK,
            "CRITICAL - Критическая ошибка": ErrorState.CRITICAL,
        }
        state = mapping.get(name, ErrorState.OK)
        self.request_state_change.emit(state)
    
    def _emit_layout_by_name(self):
        name = self.layout_combo.currentText()

        mapping = {
            "0 - Запуск": 0,
            "1 - Статус": 1,
            "2 - Диагностический": 2,
            "3 - О PLACS": 3,
            "4 - Выход": 4,
            "5 - Сервисный режим": 5
        }
        state = mapping.get(name, 1)
        self.request_layout_by_id.emit(state)


def create_debug_pult_with_thread(parent=None):
    """
    Фабрика: создаёт диалог и отдельный поток-воркер.
    Возвращает (dialog, thread, worker).
    Примечание: сам QDialog создаётся и работает в GUI-потоке (как положено Qt),
    отдельный поток выделен под фоновые штучки пульта/будущие расширения.
    """
    thread = QThread()
    worker = DebugPultWorker()
    worker.moveToThread(thread)
    dialog = DebugPultDialog(parent)
    return dialog, thread, worker


