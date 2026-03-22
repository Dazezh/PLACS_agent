import sys
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt5.QtGui import QPixmap
from PyQt5.QtCore import Qt, QTimer

class SetOnDisplayWindow(QWidget):
    def __init__(self, message, duration):
        super().__init__()

        self.initUI(message)
        self.showFullScreen()
        self.disable_button_for_seconds(duration) # Блокируем кнопку при старте

    def initUI(self, message):
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # Главный вертикальный лейаут, который будет держать всё
        main_vertical_layout = QVBoxLayout(self)

        # Верхний растяжитель, чтобы контент центрировался по вертикали
        main_vertical_layout.addStretch(1)

        pic_h_layout = QHBoxLayout() # Для картинки
        pic_h_layout.addStretch() # Отступ слева

        ahtung_pic = QPixmap("ui/media/img/icons_png/PLACS_ICON_AHTUNG.png")
        scaled_pixmap = ahtung_pic.scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setMinimumHeight(260)
        icon_label.setMinimumWidth(260)
        icon_label.setPixmap(scaled_pixmap)
        pic_h_layout.addWidget(icon_label)

        pic_h_layout.addStretch() # Отступ справа
        main_vertical_layout.addLayout(pic_h_layout) # Лэйаут картинки суём в основной.

        # Контейнер для заголовка и текста
        content_layout = QVBoxLayout()
        content_layout.setAlignment(Qt.AlignCenter)

        name_label = QLabel("Сообщение от PLACS:")
        name_label.setAlignment(Qt.AlignCenter)
        name_label.setStyleSheet("font-size: 40px;")
        content_layout.addWidget(name_label)

        self.self_label = QLabel(message)
        self.self_label.setAlignment(Qt.AlignCenter)
        self.self_label.setStyleSheet("font-size: 20px;")
        self.self_label.setWordWrap(True) # Включаем перенос слов
        content_layout.addWidget(self.self_label)

        # Добавляем контейнер с контентом в основной вертикальный лейаут
        main_vertical_layout.addLayout(content_layout)

        # Нижний растяжитель, чтобы кнопка ушла вниз
        main_vertical_layout.addStretch(2)

        # Горизонтальный лейаут для кнопки, чтобы она была по центру снизу
        button_h_layout = QHBoxLayout()
        button_h_layout.addStretch() # Левый растяжитель
        
        self.hide_window_button = QPushButton("Закрыть (5)")
        self.hide_window_button.setToolTip("Вы сможете закрыть через 5 секунд.")
        self.hide_window_button.setStyleSheet("font-size: 25px;")
        self.hide_window_button.clicked.connect(self.close)

        button_h_layout.addWidget(self.hide_window_button)
        button_h_layout.addStretch() # Правый растяжитель

        # Добавляем лейаут с кнопкой в основной вертикальный лейаут
        main_vertical_layout.addLayout(button_h_layout)

    def disable_button_for_seconds(self, seconds):
        self.hide_window_button.setEnabled(False)
        self.countdown_time = seconds
        self.update_button_text()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000) # Обновляем каждую секунду

    def update_countdown(self):
        self.countdown_time -= 1
        self.update_button_text()
        if self.countdown_time <= 0:
            self.timer.stop()
            self.hide_window_button.setEnabled(True)
            self.hide_window_button.setText("Закрыть (0)")

    def update_button_text(self):
        self.hide_window_button.setText(f"Закрыть ({self.countdown_time})")
        self.hide_window_button.setToolTip(f"Вы сможете закрыть через {self.countdown_time} секунд.")