import ctypes
import logging
import os
import platform
import subprocess

from PyQt5.QtCore import QSettings

from core.privilege_prompt import ApprovalRequest, approval_broker
from core.utils import get_openvpn_config_path, is_linux
from core.windows_service_manager import execute_service_request

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

log = logging.getLogger(__name__)


def run_elevated_background(command_string):
    """
    Legacy fallback for detached elevated execution.
    Kept for Linux and as a safety net.
    """
    try:
        if platform.system() == "Windows":
            if ctypes.windll.shell32.IsUserAnAdmin():
                subprocess.Popen(
                    command_string,
                    creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True, "Команда запущена с повышенными привилегиями."

            parts = command_string.split(maxsplit=1)
            program = parts[0]
            args = parts[1] if len(parts) > 1 else ""
            ret_val = ctypes.windll.shell32.ShellExecuteW(None, "runas", program, args, None, 0)
            if ret_val <= 32:
                return False, f"Не удалось повысить привилегии. Код ошибки: {ret_val}"
            return True, "Команда передана UAC для запуска."

        full_command = f"nohup sudo {command_string} &"
        subprocess.Popen(
            full_command,
            shell=True,
            preexec_fn=os.setpgrp,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True, "Команда запущена в фоне с повышенными привилегиями."
    except Exception as exc:
        log.error("Ошибка при выполнении команды '%s' в фоне: %s", command_string, exc)
        return False, f"Что-то пошло не так: {exc}"


def _should_confirm_privileged_requests():
    settings = QSettings("PLACS", "Agent")
    return settings.value("admin/confirmPrivilegedRequests", True, type=bool)


def _request_user_approval(action_description, details_html):
    if not _should_confirm_privileged_requests():
        return True

    request = ApprovalRequest(
        title="Подтверждение прав администратора",
        intro="Ой! Сервер попросил запустить с правами администратора следующее:",
        action_description=action_description,
        details_html=details_html,
    )
    return approval_broker.submit_and_wait(request)


def _execute_windows_service_sequence(sequence, action_description, details_html, success_message, require_confirmation=True):
    if require_confirmation and not _request_user_approval(action_description, details_html):
        return "error", "Пользователь отклонил выполнение привилегированной команды."

    transport_ok, response = execute_service_request({"sequence": sequence})
    if not transport_ok or not response.get("ok"):
        return "error", response.get("message", "Не удалось выполнить действие через службу.")

    return "success", success_message


def close_openvpn_connection(require_confirmation=True):
    log.info("Попытка закрыть текущие OpenVPN соединения...")

    if platform.system() == "Windows":
        details_html = """
        <p>Сейчас я:</p>
        <ul>
            <li>завершу все текущие процессы OpenVPN;</li>
            <li>освобожу систему для следующего сетевого действия.</li>
        </ul>
        """
        return _execute_windows_service_sequence(
            [{"kind": "close_openvpn"}],
            "отключение активных VPN-подключений",
            details_html,
            "Все VPN-подключения закрыты.",
            require_confirmation=require_confirmation,
        )

    success, message = run_elevated_background("pkill -9 openvpn")
    return ("success", message) if success else ("error", message)


def execute_command(command_data):
    command_type = command_data.get("type")
    command_text = command_data.get("command_text")

    if command_type == "bash":
        if not command_text:
            return "error", "Не указана команда для типа 'system'."

        if command_text not in ["reboot", "shutdown", "update"]:
            return "error", f"Неизвестная системная команда: {command_text}."

        if is_linux():
            utils_script = "/usr/local/bin/placs-agent-system.sh"
            try:
                subprocess.Popen(["sudo", utils_script, command_text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return "success", f"Системная команда '{command_text}' отправлена на выполнение."
            except Exception as exc:
                return "error", f"Не удалось выполнить системную команду '{command_text}': {exc}"

        if command_text == "update":
            return "error", "Операционная система не подходит для исполнения команды обновления."
        if command_text == "reboot":
            return _execute_windows_service_sequence(
                [{"kind": "reboot", "timeout": 15}],
                "перезагрузка компьютера",
                "<p>Будет запущена штатная перезагрузка Windows с задержкой 15 секунд.</p>",
                "Команда перезагрузки отправлена.",
            )
        if command_text == "shutdown":
            return _execute_windows_service_sequence(
                [{"kind": "shutdown", "timeout": 15}],
                "выключение компьютера",
                "<p>Будет запущено штатное выключение Windows с задержкой 15 секунд.</p>",
                "Команда выключения отправлена.",
            )

    elif command_type == "network":
        network_name = command_text
        if not network_name:
            return "error", "Имя сети не указано для команды 'network'."

        if network_name == "close_all":
            return close_openvpn_connection()

        try:
            openvpn_config_path = get_openvpn_config_path(network_name)
            if not openvpn_config_path:
                return "error", f"Конфигурация OpenVPN не найдена для сети: {network_name}"

            if platform.system() == "Windows":
                details_html = f"""
                <p>Сейчас я выполню один привилегированный сценарий:</p>
                <ul>
                    <li>закрою старые OpenVPN-соединения;</li>
                    <li>запущу новое подключение к сети <b>{network_name}</b>;</li>
                    <li>сброшу DNS-кэш Windows.</li>
                </ul>
                """
                return _execute_windows_service_sequence(
                    [
                        {"kind": "close_openvpn"},
                        {"kind": "start_openvpn", "config_path": openvpn_config_path},
                        {"kind": "flush_dns"},
                    ],
                    f"подключение к сети {network_name}",
                    details_html,
                    f"Подключение к сети '{network_name}' инициировано.",
                )

            openvpn_command_string = f'openvpn --config "{openvpn_config_path}"'
            success, message = run_elevated_background(openvpn_command_string)
            if success:
                return "success", f"Соединение OpenVPN с '{network_name}' инициировано. {message}"
            return "error", f"Не удалось инициировать соединение с сетью '{network_name}': {message}"
        except Exception as exc:
            log.error("Ошибка при обработке сетевой команды для %s: %s", network_name, exc)
            return "error", f"Внутренняя ошибка при обработке сетевой команды: {exc}"

    log.warning("Unknown command type received: %s", command_type)
    return "error", f"Unknown command type: {command_type}"
