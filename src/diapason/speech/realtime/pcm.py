"""PCM helpers for realtime voice (16-bit little-endian mono)."""

from __future__ import annotations

import array
import base64


def pcm16_to_b64(pcm: bytes) -> str:
    return base64.b64encode(pcm).decode("ascii")


def b64_to_pcm16(data: str) -> bytes:
    return base64.b64decode(data)


def resample_pcm16(pcm: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample mono PCM16 between sample rates (linear interpolation).

    Avoids the stdlib ``audioop`` module (removed in Python 3.13).
    """
    if src_rate == dst_rate or not pcm:
        return pcm
    if src_rate <= 0 or dst_rate <= 0:
        return pcm

    src = array.array("h")
    src.frombytes(pcm)
    if not src:
        return pcm

    ratio = dst_rate / float(src_rate)
    dst_len = max(1, int(round(len(src) * ratio)))
    dst = array.array("h", [0] * dst_len)
    last = len(src) - 1
    for i in range(dst_len):
        pos = i / ratio
        left = int(pos)
        right = left + 1
        if left >= last:
            dst[i] = src[last]
            continue
        frac = pos - left
        dst[i] = int(src[left] * (1.0 - frac) + src[right] * frac)
    return dst.tobytes()


__all__ = ["b64_to_pcm16", "pcm16_to_b64", "resample_pcm16"]
