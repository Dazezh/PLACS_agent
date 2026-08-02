import json
import logging
import socketserver
import subprocess
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from core.windows_service_manager import (
    SERVICE_DESCRIPTION,
    SERVICE_DISPLAY_NAME,
    SERVICE_HOST,
    SERVICE_NAME,
    SERVICE_PORT,
)

from core.config_manager import get_or_create_service_token

CREATE_NO_WINDOW = 0x08000000
DETACHED_PROCESS = 0x00000008

log = logging.getLogger("WindowsAdminService")


def _run_process(command, detached=False):
    if detached:
        process = subprocess.Popen(
            command,
            creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        return True, f"Started PID {process.pid}"

    result = subprocess.run(command, capture_output=True, text=True, shell=False, check=False)
    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()
    output = "\n".join(part for part in [stdout, stderr] if part)
    if result.returncode == 0:
        return True, output or "Command completed."
    return False, output or f"Command failed with code {result.returncode}."


def _is_process_running(image_name):
    success, message = _run_process(["tasklist", "/FI", f"IMAGENAME eq {image_name}"])
    if not success:
        return False, message
    return image_name.lower() in message.lower(), message


def _execute_step(step):
    kind = step.get("kind")
    if kind == "close_openvpn":
        is_running, _ = _is_process_running("openvpn.exe")
        if not is_running:
            return True, "OpenVPN sessions were already absent."

        success, message = _run_process(["taskkill", "/F", "/IM", "openvpn.exe"])
        if success:
            return True, "OpenVPN sessions were closed."
        return False, message

    if kind == "start_openvpn":
        config_path = step.get("config_path")
        if not config_path:
            return False, "OpenVPN config path is missing."
        return _run_process(["openvpn", "--config", config_path], detached=True)

    if kind == "flush_dns":
        return _run_process(["ipconfig", "/flushdns"])

    if kind == "reboot":
        return _run_process(["shutdown", "/r", "/t", str(step.get("timeout", 15))], detached=True)

    if kind == "shutdown":
        return _run_process(["shutdown", "/s", "/t", str(step.get("timeout", 15))], detached=True)

    return False, f"Unsupported service command: {kind}"


def execute_sequence(sequence):
    details = []
    for step in sequence:
        success, message = _execute_step(step)
        details.append({"kind": step.get("kind"), "success": success, "message": message})
        if not success:
            return False, details
    return True, details


class _AdminRequestHandler(socketserver.StreamRequestHandler):
    def handle(self):
        raw_line = self.rfile.readline().decode("utf-8").strip()
        response = {"ok": False, "message": "Invalid request."}

        try:
            payload = json.loads(raw_line)
            if payload.get("token") != get_or_create_service_token():
                response = {"ok": False, "message": "Authentication failed."}
            else:
                ok, details = execute_sequence(payload.get("sequence", []))
                response = {
                    "ok": ok,
                    "message": "Sequence completed." if ok else "Sequence failed.",
                    "details": details,
                }
        except Exception as exc:
            response = {"ok": False, "message": str(exc)}

        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


class _ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class PLACSAgentWindowsService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.server = None
        self.server_thread = None

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg(f"{self._svc_name_} is starting.")
        self.server = _ThreadedTCPServer((SERVICE_HOST, SERVICE_PORT), _AdminRequestHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        win32event.WaitForSingleObject(self.stop_event, win32event.INFINITE)
        servicemanager.LogInfoMsg(f"{self._svc_name_} is stopping.")
