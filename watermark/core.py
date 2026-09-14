from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
if HEIF_SUPPORTED:
    SUPPORTED_EXTENSIONS.update({'.heic', '.heif'})

POSITIONS = (
    'top-left',
    'top-center',
    'top-right',
    'center-left',
    'center-center',
    'center-right',
    'bottom-left',
    'bottom-center',
    'bottom-right',
)

MARGIN_RATIO = 0.03
DEFAULT_SCALE = 0.45
NUMBER_DIGITS = 4
SHADOW_OFFSET = (4, 4)
SHADOW_BACKGROUND = (0, 0, 0, 160)
SHADOW_BLUR_RADIUS = 6

HEIF_EXTENSIONS = {'.heic', '.heif'}
JPEG_EXTENSIONS = {'.jpg', '.jpeg'}


def add_drop_shadow(
    image: Image.Image,
    offset=SHADOW_OFFSET,
    background_color=SHADOW_BACKGROUND,
    blur_radius=SHADOW_BLUR_RADIUS,
):
    padding = blur_radius * 2
    shadow_size = (image.width + padding * 2, image.height + padding * 2)
    shadow = Image.new('RGBA', shadow_size, (0, 0, 0, 0))

    alpha = image.split()[3] if image.mode == 'RGBA' else Image.new('L', image.size, 255)
    shadow_mask = Image.new('RGBA', image.size, background_color)
    shadow_mask.putalpha(alpha)

    shadow.paste(shadow_mask, (padding + offset[0], padding + offset[1]))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur_radius))

    shadow.paste(image, (padding, padding), mask=image)
    return shadow, padding


def _compute_position(base_size, anchor_size, position):
    bw, bh = base_size
    ww, wh = anchor_size
    margin_x = int(bw * MARGIN_RATIO)
    margin_y = int(bh * MARGIN_RATIO)
    center_x = (bw - ww) // 2
    center_y = (bh - wh) // 2

    if position == 'top-left':
        x, y = margin_x, margin_y
    elif position == 'top-center':
        x, y = center_x, margin_y
    elif position == 'top-right':
        x, y = bw - ww - margin_x, margin_y
    elif position == 'center-left':
        x, y = margin_x, center_y
    elif position == 'center-center':
        x, y = center_x, center_y
    elif position == 'center-right':
        x, y = bw - ww - margin_x, center_y
    elif position == 'bottom-left':
        x, y = margin_x, bh - wh - margin_y
    elif position == 'bottom-center':
        x, y = center_x, bh - wh - margin_y
    elif position == 'bottom-right':
        x, y = bw - ww - margin_x, bh - wh - margin_y
    else:
        raise ValueError(f"Posición inválida: {position!r}. Válidas: {', '.join(POSITIONS)}")

    return max(0, x), max(0, y)


def load_image(path: Path) -> Image.Image:
    with Image.open(path) as img:
        return img.convert('RGBA').copy()


def load_watermark(path: Path) -> Image.Image:
    with Image.open(path) as wm:
        return wm.convert('RGBA').copy()


def load_thumbnail(path: Path, max_size) -> Image.Image:
    with Image.open(path) as img:
        try:
            img.draft('RGB', max_size)
        except Exception:
            pass
        thumb = img.convert('RGBA')
        thumb.thumbnail(max_size, Image.Resampling.LANCZOS)
        return thumb.copy()


def apply_watermark(
    base_image: Image.Image,
    watermark: Image.Image,
    position: str = 'bottom-right',
    scale: float = DEFAULT_SCALE,
    shadow_scale: float = 1.0,
) -> Image.Image:
    if position not in POSITIONS:
        raise ValueError(f"Posición inválida: {position!r}. Válidas: {', '.join(POSITIONS)}")

    img = base_image.convert('RGBA')
    wm = watermark.convert('RGBA')

    target_wm_width = max(1, int(img.width * scale))
    aspect_ratio = wm.height / wm.width
    target_wm_height = max(1, int(target_wm_width * aspect_ratio))
    wm = wm.resize((target_wm_width, target_wm_height), Image.Resampling.LANCZOS)

    offset = (
        max(1, round(SHADOW_OFFSET[0] * shadow_scale)),
        max(1, round(SHADOW_OFFSET[1] * shadow_scale)),
    )
    blur_radius = max(1, round(SHADOW_BLUR_RADIUS * shadow_scale))
    wm_shadowed, padding = add_drop_shadow(wm, offset=offset, blur_radius=blur_radius)

    anchor = (wm_shadowed.width - padding, wm_shadowed.height - padding)
    pos_x, pos_y = _compute_position(img.size, anchor, position)

    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    overlay.paste(wm_shadowed, (pos_x, pos_y))
    return Image.alpha_composite(img, overlay)


def save_image(image: Image.Image, out_path: Path) -> None:
    suffix = Path(out_path).suffix.lower()
    if suffix in JPEG_EXTENSIONS:
        image.convert('RGB').save(out_path, 'JPEG', quality=95)
    elif suffix == '.png':
        image.save(out_path, 'PNG')
    else:
        image.convert('RGB').save(out_path, 'JPEG', quality=95)


def output_filename(src_path: Path, number: int, digits: int = NUMBER_DIGITS) -> str:
    suffix = src_path.suffix.lower()
    ext = '.jpg' if suffix in HEIF_EXTENSIONS else (suffix or '.jpg')
    return f"{number:0{digits}d}{ext}"


def default_cli_output_path(src_path: Path, output_dir: Path) -> Path:
    if src_path.suffix.lower() in HEIF_EXTENSIONS:
        return output_dir / f"{src_path.stem}.jpg"
    return output_dir / src_path.name


def default_output_dir(input_dir: Path) -> Path:
    input_dir = Path(input_dir).resolve()
    return input_dir.parent / f"{input_dir.name}-watermark"


def iter_supported_images(directory: Path):
    directory = Path(directory)
    return sorted(
        (p for p in directory.iterdir() if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS),
        key=lambda p: p.name,
    )
