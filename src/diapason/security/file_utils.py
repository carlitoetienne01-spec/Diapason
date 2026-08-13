"""Secure file and directory creation helpers.

All Diapason data files under ``~/.diapason/`` should be created
through these helpers to ensure consistent, restrictive permissions.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path


def secure_mkdir(path: Path, mode: int = 0o700) -> Path:
    """Create a directory with restrictive permissions.

    Creates parent directories as needed, then sets *mode* on the
    target directory (even if it already exists).
    """
    path.mkdir(parents=True, exist_ok=True)
    file_stat = path.lstat()
    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISDIR(file_stat.st_mode):
        raise RuntimeError(f"Refusing unsafe directory path: {path}")
    os.chmod(path, mode)
    return path


def secure_create(path: Path, mode: int = 0o600) -> Path:
    """Ensure a file exists with restrictive permissions.

    Creates the parent directory with ``0o700`` if needed, touches the
    file if it doesn't exist, and sets *mode* on it.
    """
    parent = path.parent
    if parent.exists():
        parent_stat = parent.lstat()
        if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
            raise RuntimeError(f"Refusing unsafe parent directory: {parent}")
    else:
        parent.mkdir(mode=0o700, parents=True)
        parent_stat = parent.lstat()
        if not stat.S_ISDIR(parent_stat.st_mode):
            raise RuntimeError(f"Refusing unsafe parent directory: {parent}")
        os.chmod(parent, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, mode)
    except FileExistsError:
        file_stat = path.lstat()
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise RuntimeError(f"Refusing unsafe file path: {path}")
    else:
        os.close(descriptor)
    os.chmod(path, mode)
    return path
