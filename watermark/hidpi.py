from __future__ import annotations

import sys


def enable_dpi_awareness():
    if sys.platform != 'win32':
        return
    try:
        import ctypes

        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def apply_scaling(root):
    try:
        dpi = float(root.winfo_fpixels('1i'))
    except Exception:
        return
    if dpi <= 0:
        return
    pixels_per_point = max(0.75, min(4.0, dpi / 72.0))
    try:
        root.tk.call('tk', 'scaling', pixels_per_point)
    except Exception:
        pass
