"""
PLACS Agent Updater
===================

Автономный скрипт для проверки и применения обновлений для PLACS Agent.
- Проверяет обновления для основного приложения и для дополнительных данных (ассетов).
- Скачивает, проверяет целостность (SHA256) и устанавливает обновления.
- Показывает современное диалоговое окно с логами и результатами обновления.
- Запускает основное приложение после завершения работы.

Поддерживает несколько режимов запуска:
- Без аргументов: Диалог выбора (переустановить/запустить).
- Со стандартными аргументами: Наглядная проверка обновлений.
- --hide-process: Скрытый режим, окно показывается только при наличии обновлений.
- --reinstall: Принудительная переустановка.
"""

import sys
import os
import argparse
import requests
import getpass
import hashlib
import shutil
import zipfile
import subprocess
import platform
from urllib.parse import urljoin, urlparse

from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton, QApplication, QProgressBar, QWidget, QLineEdit, QSpinBox, QMessageBox, QFrame
from PyQt5.QtGui import QIcon, QPixmap, QTextOption
from PyQt5.QtCore import Qt, QCoreApplication

from core.config_manager import get_server_url, set_config, load_config, get_polling_interval, get_agent_token

# --- Глобальные константы ---
APP_NAME = "PLACS"
ORGANIZATION_NAME = "Agent"
UI_MEDIA_DIR = 'ui/media'
MAIN_APP_EXECUTABLE_LINUX = 'placs_agent'
MAIN_APP_EXECUTABLE_WINDOWS = 'placs_agent.exe'
MAIN_APP_EXECUTABLE_MACOS = 'placs_agent'

# --- Пути к изображениям для статусов ---
def resource_path(relative_path):
    """Возвращает правильный путь к ресурсу, работает и в исходниках, и в .exe"""
    try:
        # PyInstaller создает временную папку и сохраняет путь в _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        # Если мы не в .exe, то base_path - это просто текущая папка
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

# Восстанавливаем пути из замороженного состояния
IMG_CHECKING = resource_path('ui/update/img/status_checking.png')
IMG_SUCCESS = resource_path('ui/update/img/status_success.png')
IMG_ERROR = resource_path('ui/update/img/status_error.png' )
APP_ICON = resource_path('ui/update/manager_icon.ico')

# Чтобы получить имя пользователя
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
        return "Пользователь"

# --- Функции, унаследованные из оригинального скрипта (без изменений) ---

def get_os_string():
    system = platform.system().lower()
    if system == 'windows': return 'windows'
    elif system == 'linux': return 'linux'
    elif system == 'darwin': return 'macos'
    else: return 'unknown'

def get_main_app_executable_name():
    os_type = get_os_string()
    if os_type == 'windows': return MAIN_APP_EXECUTABLE_WINDOWS
    elif os_type == 'linux': return MAIN_APP_EXECUTABLE_LINUX
    elif os_type == 'macos': return MAIN_APP_EXECUTABLE_MACOS
    return MAIN_APP_EXECUTABLE_LINUX

def verify_hash(file_path, expected_hash, updater_window=None):
    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            for byte_block in iter(lambda: f.read(4096), b""):
                sha256_hash.update(byte_block)
        calculated_hash = sha256_hash.hexdigest()
        is_valid = calculated_hash == expected_hash
        message = f"Проверка целостности файла {os.path.basename(file_path)}: {'Успешно' if is_valid else 'ПРОВАЛЕНО'}"
        if updater_window: updater_window.log_message(message)
        else: print(message)
        return is_valid
    except FileNotFoundError:
        message = f"Ошибка: Файл для проверки хеша не найден: {file_path}"
        if updater_window: updater_window.log_message(message)
        else: print(message)
        return False

def download_file(url, destination, updater_window=None):
    message = f"Загрузка: {url}"
    if updater_window: updater_window.log_message(message)
    else: print(message)
    try:
        with requests.get(url, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(destination, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
        if updater_window: updater_window.log_message("Загрузка успешно завершена.")
        else: print("Загрузка успешно завершена.")
        return True
    except requests.exceptions.RequestException as e:
        message = f"Ошибка загрузки: {e}"
        if updater_window: updater_window.log_message(message)
        else: print(message)
        return False

# --- Новый GUI ---

class UpdaterWindow(QDialog):
    """Основное окно процесса обновления."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Обновление PLACS Agent")
        self.setFixedSize(800, 450)
        if os.path.exists(APP_ICON):
            self.setWindowIcon(QIcon(APP_ICON))

        self.init_ui()
        self.apply_styles()
        self.set_status("Инициализация...", IMG_CHECKING)

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Левая панель ---
        left_pane_widget = QWidget()
        left_pane_widget.setObjectName("LeftPane")
        left_pane_layout = QVBoxLayout(left_pane_widget)
        left_pane_layout.setContentsMargins(20, 20, 20, 20)

        self.status_label = QLabel("Инициализация...")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)

        self.image_label = QLabel()
        self.image_label.setObjectName("ImageLabel")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(360, 202) # Соотношение 16:9

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("ProgressBar")
        self.progress_bar.setTextVisible(False)

        left_pane_layout.addWidget(self.status_label)
        left_pane_layout.addWidget(self.image_label, 1) # Растягиваем
        left_pane_layout.addWidget(self.progress_bar)

        # --- Правая панель ---
        right_pane_widget = QWidget()
        right_pane_widget.setObjectName("RightPane")
        right_pane_layout = QVBoxLayout(right_pane_widget)
        right_pane_layout.setContentsMargins(20, 20, 20, 20)

        log_header = QLabel("Ход выполнения:")
        log_header.setObjectName("LogHeader")

        self.log_area = QTextEdit()
        self.log_area.setObjectName("LogArea")
        self.log_area.setReadOnly(True)
        self.log_area.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

        self.close_button = QPushButton("Закрыть")
        self.close_button.setObjectName("CloseButton")
        self.close_button.clicked.connect(self.accept)
        self.close_button.setEnabled(False)

        right_pane_layout.addWidget(log_header)
        right_pane_layout.addWidget(self.log_area)
        right_pane_layout.addWidget(self.close_button)

        # --- Сборка ---
        main_layout.addWidget(left_pane_widget, 1)
        main_layout.addWidget(right_pane_widget, 1)

    def apply_styles(self):
        # Стили из QSS файла, адаптированные для этого окна
        self.setStyleSheet("""
            QDialog {
                background-color: #2e2e2e;
            }
            QWidget#LeftPane {
                background-color: #262626;
                border-right: 1px solid #444;
            }
            QLabel#StatusLabel {
                color: #e0e0e0;
                font-family: "Inter", sans-serif;
                font-size: 22px;
                font-weight: bold;
                padding-bottom: 15px;
            }
            QLabel#LogHeader {
                color: #cccccc;
                font-size: 16px;
                margin-bottom: 5px;
                font-family: "Inter", sans-serif;
            }
            QTextEdit#LogArea {
                background-color: #1e1e1e;
                color: #d0d0d0;
                border: 1px solid #444444;
                border-radius: 5px;
                font-family: "Consolas", "Monospace";
                font-size: 12px;
            }
            QProgressBar {
                border: 1px solid #555;
                border-radius: 8px;
                text-align: center;
                height: 16px;
                background-color: #3a3a3a;
            }
            QProgressBar::chunk {
                background-color: #af604c;
                border-radius: 8px;
            }
            QPushButton#CloseButton {
                background-color: #af604c;
                color: white;
                border: 1px solid #9c5544;
                border-radius: 8px;
                padding: 8px 15px;
                min-height: 25px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton#CloseButton:hover {
                background-color: #9c5544;
            }
            QPushButton#CloseButton:pressed {
                background-color: #7a4436;
            }
            QPushButton#CloseButton:disabled {
                background-color: #383838;
                color: #999999;
                border: 1px solid #444;
            }
        """)

    def set_status(self, text, image_path):
        self.status_label.setText(text)
        self.set_status_image(image_path)

    def set_status_image(self, image_path):
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            # Масштабируем до ширины контейнера, сохраняя пропорции
            scaled_pixmap = pixmap.scaled(self.image_label.width(), self.image_label.height(),
                                          Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.image_label.setPixmap(scaled_pixmap)
        else:
            self.image_label.setText(f"Изображение\n{os.path.basename(image_path)}\nне найдено")
            self.log_message(f"Предупреждение: не найдено изображение статуса: {image_path}")


    def log_message(self, message, is_html=False):
        if is_html:
            self.log_area.append(message)
        else:
            self.log_area.append(f"-> {message}")
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())
        QCoreApplication.processEvents()

    def update_progress(self, value):
        self.progress_bar.setValue(value)
        QCoreApplication.processEvents()

    def finalize(self, success=True):
        status_text = "Обновление завершено" if success else "Произошла ошибка"
        image = IMG_SUCCESS if success else IMG_ERROR
        self.set_status(status_text, image)
        self.update_progress(100)
        self.close_button.setEnabled(True)
        self.close_button.setText("Завершить")

class ConfigDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Привязка агента PLACS")
        self.setFixedSize(400, 380) # Увеличиваем высоту окна

        self.server_url = ""
        self.auth_token = ""

        self.init_ui()
        self.apply_styles()

    def init_ui(self):
        layout = QVBoxLayout()

        icon_path = resource_path("ui/update/img/placs_server.png")
        
        try:
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                icon_label = QLabel()
                icon_label.setPixmap(scaled_pixmap)
                icon_label.setAlignment(Qt.AlignCenter)
                layout.addWidget(icon_label)
            else:
                print(f"Ошибка: Не удалось загрузить изображение '{icon_path}'. Проверьте путь и формат.")
        except Exception as e:
            print(f"Исключение при загрузке иконки в ConfigDialog: {e}")

        title_label = QLabel("<h3>«Привязка» к серверу PLACS</h3>")
        title_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(title_label)

        layout.addSpacing(20)

        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("Адрес сервера PLACS:"))
        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("Например: http://domain")
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

        if load_config():
            self.server_input.setPlaceholderText(f"Сейчас: {get_server_url()}")
            self.token_input.setPlaceholderText(f"Сейчас: {get_agent_token()}")
            self.polling_interval_spinbox.setValue(get_polling_interval())

        button_layout = QHBoxLayout()
        self.save_button = QPushButton("Обновить конфигурацию")
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

        if not is_https:
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

        set_config(
            self.server_url,
            self.auth_token,
            self.polling_interval
        )

        QMessageBox.information(self, "Сохранено.", "Настройки Сабика были изменены.")
        self.accept()
    
    def apply_styles(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #2e2e2e;
            }
            QLabel {
                color: #e0e0e0;
                font-size: 16px;
                font-family: "Inter", sans-serif;
            }
            QPushButton {
                background-color: #af604c;
                color: white;
                border: 1px solid #9c5544;
                border-radius: 8px;
                padding: 10px;
                font-size: 14px;
                font-family: "Inter", sans-serif;
            }
            QPushButton:hover {
                background-color: #9c5544;
            }
            QPushButton:pressed {
                background-color: #7a4436;
            }
            /* Стили для полей ввода */
            QLineEdit {
                background-color: #3a3a3a;
                border: 1px solid #555555;
                border-radius: 5px;
                padding: 5px;
                color: #e0e0e0;
            }

            QSpinBox  {
                background-color: #3a3a3a;
                border: 1px solid #555555;
                border-radius: 5px;
                padding: 5px;
                color: #e0e0e0;
            }
        """)

class ChoiceDialog(QDialog):
    """Диалог выбора действия, стилизованный под UpdaterWindow."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PLACS Manager")
        self.setFixedSize(800, 460) # Стандартный размер, как у UpdaterWindow
        if os.path.exists(APP_ICON):
            self.setWindowIcon(QIcon(APP_ICON))
        
        self.choice = None

        self.init_ui()
        self.apply_styles()
        self.update_info()

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # --- Левая панель (визуальная часть) ---
        left_pane_widget = QWidget()
        left_pane_widget.setObjectName("LeftPane")
        left_pane_layout = QVBoxLayout(left_pane_widget)
        left_pane_layout.setContentsMargins(20, 20, 20, 20)

        greeting_label = QLabel(f"Здравствуйте, {get_username()}!")
        greeting_label.setObjectName("GreetingLabel")
        greeting_label.setAlignment(Qt.AlignCenter)
        greeting_label.setWordWrap(True)

        image_label = QLabel()
        image_label.setObjectName("ImageLabel")
        image_label.setAlignment(Qt.AlignCenter)
        image_label.setMinimumSize(360, 202)
        
        image_path = resource_path("ui/update/img/manager.png")
        if os.path.exists(image_path):
            pixmap = QPixmap(image_path)
            scaled_pixmap = pixmap.scaled(350, 350, 
                                          Qt.KeepAspectRatio, Qt.SmoothTransformation)
            image_label.setPixmap(scaled_pixmap)
        else:
            image_label.setText(f"Изображение\n{os.path.basename(image_path)}\nне найдено")

        left_pane_layout.addWidget(greeting_label)
        left_pane_layout.addWidget(image_label, 1)

        # --- Правая панель (действия и информация) ---
        right_pane_widget = QWidget()
        right_pane_widget.setObjectName("RightPane")
        right_pane_layout = QVBoxLayout(right_pane_widget)
        right_pane_layout.setContentsMargins(25, 20, 25, 20)
        right_pane_layout.setSpacing(15)

        title_label = QLabel("Что Вы желаете сделать с Сабиком?")
        title_label.setObjectName("TitleLabel")

        # Кнопки действий
        reinstall_button = QPushButton("Переустановить Сабика")
        reinstall_button.clicked.connect(self.on_reinstall)
        
        launch_button = QPushButton("Запустить Сабика")
        launch_button.clicked.connect(self.on_launch)

        update_config_button = QPushButton("Изменить конфигурацию")
        update_config_button.clicked.connect(self.update_config)

        # Информационная панель
        self.curent_config_label = QLabel("Загрузка данных...")
        self.curent_config_label.setObjectName("ConfigInfo")
        self.curent_config_label.setWordWrap(True)
        
        # Кнопки утилит
        about_button = QPushButton("О программе")
        about_button.clicked.connect(self.show_about_dialog)

        exit_button = QPushButton("Выход")
        exit_button.setObjectName("ExitButton") # Для отдельного стиля
        exit_button.clicked.connect(self.reject) # reject() закрывает диалог

        right_pane_layout.addWidget(title_label)
        right_pane_layout.addWidget(self.curent_config_label)
        right_pane_layout.addStretch(1)
        right_pane_layout.addWidget(reinstall_button)
        right_pane_layout.addWidget(launch_button)
        right_pane_layout.addWidget(update_config_button)
        right_pane_layout.addStretch(2)

        # Горизонтальный разделитель
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        right_pane_layout.addWidget(line)

        # Нижний ряд кнопок
        bottom_buttons_layout = QHBoxLayout()
        bottom_buttons_layout.addWidget(about_button)
        bottom_buttons_layout.addStretch(1)
        bottom_buttons_layout.addWidget(exit_button)
        right_pane_layout.addLayout(bottom_buttons_layout)


        # --- Сборка ---
        main_layout.addWidget(left_pane_widget, 1)
        main_layout.addWidget(right_pane_widget, 1)

    def show_about_dialog(self):
        """Показывает информационное окно о назначении кнопок."""
        about_text = """
        <div style="color:#e0e0e0">
            <b><font size='+1'>Назначение кнопок</font></b>
            <hr>
            <p><b>Переустановить агента:</b><br>
            Полностью удаляет текущую версию агента и загружает с сервера самую последнюю. Конфигурация (адрес сервера, токен) при этом сохраняется.</p>
            <p><b>Запустить агента:</b><br>
            Запускает основное приложение агента без проверки обновлений. Используйте, если уверены, что агент не запущен.</p>
            <p><b>Изменить конфигурацию:</b><br>
            Открывает окно для изменения адреса сервера PLACS, токена доступа и интервала опроса.</p>
            <p><b>Выход:</b><br>
            Закрывает менеджера.</p>
        </div>
        """
        QMessageBox.about(self, "О программе", about_text)

    def update_info(self):
        server_url = get_server_url()
        agent_token = get_agent_token()
        polling_interval = get_polling_interval()

        url_status, url_color = '❌', '#FF6347'
        if server_url:
            parsed_url = urlparse(server_url)
            if all([parsed_url.scheme, parsed_url.netloc]):
                if parsed_url.scheme.lower() == 'https':
                    url_status, url_color = '🔒✅', '#50C878'
                else:
                    url_status, url_color = '⚠️', '#FFA500'
        
        token_status, token_color = '❌', '#FF6347'
        if agent_token:
            token_status, token_color = '✅', '#50C878'

        interval_status, interval_color = '❌', '#FF6347'
        if polling_interval:
            interval_status, interval_color = '✅', '#50C878'

        self.curent_config_label.setText(f"""
        <p style='font-size: 14px; font-weight: bold; margin-bottom: 5px; color: #e0e0e0;'>Текущая конфигурация:</p>
        <p style='font-size: 12px; margin: 2px 0; color: #cccccc;'>
            Сервер: {server_url or 'Не настроен'} <span style='font-size: 16px; color: {url_color};'>{url_status}</span> 
        </p>
        <p style='font-size: 12px; margin: 2px 0; color: #cccccc;'>
            Токен доступа <span style='font-size: 16px; color: {token_color};'>{token_status}</span>
        </p>
        <p style='font-size: 12px; margin: 2px 0; color: #cccccc;'>
            Интервал: {polling_interval or 'Не задан'} сек. <span style='font-size: 16px; color: {interval_color};'>{interval_status}</span>
        </p>
        """)

    def update_config(self):
        config_dialog = ConfigDialog(self) 
        if config_dialog.exec_() == QDialog.Accepted:
            self.update_info()

    def on_reinstall(self):
        self.choice = 'reinstall'
        self.accept()

    def on_launch(self):
        self.choice = 'launch'
        self.accept()

    def apply_styles(self):
        self.setStyleSheet("""
            QDialog {
                background-color: #2e2e2e;
                font-family: "Inter", sans-serif;
            }
            QWidget#LeftPane {
                background-color: #262626;
                border-right: 1px solid #444;
            }
            QWidget#RightPane {
                background-color: #2e2e2e;
            }
            QLabel#GreetingLabel {
                font-size: 24px;
                font-weight: bold;
                color: #e0e0e0;
                padding-bottom: 15px;
            }
            QLabel#TitleLabel {
                font-size: 18px;
                color: #d0d0d0;
            }
            QLabel#ConfigInfo {
                background-color: #262626;
                border: 1px solid #444444;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton {
                background-color: #af604c;
                color: white;
                border: 1px solid #9c5544;
                border-radius: 8px;
                padding: 12px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #9c5544;
            }
            QPushButton:pressed {
                background-color: #7a4436;
            }
            QPushButton#ExitButton {
                background-color: #5e3930;
                border: 1px solid #4a2d26;
                font-weight: normal;
            }
            QPushButton#ExitButton:hover {
                background-color: #70453a;
            }
            QPushButton#ExitButton:pressed {
                background-color: #4a2d26;
            }
        """)

# --- Модифицированные функции обновления (API без изменений) ---

def check_and_apply_software_update(server_url, current_version, updater):
    updater.set_status("Проверка ПО...", IMG_CHECKING)
    updater.log_message("\n--- Проверка обновлений ПО ---")
    updater.update_progress(10)
    api_url = urljoin(server_url, '/api/check_software_update')
    os_type = get_os_string()

    version_to_send = current_version if current_version else "0.0.0"
    payload = {"version": version_to_send, "operating_system": os_type}

    try:
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        updater.log_message(f"<font color='#FF6347'>Ошибка при запросе к API обновления ПО: {e}</font>", is_html=True)
        return None, "Не удалось связаться с сервером для проверки обновлений ПО."

    if not data.get('update_available'):
        updater.log_message("Установлена актуальная версия ПО.")
        updater.update_progress(50)
        return None, "Установлена актуальная версия ПО."

    updater.log_message(f"Найдено обновление ПО до версии: {data['current_version']}")
    updater.set_status("Загрузка ПО...", IMG_CHECKING)

    download_url = urljoin(server_url, data['download_url'])
    file_hash = data['file_hash']

    # Исполняемый файл этого скрипта может быть в разных местах (например, в temp)
    # Ищем основной исполняемый файл в текущей директории, откуда запущен скрипт
    current_dir = os.getcwd()
    main_app_name = get_main_app_executable_name()
    main_app_path = os.path.join(current_dir, main_app_name)

    new_app_path = main_app_path + ".new"
    old_app_path = main_app_path + ".old"

    if not download_file(download_url, new_app_path, updater):
        return None, "Ошибка при скачивании файла обновления ПО."
    updater.update_progress(25)

    if not verify_hash(new_app_path, file_hash, updater):
        os.remove(new_app_path)
        return None, "Ошибка проверки целостности файла обновления ПО."

    updater.set_status("Установка ПО...", IMG_CHECKING)
    updater.log_message("Замена исполняемого файла...")
    try:
        if os.path.exists(old_app_path): os.remove(old_app_path)
        if os.path.exists(main_app_path): os.rename(main_app_path, old_app_path)
        os.rename(new_app_path, main_app_path)
        if os.name != 'nt': os.chmod(main_app_path, 0o755)
        updater.log_message("Исполняемый файл успешно заменен.")
    except OSError as e:
        updater.log_message(f"<font color='#FF6347'>Критическая ошибка при замене файла: {e}</font>", is_html=True)
        if not os.path.exists(main_app_path) and os.path.exists(old_app_path):
            os.rename(old_app_path, main_app_path) # Попытка отката
        return None, f"Ошибка при замене исполняемого файла: {e}"

    updater.update_progress(50)
    release_notes = f"<h3>ПО обновлено до версии {data['current_version']}</h3>" \
                    f"<b>Описание:</b> {data.get('description', 'Отсутствует')}<br/><br/>" \
                    f"<b>Заметки к выпуску:</b><br/>" \
                    f"{data.get('release_notes', 'Отсутствуют')}" 
    return release_notes, "ПО успешно обновлено."


def check_and_apply_data_update(server_url, current_version, updater):
    updater.set_status("Проверка данных...", IMG_CHECKING)
    updater.log_message("\n--- Проверка обновлений данных ---")
    updater.update_progress(60)
    api_url = urljoin(server_url, '/api/check_data_update')
    version_to_send = current_version if current_version else "0.0.0"
    payload = {"version": version_to_send}

    try:
        response = requests.post(api_url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
    except (requests.exceptions.RequestException, ValueError) as e:
        updater.log_message(f"<font color='#FF6347'>Ошибка при запросе к API обновления данных: {e}</font>", is_html=True)
        return None, "Не удалось связаться с сервером для проверки обновлений данных."

    if not data.get('update_available'):
        updater.log_message("Установлена актуальная версия данных.")
        updater.update_progress(100)
        return None, "Установлена актуальная версия данных."

    updater.log_message(f"Найдено обновление данных до версии: {data['current_version']}")
    updater.set_status("Загрузка данных...", IMG_CHECKING)

    download_url = urljoin(server_url, data['download_url'])
    file_hash = data['file_hash']
    temp_zip_path = "temp_data_update.zip"

    if not download_file(download_url, temp_zip_path, updater):
        return None, "Ошибка при скачивании архива с данными."
    updater.update_progress(75)

    if not verify_hash(temp_zip_path, file_hash, updater):
        os.remove(temp_zip_path)
        return None, "Ошибка проверки целостности архива с данными."

    updater.set_status("Распаковка данных...", IMG_CHECKING)
    updater.log_message(f"Обновление директории '{UI_MEDIA_DIR}'...")
    try:
        # Убедимся, что директория существует перед удалением
        if os.path.isdir(UI_MEDIA_DIR):
            shutil.rmtree(UI_MEDIA_DIR)
        with zipfile.ZipFile(temp_zip_path, 'r') as zip_ref:
            zip_ref.extractall('.')
        updater.log_message("Архив успешно распакован.")
    except (OSError, zipfile.BadZipFile) as e:
        updater.log_message(f"<font color='#FF6347'>Ошибка при распаковке архива: {e}</font>", is_html=True)
        return None, f"Ошибка при распаковке архива: {e}"
    finally:
        if os.path.exists(temp_zip_path):
            os.remove(temp_zip_path)

    updater.update_progress(100)
    release_notes = f"<h3>Данные (UI) обновлены до версии {data['current_version']}</h3>" \
                    f"<b>Описание:</b> {data.get('description', 'Отсутствует')}<br/><br/>" \
                    f"<b>Заметки к выпуску:</b><br/>" \
                    f"{data.get('release_notes', 'Отсутствуют')}" 
    return release_notes, "Данные (UI) успешно обновлены."


def launch_main_app():
    print("\n--- Запуск основного приложения ---")
    try:
        current_dir = os.getcwd()
        main_app_path = os.path.join(current_dir, get_main_app_executable_name())

        if not os.path.exists(main_app_path):
            print(f"Критическая ошибка: не найден исполняемый файл: {main_app_path}")
            # Можно показать диалоговое окно об ошибке
            return

        subprocess.Popen([main_app_path, 'skip_update'])
    except Exception as e:
        print(f"Не удалось запустить основное приложение: {e}")


def main():
    parser = argparse.ArgumentParser(description='PLACS Agent Updater', add_help=False)
    parser.add_argument('--agent-version', default=None)
    parser.add_argument('--assets-version', default=None)
    parser.add_argument('--reinstall', action='store_true')
    parser.add_argument('--hide-process', action='store_true')
    parser.add_argument('-h', '--help', action='help', default=argparse.SUPPRESS,
                        help='Показать это справочное сообщение и выйти.')

    args = parser.parse_args()

    app = QApplication(sys.argv)

    # Режим: Запуск без аргументов
    if len(sys.argv) == 1:
        dialog = ChoiceDialog()
        if dialog.exec_() == QDialog.Accepted:
            if dialog.choice == 'reinstall':
                args.reinstall = True
            elif dialog.choice == 'launch':
                launch_main_app()
                sys.exit(0)
            else: # Окно просто закрыли
                sys.exit(0)
        else:
             sys.exit(0)

    # Установка версий для переустановки
    if args.reinstall:
        args.agent_version = "0.0.0"
        args.assets_version = "0.0.0"

    # Если после всех проверок версий нет, значит, аргументы были некорректными
    if args.agent_version is None or args.assets_version is None:
        print("Ошибка: для проверки обновлений необходимо указать --agent-version и --assets-version, либо --reinstall.")
        sys.exit(1)

    updater_window = UpdaterWindow()

    server_url = get_server_url()
    if not server_url:
        updater_window.log_message("<b><font color='#FF6347'>Критическая ошибка: URL сервера не настроен.</font></b>", is_html=True)
        updater_window.finalize(success=False)
        updater_window.exec_()
        launch_main_app() # Попытка запустить основное приложение для настройки
        sys.exit(1)

    if not args.hide_process:
        updater_window.show()

    all_notes = []
    has_errors = False

    # Проверка и обновление ПО
    sw_notes, sw_message = check_and_apply_software_update(server_url, args.agent_version, updater_window)
    if sw_notes: all_notes.append(sw_notes)
    if "Ошибка" in sw_message: has_errors = True
    
    # Проверка и обновление данных, только если не было критических ошибок с ПО
    if not has_errors:
        data_notes, data_message = check_and_apply_data_update(server_url, args.assets_version, updater_window)
        if data_notes: all_notes.append(data_notes)
        if "Ошибка" in data_message: has_errors = True

    # Если были обновления или ошибки, показываем итоговое окно
    if all_notes or has_errors:
        if all_notes:
            summary_notes = "<hr>".join(all_notes)
            updater_window.log_message("<br>--- ИТОГИ ---<br>", is_html=True)
            updater_window.log_message(summary_notes, is_html=True)
            updater_window.log_message(
                "<hr><h3>После закрытия данного окна будет запущен экземпляр агента.</h3>", 
                is_html=True
                )
        
        updater_window.finalize(success=not has_errors)
        if not updater_window.isVisible():
            updater_window.show()
        app.exec_()
    elif args.hide_process:
        # Если обновлений не было в скрытом режиме, просто выходим
        launch_main_app()
        sys.exit(0)
    
    # Если окно было показано, но обновлений не было, оно закроется само
    if not all_notes and not args.hide_process:
        updater_window.log_message("\nОбновлений не найдено.")
        updater_window.finalize(success=True)
        app.exec_()

    launch_main_app()
    sys.exit(0)

if __name__ == '__main__':
    main()