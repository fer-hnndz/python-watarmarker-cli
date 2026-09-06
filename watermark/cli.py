import argparse
import sys
from pathlib import Path

from . import core


def build_parser():
    parser = argparse.ArgumentParser(
        prog='watermark',
        description=(
            'Aplica marcas de agua PNG a las imágenes de una carpeta. '
            'El logo se escala relativo al ancho de la imagen (45%% por defecto). '
            'Las imágenes procesadas se guardan en una carpeta nueva '
            "'<carpeta>-watermark' en el mismo directorio padre."
        ),
    )
    parser.add_argument('folder', nargs='?', type=str, help='Carpeta de entrada con las imágenes')
    parser.add_argument('watermark', nargs='?', type=str, help='Archivo PNG con la marca de agua')
    parser.add_argument(
        '--scale',
        type=float,
        default=core.DEFAULT_SCALE,
        help='Escala de la marca relativa al ancho de la imagen (default: 45%%)',
    )
    parser.add_argument(
        '--gui',
        action='store_true',
        help='Levanta la interfaz gráfica para revisar y confirmar cada imagen antes de escribirla',
    )
    return parser


def _die(message):
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(1)


def run_gui():
    try:
        from .gui import run_gui as _run_gui
    except Exception as exc:  # tkinter faltante o sin display
        _die(f"No se pudo iniciar la interfaz gráfica ({exc}). Usá 'pip install tk' o corré la CLI sin --gui.")

    try:
        _run_gui()
    except Exception as exc:
        _die(f"No se pudo iniciar la interfaz gráfica: {exc}")


def run_cli(args):
    input_dir = Path(args.folder).resolve()
    watermark_path = Path(args.watermark).resolve()

    if not input_dir.is_dir():
        _die(f"La carpeta '{input_dir}' no existe.")
    if not watermark_path.is_file():
        _die(f"El archivo de marca de agua '{watermark_path}' no existe.")
    if not (0 < args.scale <= 1):
        _die('La escala debe estar entre 0 y 1.')

    output_dir = core.default_output_dir(input_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Source folder:      {input_dir}")
    print(f"Destination folder: {output_dir}")
    print(f"Watermark scale:    {int(args.scale * 100)}%\n")

    if not core.HEIF_SUPPORTED:
        print(
            "Notice: 'pillow_heif' is not installed. HEIC images will be skipped. "
            "Install with 'pip install pillow-heif'.\n"
        )

    images = core.iter_supported_images(input_dir)
    if not images:
        print('No compatible images found in the target directory.')
        return

    watermark = core.load_watermark(watermark_path)
    print(f"Found {len(images)} image(s). Processing...\n")
    for img_path in images:
        try:
            base = core.load_image(img_path)
            watermarked = core.apply_watermark(base, watermark, scale=args.scale)
            out_path = core.default_cli_output_path(img_path, output_dir)
            core.save_image(watermarked, out_path)
            print(f"[✓] Processed: {img_path.name} -> {out_path.name}")
        except Exception as exc:
            print(f"[X] Error processing {img_path.name}: {exc}")

    print(f"\nBatch processing complete! Output saved to: {output_dir}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.gui:
        run_gui()
        return

    if not args.folder or not args.watermark:
        parser.error('folder y watermark son obligatorios salvo que se use --gui')

    run_cli(args)


if __name__ == '__main__':
    main()
