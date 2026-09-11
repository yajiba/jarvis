"""Fixed Windows operations; no model-generated commands."""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess


HARDWARE_QUERY = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$cpu = @(Get-CimInstance Win32_Processor | Select-Object Name,LoadPercentage)
$ram = Get-CimInstance Win32_OperatingSystem
$gpu = @(Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion)
@{cpu=$cpu; ram_total_bytes=([long]$ram.TotalVisibleMemorySize * 1024);
ram_free_bytes=([long]$ram.FreePhysicalMemory * 1024); gpu=$gpu} | ConvertTo-Json -Depth 4 -Compress
"""


def hidden_process_options() -> dict:
    return {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}


def system_executable(name: str) -> Path:
    return Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32' / name


def hardware_info() -> dict:
    if os.name != 'nt':
        return {'available': False, 'reason': 'Hardware metrics require Windows'}
    powershell = system_executable('WindowsPowerShell/v1.0/powershell.exe')
    try:
        response = subprocess.run(
            [str(powershell), '-NoProfile', '-NonInteractive', '-Command', HARDWARE_QUERY],
            capture_output=True, text=True, encoding='utf-8-sig', errors='replace',
            timeout=20, check=True, shell=False, **hidden_process_options())
        result = json.loads(response.stdout)
        if not isinstance(result, dict):
            raise ValueError('Invalid hardware response')
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        return {'available': False, 'reason': f'Windows hardware query failed: {type(error).__name__}'}
    result['available'] = True
    result['gpu_metrics'] = {'available': False, 'reason': 'NVIDIA metrics unavailable; GPU names are listed separately'}
    candidates = [system_executable('nvidia-smi.exe'),
                  Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'NVIDIA Corporation/NVSMI/nvidia-smi.exe']
    executable = next((path for path in candidates if path.is_file()), None)
    if executable:
        try:
            response = subprocess.run(
                [str(executable), '--query-gpu=name,utilization.gpu,memory.total,memory.used',
                 '--format=csv,noheader,nounits'], capture_output=True, text=True,
                timeout=5, check=True, shell=False, **hidden_process_options())
            import csv
            result['gpu_metrics'] = {'available': True, 'devices': [
                {'name': row[0].strip(), 'utilization_percent': float(row[1]),
                 'memory_total_mib': float(row[2]), 'memory_used_mib': float(row[3])}
                for row in csv.reader(response.stdout.splitlines()) if len(row) == 4]}
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    return result


def request_application_close(process: subprocess.Popen) -> str:
    """Post WM_CLOSE only to top-level windows belonging to a retained process."""
    if os.name != 'nt':
        raise ValueError('Closing applications requires Windows')
    if process.poll() is not None:
        raise ValueError('The launched process has exited or handed off to another instance')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.PostMessageW.restype = wintypes.BOOL
    sent = []

    @callback_type
    def visit(window, parameter):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        if pid.value == process.pid and process.poll() is None:
            if user32.PostMessageW(window, 0x0010, 0, 0):  # WM_CLOSE
                sent.append(window)
        return True

    if not user32.EnumWindows(visit, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    if not sent:
        raise ValueError('No windows belonging to the launched process were found')
    return 'Close requested; the application may ask you to save unsaved work'


def stop_process_tree(process: subprocess.Popen) -> None:
    """Stop only the retained process and its descendants; never select by name."""
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run([str(system_executable('taskkill.exe')), '/PID', str(process.pid), '/T', '/F'],
                       capture_output=True, timeout=10, check=True, shell=False,
                       **hidden_process_options())
    else:
        import signal
        os.killpg(process.pid, signal.SIGTERM)
    process.wait(timeout=10)
