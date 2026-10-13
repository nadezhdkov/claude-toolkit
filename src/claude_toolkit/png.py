"""Minimal PNG reading and writing with the standard library (zlib).

Reads non-interlaced greyscale, RGB, palette, grey+alpha and RGBA images of
any bit depth (16-bit samples are rounded to 8 bits), which covers browser,
Godot, ImageMagick and ffmpeg screenshots.
Pixels are kept as one ``bytearray`` of RGBA rows.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path

SIGNATURE = b"\x89PNG\r\n\x1a\n"
CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}


class PNGError(ValueError):
    """The file is not a PNG this module can read."""


@dataclass
class Image:
    width: int
    height: int
    rgba: bytearray

    @classmethod
    def blank(cls, width: int, height: int, color: tuple[int, int, int, int] = (0, 0, 0, 255)) -> Image:
        return cls(width, height, bytearray(bytes(color) * (width * height)))

    def pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        i = (y * self.width + x) * 4
        r, g, b, a = self.rgba[i : i + 4]
        return r, g, b, a

    def row(self, y: int) -> bytearray:
        stride = self.width * 4
        return self.rgba[y * stride : (y + 1) * stride]


def _unfilter(data: bytes, stride: int, height: int, bpp: int) -> bytearray:
    out = bytearray(height * stride)
    previous = bytearray(stride)
    pos = 0
    for y in range(height):
        kind = data[pos]
        line = bytearray(data[pos + 1 : pos + 1 + stride])
        pos += 1 + stride
        if kind == 1:  # Sub
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif kind == 2:  # Up
            line = bytearray((a + b) & 0xFF for a, b in zip(line, previous, strict=True))
        elif kind == 3:  # Average
            for i in range(stride):
                left = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((left + previous[i]) >> 1)) & 0xFF
        elif kind == 4:  # Paeth
            for i in range(stride):
                if i >= bpp:
                    a, c = line[i - bpp], previous[i - bpp]
                else:
                    a = c = 0
                b = previous[i]
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                predictor = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[i] = (line[i] + predictor) & 0xFF
        elif kind != 0:
            raise PNGError(f"unknown filter type {kind}")
        out[y * stride : (y + 1) * stride] = line
        previous = line
    return out


def _to_rgba(raw: bytearray, color_type: int, palette: bytes, transparency: bytes) -> bytearray:
    if color_type == 6:
        return raw
    if color_type == 2:
        out = bytearray(len(raw) // 3 * 4)
        out[0::4], out[1::4], out[2::4] = raw[0::3], raw[1::3], raw[2::3]
        out[3::4] = b"\xff" * (len(raw) // 3)
        return out
    if color_type == 0:
        out = bytearray(len(raw) * 4)
        out[0::4] = out[1::4] = out[2::4] = raw
        out[3::4] = b"\xff" * len(raw)
        return out
    if color_type == 4:
        out = bytearray(len(raw) * 2)
        grey = raw[0::2]
        out[0::4] = out[1::4] = out[2::4] = grey
        out[3::4] = raw[1::2]
        return out
    # Palette
    alpha = transparency + b"\xff" * (256 - len(transparency))
    table = [bytes(palette[i * 3 : i * 3 + 3]) + alpha[i : i + 1] for i in range(len(palette) // 3)]
    try:
        return bytearray(b"".join(table[index] for index in raw))
    except IndexError as missing:
        raise PNGError("palette index out of range") from missing


def decode(data: bytes) -> Image:
    if not data.startswith(SIGNATURE):
        raise PNGError("not a PNG file")
    pos = len(SIGNATURE)
    header: tuple[int, ...] | None = None
    palette = transparency = b""
    chunks: list[bytes] = []
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos : pos + 8])
        body = data[pos + 8 : pos + 8 + length]
        pos += 12 + length
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"PLTE":
            palette = body
        elif kind == b"tRNS":
            transparency = body
        elif kind == b"IDAT":
            chunks.append(body)
        elif kind == b"IEND":
            break
    if header is None:
        raise PNGError("missing IHDR")
    width, height, depth, color_type, _compression, _filter, interlace = header
    if depth not in (1, 2, 4, 8, 16) or color_type not in CHANNELS or interlace:
        raise PNGError(f"unsupported PNG (bit depth {depth}, colour type {color_type}, interlace {interlace})")
    try:
        raw = zlib.decompress(b"".join(chunks))
    except zlib.error as broken:
        raise PNGError(f"corrupt image data: {broken}") from broken
    channels = CHANNELS[color_type]
    stride = (width * channels * depth + 7) // 8
    if len(raw) < height * (stride + 1):
        raise PNGError("truncated image data")
    pixels = _unfilter(raw, stride, height, max(1, channels * depth // 8))
    if depth == 16:
        pixels = bytearray(
            ((hi << 8 | lo) * 255 + 32767) // 65535 for hi, lo in zip(pixels[0::2], pixels[1::2], strict=True)
        )
    elif depth < 8:
        pixels = _unpack_bits(pixels, width, height, stride, depth, scale=color_type == 0)
    return Image(width, height, _to_rgba(pixels, color_type, palette, transparency))


def _unpack_bits(packed: bytearray, width: int, height: int, stride: int, depth: int, *, scale: bool) -> bytearray:
    """One byte per sample from 1, 2 or 4-bit rows; greyscale is scaled to 0-255."""
    per_byte, mask = 8 // depth, (1 << depth) - 1
    factor = 255 // mask if scale else 1
    out = bytearray()
    for y in range(height):
        row = packed[y * stride : (y + 1) * stride]
        samples = [(byte >> (8 - depth * (k + 1))) & mask for byte in row for k in range(per_byte)]
        out += bytes(value * factor for value in samples[:width])
    return out


def read(path: str | Path) -> Image:
    return decode(Path(path).read_bytes())


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)


def encode(image: Image) -> bytes:
    stride = image.width * 4
    raw = b"".join(b"\x00" + bytes(image.rgba[y * stride : (y + 1) * stride]) for y in range(image.height))
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 6, 0, 0, 0)
    return SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 6)) + _chunk(b"IEND", b"")


def write(image: Image, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(encode(image))
    return target
