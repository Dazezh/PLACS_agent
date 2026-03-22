import os
import shutil
import subprocess
import sys

# --- Конфигурация сборки (ИЗМЕНЕНО для update.py) ---
APP_NAME = "update_placs"
MAIN_SCRIPT = "update.py"

# Пути к иконкам для скрипта обновления
ICON_PATH_WIN = os.path.join("ui", "update", "manager_icon.ico")
ICON_PATH_LINUX = os.path.join("ui", "update", "img", "manager_icon.png")

# Папка с ресурсами, которую нужно включить в сборку
ASSETS_DIR = os.path.join("ui", "update")

BUILD_OUTPUT_DIR = "release_builds"

# ---

def clean_pyinstaller_artifacts():
    # ... (твой код clean_pyinstaller_artifacts() здесь, он идеален) ...
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

def run_pyinstaller():
    print(f"\n🚀 Запуск PyInstaller для сборки {APP_NAME}...")

    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name", APP_NAME,
    ]

    # --- ГЛАВНЫЕ ИЗМЕНЕНИЯ ЗДЕСЬ ---
    # Добавляем все ресурсы из папки ui/update
    if os.path.exists(ASSETS_DIR):
        # PyInstaller использует разный разделитель для путей в Windows (;) и Linux (:)
        path_separator = ';' if sys.platform.startswith('win') else ':'
        # Мы говорим: "возьми папку ASSETS_DIR и положи ее внутрь бинарника по пути 'ui/update'"
        # Таким образом, относительные пути в скрипте останутся прежними.
        cmd.append(f"--add-data={ASSETS_DIR}{path_separator}{ASSETS_DIR}")
        print(f"  Добавляю ресурсы из: {ASSETS_DIR}")
    else:
        print(f"⚠️ ВНИМАНИЕ: Папка с ресурсами не найдена: {ASSETS_DIR}. Сборка будет без картинок!")
    # --- КОНЕЦ ИЗМЕНЕНИЙ ---

    # Добавляем иконку в зависимости от ОС
    if sys.platform.startswith('win'):
        if os.path.exists(ICON_PATH_WIN):
            cmd.extend(["--icon", ICON_PATH_WIN])
        else:
            print(f"⚠️ ВНИМАНИЕ: Иконка для Windows не найдена: {ICON_PATH_WIN}.")
    elif sys.platform.startswith('linux'):
        if os.path.exists(ICON_PATH_LINUX):
            cmd.extend(["--icon", ICON_PATH_LINUX])
        else:
            print(f"⚠️ ВНИМАНИЕ: Иконка для Linux не найдена: {ICON_PATH_LINUX}.")

    cmd.append(MAIN_SCRIPT)

    # ... (твой код запуска subprocess здесь, он тоже хорош) ...
    try:
        process = subprocess.run(cmd, check=False, capture_output=True, text=True)
        print(process.stdout)
        print(process.stderr)
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


def finalize_build():
    # ... (и этот код тоже отличный, без изменений) ...
    print("\n📦 Финализация сборки: копирование и переименование...")
    if sys.platform.startswith('win'):
        file_name = f"{APP_NAME}.exe"
    elif sys.platform.startswith('linux'):
        file_name = f"{APP_NAME}"
    pyinstaller_output_path = os.path.join("dist", file_name)
    if not os.path.exists(pyinstaller_output_path):
        print(f"❌ Ошибка: Не найден собранный файл PyInstaller: {pyinstaller_output_path}")
        return False
    os.makedirs(BUILD_OUTPUT_DIR, exist_ok=True)
    if sys.platform.startswith('win'):
        final_file_name = f"{APP_NAME}.exe"
    elif sys.platform.startswith('linux'):
        final_file_name = f"{APP_NAME}"
    else:
        print(f"⚠️ Неизвестная ОС: {sys.platform}. Использую имя файла без расширения.")
        final_file_name = f"{APP_NAME}"
    destination_path = os.path.join(BUILD_OUTPUT_DIR, final_file_name)
    try:
        shutil.copy2(pyinstaller_output_path, destination_path)
        print(f"✅ Готовый файл скопирован в: {destination_path}")
        return True
    except Exception as e:
        print(f"❌ Ошибка при копировании файла: {e}")
        return False

# --- Основной процесс (без изменений) ---
if __name__ == "__main__":
    print(f"Начинаю сборку '{APP_NAME}'")
    clean_pyinstaller_artifacts()
    if run_pyinstaller():
        if finalize_build():
            clean_pyinstaller_artifacts()
            print(f"\n✨ УСПЕХ: {APP_NAME} успешно собрана и готова к распространению!")
            print(f"Ищите ее в папке: {BUILD_OUTPUT_DIR}")
        else:
            print("\n❌ ОШИБКА: Произошла ошибка на этапе финализации сборки.")
    else:
        print("\n❌ ОШИБКА: PyInstaller не смог собрать программу.")