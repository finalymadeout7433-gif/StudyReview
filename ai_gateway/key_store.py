"""Only store/retrieve the explicitly configured owner's DPAPI ciphertext UUID.

No environment lookup, key discovery, plaintext file or user-controlled filename.
Files must be excluded from portable packages/exports; DPAPI is Windows-user bound.
"""
import os
import stat
from pathlib import Path
import uuid
from django.conf import settings
from django.views.decorators.debug import sensitive_variables
from assistant.provider_security import SecretProtectionError, encrypt_api_key, decrypt_api_key


def _reject_link(path):
    if path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
        raise SecretProtectionError('密钥存储目录不安全，未读取或保存密钥。')


def root(create=False):
    data_root = getattr(settings, 'PRIVATE_DATA_ROOT', None)
    data_dir = getattr(settings, 'DATA_DIR', None)
    if data_root:
        raw = Path(data_root) / 'ai-credentials'
    elif data_dir:
        # Desktop resources may be read-only; secrets belong to mutable user data.
        # Match an explicit PRIVATE_DATA_ROOT = DATA_DIR / 'private' configuration.
        raw = Path(data_dir) / 'private' / 'ai-credentials'
    else:
        # Compatibility only for projects without a separated data directory.
        raw = Path(settings.BASE_DIR) / 'private' / 'ai'
    if not raw.is_absolute():
        raise SecretProtectionError('密钥存储必须位于本机独立私有目录。')
    for parent in [raw, *raw.parents]:
        _reject_link(parent)
    if create:
        raw.mkdir(parents=True, exist_ok=True, mode=0o700)
    base = raw.resolve(strict=False)
    if base.exists() and not base.is_dir():
        raise SecretProtectionError('密钥存储目录不可用。')
    return base


def _directory(reference):
    try:
        name = uuid.UUID(str(reference)).hex
    except (ValueError, TypeError, AttributeError):
        raise SecretProtectionError('密钥引用无效，请重新手动配置。') from None
    base = root()
    directory = base / name
    _reject_link(directory)
    if not directory.resolve(strict=False).is_relative_to(base):
        raise SecretProtectionError('密钥存储目录不安全。')
    return directory


@sensitive_variables('api_key', 'ciphertext')
def write_new(api_key):
    ciphertext = encrypt_api_key(api_key)
    base = root(create=True)
    reference = uuid.uuid4()
    directory = _directory(reference)
    directory.mkdir(mode=0o700)
    final = directory / 'key.dpapi'
    staged = directory / 'pending.dpapi'
    try:
        with staged.open('xb') as output:
            output.write(ciphertext.encode('ascii'))
            output.flush()
            os.fsync(output.fileno())
        _reject_link(final)
        if final.exists():
            raise SecretProtectionError('密钥文件冲突，未覆盖已有文件。')
        staged.rename(final)
        return reference
    except BaseException:
        remove_new(reference)
        raise


def remove_new(reference):
    """No recursive deletion, no unknown files, no path derived from user input."""
    directory = _directory(reference)
    for name in ('pending.dpapi', 'key.dpapi'):
        path = directory / name
        _reject_link(path)
        path.unlink(missing_ok=True)
    if directory.exists():
        directory.rmdir()


@sensitive_variables('ciphertext')
def read_configured(reference):
    path = _directory(reference) / 'key.dpapi'
    _reject_link(path)
    flags = os.O_RDONLY | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    try:
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, 'rb') as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise SecretProtectionError('本机密钥存储不是安全的普通文件。')
            ciphertext = source.read(12001)
        if not 0 < len(ciphertext) <= 12000:
            raise SecretProtectionError('密钥密文无效，请重新手动配置。')
        return decrypt_api_key(ciphertext.decode('ascii'))
    except (OSError, UnicodeError):
        raise SecretProtectionError('本机密钥暂不可读取，请重新手动配置。') from None
