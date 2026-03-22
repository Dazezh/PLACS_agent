import os
import shutil
import subprocess
import sys
import importlib.util

# --- Конфигурация сборки ---
APP_NAME = "placs_agent"
MAIN_SCRIPT = "main.py"

# Для Windows нужен .ico, для Linux PyInstaller поддерживает .png, .ico, .xpm
ICON_PATH_WIN = os.path.join("ui", "media", "img", "PLACS_ICON.ico")
ICON_PATH_LINUX = os.path.join("ui", "media", "img", "icons_png", "PLACS_ICON.png")

BUILD_OUTPUT_DIR = "release_builds" # Папка, куда будут складываться готовые бинарники

# --- Функция для получения версии ---
def get_app_version():
    """Читает версию приложения из core/ver.py"""
    version_file_path = os.path.join("core", "ver.py")
    if not os.path.exists(version_file_path):
        print(f"Ошибка: Файл версии не найден по пути: {version_file_path}")
        return "0.0.0" # Возвращаем дефолтную версию, если файл не найден

    spec = importlib.util.spec_from_file_location("ver_module", version_file_path)
    if spec is None:
        print(f"Ошибка: Не удалось загрузить спецификацию для {version_file_path}")
        return "0.0.0"

    ver_module = importlib.util.module_from_spec(spec)
    sys.modules["ver_module"] = ver_module
    try:
        spec.loader.exec_module(ver_module)
        return getattr(ver_module, "__version__", "0.0.0")
    except Exception as e:
        print(f"Ошибка при чтении версии из {version_file_path}: {e}")
        return "0.0.0"

# --- Функции для управления процессом сборки ---
def clean_pyinstaller_artifacts():
    """Удаляет временные папки и файлы, созданные PyInstaller."""
    print("🧹 Очистка временных файлов PyInstaller...")
    for path in ["build", "dist", f"{APP_NAME}.spec"]:
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
                print(f"  Удалена папка: {path}")
            else:
                os.remove(path)
                print(f"  Удален файл: {path}")
    print("✅ Очистка завершена.")

def run_pyinstaller(version):
    """Выполняет команду PyInstaller."""
    print(f"\n🚀 Запуск PyInstaller для сборки {APP_NAME} v{version}...")

    cmd = [
        "pyinstaller",
        "--noconfirm",  # Не запрашивать подтверждение
        "--clean",      # Очистить кэш PyInstaller и временные файлы
        "--windowed",   # Для GUI-приложения без консольного окна
        "--onefile",    # Собрать в один исполняемый файл (удобно для распространения)
        "--name", APP_NAME, # Имя выходного файла
    ]

    # Добавляем иконку в зависимости от ОС
    if sys.platform.startswith('win'):
        if os.path.exists(ICON_PATH_WIN):
            cmd.extend(["--icon", ICON_PATH_WIN])
        else:
            print(f"⚠️ ВНИМАНИЕ: Иконка для Windows не найдена по пути: {ICON_PATH_WIN}. Сборка будет без иконки.")
    elif sys.platform.startswith('linux'):
        if os.path.exists(ICON_PATH_LINUX):
            cmd.extend(["--icon", ICON_PATH_LINUX])
        else:
            print(f"⚠️ ВНИМАНИЕ: Иконка для Linux не найдена по пути: {ICON_PATH_LINUX}. Сборка будет без иконки.")

    cmd.append(MAIN_SCRIPT) # Главный скрипт

    try:
        # Запускаем PyInstaller
        process = subprocess.run(cmd, check=False, capture_output=True, text=True)
        print(process.stdout) # Выводим стандартный вывод PyInstaller
        print(process.stderr) # Выводим ошибки PyInstaller
        
        if process.returncode == 0:
            print("✅ PyInstaller завершил работу успешно.")
            return True
        else:
            print(f"❌ Ошибка PyInstaller. Код возврата: {process.returncode}")
            return False
    except FileNotFoundError:
        print("❌ Ошибка: PyInstaller не найден. Убедитесь, что он установлен (pip install pyinstaller).")
        return False
    except Exception as e:
        print(f"❌ Непредвиденная ошибка при запуске PyInstaller: {e}")
        return False

def finalize_build(version):
    """Копирует и переименовывает собранный бинарник в папку релизов."""
    print("\n📦 Финализация сборки: копирование и переименование...")
    
    # PyInstaller --onefile кладет бинарник прямо в dist/
    if sys.platform.startswith('win'):
        file_name = f"{APP_NAME}.exe"
    elif sys.platform.startswith('linux'):
        file_name = f"{APP_NAME}" # Для Linux обычно без расширения
    pyinstaller_output_path = os.path.join("dist", file_name)

    if not os.path.exists(pyinstaller_output_path):
        print(f"❌ Ошибка: Не найден собранный файл PyInstaller: {pyinstaller_output_path}")
        return False

    os.makedirs(BUILD_OUTPUT_DIR, exist_ok=True) # Создаем папку для готовых сборок

    # Определяем имя конечного файла в зависимости от ОС
    if sys.platform.startswith('win'):
        final_file_name = f"{APP_NAME}_v{version}.exe"
    elif sys.platform.startswith('linux'):
        final_file_name = f"{APP_NAME}_v{version}" # Для Linux обычно без расширения
    else:
        print(f"⚠️ Неизвестная ОС: {sys.platform}. Использую имя файла без расширения.")
        final_file_name = f"{APP_NAME}_v{version}"

    destination_path = os.path.join(BUILD_OUTPUT_DIR, final_file_name)

    try:
        shutil.copy2(pyinstaller_output_path, destination_path) # copy2 сохраняет метаданные
        print(f"✅ Готовый файл скопирован в: {destination_path}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при копировании файла: {e}")
        return False

# --- Основной процесс ---
if __name__ == "__main__":
    app_version = get_app_version()
    print(f"Начинаю сборку '{APP_NAME}' версии {app_version}")

    clean_pyinstaller_artifacts()

    if run_pyinstaller(app_version):
        if finalize_build(app_version):
            clean_pyinstaller_artifacts() # Повторная очистка временных файлов PyInstaller
            print(f"\n✨ УСПЕХ: {APP_NAME} v{app_version} успешно собрана и готова к распространению!")
            print(f"Ищите ее в папке: {BUILD_OUTPUT_DIR}")
        else:
            print("\n❌ ОШИБКА: Произошла ошибка на этапе финализации сборки.")
    else:
        print("\n❌ ОШИБКА: PyInstaller не смог собрать программу.")