#!/usr/bin/env python3
"""Детерминированные редакционные карточки для publish_batch.py."""

from __future__ import annotations

import textwrap
from pathlib import Path

import sys

if sys.platform == "win32":
    FONT_REGULAR = Path("C:/Windows/Fonts/arial.ttf")
    FONT_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")
else:
    FONT_REGULAR = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    FONT_BOLD = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def _color(value, default):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    numbers = tuple(int(part) for part in value)
    if any(part < 0 or part > 255 for part in numbers):
        raise ValueError(f"Неверный RGB-цвет: {value!r}")
    return numbers


def _font(ImageFont, path: Path, size: int):
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size=size)


def build_card(item: dict, target: Path, release_date: str) -> Path:
    """Создать оригинальную JPEG-карточку; существующую не перезаписывать."""
    if target.exists() and target.stat().st_size > 1000:
        return target
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:  # pragma: no cover - диагностика окружения
        raise RuntimeError("Pillow не установлен: python -m pip install Pillow") from exc

    spec = item.get("image_spec") or {}
    color_a = _color(spec.get("color_a"), (22, 77, 125))
    color_b = _color(spec.get("color_b"), (107, 161, 130))
    badge = str(spec.get("badge") or "ACADEMY BEPS")[:32]
    title = str(item.get("title") or "").strip()

    target.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1200, 675
    image = Image.new("RGB", (width, height), color_a)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        ratio = y / max(1, height - 1)
        color = tuple(int(color_a[i] * (1 - ratio) + color_b[i] * ratio) for i in range(3))
        draw.line((0, y, width, y), fill=color)

    draw.rounded_rectangle((70, 58, 430, 118), radius=24, fill=(255, 255, 255))
    draw.rounded_rectangle((70, 140, 1130, 588), radius=36, fill=(20, 31, 49))
    font_badge = _font(ImageFont, FONT_BOLD, 28)
    font_title = _font(ImageFont, FONT_BOLD, 46)
    font_footer = _font(ImageFont, FONT_REGULAR, 22)
    font_small = _font(ImageFont, FONT_BOLD, 24)
    draw.text((95, 73), badge, font=font_badge, fill=(18, 24, 42))

    y = 178
    for line in textwrap.wrap(title, width=34)[:6]:
        draw.text((110, y), line, font=font_title, fill=(255, 255, 255))
        y += 58
    draw.text((110, 516), "Academy BEPS • Editorial Card", font=font_small,
              fill=(236, 241, 248))
    draw.text((110, 554), f"Original Academy BEPS artwork • {release_date}",
              font=font_footer, fill=(214, 222, 235))
    image.save(target, format="JPEG", quality=92, optimize=True)
    return target


def resolve_image(root: Path, release_date: str, item: dict) -> Path:
    """Взять проверенное изображение или собрать карточку из image_spec."""
    raw_path = item.get("image_path")
    if raw_path:
        path = Path(str(raw_path)).expanduser()
        if not path.is_absolute():
            path = root / path
        path = path.resolve()
        if not path.is_file() or path.stat().st_size <= 1000:
            raise ValueError(f"Изображение не найдено/пусто: {path}")
        return path
    if not isinstance(item.get("image_spec"), dict):
        raise ValueError(f"{item.get('slug', '?')}: нужен image_path или image_spec")
    target = root / "pipeline" / "assets" / release_date / f"{item['slug']}.jpg"
    return build_card(item, target, release_date)

