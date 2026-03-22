import json
import os
import subprocess
import sys
from typing import List


SHORTCUT_NAME = "PLACS Agent.lnk"


def is_windows() -> bool:
    return os.name == "nt"


def get_current_app_path() -> str:
    if getattr(sys, "frozen", False):
        return os.path.abspath(sys.executable)
    return os.path.abspath(sys.argv[0])


def get_startup_folder() -> str:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise RuntimeError("APPDATA is not set.")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def _ps_quote(value: str) -> str:
    return value.replace("'", "''")


def _run_powershell(script: str) -> str:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(message or f"PowerShell failed with code {result.returncode}.")

    return (result.stdout or "").strip()


def _normalize_path(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


def list_startup_shortcuts() -> List[dict]:
    startup_dir = _ps_quote(get_startup_folder())
    script = f"""
$startup = '{startup_dir}'
$shell = New-Object -ComObject WScript.Shell
$items = Get-ChildItem -Path $startup -Filter *.lnk -ErrorAction SilentlyContinue | ForEach-Object {{
    $shortcut = $shell.CreateShortcut($_.FullName)
    [PSCustomObject]@{{
        shortcut_path = $_.FullName
        target_path = $shortcut.TargetPath
    }}
}}
$items | ConvertTo-Json -Compress
"""
    output = _run_powershell(script)
    if not output:
        return []

    data = json.loads(output)
    if isinstance(data, dict):
        return [data]
    return data


def is_autostart_enabled_for_current_app() -> bool:
    if not is_windows():
        return False

    current_app = _normalize_path(get_current_app_path())
    for item in list_startup_shortcuts():
        target_path = item.get("target_path")
        if target_path and _normalize_path(target_path) == current_app:
            return True
    return False


def set_autostart_enabled(enabled: bool):
    if not is_windows():
        return

    current_app = get_current_app_path()
    startup_dir = get_startup_folder()

    if enabled:
        shortcut_path = os.path.join(startup_dir, SHORTCUT_NAME)
        script = f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut('{_ps_quote(shortcut_path)}')
$shortcut.TargetPath = '{_ps_quote(current_app)}'
$shortcut.WorkingDirectory = '{_ps_quote(os.path.dirname(current_app))}'
$shortcut.Save()
"""
        _run_powershell(script)
        return

    for item in list_startup_shortcuts():
        target_path = item.get("target_path")
        shortcut_path = item.get("shortcut_path")
        if not target_path or not shortcut_path:
            continue
        if _normalize_path(target_path) == _normalize_path(current_app):
            try:
                os.remove(shortcut_path)
            except FileNotFoundError:
                pass
