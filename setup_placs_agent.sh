#!/bin/bash
# Скрипт для автоматической подготовки системы Linux для PLACS Agent

echo "---------------------------------------------------------"
echo "Начинаю автоматическую настройку системы для PLACS Agent..."
echo "---------------------------------------------------------"

# Проверка прав администратора
if [ "$(id -u)" -ne 0 ]; then
    echo "Ошибка: Этот скрипт необходимо запускать с правами root. Используйте sudo."
    exit 1
fi

# --- Шаг 1: Установка зависимостей ---
echo "1. Обновляю список пакетов и устанавливаю OpenVPN и Python-библиотеки..."
if command -v apt-get &> /dev/null; then
    apt-get update -y
    apt-get install -y openvpn python3-pip
elif command -v dnf &> /dev/null; then
    dnf install -y openvpn python3-pip
elif command -v yum &> /dev/null; then
    yum install -y openvpn python3-pip
else
    echo "Внимание: Ваш дистрибутив Linux не поддерживается этим скриптом."
fi

# Установка Python-библиотек через pip3
echo "Устанавливаю Python-библиотеки..."
pip3 install pythonping --break-system-packages
echo "Зависимости установлены."
echo ""

# --- Шаг 2: Создание скрипта-обёртки для системных команд ---
echo "2. Создаю скрипт-обёртку для выполнения команд выключения и обновления..."
UTILS_SCRIPT="/usr/local/bin/placs-agent-system.sh"

cat <<EOF > "$UTILS_SCRIPT"
#!/bin/bash
# Этот скрипт-обёртка вызывается PLACS Agent для выполнения системных команд.

case "\$1" in
  reboot)
    echo "Перезагружаю систему через 15 секунд..."
    /sbin/shutdown -r -h -t 15
    ;;
  update)
    echo "Обновляю систему..."
    if command -v apt-get &> /dev/null; then
        /usr/bin/apt-get update -y
        /usr/bin/apt-get upgrade -y
    elif command -v dnf &> /dev/null; then
        /usr/bin/dnf update -y
    elif command -v yum &> /dev/null; then
        /usr/bin/yum update -y
    else
        echo "Ошибка: Не удалось определить менеджер пакетов для обновления."
        exit 1
    fi
    ;;
  shutdown)
    echo "Выключаю систему через 15 секунд..."
    /sbin/shutdown -h -t 15
    ;;
  *)
    echo "Команда '\$1' не поддерживается этим скриптом."
    exit 1
    ;;
esac
EOF
chmod +x "$UTILS_SCRIPT"
echo "Скрипт-обёртка для системных команд создан: $UTILS_SCRIPT"
echo ""

# --- Шаг 3: Создание скрипта-помощника для пинга ---
echo "3. Создаю скрипт-помощник для безопасного пинга с root-правами..."
PING_HELPER_SCRIPT="/usr/local/bin/placs-ping-helper.py"

cat <<EOF > "$PING_HELPER_SCRIPT"
#!/usr/bin/env python3
# /usr/local/bin/placs-ping-helper.py
# Скрипт для безопасного пинга с root-правами.

import sys
from pythonping import ping

if len(sys.argv) < 2:
    print("Ошибка: Необходимо указать адрес для пинга.")
    sys.exit(1)

target = sys.argv[1]

try:
    result = ping(target, count=4, timeout=2, verbose=True)
    print(f"success:{result.success}")
    print(f"stats_received:{result.stats_received}")
    print(f"stats_lost:{result.stats_lost}")
    print(f"stats_avg_rtt:{result.stats_avg_rtt}")
    sys.exit(0 if result.success else 1)
except Exception as e:
    print(f"error:{e}")
    sys.exit(1)
EOF
chmod +x "$PING_HELPER_SCRIPT"
echo "Скрипт-помощник для пинга создан: $PING_HELPER_SCRIPT"
echo ""

# --- Шаг 4: Проверка файлов агента и установка прав на исполнение ---
echo "4. Проверяю файлы агента и устанавливаю права на исполнение..."
AGENT_EXEC_PATH="$PWD/placs_agent"
UPDATE_EXEC_PATH="$PWD/update_placs"

if [ ! -f "$AGENT_EXEC_PATH" ] || [ ! -f "$UPDATE_EXEC_PATH" ]; then
    echo "Ошибка: Не найдены один или оба исполняемых файла: 'placs_agent' или 'update_placs'."
    echo "Автозапуск не будет настроен. Убедитесь, что файлы находятся рядом с этим скриптом."
    exit 1
fi

chmod +x "$AGENT_EXEC_PATH"
chmod +x "$UPDATE_EXEC_PATH"
echo "Права на исполнение для 'placs_agent' и 'update_placs' установлены."
echo ""

# --- Шаг 5: Настройка sudoers.d ---
echo "5. Настраиваю права доступа в /etc/sudoers.d/..."
SUDOERS_FILE="/etc/sudoers.d/placs-agent"
USER_NAME="$(logname)"

OPENVPN_PATH=$(which openvpn)
PKILL_PATH=$(which pkill)

cat <<EOF > "$SUDOERS_FILE"
$USER_NAME ALL=(ALL) NOPASSWD: $OPENVPN_PATH
$USER_NAME ALL=(ALL) NOPASSWD: $PKILL_PATH openvpn
$USER_NAME ALL=(ALL) NOPASSWD: $UTILS_SCRIPT
$USER_NAME ALL=(ALL) NOPASSWD: $PING_HELPER_SCRIPT
EOF
chmod 0440 "$SUDOERS_FILE"
echo "Правила для sudoers.d добавлены. Будьте осторожны."
echo ""

# --- Шаг 6: Настройка автозапуска через .desktop файл ---
echo "6. Настраиваю автозапуск PLACS Agent после входа пользователя..."
TARGET_USER=$(logname)
HOME_DIR=$(getent passwd "$TARGET_USER" | cut -d: -f6)
AUTOSTART_DIR="$HOME_DIR/.config/autostart"

mkdir -p "$AUTOSTART_DIR"
chown "$TARGET_USER":"$TARGET_USER" "$AUTOSTART_DIR"

DESKTOP_FILE="$AUTOSTART_DIR/placs_agent.desktop"

cat <<EOF > "$DESKTOP_FILE"
[Desktop Entry]
Type=Application
Exec=$AGENT_EXEC_PATH
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=PLACS Agent
Comment=Passive Linux Agent Control System
Terminal=false
EOF
chown "$TARGET_USER":"$TARGET_USER" "$DESKTOP_FILE"

echo "Файл автозапуска создан: $DESKTOP_FILE"
echo "PLACS Agent будет запускаться автоматически после входа пользователя."
echo ""

echo "---------------------------------------------------------"
echo "Настройка завершена! Система готова к PLACS Agent."
echo "---------------------------------------------------------"
