import keyboard
import threading
import time
import logging
import os
import sys
from datetime import datetime

# Для скриншотов
import mss
from PIL import Image

from core.ver import __assets_packet_version__, __version__
from core.utils import is_windows

# Для звука
from playsound import playsound
# Чтобы playsound не блокировал поток, лучше запускать его в своем потоке
import concurrent.futures 

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QCoreApplication

log = logging.getLogger('HotkeyListener')

SCREEN_SOUND_PATH = 'ui/media/audio/screen.wav'
ERROR_SOUND_PATH = 'ui/media/audio/error.wav'

class GlobalHotkeyListener:
    def __init__(self):
        self._listener_thread = None
        self._running = False
        # Пул потоков для неблокирующего воспроизведения звука
        self._sound_player_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def _listen_for_hotkeys(self):
        """Метод, который запускается в отдельном потоке и слушает горячие клавиши."""
        log.info("Слушатель горячих клавиш запущен.")
        self._running = True
        
        keyboard.add_hotkey('caps lock+s', self._on_screenshot_hotkey)
        log.info("Зарегистрирована горячая клавиша: Сaps Lock + S (Скриншот)")

        keyboard.add_hotkey('caps lock+r', self._on_restart_hotkey)
        log.info("Зарегистрирована горячая клавиша: Сaps Lock + R (Перезапуск)")

        while self._running:
            time.sleep(0.1)

        log.info("Слушатель горячих клавиш остановлен.")
        keyboard.unhook_all()
    
    def _play_sound(self, sound_path):
        """Воспроизводит звук в отдельном неблокирующем потоке."""
        if os.path.exists(sound_path):
            try:
                if is_windows():
                    import winsound
                    # В windows лучше это, чтобы избежать проблемы MCI
                    winsound.PlaySound(sound_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                
                else:
                    # Запускаем playsound в отдельном потоке из пула, чтобы не блокировать текущий поток hotkey_listener
                    self._sound_player_executor.submit(playsound, sound_path)

                log.info(f"Воспроизвожу звук: {sound_path}")
            except Exception as e:
                log.error(f"Ошибка при воспроизведении звука {sound_path}: {e}")
        else:
            log.warning(f"Звуковой файл не найден: {sound_path}")
    
    def _on_restart_hotkey(self):
        """Обработчик нажатия Caps Lock + R (Перезапуск)."""
        import subprocess

        log.info("Горячая клавиша: Caps Lock + R нажата! Перезагружаю агента.")

        self._play_sound(ERROR_SOUND_PATH)

        time.sleep(2)
                        
        try:
            executable_name = "placs_agent.exe" if is_windows() else "./placs_agent"

            # Собираем команду
            command = [executable_name]

            subprocess.Popen(command, shell=True) 

            log.warning("Запустил новый экземпляр. Принудительно завершаю работу агента.")
            QCoreApplication.quit()  # Завершаем текущий скрипт
        except Exception as e:
            log.warning(f"Не удалось перезапустить: {e}")


    def _on_screenshot_hotkey(self):
        """Обработчик нажатия Caps Lock + S (Скриншот)."""
        log.info("Горячая клавиша: Caps Lock + S нажата! Создаю скриншот(ы).")
        try:
            screenshot_paths = self._take_screenshot()
            
            if screenshot_paths:
                log.info(f"Скриншоты сохранены: {screenshot_paths}")
                self._play_sound(SCREEN_SOUND_PATH) # Воспроизводим звук успеха!
            else:
                log.warning("Скриншоты не были созданы.")
                self._play_sound(ERROR_SOUND_PATH) # Звук ошибки, если ничего не создано

        except Exception as e:
            log.error(f"Ошибка при создании скриншота(ов): {e}")
            self._play_sound(ERROR_SOUND_PATH) # Звук ошибки!

    def _take_screenshot(self):
        """Делает скриншоты всех экранов и сохраняет их в папку пользователя."""
        saved_paths = []

        from PyQt5.QtCore import QSettings

        try:
            # Получаем путь из настроек
            settings = QSettings("PLACS", "Agent")
            # Значение по умолчанию должно совпадать с тем, что устанавливается в ClientSettingsDialog
            default_screenshot_path = os.path.join(os.path.expanduser('~'), 'Pictures')
            if not os.path.exists(default_screenshot_path):
                default_screenshot_path = os.path.expanduser('~')
                
            save_dir = settings.value("screenshots/savePath", default_screenshot_path, type=str)
            
            if not os.path.exists(save_dir):
                os.makedirs(save_dir, exist_ok=True) 
                log.info(f"Создана директория для скриншотов: {save_dir}")

            timestamp = datetime.now().strftime("%d-%m-%Y_%H-%M-%S")
            base_filename = f"placs_screenshot_{timestamp}"
            
            with mss.mss() as sct:
                num_monitors = len(sct.monitors) - 1 

                if num_monitors == 0:
                    log.warning("Не найдено ни одного монитора для захвата (кроме общего 'all screens').")
                    return []

                for i, monitor in enumerate(sct.monitors[1:], start=1):
                    log.info(f"Захват монитора {i}...")
                    sct_img = sct.grab(monitor) 

                    img = Image.frombytes("RGB", sct_img.size, sct_img.rgb)
                    
                    file_number_suffix = 0
                    current_file_path = os.path.join(save_dir, f"{base_filename}_monitor-{i}.png")
                    while os.path.exists(current_file_path):
                        file_number_suffix += 1
                        current_file_path = os.path.join(save_dir, f"{base_filename}_monitor-{i}_{file_number_suffix:02d}.png")

                    img.save(current_file_path)
                    saved_paths.append(current_file_path)
                    log.info(f"Монитор {i} сохранен в: {current_file_path}")
            
            return saved_paths
        except mss.exception.ScreenShotError as e:
            log.error(f"Ошибка захвата экрана (MSS): {e}")
            raise 
        except Exception as e:
            log.error(f"Неизвестная ошибка при создании или сохранении скриншота(ов): {e}")
            raise

    def start(self):
        """Запускает слушателя горячих клавиш в отдельном потоке."""
        if not self._listener_thread or not self._listener_thread.is_alive():
            self._listener_thread = threading.Thread(target=self._listen_for_hotkeys, daemon=True)
            self._listener_thread.start()
            log.info("Поток слушателя горячих клавиш запущен.")

    def stop(self):
        """Останавливает слушателя горячих клавиш."""
        self._running = False
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=1)
            if self._listener_thread.is_alive():
                log.warning("Поток слушателя горячих клавиш не завершился корректно. Он будет убит.")