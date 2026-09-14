from .core import (
    HEIF_SUPPORTED,
    SUPPORTED_EXTENSIONS,
    POSITIONS,
    DEFAULT_SCALE,
    NUMBER_DIGITS,
    load_image,
    load_watermark,
    load_thumbnail,
    apply_watermark,
    save_image,
    output_filename,
    default_cli_output_path,
    default_output_dir,
    iter_supported_images,
)

__version__ = '0.2.0'

__all__ = [
    'HEIF_SUPPORTED',
    'SUPPORTED_EXTENSIONS',
    'POSITIONS',
    'DEFAULT_SCALE',
    'NUMBER_DIGITS',
    'load_image',
    'load_watermark',
    'load_thumbnail',
    'apply_watermark',
    'save_image',
    'output_filename',
    'default_cli_output_path',
    'default_output_dir',
    'iter_supported_images',
]
