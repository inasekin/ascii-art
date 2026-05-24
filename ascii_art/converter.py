from __future__ import annotations
from pathlib import Path
from PIL import Image

CHAR_SETS: dict[str, str] = {
    "standard": "@#S%?*+;:,. ",
    "extended": '@#$%&8BWM*oahkbdpqwmZO0QLCJUYXzcvunxrjft/\\|()1{}[]?-_+~<>i!lI;:,". ',
    "gradient": "@%#*+=-:. ",
}

SUPPORTED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif"}


def _prepare(img: Image.Image) -> Image.Image:
    if img.mode == "P":
        img = img.convert("RGBA")
    if img.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        alpha = img.split()[-1]
        bg.paste(img.convert("RGB"), mask=alpha)
        return bg
    return img.convert("RGB")


def _convert_frame(
    img: Image.Image,
    width: int,
    height: int,
    chars: str,
    invert: bool,
    color: bool,
) -> str:
    img = img.resize((width, height), Image.LANCZOS)
    n = len(chars) - 1
    gray = img.convert("L")
    gray_pixels = list(gray.getdata())

    if color:
        rgb_pixels = list(img.getdata())
        lines = []
        for y in range(height):
            parts = []
            for x in range(width):
                i = y * width + x
                b = gray_pixels[i]
                if invert:
                    b = 255 - b
                ch = chars[int(b / 255 * n)]
                r, g, bv = rgb_pixels[i]
                parts.append(f"\033[38;2;{r};{g};{bv}m{ch}\033[0m")
            lines.append("".join(parts))
        return "\n".join(lines)
    else:
        lines = []
        for y in range(height):
            row = gray_pixels[y * width:(y + 1) * width]
            if invert:
                line = "".join(chars[int((255 - p) / 255 * n)] for p in row)
            else:
                line = "".join(chars[int(p / 255 * n)] for p in row)
            lines.append(line)
        return "\n".join(lines)


def convert_image(
    image_path: str,
    width: int = 120,
    height: int | None = None,
    charset: str = "standard",
    invert: bool = False,
    color: bool = False,
) -> str:
    ext = Path(image_path).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Неподдерживаемый формат: {ext}")

    img = Image.open(image_path)
    if hasattr(img, "n_frames") and img.n_frames > 1:
        img.seek(0)
    img = _prepare(img)

    orig_w, orig_h = img.size
    if height is None:
        height = max(1, int(width * (orig_h / orig_w) * 0.5))

    chars = CHAR_SETS.get(charset, CHAR_SETS["standard"])
    return _convert_frame(img, width, height, chars, invert, color)


def generate_rotation_frames(
    image_path: str,
    width: int = 120,
    height: int | None = None,
    charset: str = "standard",
    invert: bool = False,
    color: bool = False,
    n_frames: int = 24,
    duration: int = 80,
) -> list[tuple[str, int]]:
    img = Image.open(image_path)
    if hasattr(img, "n_frames") and img.n_frames > 1:
        img.seek(0)
    img = _prepare(img)

    orig_w, orig_h = img.size
    if height is None:
        height = max(1, int(width * (orig_h / orig_w) * 0.5))

    chars = CHAR_SETS.get(charset, CHAR_SETS["standard"])
    frames = []

    for i in range(n_frames):
        angle = 360 * i / n_frames
        rotated = img.rotate(-angle, expand=False, fillcolor=(255, 255, 255), resample=Image.BICUBIC)
        ascii_text = _convert_frame(rotated, width, height, chars, invert, color)
        frames.append((ascii_text, duration))

    return frames


def convert_gif_frames(
    image_path: str,
    width: int = 120,
    height: int | None = None,
    charset: str = "standard",
    invert: bool = False,
    color: bool = False,
) -> list[tuple[str, int]]:
    img = Image.open(image_path)
    n_frames = getattr(img, "n_frames", 1)
    chars = CHAR_SETS.get(charset, CHAR_SETS["standard"])

    img.seek(0)
    if height is None:
        orig_w, orig_h = img.size
        height = max(1, int(width * (orig_h / orig_w) * 0.5))

    canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
    frames: list[tuple[str, int]] = []

    for i in range(n_frames):
        img.seek(i)
        duration = max(50, img.info.get("duration", 100))
        disposal = img.info.get("disposal", 0)

        frame = img.convert("RGBA")
        composite = canvas.copy()
        composite.paste(frame, mask=frame)

        ascii_text = _convert_frame(composite.convert("RGB"), width, height, chars, invert, color)
        frames.append((ascii_text, duration))

        if disposal == 2:
            canvas = Image.new("RGBA", img.size, (255, 255, 255, 255))
        else:
            canvas = composite

    return frames
