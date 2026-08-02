import os

from PyQt6.QtWidgets import (QDialog, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, 
                             QStackedWidget, QDialogButtonBox, QCheckBox, QSpinBox, 
                             QComboBox, QLabel, QFormLayout, QMessageBox, QLineEdit,
                             QPushButton, QFileDialog, QTextEdit)
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QSettings, QCoreApplication

from core.config_manager import (get_agent_token, get_polling_interval, get_server_url, 
                                 load_config, save_config, get_debug_state,
                                 server_url_is_constant, agent_token_is_constant, 
                                 polling_interval_is_constant)

from core.logger import set_global_log_level
from core.windows_service_manager import (
    SERVICE_SETTINGS_KEY,
    SERVICE_STATUS_RUNNING,
    disable_service_elevated,
    query_service_status,
)
from core.windows_autostart import is_autostart_enabled_for_current_app, set_autostart_enabled

from core.utils import is_linux, is_windows

from urllib.parse import urlparse

# Это для проверки соединения
from workers.server_communicator import get_me
from core.error_types import ErrorType

import logging

class ConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Привязка агента PLACS")
        self.setFixedSize(400, 380) # Увеличиваем высоту окна

        self.server_url = ""
        self.auth_token = ""

        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        icon_path = 'ui/media/img/icons_png/PLACS_ICON_SERVER.png'
        
        try:
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(150, 150, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon_label = QLabel()
                icon_label.setPixmap(scaled_pixmap)
                icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(icon_label)
            else:
                print(f"Ошибка: Не удалось загрузить изображение '{icon_path}'. Проверьте путь и формат.")
        except Exception as e:
            print(f"Исключение при загрузке иконки в ConfigDialog: {e}")

        title_label = QLabel("<h3>«Привязка» к серверу PLACS</h3>")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        layout.addSpacing(20)

        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("Адрес сервера PLACS:"))
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("Например: https://example.com")
        server_layout.addWidget(self.server_input)
        layout.addLayout(server_layout)

        token_layout = QHBoxLayout()
        token_layout.addWidget(QLabel("Токен клиента (X-Auth-Token):"))
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Например: a1b2c3d4e5f6...")
        token_layout.addWidget(self.token_input)
        layout.addLayout(token_layout)

        polling_layout = QHBoxLayout()
        polling_layout.addWidget(QLabel("Интервал опроса (Сек.):"))
        self.polling_interval_spinbox = QSpinBox(self)
        self.polling_interval_spinbox.setRange(1, 300)
        self.polling_interval_spinbox.setSingleStep(1)
        self.polling_interval_spinbox.setValue(5)
        polling_layout.addWidget(self.polling_interval_spinbox)
        layout.addLayout(polling_layout)

        # Загружаю текущие настройки
        if load_config():
            self.server_input.setPlaceholderText(f"Сейчас: {get_server_url()}")
            self.token_input.setPlaceholderText(f"Сейчас: {get_agent_token()[:12]}...")
            self.polling_interval_spinbox.setValue(get_polling_interval())

            if server_url_is_constant():
                self.server_input.setDisabled(True)
                self.server_input.setToolTip("Адрес сервера задан администратором и не может быть изменён.")
            if agent_token_is_constant():
                self.token_input.setDisabled(True)
                self.token_input.setToolTip("Токен клиента задан администратором и не может быть изменён.")
            if polling_interval_is_constant():
                self.polling_interval_spinbox.setDisabled(True)
                self.polling_interval_spinbox.setToolTip("Интервал опроса задан администратором и не может быть изменён.")

        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Сохранить и запустить")
        self.save_button.clicked.connect(self.accept_config)
        button_layout.addWidget(self.save_button)

        self.cancel_button = QPushButton("Отмена")
        self.cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(self.cancel_button)
        layout.addLayout(button_layout)

        self.setLayout(layout)

    def accept_config(self):
        self.server_url = self.server_input.text().strip()
        self.auth_token = self.token_input.text().strip()
        self.polling_interval = self.polling_interval_spinbox.value()

        if load_config():
            self.server_url = self.server_url if self.server_url else get_server_url()
            self.auth_token = self.auth_token if self.auth_token else get_agent_token()

        if not self.server_url or not self.auth_token:
            QMessageBox.warning(self, "Ошибка", "Пожалуйста, заполните оба поля: адрес сервера и токен.")
            return

        # --- Добавлена проверка URL ---
        parsed_url = urlparse(self.server_url)
        is_valid_url = all([parsed_url.scheme, parsed_url.netloc])
        is_https = parsed_url.scheme.lower() == 'https'

        if not is_valid_url:
            QMessageBox.critical(self, "Ошибка", "Введён некорректный адрес сервера. Пожалуйста, убедитесь, что это полная ссылка (например, https://example.com).")
            return

        if not is_https and not self.server_url == get_server_url():
            reply = QMessageBox.question(
                self,
                "Предупреждение безопасности",
                "Вы ввели адрес без HTTPS. Это небезопасно и может привести к перехвату данных.\n\nВы уверены, что хотите продолжить?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )
            if reply == QMessageBox.No:
                return
        # --- Конец проверки URL ---

        QMessageBox.information(self, "Применяю...", "Настройки будут применены после сохранения.")
        self.accept()

class ClientSettingsDialog(QDialog):
    """
    Обновленное диалоговое окно настроек с обзорной панелью и 
    дополнительными настройками из предоставленного файла.
    """
    SettingsSaved = QDialog.DialogCode.Accepted      # Просто сохранено, значение = 1
    RestartRequired = QDialog.DialogCode.Accepted + 1 # Сохранено и нужен перезапуск, значение = 2
    ServiceDisabled = QDialog.DialogCode.Accepted + 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки Агента")
        self.setFixedSize(750, 480)

        self.settings = QSettings("PLACS", "Agent")
        self.restart_required_flag = False

        self.init_ui()
        self.load_settings()
        self.connect_signals()
        
        # Запускаем с первой страницы (Обзор)
        self.nav_list.setCurrentRow(0)

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        content_layout = QHBoxLayout()
        
        self.nav_list = QListWidget()
        self.nav_list.setObjectName("NavList")
        self.nav_list.setFixedWidth(180)
        
        self.stacked_widget = QStackedWidget()
        
        self.create_pages()
        
        content_layout.addWidget(self.nav_list)
        content_layout.addWidget(self.stacked_widget)
        
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Применить")
        button_box.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        
        main_layout.addLayout(content_layout)
        main_layout.addWidget(button_box)
        
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

    def create_pages(self):
        pages = {
            "Обзор": self.create_overview_page,
            "Основные": self.create_general_page,
            "Уведомления": self.create_notifications_page,
            "Логирование": self.create_logging_page,
            "Фоновая служба": self.create_background_service_page,
            "СОЕДИНЕНИЕ": self.create_server_settings_page,
        }

        for name, create_func in pages.items():
            page = create_func()
            self.stacked_widget.addWidget(page)
            self.nav_list.addItem(name)
            
    def create_overview_page(self):
        """Создает стартовую 'обзорную' страницу."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("<h1>Настройки клиента</h1>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Та самая картинка для тупого пользователя
        pixmap = QPixmap('ui/media/img/colar_man/SILLY_COLLAR_MAN.png')
        icon_label = QLabel()
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap.scaled(250, 250, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        description = QLabel(
            "Здесь ты можешь настроить поведение агента PLACS.\n"
            "Выбери интересующую тебя категорию в меню слева."
        )
        description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        description.setWordWrap(True)

        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(icon_label)
        layout.addWidget(description)
        layout.addStretch()
        
        return page
    
    def create_server_settings_page(self):
        # Главный контейнер для этой страницы - QStackedWidget
        page_stack = QStackedWidget()

        # --- СЛОЙ 1: Предупреждение ---
        page_warning = QWidget()
        warning_layout = QVBoxLayout(page_warning)
        warning_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 1. Заголовок "Ахтунг!"
        achtung_label = QLabel("<p style='color: #ff3333;font-size: 28px;'>Слушай сюда.<br>Это моё соединение с Сабиком.</p>")
        achtung_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 2. Картинка Менеджера
        manager_pixmap = QPixmap('ui/media/mascot_img/manager/MANAGER_POINTING.png') # Твой файл
        manager_label = QLabel()
        if not manager_pixmap.isNull():
            manager_label.setPixmap(manager_pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        manager_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # 3. Текст предупреждения
        warning_text_label = QLabel(
            "<p style='color: #ff6666;font-size: 14px;'>Одно неверное движение, и он превратится в бесполезный кусок кода."
            " И угадай, кто будет виноват? <b>Не я.</b></p>"
        )
        warning_text_label.setWordWrap(True)
        warning_text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # 4. Единственная кнопка согласия
        proceed_button = QPushButton("Я осознаю риск и хочу продолжить")
        proceed_button.setObjectName("ProceedButton") # Для QSS
        # При нажатии переключаем QStackedWidget на следующий (второй) слой
        proceed_button.clicked.connect(lambda: page_stack.setCurrentIndex(1))

        # Собираем первый слой
        warning_layout.addStretch(1)
        warning_layout.addWidget(achtung_label)
        warning_layout.addWidget(manager_label)
        warning_layout.addWidget(warning_text_label)
        warning_layout.addWidget(proceed_button)
        warning_layout.addStretch(1)

        # --- СЛОЙ 2: Сами настройки ---
        page_settings = QWidget()
        settings_layout = QFormLayout(page_settings)
        settings_layout.setContentsMargins(20, 10, 20, 10)
        
        # Поле ввода имени сервера
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("Например: https://example.com")

        # Поле ввода токена
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Например: a1b2c3d4e5f6...")

        # Поле ввода токена
        self.polling_interval_spinbox = QSpinBox(self)
        self.polling_interval_spinbox.setRange(1, 300)
        self.polling_interval_spinbox.setSingleStep(1)
        self.polling_interval_spinbox.setValue(5)
        
        self.check_server_button = QPushButton("Проверить соединение")
        self.check_server_button.clicked.connect(self.__test_config)
        self.check_server_button.setObjectName("CheckServerButton") # Для QSS
        self.server_check_status_label = QLabel("<i>Статус: Не проверено</i>")
        self.server_check_status_label.setObjectName("ServerCheckStatusLabel") # Для QSS
        
        check_layout = QHBoxLayout()
        check_layout.addWidget(self.check_server_button)
        check_layout.addWidget(self.server_check_status_label, 1)

        settings_layout.addRow(QLabel("<h3>Настройки подключения к серверу</h3>"))

        # Добавляем поле для адреса сервера
        settings_layout.addRow("Адрес сервера:", self.server_input)
        text = QLabel("<i>Настоятельно рекомендую использовать защищённое соединение (начинается с https)</p>")
        text.setWordWrap(True)
        settings_layout.addRow(text)

        # Добавляем поле для токена Агента
        settings_layout.addRow("Токен Сабика:", self.token_input)
        text = QLabel("<i>Это уникальный 64-х символьный «пароль» доступа, который нужен для общения с сервером</p>")
        text.setWordWrap(True)
        settings_layout.addRow(text)

        # Добавляем слайдер для интервала
        settings_layout.addRow("Интервал опроса:", self.polling_interval_spinbox)
        text = QLabel("<i>Раз в какое количество секунд Сабик будет стучаться к серверу</p>")
        text.setWordWrap(True)
        settings_layout.addRow(text)

        # Подгружаем текущие настройки
        if load_config():
            self.server_input.setPlaceholderText(f"Сейчас: {get_server_url()}")
            self.token_input.setPlaceholderText(f"Сейчас: {get_agent_token()[:12]}...")
            self.polling_interval_spinbox.setValue(get_polling_interval())

            if server_url_is_constant():
                self.server_input.setDisabled(True)
                self.server_input.setToolTip("Адрес сервера задан администратором и не может быть изменён.")
            if agent_token_is_constant():
                self.token_input.setDisabled(True)
                self.token_input.setToolTip("Токен клиента задан администратором и не может быть изменён.")
            if polling_interval_is_constant():
                self.polling_interval_spinbox.setDisabled(True)
                self.polling_interval_spinbox.setToolTip("Интервал опроса задан администратором и не может быть изменён.")

        settings_layout.addRow(check_layout)

        # Добавляем поле для вывода результатов диагностики, по умолчанию пустое
        self.config_test_output = QTextEdit()
        self.config_test_output.setReadOnly(True)
        self.config_test_output.setObjectName("DiagnosticDetailOutput")
        settings_layout.addRow(self.config_test_output)
        
        # --- Сборка QStackedWidget ---
        page_stack.addWidget(page_warning)  # Индекс 0
        page_stack.addWidget(page_settings) # Индекс 1

        return page_stack

    def create_notifications_page(self):
        page = QWidget()
        layout = QFormLayout(page)

        # --- Настройки ---
        self.notif_on_finish_check = QCheckBox("Когда команда успешно завершилась")
        self.notif_on_error_check = QCheckBox("Когда что-то пошло не так (ошибка)")

        # --- Заметка для "тупого" ---
        notes = QLabel(
            "<p>Иногда я работаю в фоновом режиме и хочу сообщить тебе о результатах. "
            "Эти галочки отвечают за всплывающие уведомления в углу экрана.</p>"
            "<p><b>Совет:</b> Если я тебя раздражаю, просто отключи их. "
            "Но тогда не жалуйся, что ты что-то пропустил.</p>"
        )
        notes.setWordWrap(True)

        # --- Компоновка ---
        layout.addRow(QLabel("<h3>Когда показывать всплывающие уведомления?</h3>"))
        layout.addRow(self.notif_on_finish_check)
        layout.addRow(self.notif_on_error_check)
        layout.addRow(notes)

        return page
        
    def create_logging_page(self):
        page = QWidget()
        layout = QFormLayout(page)

        # --- Настройки ---
        self.log_level_combo = QComboBox()
        self.log_level_combo.addItems(["Минимальный", "Оптимальный", "ВСЁ"])
        
        self.log_size_spin = QSpinBox()
        self.log_size_spin.setRange(10, 1024)
        self.log_size_spin.setSuffix(" МБ")
        
        self.log_size_restart_label = QLabel("Применится при перезапуске")
        self.log_size_restart_label.setObjectName("RestartLabel")
        self.log_size_restart_label.hide()
        
        # --- Заметка для "тупого" ---
        notes = QLabel(
            "<p>Я веду текстовый дневник (логи) своей работы. Это нужно, чтобы в случае проблем можно было понять, что пошло не так.</p>"
            "<ul>"
            "<li><b>Уровень записей:</b> Сколько всего я должен записывать. <b>Минимальный</b> — только ошибки, <b>Оптимальный</b> — основную информацию, <b>ВСЁ</b> — вообще всё подряд (для техподдержки).</li>"
            "<li><b>Размер дневника:</b> Как сильно я могу его растить, прежде чем начну удалять старые записи.</li>"
            "</ul>"
            "<p><b>Обычному пользователю здесь лучше ничего не трогать.</b></p>"
        )
        notes.setWordWrap(True)

        # --- Компоновка ---
        layout.addRow(QLabel("<h3>Настройки «дневника» работы</h3>"))
        layout.addRow("Уровень записей:", self.log_level_combo)
        layout.addRow("Макс. размер дневника:", self.log_size_spin)
        layout.addRow(self.log_size_restart_label)
        layout.addRow(notes)

        return page
    
    def _update_server_status(self, status: str, text: str):
        """
        Обновляет текст и цвет статусной метки в зависимости от статуса.
        """
        # 1. Устанавливаем текст
        self.server_check_status_label.setText(f"<i>Статус: {text}</i>")
        
        # 2. Устанавливаем свойство для QSS
        self.server_check_status_label.setProperty("status", status)
        
        # 3. Обновляем стиль
        self.server_check_status_label.style().unpolish(self.server_check_status_label)
        self.server_check_status_label.style().polish(self.server_check_status_label)
    
    def __test_config(self):
        self._update_server_status("checking", "Инициирую проверку...")

        config = self.__get_config_from_form()
        if not config:
            self._update_server_status("aborted", "Проверка прервана!")
            return
        
        self._update_server_status("checking", "Терпеливо ждите... Отправляю запрос...")
        
        subik, status = get_me(config)

        if not subik:
            if status.get("type") == ErrorType.NETWORK_TRANSIENT:
                self._update_server_status("error", "Сетевая ошибка! Проверьте логи!")
            
            elif "авторизации" in status.get("message"):
                self._update_server_status("error", "Нет доступа! Проверьте токен!")
            
            else:
                self._update_server_status("error", "Что-то пошло не так. Читай логи.")

            self.config_test_output.setText(status.get("message"))
        
        else:
            self._update_server_status("success", "Конфигурация коректна")
            self.config_test_output.setText(f"""
                <h4>Информация о агенте успешно получена!</h4>
                <p><b>Имя агента:</b> <pre>{subik.get('agent_name')}</pre></p>
                <p><b>Количество VPN конфигураций:</b> <pre>{len(subik.get('vpn_configs'))}</pre></p>
                """)
    
    def __get_config_from_form(self):
        server_url = self.server_input.text().strip()
        auth_token = self.token_input.text().strip()
        polling_interval = self.polling_interval_spinbox.value()

        if load_config():
            server_url = server_url if server_url else get_server_url()
            auth_token = auth_token if auth_token else get_agent_token()
        
        parsed_url = urlparse(server_url)
        is_valid_hypertext_url = parsed_url.scheme.lower() in ['http', 'https'] and parsed_url.netloc
        is_https = parsed_url.scheme.lower() == 'https'

        if not is_valid_hypertext_url:
            QMessageBox.critical(self, "Ошибка", "Введён некорректный адрес сервера. Пожалуйста, убедитесь, что это полная ссылка (например, https://example.com).")
            return

        if not is_https and not server_url == get_server_url():
            reply = QMessageBox.question(
                self,
                "Предупреждение безопасности",
                "Вы ввели адрес без HTTPS. Это небезопасно и может привести к перехвату данных.\n\nВы уверены, что хотите продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        return {
            "server_url": server_url,
            "auth_token": auth_token,
            "polling_interval": polling_interval,
            "DEBUG": get_debug_state()
        }

    def create_background_service_page(self):
        page_stack = QStackedWidget()

        page_warning = QWidget()
        warning_layout = QVBoxLayout(page_warning)
        warning_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel("<p style='color: #ff3333;font-size: 28px;'>Слушай сюда.<br>Это фоновая служба Сабика.</p>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        warning_text = QLabel(
            "<p style='color: #ff6666;font-size: 14px;'>Если выключить эту службу, агент потеряет безопасный путь для привилегированных команд. "
            "После отключения я сразу завершу работу приложения, чтобы не остаться в полусломанном состоянии.</p>"
        )
        warning_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        warning_text.setWordWrap(True)

        proceed_button = QPushButton("Я понимаю риск и хочу открыть настройки службы")
        proceed_button.clicked.connect(lambda: page_stack.setCurrentIndex(1))

        warning_layout.addStretch(1)
        warning_layout.addWidget(title)
        warning_layout.addWidget(warning_text)
        warning_layout.addWidget(proceed_button)
        warning_layout.addStretch(1)

        page_settings = QWidget()
        settings_layout = QFormLayout(page_settings)
        settings_layout.setContentsMargins(20, 10, 20, 10)

        self.background_service_status_label = QLabel()
        self.background_service_status_label.setWordWrap(True)
        self.background_service_note_label = QLabel(
            "<p>Здесь можно проверить, жива ли фоновая служба, и при необходимости отключить её.</p>"
        )
        self.background_service_note_label.setWordWrap(True)

        refresh_button = QPushButton("Обновить статус")
        refresh_button.clicked.connect(self.refresh_background_service_status)

        self.disable_background_service_button = QPushButton("Отключить службу и закрыть агент")
        self.disable_background_service_button.clicked.connect(self.disable_background_service)

        settings_layout.addRow(QLabel("<h3>Состояние фоновой службы</h3>"))
        settings_layout.addRow("Текущий статус:", self.background_service_status_label)
        settings_layout.addRow(refresh_button)
        settings_layout.addRow(self.disable_background_service_button)
        settings_layout.addRow(self.background_service_note_label)

        page_stack.addWidget(page_warning)
        page_stack.addWidget(page_settings)

        self.refresh_background_service_status()
        return page_stack

    def refresh_background_service_status(self):
        status_info = query_service_status()
        status = status_info.get("status")
        message = status_info.get("message", "")

        if status == SERVICE_STATUS_RUNNING:
            view_text = "Служба установлена и запущена."
            self.disable_background_service_button.setEnabled(True)
        else:
            view_text = "Служба не работает или отсутствует."
            self.disable_background_service_button.setEnabled(False)

        self.background_service_status_label.setText(f"{view_text}\n\n{message}")

    def disable_background_service(self):
        ok, message = disable_service_elevated()
        if not ok:
            QMessageBox.critical(self, "Ошибка", f"Не удалось отключить службу.\n\n{message}")
            return

        self.settings.setValue(SERVICE_SETTINGS_KEY, False)
        QMessageBox.information(
            self,
            "Служба отключена",
            "Фоновая служба отключена. Агент сейчас завершит работу.",
        )
        self.done(self.ServiceDisabled)

    def create_general_page(self):
        page = QWidget()
        layout = QFormLayout(page)
        layout.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)

        self.ui_show_on_start_check = QCheckBox("Показывать основное окно при каждом запуске")
        self.ui_on_top_check = QCheckBox("Держать окно поверх всех других")
        self.autostart_check = QCheckBox("Запускать агент автоматически при входе в Windows")
        self.confirm_admin_requests_check = QCheckBox("Спрашивать перед выполнением действий с правами администратора")

        notes = QLabel(
            "<p>Здесь собраны базовые настройки интерфейса и поведения привилегированных действий.</p>"
            "<p>Если галочка подтверждения включена, я покажу один общий запрос перед выполнением администраторского сценария.</p>"
        )
        notes.setWordWrap(True)

        layout.addRow(QLabel("<h3>Поведение окна</h3>"))
        layout.addRow(self.ui_show_on_start_check)
        layout.addRow(self.ui_on_top_check)
        if not is_windows():
            self.autostart_check.setEnabled(False)
            self.autostart_check.setToolTip("Автозапуск сейчас поддержан только в Windows.")
        layout.addRow(self.autostart_check)
        if is_linux():
            self.confirm_admin_requests_check.setEnabled(False)
        layout.addRow(self.confirm_admin_requests_check)
        layout.addRow(notes)
        return page

    def connect_signals(self):
        self.nav_list.currentRowChanged.connect(self.stacked_widget.setCurrentIndex)
        self.log_size_spin.valueChanged.connect(self.on_restart_setting_changed)

    def on_restart_setting_changed(self):
        sender = self.sender()
        self.restart_required_flag = True
        if sender == self.log_size_spin: self.log_size_restart_label.show()
    
    def __dehumanize_log_level(self, level: str):
        log_level = {
            "Минимальный": "WARNING",
            "Оптимальный": "INFO",
            "ВСЁ": "DEBUG"
        }
        return log_level.get(level, "INFO")
    
    def __humanize_log_level(self, level: str):
        log_level = {
            "WARNING": "Минимальный",
            "INFO": "Оптимальный",
            "DEBUG": "ВСЁ"
        }
        return log_level.get(level, "Оптимальный")

    def load_settings(self):
        s = self.settings
        self.ui_show_on_start_check.setChecked(s.value("ui/showMainWindowOnStart", True, type=bool))
        self.ui_on_top_check.setChecked(s.value("ui/mainWindowOnTop", False, type=bool))
        self.autostart_check.setChecked(
            is_autostart_enabled_for_current_app() if is_windows() else s.value("startup/enabled", False, type=bool)
        )
        self.notif_on_finish_check.setChecked(s.value("notifications/pushOnCommandFinish", True, type=bool))
        self.notif_on_error_check.setChecked(s.value("notifications/pushOnError", True, type=bool))
        self.log_level_combo.setCurrentText(self.__humanize_log_level(s.value("logging/level", "INFO", type=str)))
        self.log_size_spin.setValue(s.value("logging/maxLogFolderSizeMB", 100, type=int))
        self.confirm_admin_requests_check.setChecked(s.value("admin/confirmPrivilegedRequests", True, type=bool))

    def save_settings(self):
        s = self.settings
        s.setValue("ui/showMainWindowOnStart", self.ui_show_on_start_check.isChecked())
        s.setValue("ui/mainWindowOnTop", self.ui_on_top_check.isChecked())
        s.setValue("startup/enabled", self.autostart_check.isChecked())
        s.setValue("notifications/pushOnCommandFinish", self.notif_on_finish_check.isChecked())
        s.setValue("notifications/pushOnError", self.notif_on_error_check.isChecked())
        s.setValue("admin/confirmPrivilegedRequests", self.confirm_admin_requests_check.isChecked())

        # Логи
        s.setValue("logging/maxLogFolderSizeMB", self.log_size_spin.value())
        log_level = self.__dehumanize_log_level(self.log_level_combo.currentText())
        set_global_log_level(log_level)
        s.setValue("logging/level", log_level)

        if is_windows():
            try:
                set_autostart_enabled(self.autostart_check.isChecked())
                s.setValue("startup/enabled", is_autostart_enabled_for_current_app())
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Автозапуск",
                    f"Не удалось изменить автозапуск Windows.\n\n{exc}",
                )
                return False

        # Настройки подключения
        config = self.__get_config_from_form()
        if config:
            save_config(config)
        return True

    def accept(self):
        if self.save_settings() is False:
            return

        # Показываем сообщение, если нужно
        if self.restart_required_flag:
            QMessageBox.information(
                self,
                "Применяю настройки...",
                "Ты изменил одну из тех важных настроек, которые вступают в силу только 'на свежую голову'.\n\n"
                "Поэтому я сейчас сам себя перезапущу, чтобы всё заработало как надо. "
                "Просто нажми 'ОК', и я мигом вернусь."
            )
            # Закрываем диалог и возвращаем код "НУЖЕН ПЕРЕЗАПУСК"
            self.done(self.RestartRequired)
        else:
            # Закрываем диалог и возвращаем код "ПРОСТО СОХРАНЕНО"
            self.done(self.SettingsSaved)
