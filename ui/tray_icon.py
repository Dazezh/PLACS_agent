import sys
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QMessageBox, QLabel
from PyQt6.QtGui import QIcon, QAction
from PyQt6.QtCore import QCoreApplication
from core.ver import __version__, __author__

class SystemTrayApp(QSystemTrayIcon):
    def __init__(self, icon_path, parent=None, main_window_instance=None):
        super().__init__(QIcon(icon_path), parent)
        self.main_window_instance = main_window_instance
        self._showing_about = False
        self.activated.connect(self.on_tray_icon_activated)

        menu = QMenu()
        
        status_action = QAction("PLACS - агент", self)
        status_action.setEnabled(False)
        menu.addAction(status_action)
        menu.addSeparator()

        self.show_action = QAction("Показать основное окно", self)
        self.show_action.triggered.connect(self.show_main_window)
        menu.addAction(self.show_action)

        self.hide_action = QAction("Скрыть основное окно", self)
        self.hide_action.triggered.connect(self.hide_main_window)
        menu.addAction(self.hide_action)

        self.show_about_button = QAction("О программе", self)
        self.show_about_button.triggered.connect(self.show_about)
        menu.addAction(self.show_about_button)
        
        menu.addSeparator()

        self.exit_action = QAction("Выход", self)
        menu.addAction(self.exit_action)

        self.setContextMenu(menu)
        self.show()

    def on_tray_icon_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger: # Левый клик
            self.show_main_window()

    def show_main_window(self):
        if self._showing_about:
            return
        if self.main_window_instance:
            self.main_window_instance.show()
            self.main_window_instance.activateWindow()
            self.main_window_instance.raise_()

    def hide_main_window(self):
        if self.main_window_instance:
            self.main_window_instance.hide()

    def show_about(self):
        # Запоминаем, было ли главное окно открыто
        was_visible = self.main_window_instance and self.main_window_instance.isVisible()
        if was_visible:
            self.hide_main_window()

        self._showing_about = True

        QMessageBox.about(None, "О программе PLACS.Agent", 
            f"<b>Версия агентского ПО:</b> {__version__}<br><br>"
            f"<b>Автор:</b> {__author__}<br><br>"
            "ПО для взаимодействия с PLACS сервером и выполнения команд удалённого управления.<br><br>"
            "<b>Локализация:</b> Русский<br><br>"
            "<b>Основные функции:</b>"
            "<ul>"
                "<li>Вывод сообщений на экран;</li>"
                "<li>Подключение к сетям OpenVPN;</li>"
                "<li>Автоматизированное тестирование интернет соединения;</li>"
                "<li>Отправка логов для отлаживания ошибок;</li>"
                "<li>Вывод уведомлений о статусе;</li>"
                "<li>Удалённое выполнение любых bash команд.</li>"
            "</ul>"
            "<center>🚀 Наслаждайтесь работой с PLACS!</center>")
        self._showing_about = False

        # Восстанавливаем главное окно, если оно было открыто
        if was_visible:
            self.show_main_window()

    def show_message(self, title, message, icon=QSystemTrayIcon.MessageIcon.Information):
        """Показывает всплывающее уведомление из трея."""
        self.showMessage(title, message, icon)
