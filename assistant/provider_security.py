"""Windows current-user DPAPI for a manually supplied DeepSeek key.

This module neither discovers keys nor reads/writes files. A local configuration
form must obtain explicit consent before persisting the returned ciphertext.
Ciphertext is bound to this Windows user; exported project/backup packages must
exclude it. There is deliberately no plaintext or non-Windows fallback.
"""
import base64
import binascii
import ctypes
import hashlib
import sys

PREFIX = 'dpapi-user-v1:'
_ENTROPY = hashlib.sha256(b'StudyReview/DeepSeek/current-user/v1').digest()
_MAX_CIPHERTEXT = 8192


class SecretProtectionError(Exception):
    """Safe exception whose message never includes the input key/ciphertext."""


def validate_api_key(value):
    if not isinstance(value, str):
        raise SecretProtectionError('请手动填写有效的 DeepSeek API 密钥。')
    value = value.strip()
    if not 16 <= len(value) <= 256 or any(not 33 <= ord(ch) <= 126 for ch in value):
        raise SecretProtectionError('请手动填写有效的 DeepSeek API 密钥。')
    return value


class _DataBlob(ctypes.Structure):
    _fields_ = [('cbData', ctypes.c_ulong), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data):
    storage = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
    return _DataBlob(len(data), ctypes.cast(storage, ctypes.POINTER(ctypes.c_ubyte))), storage


def _crypt(data, *, protect):
    if sys.platform != 'win32' or not hasattr(ctypes, 'WinDLL'):
        raise SecretProtectionError('当前系统不支持 Windows 用户密钥保护；未保存密钥。')
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    operation = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    second_type = ctypes.c_wchar_p if protect else ctypes.POINTER(ctypes.c_wchar_p)
    operation.argtypes = [ctypes.POINTER(_DataBlob), second_type,
                          ctypes.POINTER(_DataBlob), ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(_DataBlob)]
    operation.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    incoming, incoming_storage = _blob(data)
    entropy, entropy_storage = _blob(_ENTROPY)
    outgoing = _DataBlob()
    description = 'StudyReview DeepSeek API key' if protect else None
    try:
        # CRYPTPROTECT_UI_FORBIDDEN only: never CRYPTPROTECT_LOCAL_MACHINE.
        if not operation(ctypes.byref(incoming), description, ctypes.byref(entropy),
                         None, None, 1, ctypes.byref(outgoing)):
            raise SecretProtectionError('无法使用当前 Windows 用户保护或读取密钥；请重新手动配置。')
        if not 0 < outgoing.cbData <= _MAX_CIPHERTEXT:
            raise SecretProtectionError('密钥保护结果无效；未保存密钥。')
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.memset(incoming_storage, 0, len(incoming_storage))
        ctypes.memset(entropy_storage, 0, len(entropy_storage))
        if outgoing.pbData:
            ctypes.memset(outgoing.pbData, 0, outgoing.cbData)
            kernel32.LocalFree(ctypes.cast(outgoing.pbData, ctypes.c_void_p))


def encrypt_api_key(manually_supplied_key):
    """Return ciphertext only; caller owns action-time approval and safe storage."""
    value = validate_api_key(manually_supplied_key)
    return PREFIX + base64.b64encode(_crypt(value.encode('ascii'), protect=True)).decode('ascii')


def decrypt_api_key(ciphertext):
    """Decrypt an explicitly selected current-user value, never search for one.

    Python strings cannot promise in-memory erasure. Do not log, serialize,
    return to a browser, or include the resulting string in exception messages.
    """
    if not isinstance(ciphertext, str) or not ciphertext.startswith(PREFIX) or len(ciphertext) > 12000:
        raise SecretProtectionError('密钥保护格式无效；请重新手动配置。')
    try:
        encoded = base64.b64decode(ciphertext[len(PREFIX):], validate=True)
    except (ValueError, binascii.Error):
        raise SecretProtectionError('密钥保护格式无效；请重新手动配置。') from None
    if not 0 < len(encoded) <= _MAX_CIPHERTEXT:
        raise SecretProtectionError('密钥保护格式无效；请重新手动配置。')
    try:
        return validate_api_key(_crypt(encoded, protect=False).decode('ascii'))
    except (UnicodeError, ValueError):
        raise SecretProtectionError('密钥保护结果无效；请重新手动配置。') from None
