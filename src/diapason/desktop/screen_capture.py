"""Screen capture helpers (macOS screencapture + cross-platform fallbacks)."""

from __future__ import annotations

import base64
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LOCAL_VISION_ENGINES = frozenset(
    {
        "ollama",
        "llamacpp",
        "vllm",
        "sglang",
        "exo",
        "nexa",
        "uzu",
        "apple_fm",
        "gemma_cpp",
        "mlx",
        "lmstudio",
    }
)


def capture_screen_to_temp(*, monitor: int = 0) -> str:
    """Capture screen to a temp PNG; return absolute path.

    ``monitor``: 1-based display index for macOS ``screencapture -D``.
    ``0`` = default / primary.
    """
    # Prefer shared CLI helper path so jarvis ask --screen stays consistent
    if sys.platform == "darwin" and shutil.which("screencapture"):
        fd, path = tempfile.mkstemp(prefix="oj_screen_", suffix=".png")
        os.close(fd)
        cmd = ["screencapture", "-x"]
        if monitor and monitor > 0:
            cmd.extend(["-D", str(int(monitor))])
        cmd.append(path)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if (
                proc.returncode != 0
                or not os.path.exists(path)
                or not os.path.getsize(path)
            ):
                try:
                    os.unlink(path)
                except OSError:
                    pass
                err = (proc.stderr or proc.stdout or "empty image").strip()
                raise RuntimeError(
                    f"screencapture failed: {err}. "
                    "Grant Screen Recording in System Settings → Privacy & Security."
                )
            return path
        except FileNotFoundError as exc:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise RuntimeError("screencapture not found") from exc

    # Fallback: existing CLI helper (mss / Pillow / Windows)
    from diapason.cli._screen import capture_screen_to_temp as _cli_capture

    return _cli_capture()


def resize_image_file(path: str | Path, *, max_dimension: int = 1280) -> Path:
    """Downscale image in-place (or copy) so longest edge ≤ max_dimension."""
    p = Path(path)
    if max_dimension <= 0:
        return p
    try:
        from PIL import Image  # type: ignore
    except ImportError:
        return p

    with Image.open(p) as img:
        w, h = img.size
        longest = max(w, h)
        if longest <= max_dimension:
            return p
        scale = max_dimension / float(longest)
        new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
        resized = img.resize(new_size)
        resized.save(p)
    return p


def image_file_to_b64(path: str | Path) -> str:
    data = Path(path).read_bytes()
    return base64.b64encode(data).decode("ascii")


def capture_screen_b64(
    *,
    monitor: int = 0,
    max_dimension: int = 1280,
    keep_temp: bool = False,
) -> tuple[str, dict]:
    """Capture → resize → base64. Deletes temp unless keep_temp.

    Returns ``(b64, meta)``.
    """
    path = capture_screen_to_temp(monitor=monitor)
    meta: dict = {"path": path, "monitor": monitor}
    try:
        resize_image_file(path, max_dimension=max_dimension)
        size = os.path.getsize(path)
        meta["bytes"] = size
        b64 = image_file_to_b64(path)
        return b64, meta
    finally:
        if not keep_temp:
            try:
                os.unlink(path)
            except OSError:
                pass
            meta.pop("path", None)


__all__ = [
    "LOCAL_VISION_ENGINES",
    "capture_screen_b64",
    "capture_screen_to_temp",
    "image_file_to_b64",
    "resize_image_file",
]
