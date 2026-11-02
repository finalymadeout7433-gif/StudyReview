"""Recover abandoned development state only; never terminate a process or touch DBs."""
import argparse
import ctypes
import errno
import json
import os
from pathlib import Path
import re
import socket
import uuid

from .runtime import APP_ID, APP_VERSION, DesktopError, InstanceLock


def pid_is_alive(pid):
    if os.name == 'nt':
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied/unknown stays protected.
        try:
            code = wintypes.DWORD()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)  # POSIX existence probe only, never a termination signal.
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def port_is_busy(port):
    try:
        # Closed-port connect can time out on Windows. Exclusive bind proves
        # availability without sending data to a potentially unrelated service.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if os.name == 'nt':
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('127.0.0.1', port))
        return False
    except OSError as error:
        if error.errno in (errno.EADDRINUSE, errno.EACCES, 10048, 10013):
            return True
        raise DesktopError('无法确认开发端口是否空闲，已保留原运行记录。') from None


def recover(data_dir, port, *, alive=pid_is_alive, busy=port_is_busy):
    data = Path(data_dir)
    if not data.is_absolute() or type(port) is not int or not 1024 <= port <= 65535:
        raise DesktopError('开发恢复参数无效。')
    private = data / 'private'
    state = private / 'desktop-state.json'
    for path in (state, *state.parents):
        if path.is_symlink() or getattr(path, 'is_junction', lambda: False)():
            raise DesktopError('开发数据路径含链接，已保留运行记录。')
    try:
        profile = json.loads((private / 'development-environment.json').read_text(encoding='utf-8-sig'))
        if (not re.fullmatch(r'study_review_v2_dev_[A-Za-z0-9_]+', profile.get('database', ''))
                or not re.fullmatch(r'test_study_review_v2_[A-Za-z0-9_]+', profile.get('test_database', ''))):
            raise ValueError()
    except (OSError, ValueError, TypeError, AttributeError):
        raise DesktopError('只能恢复已配置的独立开发环境。') from None
    if not state.exists():
        return False
    with InstanceLock(private / 'desktop.lock'):
        try:
            original = state.read_bytes()
            value = json.loads(original.decode('utf-8-sig'))
            if (value.get('app') != APP_ID or str(value.get('version')) != APP_VERSION
                    or type(value.get('port')) is not int or value['port'] != port
                    or type(value.get('pid')) is not int or not 1 <= value['pid'] <= 4294967295):
                raise ValueError()
        except (OSError, ValueError, AttributeError):
            raise DesktopError('运行记录无法核验，已保留原文件。') from None
        if alive(value['pid']):
            raise DesktopError('开发服务进程仍在运行，请稍后重试或使用停止入口。')
        if busy(port):
            raise DesktopError('开发端口正在被使用，未停止任何程序。')
        if state.read_bytes() != original:
            raise DesktopError('运行记录已变化，已取消恢复。')
        state.rename(private / ('desktop-state.stale-' + uuid.uuid4().hex + '.json'))
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--port', type=int, required=True)
    args = parser.parse_args()
    try:
        recovered = recover(args.data_dir, args.port)
    except DesktopError as error:
        print(str(error))
        return 1
    print('已备份并恢复上次异常退出的运行状态。' if recovered else '无需恢复运行状态。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
