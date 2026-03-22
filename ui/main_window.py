import os
import re

from PyQt5.QtWidgets import (
    QMainWindow, QVBoxLayout, QWidget, QSizePolicy, QScrollArea,
    QLabel, QTextEdit, QToolBar, QPushButton, 
    QDialog, QHBoxLayout, QStackedWidget, QGridLayout,
    QApplication, QMessageBox, QListWidget,
    QListWidgetItem, QShortcut
)

from PyQt5.QtCore import Qt, QSettings, pyqtSignal, QSize, QTimer
from PyQt5.QtGui import QPixmap, QFont, QMovie, QColor, QKeySequence, QIcon

from ui.config_dialog import ClientSettingsDialog
from ui.service_setup_window import ServiceSetupWindow
from core.config_manager import set_debug_state
from core.error_types import ErrorState
from core.privilege_prompt import approval_broker

from ui.set_on_display_window import SetOnDisplayWindow
from core.utils import get_current_time, is_linux, get_random_file_path, get_username, clear_folder, is_windows
from core.logger import LOG_FOLDER

from workers.server_communicator import send_log_to_server

import logging

log = logging.getLogger("MainWindow")

LOAD_LAYOUT_INDEX = 0
STATUS_LAYOUT_INDEX = 1
DIAGNOSTIC_LAYOUT_INDEX = 2
ABOUT_LAYOUT_INDEX = 3
EXIT_LAYOUT_INDEX = 4
SERVICE_LAYOUT_INDEX = 5
VPN_LAYOUT_INDEX = 6
MENU_LAYOUT_INDEX = 7

class HtmlMessageDialog(QDialog):
    def __init__(self, title, html_content, img_src=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)

        self.setMinimumWidth(600) # Минимальная ширина
        self.setMaximumWidth(810) # Максимальная ширина
        self.setMinimumHeight(400) # Минимальная высота
        self.setMaximumHeight(440) # максимальная высота

        self.setModal(False) # Не делает диалог модальным (блокирует родительское окно)

        layout_v = QVBoxLayout(self)
        layout_h = QHBoxLayout(self)

        message_label = QLabel(html_content)
        message_label.setWordWrap(True) # Автоматический перенос строк
        message_label.setTextFormat(Qt.RichText) # HTML
        layout_h.addWidget(message_label)

        if img_src:
            collar_man_pic = QPixmap(img_src)
            scaled_pixmap = collar_man_pic.scaled(180, 180, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icon_label = QLabel()
            icon_label.setPixmap(scaled_pixmap)
            icon_label.setMinimumHeight(180) # Чтобы от текста не обрезали
            icon_label.setAlignment(Qt.AlignCenter) # Центрируем картинку
            layout_h.addWidget(icon_label)
        
        layout_v.addLayout(layout_h)

        ok_button = QPushButton("Хорошо")
        ok_button.clicked.connect(self.accept) # Закрывает диалог по нажатию
        layout_v.addWidget(ok_button, alignment=Qt.AlignCenter) # Кнопка по центру

        self.setLayout(layout_v)

class MainWindow(QMainWindow):
    last_status = ["-", "-", "-", "-", "-"]
    start_diagnostic_signal = pyqtSignal()  # Для запуска диагностики из UI (например, кнопкой "Перезапустить")
    try_fix_network_signal = pyqtSignal()  # Для кнопки "Попробовать исправить" (только Linux)
    restart_app = None  # Функция принудительного перезапуска
    # --- VPN Сигналы ---
    request_vpn_refresh = pyqtSignal()  # Запрос на обновление списка конфигов
    request_vpn_connect = pyqtSignal(str)  # Запрос на подключение к сети (network_name)
    request_vpn_disconnect = pyqtSignal()  # Запрос на отключение всех соединений

    def __init__(self, debug, log_path):
        super().__init__()
        settings = QSettings("PLACS", "Agent")

        self.setWindowTitle("PLACS Agent - Запуск агента...")
        self.setFixedSize(910, 560) # Фиксируем

        if settings.value("ui/mainWindowOnTop", True, type=bool):
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint) # Окно поверх других
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint) # Окно не поверх других
        
        self.DEBUG = debug
        self.log_path = log_path
        
        log.info("MainWindow инициализированно!")
        self.current_display_window = None
        self._approval_dialog_open = False

        self.stacked_widget = QStackedWidget() # Используем QStackedWidget для переключения лейаутов
        self.stacked_widget.setContentsMargins(0, 0, 0, 0)
        
        self.setCentralWidget(self.stacked_widget)

        self.init_load_layout() # Инициализируем layout запуска, он самый первый и основной
        self.init_status_layout() # Инициализируем новый layout
        self.init_diagnostic_layout() # Экран диагностики

        self.init_ui() # layout "О PLACS"
        self.init_exit_layout() # Слой завершения программы

        self.init_service_layout()

        self.init_toolbar() # Добавляем окну тулбар
        self.init_vpn_layout()  # VPN layout (добавляем до возможных переключений)
        self.init_menu_layout()
        self._approval_timer = QTimer(self)
        self._approval_timer.timeout.connect(self.process_pending_privileged_requests)
        self._approval_timer.start(200)

        self.layout_befor = None # Нужно чтобы возвращаться из окна "о программе" на предыдущее состояние

        if not settings.value("ui/showMainWindowOnStart", True, type=bool):
            self.hide()
        else:
            self.show()

    # ------------------------ VPN LAYOUT ------------------------
    def init_vpn_layout(self):
        """Создает основной VPN виджет и два слоя: загрузка и список сетей."""
        self.vpn_widget = QWidget()
        self.vpn_widget.setObjectName("VpnRootWidget")
        vpn_root_layout = QVBoxLayout(self.vpn_widget)
        vpn_root_layout.setContentsMargins(0, 0, 0, 0)
        vpn_root_layout.setSpacing(10)

        # Внутренний QStackedWidget (0: загрузка, 1: список)
        self.vpn_stack = QStackedWidget()
        self.vpn_stack.setObjectName("VpnStack")

        # --- Слой 0: Загрузка ---
        loading_layer = QWidget()
        loading_layout = QVBoxLayout(loading_layer)
        loading_layout.setAlignment(Qt.AlignCenter)
        loading_layout.addStretch(1)

        self.vpn_loading_label = QLabel("<h2>Секундочку! Обновляю список...</h2>")
        self.vpn_loading_label.setAlignment(Qt.AlignCenter)
        self.vpn_loading_label.setObjectName("VpnUpdatingLabel")
        loading_layout.addWidget(self.vpn_loading_label)

        self.vpn_spinner_label = QLabel()
        self.vpn_spinner_movie = QMovie("ui/media/img/anim/spinner.gif")
        self.vpn_spinner_movie.setScaledSize(QSize(200, 200))
        self.vpn_spinner_label.setMovie(self.vpn_spinner_movie)
        self.vpn_spinner_label.setAlignment(Qt.AlignCenter)
        loading_layout.addWidget(self.vpn_spinner_label)
        loading_layout.addStretch(1)

        self.vpn_stack.addWidget(loading_layer)

        # --- Слой 1: Список сетей ---
        self.vpn_list_layer = QWidget()
        vpn_list_layout = QVBoxLayout(self.vpn_list_layer)
        vpn_list_layout.setContentsMargins(10, 10, 10, 10)
        vpn_list_layout.setSpacing(12)

        # Заголовок / приветствие
        self.vpn_header_label = QLabel("<h2>VPN Сети</h2>")
        self.vpn_header_label.setObjectName("VpnHeader")
        vpn_list_layout.addWidget(self.vpn_header_label)

        # Статус текущего подключения
        self.vpn_status_label = QLabel("Не подключено")
        self.vpn_status_label.setObjectName("VpnStatusLabel")
        vpn_list_layout.addWidget(self.vpn_status_label)

        # Scroll area для списка сетей
        self.vpn_scroll_area = QScrollArea()
        self.vpn_scroll_area.setObjectName("VpnScrollArea")
        self.vpn_scroll_area.setWidgetResizable(True)
        self.vpn_scroll_content = QWidget()
        self.vpn_scroll_layout = QVBoxLayout(self.vpn_scroll_content)
        self.vpn_scroll_layout.setSpacing(8)
        self.vpn_scroll_layout.addStretch(1)
        self.vpn_scroll_area.setWidget(self.vpn_scroll_content)
        vpn_list_layout.addWidget(self.vpn_scroll_area, 1)

        # Кнопки управления (Назад + Отключение)
        buttons_row = QWidget()
        buttons_layout = QHBoxLayout(buttons_row)
        buttons_layout.setContentsMargins(0, 0, 0, 0)

        self.vpn_back_button = QPushButton("<< На главную")
        self.vpn_back_button.setStyleSheet("background-color: #2e2e2e;")
        self.vpn_back_button.setToolTip("Вернуться в предыдущее меню")
        self.vpn_back_button.clicked.connect(self.hide_vpn)
        buttons_layout.addWidget(self.vpn_back_button)

        buttons_layout.addStretch(1)

        self.vpn_disconnect_button = QPushButton("Отключение")
        self.vpn_disconnect_button.setObjectName("VpnDisconnectButton")
        self.vpn_disconnect_button.clicked.connect(lambda: self.request_vpn_disconnect.emit())
        buttons_layout.addWidget(self.vpn_disconnect_button)

        vpn_list_layout.addWidget(buttons_row)

        self.vpn_stack.addWidget(self.vpn_list_layer)

        vpn_root_layout.addWidget(self.vpn_stack)

        # Добавляем основной VPN виджет в общий стек
        self.stacked_widget.addWidget(self.vpn_widget)

        # Текущее подключение
        self.current_vpn_network = None
        # Индекс предыдущего экрана для кнопки Назад
        self.vpn_prev_index = None

    def show_vpn_layout(self):
        """Показать VPN интерфейс и инициировать обновление списка конфигов."""
        self.vpn_stack.setCurrentIndex(0)  # Показываем слой загрузки
        self.vpn_spinner_movie.start()
        self.request_vpn_refresh.emit()
        self.switch_layout(VPN_LAYOUT_INDEX)  # Индекс VPN виджета в основном стеке

    def hide_vpn(self):
        """Возврат с экрана VPN к предыдущему экрану."""
        # Останавливаем спиннер, если он крутится
        try:
            self.vpn_spinner_movie.stop()
        except Exception:
            pass
        self.switch_layout(MENU_LAYOUT_INDEX)

    def update_vpn_configs_view(self, configs):
        """Обновляет список VPN конфигураций.
        configs: list[{'config_id':..., 'network_id':..., 'network_name':..., 'path':...}]
        """
        # Очищаем старые элементы (кроме стретча в конце)
        while self.vpn_scroll_layout.count() > 1:
            item = self.vpn_scroll_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        username = get_username() if callable(get_username) else "user"
        if configs:
            count = len(configs)
            if count == 1:
                header_html = f"<h3>Ох, {username}, у тебя выбор не большой... Только одна сеть...</h3>"
            else:
                # Правильное склонение слова "сеть"
                if count % 10 == 1 and count % 100 != 11:
                    network_word = "сети"
                elif count % 10 in [2, 3, 4] and count % 100 not in [12, 13, 14]:
                    network_word = "сетей"
                else:
                    network_word = "сетей"
                header_html = f"<h3>Ого! {username}, у тебя выбор из {count} {network_word}!</h3>"
        else:
            header_html = f"<h3>Ой! Прости, {username}, сервер не выдал конфигурации...</h3>"
        self.vpn_header_label.setText(header_html)

        for cfg in configs:
            network_name = cfg.get('network_name') or 'unknown'
            config_id = cfg.get('config_id')
            network_id = cfg.get('network_id')

            item_widget = QWidget()
            item_widget.setObjectName("VpnItem")
            item_layout = QHBoxLayout(item_widget)
            item_layout.setContentsMargins(10, 10, 10, 10)
            item_layout.setSpacing(15)

            # Иконка сети
            icon_label = QLabel()
            icon_pixmap = QPixmap("ui/media/img/icons_png/PLACS_ICON_NETWORK.png")
            if not icon_pixmap.isNull():
                icon_label.setPixmap(icon_pixmap.scaled(76, 76, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            icon_label.setAlignment(Qt.AlignCenter)
            item_layout.addWidget(icon_label)

            # Текстовая часть
            text_container = QWidget()
            text_layout = QVBoxLayout(text_container)
            text_layout.setContentsMargins(0, 0, 0, 0)
            meta_label = QLabel(f"ID сети: {network_id} | ID конфигурации: {config_id}")
            meta_label.setStyleSheet("color: #888; font-size: 11px;")
            name_label = QLabel(f"<b>{network_name}</b>")
            name_label.setStyleSheet("font-size:14px;")
            text_layout.addWidget(meta_label)
            text_layout.addWidget(name_label)
            item_layout.addWidget(text_container, 1)

            # Кнопка подключения
            connect_btn = QPushButton("Подключиться")
            connect_btn.setObjectName("VpnConnectButton")
            connect_btn.clicked.connect(lambda _, n=network_name: self._confirm_and_connect(n))
            item_layout.addWidget(connect_btn)

            self.vpn_scroll_layout.insertWidget(self.vpn_scroll_layout.count() - 1, item_widget)

        # После обновления показываем слой списка
        # С небольшой задержкой чтобы избежать мерцания
        QTimer.singleShot(1500, lambda: self.vpn_stack.setCurrentIndex(1))
        self.vpn_spinner_movie.stop()

    def _confirm_and_connect(self, network_name: str):
        """Подтверждение перед подключением."""
        if is_windows():
            msg = (f"""<div style="padding:12px; color:#eaeaea; border-radius:10px; font-family: 'Segoe UI', Tahoma, sans-serif;">
                        <div style="font-size:18px; margin-bottom:8px;">✨ <b>Готов войти в сегмент «{network_name}»?</b></div>
                        <div style="margin-bottom:10px; color:#d0d0d0;">Вот что я сделаю для корректного подключения:</div>
                        <ul style="list-style:none; padding:0; margin:0 0 12px 0;">
                            <li style="margin-bottom:8px;">🛑 <b>Принудительно закрою</b> все существующие соединения — чтобы не было конфликтов.</li>
                            <li style="margin-bottom:8px;">🔁 <b>Инициирую новое</b> подключение под нужной конфигурацией.</li>
                            <li style="margin-bottom:8px;">🧭 <b>Сброшу настройки DNS</b>, чтобы внутренние сервисы открывались корректно.</li>
                        </ul>
                        <div style="font-size:12px; color:#cfcfcf;">⚠️ Система может запросить подтверждение прав администратора. Согласен?</div>
                    </div>""")
        else:
            msg = f"Ты уверен, что хочешь войти в сегмент сети: «{network_name}»?"

        reply = QMessageBox.question(self, "Подключение к VPN", msg,
                                     QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.request_vpn_connect.emit(network_name)

    def handle_vpn_operation_status(self, status: str, message: str):
        """Обновление статуса VPN операций."""
        # status: success|error|info
        prefix = {"success": "✅", "error": "❌", "info": "ℹ"}.get(status, "")
        self.vpn_status_label.setText(f"{prefix} {message}")
        if status == 'success' and 'инициировано' in message.lower():
            # Небольшой хук чтобы отобразить текущее подключение
            self.current_vpn_network = message.split('"')[-2] if '"' in message else None

    
    def init_load_layout(self):
        # Новый Layout для отображения статуса
        load_widget = QWidget()

        # Левая часть с блоками информации
        left_pane = QWidget()
        left_pane.setObjectName("LeftPane")
        info_blocks_layout = QVBoxLayout(left_pane)
        info_blocks_layout.addStretch(2)

        # Блок "Запускаюсь~"
        load_label = QLabel("<h1>Я запускаюсь~</h1>")
        load_label.setObjectName("loadLabel") # Устанавливаем objectName для стилизации
        load_label.setWordWrap(True)
        load_label.setAlignment(Qt.AlignCenter)
        info_blocks_layout.addWidget(load_label)

        # Блок "Ща те всё расскажу"
        need_label = QLabel("""
            <h3 style="font-size: 1.3em; margin-bottom: 10px;">Ой, столько всего интересного! Мне нужно бы...</h3>
            <ul style="list-style-type: '✨ '; margin-left: 15px; padding-left: 0;">
                <li style="margin-bottom: 8px;"><b>Выспаться</b>, чтобы быть готовым ко всем глупым командам. Ну, то есть, к важным!</li>
                <li style="margin-bottom: 8px;"><b>Посмотреть что я делал...</b> А то мало ли мои логи уже слишком большие! Мррр...</li>
                <li style="margin-bottom: 8px;"><b>Спросить сервер, как у него дела</b>. Важно же знать, не грустит ли он там один.</li>
                <li style="margin-bottom: 8px;"><b>Попросить печеньку от сервера</b>, если он вдруг очень добрый сегодня. 🍪(Или хотя бы даст мне ключи для сетей!)</li>
                <li style="margin-bottom: 8px;"><b>Продолжить бездельничать...</b> Ой, то есть, конечно же, работать!</li>
            </ul>
            <p style="text-align: right; margin-top: 15px; font-size: 0.9em; color: #b0b0b0;">
                (Шучу, я очень старательный!)<br>А пока я тут загружаюсь, советую просто немного подождать... <br>
                Как только закончу свои <i>очень важные</i> дела, это окошко само закроется!
            </p>
        """)
        need_label.setObjectName("needLabel")
        need_label.setWordWrap(True)
        info_blocks_layout.addWidget(need_label)

        info_blocks_layout.addStretch(1)

        go_to_main_button = QPushButton("Всё равно перейти к основному окну!")
        go_to_main_button.clicked.connect(lambda: self.update_ui_for_error_state(ErrorState.START))
        info_blocks_layout.addWidget(go_to_main_button)

        # Правая часть с картинкой
        right_pane = QWidget()
        right_pane.setObjectName("RightPane")
        right_pane.setFixedWidth(430)
        right_pane_layout = QVBoxLayout(right_pane)

        collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/start", ".png"))
        scaled_pixmap = collar_man_pic.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_label_status = QLabel()
        icon_label_status.setPixmap(scaled_pixmap)
        icon_label_status.setAlignment(Qt.AlignCenter) # Центрируем картинку
        right_pane_layout.addWidget(icon_label_status)

        # Соединяем панели на одной подложке
        load_main_layout = QHBoxLayout(load_widget)
        load_main_layout.setSpacing(0)
        load_main_layout.setContentsMargins(0, 0, 0, 0)
        load_main_layout.addWidget(left_pane)
        load_main_layout.addWidget(right_pane)

        # Добавляем новый виджет в QStackedWidget
        self.stacked_widget.addWidget(load_widget)

    def init_exit_layout(self):
        # Новый Layout для отображения окна выхода
        exit_widget = QWidget()

        # Левая часть с прощанием
        left_pane = QWidget()
        left_pane.setObjectName("LeftPane")
        left_pane.setFixedWidth(350)
        bb_blocks_layout = QVBoxLayout(left_pane)
        bb_blocks_layout.addStretch()

        # Анимация
        spiner_label = QLabel(self)
        self.exit_spiner = QMovie("ui/media/img/anim/spinner.gif")
        self.exit_spiner.setScaledSize(QSize(300, 300))
        spiner_label.setMovie(self.exit_spiner)
        spiner_label.setAlignment(Qt.AlignCenter)
        spiner_label.setObjectName("LeftPaneNoBG")
        bb_blocks_layout.addWidget(spiner_label)
        bb_blocks_layout.addStretch()

        # Правая часть с анимацией и большими буквами
        right_pane = QWidget()
        right_pane.setObjectName("RightPane")
        right_pane_layout = QVBoxLayout(right_pane)
        right_pane_layout.addStretch(1)

        # Текст с тем, что делает (он может перезапускаться)
        self.exit_label = QLabel("<h1>Отключаюсь...</h1>")
        self.exit_label.setObjectName("exitLabel") # Устанавливаем objectName для стилизации
        self.exit_label.setWordWrap(True)
        self.exit_label.setAlignment(Qt.AlignCenter)
        right_pane_layout.addWidget(self.exit_label)

        # Почему агент перезапускается? Данное поле может отстутвовать
        self.exit_reason = QLabel("")
        self.exit_reason.setObjectName("exitReason") # Устанавливаем objectName для стилизации
        self.exit_reason.setWordWrap(True)
        self.exit_reason.setAlignment(Qt.AlignCenter)

        right_pane_layout.addWidget(self.exit_reason)
        right_pane_layout.addStretch(2)

        # Картинка
        collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/sleep", ".png"))
        scaled_pixmap = collar_man_pic.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.icon_label_exit = QLabel()
        self.icon_label_exit.setPixmap(scaled_pixmap)
        self.icon_label_exit.setAlignment(Qt.AlignCenter) # Центрируем картинку
        right_pane_layout.addWidget(self.icon_label_exit)
        right_pane_layout.addStretch()

        # Соединяем панели на одной подложке
        exit_main_layout = QHBoxLayout(exit_widget)
        exit_main_layout.setSpacing(0)
        exit_main_layout.setContentsMargins(0, 0, 0, 0)
        exit_main_layout.addWidget(left_pane)
        exit_main_layout.addWidget(right_pane)

        # Добавляем новый виджет в QStackedWidget
        self.stacked_widget.addWidget(exit_widget)
    
    def init_diagnostic_layout(self):
        """Инициализирует UI для экрана диагностики сети."""
        diagnostic_widget = QWidget()
        layout = QVBoxLayout(diagnostic_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 1. Заголовок
        name_and_icon_layout = QHBoxLayout()
        name_and_icon_layout.addStretch()
        header_label = QLabel("<h4>Диагностика сетевых проблем!</h4>")
        header_label.setAlignment(Qt.AlignCenter)
        header_label.setObjectName("DiagnosticHeader")
        name_and_icon_layout.addWidget(header_label)
        
        try:
            pixmap = QPixmap("ui/media/img/colar_man/TROUBLE_COLLAR_MAN.png")
            if pixmap.isNull():
                log.error(f"Не удалось загрузить проблемное изображение.")
                image_label = QLabel("⚠️ Изображение не найдено")
            else:
                image_label = QLabel()
                # Масштабируем картинку, сохраняя пропорции, до разумного размера
                scaled_pixmap = pixmap.scaled(130, 130, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                image_label.setPixmap(scaled_pixmap)
                image_label.setAlignment(Qt.AlignCenter)
                image_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed) # Фиксированный размер для картинки

            image_label.setObjectName("DiagnosticImage")
            name_and_icon_layout.addWidget(image_label, alignment=Qt.AlignCenter)

        except Exception as e:
            log.exception(f"Error loading diagnostic image: {e}")
            image_label = QLabel("⚠️ Ошибка загрузки изображения")
            image_label.setObjectName("DiagnosticImage")
            name_and_icon_layout.addWidget(image_label, alignment=Qt.AlignCenter)
        
        name_and_icon_widget = QWidget()
        name_and_icon_widget.setLayout(name_and_icon_layout)
        name_and_icon_widget.setObjectName("DiagnosticNaleAndLable")
        
        layout.addWidget(name_and_icon_widget)

        # 3. Что я проверяю?
        info_label = QLabel("Проверяю доступность сервера PLACS Agent и общую сетевую связность.")
        info_label.setAlignment(Qt.AlignCenter)
        info_label.setWordWrap(True)
        info_label.setObjectName("DiagnosticInfoLabel")
        layout.addWidget(info_label)

        # 4. Список проверок (динамически обновляемый)
        self.checklist_label = QLabel("Загрузка списка проверок...")
        self.checklist_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.checklist_label.setObjectName("DiagnosticChecklist")
        self.checklist_label.setFont(QFont("Monospace", 10)) # Фиксированная ширина шрифта для смайликов
        layout.addWidget(self.checklist_label)
        
        # 5. Результат последней проверки подробнее
        detail_header_label = QLabel("<h5>Подробный результат проверки:</h5>")
        detail_header_label.setObjectName("DiagnosticDetailHeader")
        layout.addWidget(detail_header_label)

        self.detail_output_text = QTextEdit()
        self.detail_output_text.setReadOnly(True)
        self.detail_output_text.setObjectName("DiagnosticDetailOutput")
        self.detail_output_text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding) # Расширяется по вертикали
        layout.addWidget(self.detail_output_text)

        # Кнопки управления
        button_layout = QHBoxLayout()
        button_layout.setSpacing(10)

        # Кнопка "Попробовать исправить" (только для Linux)
        if is_linux():
            self.fix_button = QPushButton("Попробовать исправить")
            self.fix_button.setObjectName("FixButton")
            self.fix_button.clicked.connect(self.try_fix_network_signal.emit)
            button_layout.addWidget(self.fix_button)
        else:
            self.fix_button = None # Устанавливаем в None, если не создана

        self.restart_diagnostic_button = QPushButton("Перезапустить диагностику")
        self.restart_diagnostic_button.setObjectName("RestartDiagnosticButton")
        self.restart_diagnostic_button.clicked.connect(self.start_diagnostic_signal.emit)
        button_layout.addWidget(self.restart_diagnostic_button)

        self.back_button = QPushButton("Вернуться в меню")
        self.back_button.setObjectName("BackButton")
        self.back_button.clicked.connect(lambda: self.switch_to_main_status_layout())
        button_layout.addWidget(self.back_button)

        layout.addLayout(button_layout)
        
        self.diagnostic_check_items = [] # Список для хранения пар (название, статус-эмодзи)
        self._update_diagnostic_checklist_display() # Инициализируем пустой список

        self.stacked_widget.addWidget(diagnostic_widget)

    def init_status_layout(self):
        """
        Инициализирует и компонует виджет статуса с чётким разделением
        на левую (информация) и правую (изображение) панели.
        """
        # 1. Главный контейнер для всего экрана статуса
        status_widget = QWidget()

        # 2. Создаём левую панель как отдельный виджет
        left_pane = QWidget()
        left_pane.setObjectName("LeftPane")
        info_blocks_layout = QVBoxLayout(left_pane) # Сразу устанавливаем layout для левой панели

        # Блок "Текущее состояние"
        self.current_state_label = QLabel("<h2>Не подглядывай...</h2><p>Мой интерфейс ещё загружается....</p>")
        self.current_state_label.setObjectName("currentStateLabel")
        self.current_state_label.setWordWrap(True)
        info_blocks_layout.addWidget(self.current_state_label)

        # Блок "Что я делаю сейчас"
        self.current_activity_label = QLabel("<h3>Что я делаю сейчас:</h3><p>Ожидаю команды от сервера...</p>")
        self.current_activity_label.setObjectName("currentActivityLabel")
        self.current_activity_label.setWordWrap(True)
        info_blocks_layout.addWidget(self.current_activity_label)

        # Блок "Что я делал недавно"
        self.recent_activity_label = QLabel()
        self.recent_activity_label.setObjectName("recentActivityLabel")
        self.recent_activity_label.setWordWrap(True)
        self.recent_activity_label.setText(self.generate_recent_activity_html())
        info_blocks_layout.addWidget(self.recent_activity_label)

        # Блок "Последняя ошибка"
        self.last_error_label = QLabel("<h3>Последняя ошибка:</h3><p>Их нету! Всё хорошо!</p>")
        # Я исправил здесь objectName, чтобы он был уникальным
        self.last_error_label.setObjectName("lastErrorLabel")
        self.last_error_label.setWordWrap(True)
        info_blocks_layout.addWidget(self.last_error_label)

        # 3. Создаём правую панель (это просто QLabel с картинкой и статичный текст)
        right_pane = QWidget()
        right_pane.setObjectName("RightPane")
        right_pane.setFixedWidth(430)
        right_pane_layout = QVBoxLayout(right_pane)
        #right_pane_layout.setContentsMargins(5, 2, 5, 2)

        # Текст на правой панельке
        hello_label = QLabel(f"<h1>Привет, {get_username()}!</h1>")
        hello_label.setWordWrap(True)
        hello_label.setAlignment(Qt.AlignCenter)
        right_pane_layout.addWidget(hello_label)
        #Небольшой промежуток после текста, чтобы он прилип к верху
        right_pane_layout.addStretch()

        self.icon_label_status = QLabel()
        collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/unhappy", ".png"))
        scaled_pixmap = collar_man_pic.scaled(420, 420, 
                                              Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.icon_label_status.setPixmap(scaled_pixmap)
        self.icon_label_status.setAlignment(Qt.AlignCenter)
        right_pane_layout.addWidget(self.icon_label_status)
        # Небольшой промежуток после картинки, чтобы не упала
        right_pane_layout.addStretch()

        # 4.  Версия агента
        from core.ver import __version__, __assets_packet_version__
        indicator = QLabel(f"<p style=\"font-weight: normal;margin: 3px;font-size: 11px;color: #cfcfcf;\">Agent v{__version__} | Assets v{__assets_packet_version__} | {'Сервисный' if self.DEBUG else 'Стандартный'}</p>")
        indicator.setAlignment(Qt.AlignRight)
        right_pane_layout.addWidget(indicator)

        # 5. Собираем всё в главном layout'е
        status_main_layout = QHBoxLayout(status_widget) # Устанавливаем layout для status_widget
        status_main_layout.setSpacing(0)
        status_main_layout.setContentsMargins(0, 0, 0, 0)
        status_main_layout.addWidget(left_pane)
        status_main_layout.addWidget(right_pane)

        # 6. Добавляем собранный виджет в QStackedWidget
        self.stacked_widget.addWidget(status_widget)

    def init_ui(self):
        # Основной Layout
        main_widget = QWidget()
        main_layout = QVBoxLayout(main_widget)

        about_layout = QHBoxLayout()

        # Тут будет кнопка назад и картинка
        layout_v = QVBoxLayout()
        go_back_button = QPushButton("<< На главную")
        go_back_button.setStyleSheet("background-color: #2e2e2e;")
        go_back_button.setToolTip("Вернуться на предыдущий экран.")
        go_back_button.clicked.connect(lambda: self.switch_layout(MENU_LAYOUT_INDEX))
        layout_v.addWidget(go_back_button)

        # Добавляем небольшой промежуток и картинку
        layout_v.addStretch()
        rbdz_pic = QPixmap("ui/media/img/rcn_placs_logo.png")
        scaled_pixmap = rbdz_pic.scaled(320, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_label = QLabel()
        icon_label.setPixmap(scaled_pixmap)
        layout_v.addWidget(icon_label)

        # Добавляем промежуток после и суём в основной лэйаут
        layout_v.addStretch()
        about_layout.addLayout(layout_v)

        description_text_edit = QTextEdit()
        description_text_edit.setReadOnly(True)
        description_text_edit.setStyleSheet("background-color: transparent; border: none;")

        from core.ver import __version__, __author__

        html_description = f"""
        <center>
            <h1 style="margin-bottom: 5px; font-size: 2.2em;">Passive Linux Agent Control System</h1>
            <p style="font-size: 1.2em; color: #c9c9c9; margin-top: 5px;"><i>Твой надёжный помощник в мире удалённого доступа.</i></p>
        </center>

        <hr style="border: 0; height: 1px; background: #ddd; margin: 20px 0;">

        <p style="font-size: 1.1em; line-height: 1.6;">
            Ты работаешь с <b>PLACS Агентом</b> — это маленькая, но очень умная программа, которая позволяет твоим системным администраторам (или тебе самому!) удобно и безопасно <b>управлять твоим компьютером удалённо</b>. Думай об этом как о невидимом мостике, который соединяет твой компьютер с центром управления PLACS.
        </p>

        <p style="font-size: 1.1em; line-height: 1.6;">
            <b>Что PLACS Агент умеет делать для тебя?</b>
            <ul style="list-style-type: '🚀 '; margin-left: 15px; padding-left: 0;">
                <li style="margin-bottom: 10px;">
                    <b>Быстрая помощь:</b> Администратор может мгновенно решить проблему на твоём компьютере, даже если он находится далеко. Больше не нужно ждать!
                </li>
                <li style="margin-bottom: 10px;">
                    <b>Автоматическое обновление:</b> PLACS помогает поддерживать программы и систему в актуальном состоянии, чтобы твой компьютер работал быстро и безопасно.
                </li>
                <li style="margin-bottom: 10px;">
                    <b>Простой доступ к ресурсам:</b> Нужен доступ к удалённой сети или ресурсам? PLACS может настроить это за тебя, без лишних сложностей.
                </li>
                <li style="margin-bottom: 10px;">
                    <b>Поддержание стабильности:</b> Агент следит за "здоровьем" компьютера и отправляет отчёты, чтобы специалисты могли предотвратить возможные проблемы до их возникновения.
                </li>
            </ul>
        </p>

        <p style="font-size: 1.1em; line-height: 1.6;">
            Всё это происходит <b>безопасно и незаметно</b> в фоновом режиме, не отвлекая тебя от работы. Твоя информация надёжно защищена, а все действия контролируются твоими администраторами.
        </p>

        <hr style="border: 0; height: 1px; background: #ddd; margin: 20px 0;">

        <p style="font-size: 0.95em; color: #c9c9c9; text-align: center;">
            <b>Версия этого Агента:</b> {__version__}<br>
            <b>Разработано с заботой:</b> {__author__}
        </p>

        <center style="margin-top: 25px;">
            <p style="font-size: 1.2em; font-weight: bold;">
                Просто работай, а PLACS позаботится обо всём остальном! ✨
            </p>
        </center>
        """
        description_text_edit.setHtml(html_description)
        about_layout.addWidget(description_text_edit)
        main_layout.addLayout(about_layout)
        
        self.status_label = QLabel('<h3 style="margin-bottom: 2px;">Статус агента:</h3> Запущен и работает в фоне...')
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("background-color: #af604c; padding: 3px; border-radius: 8px; min-height: 30px;")
        main_layout.addWidget(self.status_label)

        # Добавляем основной виджет в QStackedWidget
        self.stacked_widget.addWidget(main_widget)
    
    # Сервисный режим
    def toggle_service_mode(self):
        """Активирует сервисный режим и обновляет список логов."""
        log.info("Активирован сервисный режим через шорткат.")
        self.switch_layout(SERVICE_LAYOUT_INDEX)
        self.refresh_log_list()
        self.update_debug_button_text()

    def init_service_layout(self):
        """Инициализирует основной виджет сервисного слоя."""
        self.service_page = QWidget()
        main_layout = QVBoxLayout(self.service_page)
        self.service_stacked_widget = QStackedWidget()
        main_layout.addWidget(self.service_stacked_widget)

        warning_page = self.create_service_warning_page()
        main_service_page = self.create_main_service_page()

        self.service_stacked_widget.addWidget(warning_page)
        self.service_stacked_widget.addWidget(main_service_page)
        self.service_stacked_widget.setCurrentIndex(0)

        self.stacked_widget.addWidget(self.service_page)

    def create_service_warning_page(self):
        """Создает страницу с предупреждением."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)

        achtung_label = QLabel("<p style='color: #ff3333;font-size: 28px;'>Стоять!<br>Не пущу - если не прочитаешь...</p>")
        achtung_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(achtung_label)

        image_label = QLabel()
        pixmap = QPixmap("ui/media/mascot_img/manager/MANAGER_POINTING.png")
        if not pixmap.isNull():
            image_label.setPixmap(pixmap.scaled(250, 250, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        image_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(image_label)

        warning_label = QLabel("<p style='color: #ff6666;font-size: 14px;'>Ты переходишь к функционалу, который может инвазивно влиять на работу Сабика!<br>Если не уверен, что готов к этому, просто выйди отсюда</p>")
        warning_label.setAlignment(Qt.AlignCenter)
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        continue_button = QPushButton("Я осознаю риски и хочу продолжить")
        continue_button.clicked.connect(lambda: self.service_stacked_widget.setCurrentIndex(1))
        layout.addWidget(continue_button)

        go_back_button = QPushButton("<< В статус")
        go_back_button.setStyleSheet("background-color: #2e2e2e;")
        go_back_button.setToolTip("Вернуться в меню статуса")
        go_back_button.clicked.connect(lambda: self.switch_layout(MENU_LAYOUT_INDEX))
        layout.addWidget(go_back_button)
        
        return page

    def create_main_service_page(self):
        """Создает основную двухпанельную страницу сервисного режима."""
        page = QWidget()
        layout = QHBoxLayout(page)

        # Левая панель
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setAlignment(Qt.AlignTop)

        where_iam = QLabel("<h3>Дневники и дороги...</h3>")
        where_iam.setWordWrap(True)
        what_i_can_do  = QLabel("<p>Ну тут короче кнопки... журналы... делай что хочешь, что пристал? cам нажал...</p>")
        what_i_can_do.setWordWrap(True)

        self.debug_toggle_button = QPushButton()
        self.debug_toggle_button.clicked.connect(self.handle_debug_toggle)
        clear_logs_button = QPushButton("Полная очистка журнала")
        clear_logs_button.clicked.connect(self.handle_clear_logs)

        go_back_button = QPushButton("<< В статус")
        go_back_button.setStyleSheet("background-color: #2e2e2e;")
        go_back_button.setToolTip("Вернуться в меню статуса")
        go_back_button.clicked.connect(lambda: self.switch_layout(MENU_LAYOUT_INDEX))

        left_layout.addWidget(where_iam)
        left_layout.addWidget(self.debug_toggle_button)
        left_layout.addWidget(clear_logs_button)
        left_layout.addWidget(go_back_button)
        left_layout.addWidget(what_i_can_do)

        # Правая панель
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        self.log_summary_label = QLabel("Загрузка...")
        self.log_list_widget = QListWidget()
        self.log_list_widget.currentItemChanged.connect(self.display_log_content)
        log_header_widget = QWidget()
        log_header_layout = QHBoxLayout(log_header_widget)
        log_header_layout.setContentsMargins(0,0,0,0)
        self.log_meta_label = QLabel("Выберите лог для просмотра")
        self.send_log_button = QPushButton("Отправить на сервер")
        self.send_log_button.setEnabled(False)
        self.send_log_button.clicked.connect(self.send_current_log_to_server)
        log_header_layout.addWidget(self.log_meta_label)
        log_header_layout.addStretch()
        log_header_layout.addWidget(self.send_log_button)
        self.log_content_view = QTextEdit()
        self.log_content_view.setReadOnly(True)
        self.log_content_view.setFont(QFont("Courier", 10))
        right_layout.addWidget(self.log_summary_label)
        right_layout.addWidget(self.log_list_widget, 1)
        right_layout.addWidget(log_header_widget)
        right_layout.addWidget(self.log_content_view, 2)

        layout.addWidget(left_panel, 1)
        layout.addWidget(right_panel, 3)
        return page

    def update_debug_button_text(self):
        """Обновляет текст на кнопке вкл/выкл отладки."""
        text = "Выключить Debug режим" if self.DEBUG else "Включить Debug режим"
        self.debug_toggle_button.setText(text)

    def handle_debug_toggle(self):
        """Обрабатывает нажатие кнопки вкл/выкл отладки."""
        action_text = "выключить" if self.DEBUG else "включить"

        if not self.DEBUG:
            dialod = HtmlMessageDialog(
                "Описание режима отладки",
                """
                <div style="font-family: Segoe UI, sans-serif; color: #e0e0e0;">
                    <h2 style=\"color: #d9534f; border-bottom: 2px solid #eee; padding-bottom: 10px; margin-top: 0;\">Режим Отладки: Только для служебного пользования</h2>
                    <p>Слушай сюда. Ты запросил прямой доступ к внутренностям Агента. Я его даю, но вся ответственность — на тебе. Это не игрушки, это набор инструментов для разработчика.</p>
                    
                    <p>Что этот режим сделает с Агентом под моим управлением:</p>
                    
                    <ul style="list-style-type: none; padding-left: 0;">
                        <li style="margin-bottom: 10px; padding: 10px; border-left: 4px solid #f0ad4e; border-radius: 3px;">
                            <b style="color: #337ab7;">Поиск обновлений отключается.</b> Агент не будет отвлекаться на всякую ерунду, пока ты в нём копаешься.
                        </li>
                        <li style="margin-bottom: 10px; padding: 10px; border-left: 4px solid #f0ad4e; border-radius: 3px;">
                            <b style="color: #337ab7;">Автоматический перезапуск блокируется.</b> Если Агент "захлебнётся" от твоих действий, он не встанет сам. Придётся поднимать его вручную. Его страховка отключена.
                        </li>
                        <li style="margin-bottom: 10px; padding: 10px; border-left: 4px solid #f0ad4e; border-radius: 3px;">
                            <b style="color: #337ab7;">Появляется пульт управления.</b> Получишь прямой доступ к его состоянию и интерфейсу. Большая сила — большая ответственность.
                        </li>
                    </ul>

                    <p><b>Запомни:</b> этот режим превращает боевую машину в стенд для испытаний. Он не предназначен для штатной работы. Оставишь Агента в таком состоянии — жди беды.</p>

                    <div style="margin-top: 20px; font-size: 0.9em; color: #777; text-align: center; border-top: 1px solid #eee; padding-top: 10px;">
                        Если ты не разработчик, просто нажми "Нет" в следующем окне. Сломаешь — будешь чинить сам. Я всё сказал.
                    </div>
                </div>
                """
            )
            dialod.exec_()

        reply = QMessageBox.question(self, 'Подтверждение', f"Вы уверены, что хотите {action_text} режим отладки? Агент будет перезапущен.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            log.info(f"Пользователь {action_text} Debug режим. Перезапуск...")
            set_debug_state(not self.DEBUG)
            self.restart_app(True, "Применение конфигурации отладки")

    def handle_clear_logs(self):
        """Обрабатывает нажатие кнопки очистки логов."""
        reply = QMessageBox.question(self, 'Подтверждение', "Вы уверены, что хотите удалить ВСЕ логи? Текущий лог сессии будет пропущен.", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply == QMessageBox.Yes:
            log.info("Запрос на полную очистку журнала.")
            self.log_list_widget.clear()
            self.log_list_widget.addItem("Обработка...")
            QApplication.processEvents()
            clear_folder(LOG_FOLDER)
            self.refresh_log_list()

    def refresh_log_list(self):
        """Обновляет список логов на панели."""
        self.log_list_widget.clear()
        self.log_content_view.clear()
        self.log_meta_label.setText("Выберите лог для просмотра")
        self.send_log_button.setEnabled(False)
        log_files = []
        total_size = 0
        try:
            for filename in os.listdir(LOG_FOLDER):
                if filename.endswith(".log"):
                    file_path = os.path.join(LOG_FOLDER, filename)
                    try:
                        stat = os.stat(file_path)
                        log_files.append((filename, stat.st_mtime, stat.st_size))
                        total_size += stat.st_size
                    except FileNotFoundError: continue
        except Exception as e:
            self.log_summary_label.setText(f"Ошибка чтения логов: {e}")
            return
        log_files.sort(key=lambda x: x[1], reverse=True)
        self.log_summary_label.setText(f"Всего логов: {len(log_files)}. Общий размер: {total_size / 1024 / 1024:.2f} MB")
        current_log_file = os.path.basename(self.log_path)
        for filename, _, size in log_files:
            display_name = self.parse_log_filename(filename)
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, filename)
            if filename == current_log_file:
                item.setBackground(QColor("#242424"))
                item.setText(f"▶ {display_name} (Текущая сессия)")
            self.log_list_widget.addItem(item)

    def parse_log_filename(self, filename: str):
        """Преобразует имя файла лога в читаемый формат."""
        filename = filename.replace("initial_setup", "initial")
        match = re.match(r"agent_([a-zA-Z0-9]+)_(\d{2}-\d{2}-\d{4})_(\d{2}-\d{2}-\d{2})\.log", filename)
        if match:
            part1, date_str, time_str = match.groups()
            time_str = time_str.replace('-', ':')
            if "initial" in part1:
                return f"Установка от {date_str} {time_str}"
            else:
                return f"Сессия от {date_str} {time_str} (Агент: {part1}...)"
        return filename

    def display_log_content(self, current_item):
        """Отображает содержимое выбранного лога."""
        if not current_item: return
        filename = current_item.data(Qt.UserRole)
        file_path = os.path.join(LOG_FOLDER, filename)
        self.log_content_view.setText(f"Обработка лога {filename}...")
        QApplication.processEvents()
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            file_size = os.path.getsize(file_path)
            meta_text = f"Сообщений: {len(lines)} | Размер: {file_size/1024:.2f} KB"
            self.log_meta_label.setText(meta_text)
            self.log_content_view.clear()
            for line in lines:
                line_html = line.replace('<', '&lt;').replace('>', '&gt;').strip()
                color = "white"
                if "ERROR" in line: color = "red"
                elif "CRITICAL" in line: color = "darkred"
                elif "WARNING" in line: color = "orange"
                elif "DEBUG" in line: color = "blue"
                self.log_content_view.append(f'<span style="color: {color};">{line_html}</span>')
            self.send_log_button.setEnabled(True)
        except Exception as e:
            self.log_content_view.setText(f"Не удалось прочитать файл лога:\n{e}")
            self.log_meta_label.setText("Ошибка чтения файла")
            self.send_log_button.setEnabled(False)
            
    def send_current_log_to_server(self):
        """Отправляет текущий лог на сервер."""
        log_text = self.log_content_view.toPlainText().strip()
        if not log_text:
            QMessageBox.warning(self, "Ошибка", "Нет данных для отправки.")
            return

        original_text = self.send_log_button.text()
        self.send_log_button.setText("Отправка...")
        self.send_log_button.setEnabled(False)
        QApplication.processEvents()
        
        try:
            # Тут в идеале нужен отдельный поток, но для админа сойдет и так
            _, result = send_log_to_server('plain', log_text)
            if not result:
                 QMessageBox.information(self, "Успех", "Лог успешно отправлен на сервер.")
            else:
                 QMessageBox.critical(self, "Ошибка", f"Не удалось отправить лог: {result.get('message', 'Неизвестная ошибка')}")
        except Exception as e:
            QMessageBox.critical(self, "Критическая ошибка", f"Произошла ошибка при отправке: {e}")
        finally:
            self.send_log_button.setText(original_text)
            self.send_log_button.setEnabled(True)

    def switch_layout(self, index):
        """
        Переключает отображаемый layout в QStackedWidget.
        index: Индекс layout'а, который нужно показать (0 для основного, 1 для статуса).
        """
        self.stacked_widget.setCurrentIndex(index)

        # На некоторых слоях тулбар мешает
        if index in (LOAD_LAYOUT_INDEX, EXIT_LAYOUT_INDEX):
            self.toolbar.hide()
        
        else:
            self.toolbar.show()
        
        # Динамичное обновление заголовка
        if index == LOAD_LAYOUT_INDEX:
            self.setWindowTitle("PLACS Agent - Запуск Сабика...")
        
        elif index == STATUS_LAYOUT_INDEX:
            self.setWindowTitle("PLACS Agent - Состояние Вашего Сабика!")

        elif index == DIAGNOSTIC_LAYOUT_INDEX:
            self.setWindowTitle("PLACS Agent - Диагностика сети")

        elif index == ABOUT_LAYOUT_INDEX:
            self.setWindowTitle("PLACS Agent - Что такое PLACS и зачем он тебе")

        elif index == EXIT_LAYOUT_INDEX:
            self.setWindowTitle("PLACS Agent - Отключение Сабика...")
        
        elif index == SERVICE_LAYOUT_INDEX:
            self.setWindowTitle("PLACS Agent - Сервисный режим")

        elif index == VPN_LAYOUT_INDEX:
            self.setWindowTitle("PLACS Agent - VPN Менеджер")

        elif index == MENU_LAYOUT_INDEX:
            self.setWindowTitle("PLACS Agent - Основное меню")
        
        else:
            self.setWindowTitle("PLACS Agent - Ты... Как вообще?")

        log.info(f"Переключен на layout с индексом: {index}")

    def handle_toolbar_send_log(self):
        """
        Обрабатывает нажатие кнопки "Отправить лог сессии" в тулбаре.
        Отправляет лог ТЕКУЩЕЙ сессии на сервер и блокирует кнопку на 60 секунд.
        """
        button = self.toolbar_send_log_button
        original_text = button.text()

        button.setText("Отправка...")
        button.setEnabled(False)
        QApplication.processEvents()  # Заставляем UI немедленно обновиться

        try:
            with open(self.log_path, 'r', encoding='utf-8') as f:
                log_text = f.read()
                
        except Exception as e:
            QMessageBox.critical(self, "Ошибка чтения файла", f"Не удалось прочитать файл лога: {self.log_path}\n\n{e}")
            # Даже если ошибка, блокируем кнопку, чтобы не спамили
            button.setText("Ошибка чтения")
            button.setToolTip("Подождите 10 секунд перед повторной отправкой журналов")
            QTimer.singleShot(10000, lambda: self.enable_button_after_timeout(button, original_text))
            return

        try:
            # Эта функция может "заморозить" интерфейс на время отправки.
            # Для админского функционала это допустимо.
            _, result = send_log_to_server('plain', log_text)
            if not result:
                QMessageBox.information(self, "Успех", "Лог текущей сессии успешно отправлен на сервер.")
            else:
                QMessageBox.critical(self, "Ошибка отправки", f"Не удалось отправить лог: {result.get('message', 'Неизвестная ошибка')}")
        except Exception as e:
            QMessageBox.critical(self, "Критическая ошибка", f"Произошла критическая ошибка при отправке лога: {e}")
        finally:
            # В любом случае (успех или провал), блокируем кнопку на минуту
            button.setText("Заблокировано")
            button.setToolTip("Подождите 60 секунд перед повторной отправкой журналов")
            QTimer.singleShot(60000, lambda: self.enable_button_after_timeout(button, original_text))

    def enable_button_after_timeout(self, button, original_text):
        """
        Вспомогательный метод. Возвращает кнопку в рабочее состояние по истечении таймера.
        """
        button.setEnabled(True)
        button.setText(original_text)
        button.setToolTip("Отправить журнал работы на сервер")

    def switch_to_diagnostic_layout_and_start(self):
        """
        Переключает на экран диагностики и сигнализирует о начале проверки.
        Вызывается ErrorStateManager'ом.
        """
        log.info("Переключение на экран диагностики.")
        self.stacked_widget.setCurrentIndex(2) # Индекс 1 для диагностического виджета
        self.detail_output_text.clear() # Очищаем старые результаты
        self.diagnostic_check_items = [] # Очищаем список проверок
        self._update_diagnostic_checklist_display() # Обновляем, чтобы было пусто
        
        # Сразу начинаем диагностику, чтобы пользователь не ждал ручного старта
        self.start_diagnostic_signal.emit()
        
        # Деактивируем кнопки во время диагностики
        self.restart_diagnostic_button.setEnabled(False)
        self.back_button.setEnabled(False)
        self.toolbar.hide()
        if self.fix_button:
            self.fix_button.setEnabled(False)

    def switch_to_main_status_layout(self):
        """Переключает обратно на основной экран статуса."""
        log.info("Переключение на основной экран статуса.")
        self.stacked_widget.setCurrentIndex(MENU_LAYOUT_INDEX)

    def update_diagnostic_checklist(self, check_name: str, status_emoji: str):
        """
        Обновляет список проверок (эмодзи) в UI.
        Вызывается NetworkDiagnoser.
        """
        # Если проверка уже есть, обновляем ее, иначе добавляем
        found = False
        for i, (name, _) in enumerate(self.diagnostic_check_items):
            if name == check_name:
                self.diagnostic_check_items[i] = (check_name, status_emoji)
                found = True
                break
        if not found:
            self.diagnostic_check_items.append((check_name, status_emoji))
        
        self._update_diagnostic_checklist_display()

    def _update_diagnostic_checklist_display(self):
        """Внутренний метод для отрисовки списка проверок."""
        display_text = ""
        if not self.diagnostic_check_items:
            display_text = "<i>Ожидание начала проверки...</i>"
        else:
            temp_diagnostic_check_items = self.diagnostic_check_items.copy()
            temp_diagnostic_check_items.reverse()
            for name, emoji in temp_diagnostic_check_items:
                display_text += f"{emoji} {name}\n"
        self.checklist_label.setText(display_text)

    def append_diagnostic_details(self, detail_text: str):
        """
        Добавляет подробный текст в поле результатов.
        Вызывается NetworkDiagnoser.
        """
        self.detail_output_text.append(detail_text)

    def handle_diagnostic_finish(self, overall_success: bool, message: str):
        """
        Обрабатывает завершение диагностики.
        Вызывается NetworkDiagnoser.
        """
        settings = QSettings("PLACS", "Agent")

        log.info(f"Диагностика завершена: Успех={overall_success}, Сообщение='{message}'")
        self.append_diagnostic_details(f"\n{message}\n")

        if settings.value("diag/reportInPopup", True, type=bool):
            if not overall_success:
                dialog = HtmlMessageDialog(
                    "Результат проверки: Проблема с сетью!",
                    message,
                    "ui/media/img/colar_man/UNHAPPY_COLLAR_MAN.png",
                    self
                )
            
            else:
                dialog = HtmlMessageDialog(
                    "Результат проверки: Сеть исправна!",
                    message,
                    "ui/media/img/colar_man/SILLY_COLLAR_MAN.png",
                    self
                )
        
            dialog.exec_()

        if settings.value("diag/autoRecoveryNetwork", False, type=bool):
            self.try_fix_network_signal.emit()
        
        # Активируем кнопки после завершения диагностики
        self.restart_diagnostic_button.setEnabled(True)
        self.back_button.setEnabled(True)
        self.toolbar.show()
        if self.fix_button:
            self.fix_button.setEnabled(True)
    
    def run_network_diagnostic(self):
        """
        Слот, вызываемый ErrorStateManager, когда сетевая ошибка длится слишком долго.
        Здесь будет логика запуска диагностики.
        """
        log.warning("Получен сигнал: СЕТЕВАЯ ОШИБКА ДЛИТСЯ СЛИШКОМ ДОЛГО. ЗАПУСКАЮ ДИАГНОСТИКУ!")
        
        self.switch_to_diagnostic_layout_and_start()

    def update_status(self, message):
        """Метод для обновления статуса в окне."""
        message = message if len(message) < 70 else message[:70]
        self.status_label.setText(f'<h3 style="margin-bottom: 2px;">Статус агента:</h3> <span>{message}</span>')

        message = message if len(message) < 50 else message[:50]
        self.last_status.append(message)
        if len(self.last_status) > 5:
            self.last_status.pop(0)

        self.current_activity_label.setText(f"<h3>Что я делаю сейчас:</h3><p>{message}</p>") # Обновляем и в новом layout
        self.recent_activity_label.setText(self.generate_recent_activity_html())
    
    def update_last_error_display(self, message: str):
        message = message if len(message) < 30 else message[:30]
        self.last_error_label.setText(f"<h3>Последняя ошибка:</h3><p>{get_current_time()}{message}</p>")
    
    def generate_recent_activity_html(self):
        if not self.last_status:
            return "<h3>Что я делал недавно:</h3><p>Пока ничего особо интересного... 🥱</p>"

        # Заголовок для списка
        html_content = "<h3>Что я делал недавно:</h3>"

        last_status = self.last_status.copy()
        last_status.reverse()

        for item in last_status:
            # Заменяем переносы строк на <br>, чтобы они отображались в HTML
            formatted_item = item.replace('/n', '<br>')
            html_content += f"<p style='margin-bottom: 5px; margin-left: 1px;'>{get_current_time(True)} {formatted_item}</p>"

        return html_content
    
    def update_client_config(self):
        self.hide()
        dialog = ClientSettingsDialog()
        dialog_end = dialog.exec_()
        if dialog_end == ClientSettingsDialog.SettingsSaved:
            log.warning("Клиент сохранил конфигурацию!")
        
        elif dialog_end == ClientSettingsDialog.RestartRequired:
            log.warning("Инициирую перезапуск...")
            self.restart_app(True, "Обновление конфигурации.")

        else:
            log.info("Клиент не стал менять конфигурацию.")
        self.show()

    def update_ui_for_error_state(self, state: ErrorState):
        """
        Обновляет фон главного окна и другие элементы UI в зависимости от состояния ошибки.
        """
        # Общие части, которые всегда меняются
        collar_man_pic = None
        current_state_text = ""
        current_activity_style = ""
        recent_activity_style = ""
        last_error_style = ""
        current_state_style = ""

        if state == ErrorState.OK:
            current_state_text = "<h2>Что по настроению:</h2><p>У меня всё отлично! Работаю исправно.</p>"
            collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/happy", ".png"))

            current_state_style = "background-color: #4CAF50;" # Зеленый фон
            current_activity_style = "background-color: #7CB342;" # Салатовый фон
            recent_activity_style = "background-color: #7CB342;"
            last_error_style = "background-color: #4CAF50;"

        elif state == ErrorState.WARNING:
            current_state_text = "<h2>Что-то не так...</h2><p>У меня проблемы... н-но пока не переживай!</p>"
            collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/neutral", ".png"))

            current_state_style = "background-color: #a06b39;" # Оранжевый фон ошибки
            current_activity_style = "background-color: #b38f42;" # Понос фон
            recent_activity_style = "background-color: #b38f42;"
            last_error_style = "background-color: #a06b39;"

        elif state == ErrorState.CRITICAL:
            current_state_text = "<h2>О НЕТ!</h2><p>Произошла критическая ошибка! РАПОРТУЮ!</p>"
            collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/dizzy", ".png"))

            current_state_style = "background-color: #af2b2b;" # Типо бардовый фон ошибки
            current_activity_style = "background-color: #b45050;" # Бледно-розовый фон
            recent_activity_style = "background-color: #b45050;"
            last_error_style = "background-color: #af2b2b;"

        elif state == ErrorState.SERVER_CONNECT: 
            current_state_text = "<h2>Сервер не отвечает...</h2><p>Если это продлится ещё немного, то я запущу диагностику...</p>"
            collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/sick", ".png"))

            current_state_style = "background-color: #6A5ACD;" # Сланец синий
            current_activity_style = "background-color: #836FFF;" # Голубовато-фиолетовый
            recent_activity_style = "background-color: #836FFF;"
            last_error_style = "background-color: #6A5ACD;"
        
        elif state == ErrorState.NETWORK:
            current_state_text = "<h2>Связь потеряна!</h2><p>Сейчас всё проверю!</p>"
            collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/trouble", ".png"))

            current_state_style = "background-color: #8B0000;" # Тёмно-красный, почти бордовый
            current_activity_style = "background-color: #A52A2A;" # Коричневато-красный
            recent_activity_style = "background-color: #A52A2A;"
            last_error_style = "background-color: #8B0000;"
        
        elif state == ErrorState.START:
            current_state_text = "<h2>Не подглядывай...</h2><p>Мой интерфейс ещё загружается....</p>"
            collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/unhappy", ".png"))

        # Применяем текст и стили
        self.current_state_label.setText(current_state_text)
        self.current_state_label.setStyleSheet(self.current_state_label.styleSheet().split('background-color:')[0].strip() + "; " + current_state_style)
        self.current_activity_label.setStyleSheet(self.current_activity_label.styleSheet().split('background-color:')[0].strip() + "; " + current_activity_style)
        self.recent_activity_label.setStyleSheet(self.recent_activity_label.styleSheet().split('background-color:')[0].strip() + "; " + recent_activity_style)
        self.last_error_label.setStyleSheet(self.last_error_label.styleSheet().split('background-color:')[0].strip() + "; " + last_error_style)

        # Обновляем изображение
        if collar_man_pic: # Проверка, что картинка загрузилась
            scaled_pixmap = collar_man_pic.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.icon_label_status.setPixmap(scaled_pixmap)
        
        if self.stacked_widget.currentIndex() == EXIT_LAYOUT_INDEX:
            pass

        elif self.stacked_widget.currentIndex() == ABOUT_LAYOUT_INDEX and state not in (ErrorState.NETWORK, ErrorState.CRITICAL):
            self.switch_layout(MENU_LAYOUT_INDEX)
        
        elif self.stacked_widget.currentIndex() == DIAGNOSTIC_LAYOUT_INDEX and state in (ErrorState.OK, ErrorState.WARNING):
            self.switch_layout(MENU_LAYOUT_INDEX)
        
        elif self.stacked_widget.currentIndex() == LOAD_LAYOUT_INDEX:
            self.switch_layout(MENU_LAYOUT_INDEX)
            self.toolbar.show()

        log.info(f"UI фон изменен из-за изменения ситуации. Текущее состояние: {state}")
    
    def init_toolbar(self):
        self.toolbar = QToolBar("Основные действия")
        self.addToolBar(self.toolbar)
        self.toolbar.setMovable(False)

        self.toolbar_send_log_button = QPushButton("Отправить лог сессии")
        self.toolbar_send_log_button.clicked.connect(self.handle_toolbar_send_log)
        self.toolbar_send_log_button.setToolTip("Отправить журнал работы на сервер")

        self.toolbar_status_button = QPushButton("Статус")
        self.toolbar_status_button.setToolTip("Открыть экран со статусом агента")
        self.toolbar_status_button.clicked.connect(lambda: self.switch_layout(STATUS_LAYOUT_INDEX))
        self.toolbar.addWidget(self.toolbar_status_button)

        self.service_button = QPushButton("Сервисный режим")
        self.service_button.clicked.connect(self.toggle_service_mode)
        self.service_button.setVisible(False)
        self.toolbar.addWidget(self.service_button)

        self.toolbar_menu_button = QPushButton("Меню")
        self.toolbar_menu_button.setToolTip("Открыть основное меню действий")
        self.toolbar_menu_button.clicked.connect(lambda: self.switch_layout(MENU_LAYOUT_INDEX))
        self.toolbar.addWidget(self.toolbar_menu_button)

        self.service_shortcut = QShortcut(QKeySequence("Shift+A"), self)
        self.service_shortcut.activated.connect(self.toggle_service_mode)
        self.toolbar.hide()

    def init_menu_layout(self):
        menu_widget = QWidget()
        menu_widget.setObjectName("MainMenuWidget")

        root_layout = QVBoxLayout(menu_widget)
        root_layout.setContentsMargins(28, 24, 28, 24)
        root_layout.setSpacing(18)

        header = QLabel("<h1>Меню PLACS</h1><p>Выберите нужное действие.</p>")
        header.setObjectName("MainMenuHeader")
        header.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setWordWrap(True)
        root_layout.addWidget(header)

        button_grid = QGridLayout()
        button_grid.setHorizontalSpacing(18)
        button_grid.setVerticalSpacing(18)

        actions = [
            ("Статус", "ui/media/img/icons_png/PLACS_ICON_AHTUNG.png", lambda: self.switch_layout(STATUS_LAYOUT_INDEX), "MainMenuActionButtonPriority"),
            ("VPN сети", "ui/media/img/icons_png/PLACS_ICON_VPN.png", self.show_vpn_layout, "MainMenuActionButtonPriority"),
            ("Диагностика сети", "ui/media/img/icons_png/PLACS_ICON_NETWORK_CHEK.png", self.switch_to_diagnostic_layout_and_start, "MainMenuActionButton"),
            ("Отправить логи", "ui/media/img/icons_png/PLACS_ICON_SENDLOG.png", self.handle_toolbar_send_log, "MainMenuActionButton"),
            ("Настройки", "ui/media/img/icons_png/PLACS_ICON_SETTINGS.png", self.update_client_config, "MainMenuActionButton"),
            ("Перезапуск", "ui/media/img/icons_png/PLACS_ICON_RESTART.png", lambda: self.restart_app(True, "Требование пользователя."), "MainMenuActionButton"),
            ("Скрыть окно", "ui/media/img/icons_png/PLACS_ICON_HIDE.png", self.hide, "MainMenuActionButton"),
            ("О PLACS", "ui/media/img/icons_png/PLACS_ICON.png", lambda: self.switch_layout(ABOUT_LAYOUT_INDEX), "MainMenuActionButton"),
        ]

        positions = [
            (0, 0), (0, 1),
            (1, 0), (1, 1),
            (2, 0), (2, 1),
            (3, 0), (3, 1),
        ]

        for (title, icon_path, handler, object_name), (row, col) in zip(actions, positions):
            button = self.create_menu_action_button(title, icon_path, handler, object_name)
            button_grid.addWidget(button, row, col)

        button_grid.setColumnStretch(0, 1)
        button_grid.setColumnStretch(1, 1)
        root_layout.addLayout(button_grid)
        root_layout.addStretch(1)

        self.stacked_widget.addWidget(menu_widget)

    def create_menu_action_button(self, title, icon_path, handler, object_name):
        button = QPushButton(title)
        button.setObjectName(object_name)
        button.setCursor(Qt.PointingHandCursor)
        button.setIcon(QIcon(icon_path))
        button.setIconSize(QSize(64, 64))
        button.setMinimumHeight(88)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        button.clicked.connect(handler)
        return button

    def handle_display_message(self, message, duration=5):
        if self.current_display_window:
            self.current_display_window.close()
            self.current_display_window = None

        self.current_display_window = SetOnDisplayWindow(message, duration)
        log.info(f"Вывел на экран: {message}")
    
    def power_off(self, title, reason):
        # Запускаем спинер
        self.exit_spiner.start()

        self.switch_layout(EXIT_LAYOUT_INDEX)

        # Обновляем текст
        self.exit_label.setText(f"<h1>{title}</h1>")
        if reason:
            self.exit_reason.setText(f"<p style=\"margin: 3px;font-size: 16px; font-family: 'Monospace';\">({reason})</p>")

        # Обновляем картинку
        collar_man_pic = QPixmap(get_random_file_path("ui/media/mascot_img/sleep", ".png"))
        scaled_pixmap = collar_man_pic.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.icon_label_exit.setPixmap(scaled_pixmap)

        self.repaint() # Перерисовать окно немедленно
        QApplication.processEvents() # Обработать все ожидающие события UI (включая отрисовку)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint) # Окно поверх других
        self.show()
        
    def _confirm_and_connect(self, network_name: str):
        """На Windows подтверждение приходит через единый брокер привилегированных действий."""
        if is_windows():
            self.request_vpn_connect.emit(network_name)
            return

        reply = QMessageBox.question(
            self,
            "Подключение к VPN",
            f"Ты уверен, что хочешь войти в сегмент сети: «{network_name}»?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self.request_vpn_connect.emit(network_name)

    def process_pending_privileged_requests(self):
        if self._approval_dialog_open:
            return

        request = approval_broker.get_next_request()
        if not request:
            return

        self._approval_dialog_open = True
        dialog = QMessageBox(self)
        dialog.setWindowTitle(request.title)
        dialog.setTextFormat(Qt.RichText)
        dialog.setText(request.to_html())
        dialog.setIcon(QMessageBox.Question)
        allow_button = dialog.addButton("Разрешить", QMessageBox.YesRole)
        deny_button = dialog.addButton("Не сейчас", QMessageBox.NoRole)
        dialog.setDefaultButton(allow_button)
        dialog.exec_()

        request.approved = dialog.clickedButton() == allow_button
        request.event.set()
        self._approval_dialog_open = False

    def show_service_setup_window(self, retry_mode=False):
        dialog = ServiceSetupWindow(retry_mode=retry_mode, parent=self)
        return dialog.exec_(), dialog.accepted_setup

    def update_client_config(self):
        self.hide()
        dialog = ClientSettingsDialog()
        dialog_end = dialog.exec_()
        if dialog_end == ClientSettingsDialog.SettingsSaved:
            log.warning("Клиент сохранил конфигурацию!")
        elif dialog_end == ClientSettingsDialog.RestartRequired:
            log.warning("Инициирую перезапуск...")
            self.restart_app(True, "Обновление конфигурации.")
            return
        elif dialog_end == ClientSettingsDialog.ServiceDisabled:
            log.warning("Фоновая служба отключена. Завершаю агент.")
            QApplication.instance().quit()
            return
        else:
            log.info("Клиент не стал менять конфигурацию.")
        self.show()

    def closeEvent(self, event):
        self.hide()
        event.ignore()
