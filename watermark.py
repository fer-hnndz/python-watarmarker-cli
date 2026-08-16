#!/usr/bin/env python3
"""
Dependencies:
    - Pillow (pip install Pillow)
    - pillow-heif (pip install pillow-heif)  # Optional, required for HEIC/HEIF format support

Description:
    Watermarking script that processes all images in a target directory and overlays
    a PNG watermark resized relative to the image width (45% by default).

    The processed images are saved in a new folder located in the same parent directory,
    named '<folder_name>-watermark'.
"""

import os
import sys
import argparse
from pathlib import Path
from PIL import Image, ImageEnhance, ImageFilter

# Register HEIC/HEIF file format opener if the library is available
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:
    HEIF_SUPPORTED = False

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.bmp', '.tiff', '.tif'}
if HEIF_SUPPORTED:
    SUPPORTED_EXTENSIONS.update({'.heic', '.heif'})


def add_drop_shadow(image: Image.Image, offset=(4, 4), background_color=(0, 0, 0, 160), blur_radius=6):
    """
    Applies a soft drop-shadow effect to an RGBA watermark image to ensure high contrast
    and visibility over both light and dark backgrounds.
    """
    padding = blur_radius * 2
    shadow_size = (image.width + padding * 2, image.height + padding * 2)
    shadow = Image.new("RGBA", shadow_size, (0, 0, 0, 0))

    # Extract alpha channel to create a shadow mask
    alpha = image.split()[3] if image.mode == 'RGBA' else Image.new("L", image.size, 255)
    shadow_mask = Image.new("RGBA", image.size, background_color)
    shadow_mask.putalpha(alpha)

    # Paste shadow mask with offset and apply Gaussian Blur
    shadow.paste(shadow_mask, (padding + offset[0], padding + offset[1]))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur_radius))

    # Overlay original watermark image onto the blurred shadow
    shadow.paste(image, (padding, padding), mask=image)
    return shadow, padding


def process_image(img_path: Path, watermark_path: Path, output_dir: Path, scale: float = 0.45):
    """
    Reads an image file, scales and applies the PNG watermark with a drop shadow,
    and writes the final watermarked file to the output directory.
    """
    try:
        with Image.open(img_path) as base_img:
            img = base_img.convert("RGBA")
            bw, bh = img.size

            with Image.open(watermark_path) as wm:
                wm = wm.convert("RGBA")

                # Calculate target watermark size relative to base image width
                target_wm_width = max(1, int(bw * scale))
                aspect_ratio = wm.height / wm.width
                target_wm_height = int(target_wm_width * aspect_ratio)

                wm_resized = wm.resize((target_wm_width, target_wm_height), Image.Resampling.LANCZOS)

                # Add adaptive drop shadow
                wm_shadowed, padding = add_drop_shadow(wm_resized, offset=(4, 4), blur_radius=6)

                # Position: Bottom-Right corner with 3% margin
                margin_x = int(bw * 0.03)
                margin_y = int(bh * 0.03)

                pos_x = max(0, bw - (wm_resized.width + padding) - margin_x)
                pos_y = max(0, bh - (wm_resized.height + padding) - margin_y)

                # Composite watermark onto base image
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                overlay.paste(wm_shadowed, (pos_x, pos_y))
                watermarked = Image.alpha_composite(img, overlay)

                # Determine output path and format
                out_ext = img_path.suffix.lower()
                if out_ext in ['.heic', '.heif']:
                    out_path = output_dir / f"{img_path.stem}.jpg"
                else:
                    out_path = output_dir / img_path.name

                if out_path.suffix.lower() in ['.jpg', '.jpeg']:
                    watermarked.convert("RGB").save(out_path, "JPEG", quality=95)
                elif out_path.suffix.lower() == '.png':
                    watermarked.save(out_path, "PNG")
                else:
                    watermarked.convert("RGB").save(out_path, "JPEG", quality=95)

                print(f"[✓] Processed: {img_path.name} -> {out_path.name}")
    except Exception as e:
        print(f"[X] Error processing {img_path.name}: {e}")


def main():
    parser = argparse.ArgumentParser(
        description="Batch watermark images using a PNG logo scaled relative to image width."
    )
    parser.add_argument("folder", type=str, help="Path to the input folder containing images")
    parser.add_argument("watermark", type=str, help="Path to the PNG watermark file")
    parser.add_argument(
        "--scale", type=float, default=0.45, help="Watermark scale relative to image width (default: 0.45 for 45%%)"
    )

    args = parser.parse_args()

    input_dir = Path(args.folder).resolve()
    watermark_path = Path(args.watermark).resolve()

    if not input_dir.is_dir():
        print(f"Error: Target directory '{input_dir}' does not exist.")
        sys.exit(1)

    if not watermark_path.is_file():
        print(f"Error: Watermark file '{watermark_path}' does not exist.")
        sys.exit(1)

    # Destination folder created in the same parent directory: <folder_name>-watermark
    parent_dir = input_dir.parent
    output_dir = parent_dir / f"{input_dir.name}-watermark"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Source folder:      {input_dir}")
    print(f"Destination folder: {output_dir}")
    print(f"Watermark scale:    {int(args.scale * 100)}%\n")

    if not HEIF_SUPPORTED:
        print("Notice: 'pillow_heif' is not installed. HEIC images will be skipped. Install with 'pip install pillow-heif'.\n")

    images = [f for f in input_dir.iterdir() if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS]

    if not images:
        print("No compatible images found in the target directory.")
        return

    print(f"Found {len(images)} image(s). Processing...\n")
    for img in images:
        process_image(img, watermark_path, output_dir, scale=args.scale)

    print(f"\nBatch processing complete! Output saved to: {output_dir}")

if __name__ == "__main__":
    main()
