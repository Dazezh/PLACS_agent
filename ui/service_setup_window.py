from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)


class ServiceSetupWindow(QDialog):
    def __init__(self, retry_mode=False, parent=None):
        super().__init__(parent)
        self.retry_mode = retry_mode
        self.setWindowTitle("Настройка службы PLACS")
        self.setWindowState(self.windowState() | Qt.WindowState.WindowFullScreen)
        self.setModal(True)
        self._accepted_setup = False
        self._init_ui()
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.showFullScreen()

    def _build_copy(self):
        if self.retry_mode:
            intro = "Привет снова!"
            body = """
            <h2>Похоже, служба пропала или не смогла запуститься.</h2>
            <p>Я уже помню, что настройку завершали раньше, но во время проверки не нашёл рабочую службу. Без неё Windows снова начнёт дёргать подтверждения прав администратора или вообще сорвёт привилегированную команду.</p>
            <p>Сейчас я попробую восстановить служебную часть. Возможны:</p>
            <ul>
                <li>один запрос прав администратора от Windows;</li>
                <li>краткая пауза в работе агента;</li>
                <li>повторный запуск служебного процесса.</li>
            </ul>
            <p>Если отказаться, агент закроется, чтобы не работать в сломанном состоянии.</p>
            """
        else:
            intro = "Привет!"
            body = """
            <h2>Давай один раз завершим настройку привилегированных действий.</h2>
            <p>Я установлю Windows-службу, через которую PLACS сможет выполнять администраторские команды аккуратно и без повторяющихся всплывающих запросов UAC при каждой операции.</p>
            <p>Во время настройки может понадобиться:</p>
            <ul>
                <li>подтвердить права администратора;</li>
                <li>дождаться создания и запуска службы;</li>
                <li>дать агенту несколько секунд на проверку результата.</li>
            </ul>
            <p>После успешной настройки я буду проверять службу при каждом запуске и подскажу, если с ней что-то случится.</p>
            """
        return intro, body

    def _init_ui(self):
        intro, body = self._build_copy()

        self.setObjectName("ServiceSetupDialog")

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(32, 32, 32, 32)
        root_layout.setSpacing(0)
        root_layout.addStretch(1)

        center_row = QHBoxLayout()
        center_row.setContentsMargins(0, 0, 0, 0)
        center_row.setSpacing(0)
        center_row.addStretch(1)

        content_widget = QWidget()
        content_widget.setObjectName("ServiceSetupCard")
        content_widget.setMaximumWidth(1180)

        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(28, 28, 28, 28)
        content_layout.setSpacing(28)

        left_panel = QWidget()
        left_panel.setObjectName("ServiceSetupLeftPanel")
        left_panel.setMaximumWidth(640)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(18)

        title = QLabel(f"<h1>{intro}</h1>")
        title.setObjectName("ServiceSetupTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        title.setWordWrap(True)
        left_layout.addWidget(title)

        description_scroll = QScrollArea()
        description_scroll.setObjectName("ServiceSetupScroll")
        description_scroll.setWidgetResizable(True)
        description_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        description_widget = QWidget()
        description_layout = QVBoxLayout(description_widget)
        description_layout.setContentsMargins(0, 0, 0, 0)

        description_browser = QTextBrowser()
        description_browser.setObjectName("ServiceSetupDescription")
        description_browser.setOpenExternalLinks(False)
        description_browser.setHtml(body)
        description_layout.addWidget(description_browser)

        description_scroll.setWidget(description_widget)
        left_layout.addWidget(description_scroll, 1)

        buttons_row = QHBoxLayout()
        buttons_row.setContentsMargins(0, 0, 0, 0)
        buttons_row.setSpacing(14)

        self.close_button = QPushButton("Закрыть Сабика")
        self.close_button.setObjectName("ServiceSetupSecondaryButton")
        self.close_button.clicked.connect(self.reject)
        buttons_row.addWidget(self.close_button)

        self.accept_button = QPushButton("Продолжить настройку")
        self.accept_button.setObjectName("ServiceSetupPrimaryButton")
        self.accept_button.clicked.connect(self._accept_setup)
        buttons_row.addWidget(self.accept_button)

        left_layout.addLayout(buttons_row)

        right_panel = QWidget()
        right_panel.setObjectName("ServiceSetupRightPanel")
        right_panel.setMaximumWidth(420)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(12, 12, 12, 12)
        right_layout.setSpacing(18)
        right_layout.addStretch(1)

        image_label = QLabel()
        image_label.setObjectName("ServiceSetupImage")
        pixmap = QPixmap("ui/media/mascot_art/heart.png")
        if not pixmap.isNull():
            image_label.setPixmap(pixmap.scaled(340, 340, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(image_label)

        caption = QLabel("<h2>Давай завершим настройку Сабика.</h2>")
        caption.setObjectName("ServiceSetupCaption")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        caption.setWordWrap(True)
        right_layout.addWidget(caption)
        right_layout.addStretch(1)

        content_layout.addWidget(left_panel, 3)
        content_layout.addWidget(right_panel, 2)

        center_row.addWidget(content_widget)
        center_row.addStretch(1)

        root_layout.addLayout(center_row)
        root_layout.addStretch(1)

    def _accept_setup(self):
        self._accepted_setup = True
        self.accept()

    @property
    def accepted_setup(self):
        return self._accepted_setup
