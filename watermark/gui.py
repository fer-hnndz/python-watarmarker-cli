from __future__ import annotations

import tkinter as tk
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from . import core
from . import hidpi

POSITION_LABELS = {
    'top-left': 'Arriba-izq',
    'top-center': 'Arriba-cen',
    'top-right': 'Arriba-der',
    'center-left': 'Centro-izq',
    'center-center': 'Centro',
    'center-right': 'Centro-der',
    'bottom-left': 'Abajo-izq',
    'bottom-center': 'Abajo-cen',
    'bottom-right': 'Abajo-der',
}
POSITION_GRID = {
    'top-left': (1, 0),
    'top-center': (1, 1),
    'top-right': (1, 2),
    'center-left': (2, 0),
    'center-center': (2, 1),
    'center-right': (2, 2),
    'bottom-left': (3, 0),
    'bottom-center': (3, 1),
    'bottom-right': (3, 2),
}
ACTIVE_BG = '#2f6db3'
SCALE_MIN = 5
SCALE_MAX = 95
SCALE_STEP = 1
SCALE_DEBOUNCE_MS = 250
NAV_DEBOUNCE_MS = 120
CAROUSEL_WIDTH = 196
THUMB_MAX = (160, 110)
PREVIEW_MAX = 1200
PREVIEW_CACHE_BYTES = 512 * 1024 * 1024
ITEM_BG = '#f0f0f0'
ITEM_SEL_BG = '#cfe3ff'


@dataclass
class ImageItem:
    path: Path
    position: str = 'bottom-right'
    scale: float = core.DEFAULT_SCALE
    width: int = 0
    height: int = 0
    base_preview: Image.Image | None = None
    preview: Image.Image | None = None
    preview_key: tuple | None = None
    thumb: ImageTk.PhotoImage | None = None

    def cached_bytes(self) -> int:
        total = 0
        if self.base_preview is not None:
            total += self.base_preview.width * self.base_preview.height * 4
        if self.preview is not None:
            total += self.preview.width * self.preview.height * 3
        return total

    def drop_composite(self) -> None:
        self.preview = None
        self.preview_key = None

    def drop_preview(self) -> None:
        self.base_preview = None
        self.preview = None
        self.preview_key = None


class PreviewCache:
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes
        self.total = 0
        self._lru: 'OrderedDict[Path, tuple[ImageItem, int]]' = OrderedDict()

    def touch(self, item: ImageItem) -> None:
        previous = self._lru.pop(item.path, None)
        if previous is not None:
            self.total -= previous[1]
        size = item.cached_bytes()
        self._lru[item.path] = (item, size)
        self.total += size
        self._evict()

    def remove(self, item: ImageItem) -> None:
        previous = self._lru.pop(item.path, None)
        if previous is not None:
            self.total -= previous[1]

    def clear(self) -> None:
        for item, _size in self._lru.values():
            item.drop_preview()
        self._lru.clear()
        self.total = 0

    def _evict(self) -> None:
        while self.total > self.max_bytes and len(self._lru) > 1:
            _path, (item, size) = self._lru.popitem(last=False)
            self.total -= size
            item.drop_preview()


class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Marcador de Agua')
        self.root.geometry('1260x780')
        self.root.minsize(1060, 660)

        self.src_var = tk.StringVar()
        self.wm_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.scale_var = tk.IntVar(value=int(core.DEFAULT_SCALE * 100))
        self.filename_var = tk.StringVar(value='—')
        self.status_var = tk.StringVar(value='Elegí carpeta origen, marca de agua y destino, y presioná Comenzar.')
        self.counter_var = tk.StringVar(value='')

        self.state = 'idle'
        self.started = False
        self.writing = False

        self.items: list[ImageItem] = []
        self.index = 0
        self.current_position = 'bottom-right'
        self._cache = PreviewCache(PREVIEW_CACHE_BYTES)

        self.watermark_img = None
        self._photo = None
        self._photo_source = None
        self._photo_size = None
        self._carousel_items = []
        self._btn_bg = None
        self._btn_fg = None
        self._after_id = None
        self._nav_after_id = None
        self._loading = False
        self._cancel_requested = False
        self._modal_open = False
        self._discarded_stack = []

        self._build_widgets()
        self._set_ui_state('idle')

    def _build_widgets(self):
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        cfg = tk.Frame(self.root, padx=10, pady=4)
        cfg.grid(row=0, column=0, sticky='ew')
        cfg.columnconfigure(1, weight=1)

        self.config_widgets = []

        self._add_path_row(cfg, 0, 'Carpeta origen:', self.src_var, self._pick_source)
        self._add_path_row(cfg, 1, 'Marca de agua:', self.wm_var, self._pick_watermark)
        self._add_path_row(cfg, 2, 'Carpeta destino:', self.dest_var, self._pick_dest)

        bar = tk.Frame(cfg)
        bar.grid(row=3, column=0, columnspan=4, sticky='ew', pady=(8, 2))
        bar.columnconfigure(6, weight=1)

        tk.Label(bar, text='Escala:').grid(row=0, column=0)
        self.minus_btn = tk.Button(bar, text='−', width=3, command=self._scale_down, takefocus=0)
        self.minus_btn.grid(row=0, column=1, padx=(4, 2))
        self.scale_slider = tk.Scale(
            bar, from_=SCALE_MIN, to=SCALE_MAX, orient='horizontal', showvalue=False,
            length=150, variable=self.scale_var,
        )
        self.scale_slider.grid(row=0, column=2, padx=2)
        self.plus_btn = tk.Button(bar, text='+', width=3, command=self._scale_up, takefocus=0)
        self.plus_btn.grid(row=0, column=3, padx=(2, 6))
        self.scale_label = tk.Label(bar, text=f'{self.scale_var.get()}%')
        self.scale_label.grid(row=0, column=4, padx=(0, 12))

        self.scale_controls = [self.minus_btn, self.plus_btn, self.scale_slider]

        self.start_btn = tk.Button(bar, text='Comenzar', command=self._on_start)
        self.start_btn.grid(row=0, column=6, sticky='e')

        status_row = tk.Frame(cfg)
        status_row.grid(row=4, column=0, columnspan=4, sticky='ew', pady=(2, 0))
        status_row.columnconfigure(0, weight=1)
        self._status_label = tk.Label(status_row, textvariable=self.status_var, anchor='w')
        self._status_label.grid(row=0, column=0, sticky='ew')

        body = tk.Frame(self.root, padx=10, pady=4)
        body.grid(row=1, column=0, sticky='nsew')
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._build_carousel(body)

        right = tk.Frame(body)
        right.grid(row=0, column=1, sticky='nsew')
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(right, bg='#232323', highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky='nsew')
        self.canvas.bind('<Configure>', lambda _e: self._render_preview())

        pos_wrap = tk.Frame(right)
        pos_wrap.grid(row=1, column=0, pady=(8, 0))
        tk.Label(pos_wrap, text='Posición de la marca', font=('', 10, 'bold')).pack(pady=(0, 4))

        grid = tk.Frame(pos_wrap)
        grid.pack()
        self.position_buttons = {}
        for pos, (row, col) in POSITION_GRID.items():
            btn = tk.Button(grid, text=POSITION_LABELS[pos], width=9, takefocus=0)
            btn.grid(row=row, column=col, padx=3, pady=3, sticky='ew')
            btn.config(command=lambda p=pos: self._set_position(p))
            self.position_buttons[pos] = btn

        bottom = tk.Frame(self.root, padx=10, pady=6)
        bottom.grid(row=2, column=0, sticky='ew')
        bottom.columnconfigure(4, weight=1)

        tk.Label(bottom, text='Archivo de salida:').grid(row=0, column=0)
        self.filename_entry = tk.Entry(
            bottom, width=12, justify='center', font=('', 12, 'bold'),
            textvariable=self.filename_var, state='readonly', readonlybackground='#ffffff',
        )
        self.filename_entry.grid(row=0, column=1, padx=(6, 10), pady=4)

        tk.Label(bottom, textvariable=self.counter_var).grid(row=0, column=2, padx=(4, 8))

        self.write_btn = tk.Button(
            bottom, text='Aplicar y escribir todo', command=self._write_all, takefocus=0,
            bg='#2e7d32', fg='white', activebackground='#256b2b', activeforeground='white',
            padx=12,
        )
        self.write_btn.grid(row=0, column=4, sticky='e', padx=(8, 0))

        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.grid(row=3, column=0, sticky='ew', padx=10, pady=(2, 8))
        self.progress.grid_remove()

        self.scale_var.trace_add('write', self._on_scale_var)
        self.src_var.trace_add('write', self._on_src_var)
        self.root.bind_all('<Delete>', self._on_delete_key)
        self.root.bind_all('<Control-z>', self._on_undo_key)
        self.root.bind_all('<Control-Z>', self._on_undo_key)

    def _build_carousel(self, parent):
        carousel = tk.Frame(parent, width=CAROUSEL_WIDTH)
        carousel.grid(row=0, column=0, sticky='ns', padx=(0, 8))
        carousel.grid_propagate(False)
        carousel.rowconfigure(0, weight=1)
        carousel.columnconfigure(0, weight=1)

        self.carousel_canvas = tk.Canvas(
            carousel, bg=ITEM_BG, highlightthickness=1, highlightbackground='#cccccc',
            takefocus=1, width=CAROUSEL_WIDTH - 20,
        )
        self.carousel_canvas.grid(row=0, column=0, sticky='nsew')
        scrollbar = ttk.Scrollbar(carousel, orient='vertical', command=self.carousel_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky='ns')
        self.carousel_canvas.configure(yscrollcommand=scrollbar.set)

        self.carousel_inner = tk.Frame(self.carousel_canvas, bg=ITEM_BG)
        self._carousel_window = self.carousel_canvas.create_window(
            (0, 0), window=self.carousel_inner, anchor='nw'
        )
        self.carousel_inner.bind(
            '<Configure>',
            lambda _e: self.carousel_canvas.configure(scrollregion=self.carousel_canvas.bbox('all')),
        )
        self.carousel_canvas.bind(
            '<Configure>',
            lambda e: self.carousel_canvas.itemconfigure(self._carousel_window, width=e.width),
        )
        self.carousel_canvas.bind('<Up>', lambda _e: self._nav(-1))
        self.carousel_canvas.bind('<Down>', lambda _e: self._nav(1))
        self.carousel_canvas.bind('<Control-Up>', lambda _e: self._move_selected(-1))
        self.carousel_canvas.bind('<Control-Down>', lambda _e: self._move_selected(1))
        self.carousel_canvas.bind('<Return>', lambda _e: self._nav(1))
        for widget in (self.carousel_canvas, self.carousel_inner):
            self._bind_wheel(widget)

        nav = tk.Frame(carousel)
        nav.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(4, 0))
        nav.columnconfigure(0, weight=1)
        nav.columnconfigure(1, weight=1)
        self.up_btn = tk.Button(nav, text='Subir', command=lambda: self._move_selected(-1), takefocus=0)
        self.up_btn.grid(row=0, column=0, sticky='ew', padx=(0, 2))
        self.down_btn = tk.Button(nav, text='Bajar', command=lambda: self._move_selected(1), takefocus=0)
        self.down_btn.grid(row=0, column=1, sticky='ew', padx=(2, 0))
        self.discard_btn = tk.Button(nav, text='Descartar (Del)', command=self._discard_selected, takefocus=0)
        self.discard_btn.grid(row=1, column=0, columnspan=2, sticky='ew', pady=(3, 0))

    def _bind_wheel(self, widget):
        widget.bind('<MouseWheel>', self._on_carousel_wheel)
        widget.bind('<Button-4>', self._on_carousel_wheel)
        widget.bind('<Button-5>', self._on_carousel_wheel)

    def _on_carousel_wheel(self, event):
        if event.num == 4:
            delta = -1
        elif event.num == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        self.carousel_canvas.yview_scroll(delta * 2, 'units')
        return 'break'

    def _add_path_row(self, parent, row, label, var, command):
        tk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=2)
        entry = tk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        btn = tk.Button(parent, text='…', width=3, command=command, takefocus=0)
        btn.grid(row=row, column=2, padx=(0, 4))
        self.config_widgets.extend([entry, btn])

    def _current_item(self) -> ImageItem | None:
        if 0 <= self.index < len(self.items):
            return self.items[self.index]
        return None

    def _on_scale_var(self, *_args):
        self._on_scale()

    def _on_scale(self, _value=None):
        self.scale_label.config(text=f'{self.scale_var.get()}%')
        item = self._current_item()
        if not self._loading and self.state == 'working' and item is not None:
            item.scale = self._scale()
            item.drop_composite()
        self._schedule_preview()

    def _scale_down(self):
        self._set_scale_value(self.scale_var.get() - SCALE_STEP)

    def _scale_up(self):
        self._set_scale_value(self.scale_var.get() + SCALE_STEP)

    def _set_scale_value(self, value):
        self.scale_var.set(max(SCALE_MIN, min(SCALE_MAX, value)))

    def _cancel_timers(self):
        for attr in ('_after_id', '_nav_after_id'):
            pending = getattr(self, attr)
            if pending is not None:
                self.root.after_cancel(pending)
                setattr(self, attr, None)

    def _schedule_preview(self):
        if self._loading or self.state != 'working' or not self.items:
            return
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(SCALE_DEBOUNCE_MS, self._apply_scale_preview)

    def _apply_scale_preview(self):
        self._after_id = None
        if self.state == 'working':
            self._rebuild_composite()

    def _schedule_nav_preview(self):
        if self.state != 'working' or not self.items:
            return
        if self._nav_after_id is not None:
            self.root.after_cancel(self._nav_after_id)
        self._nav_after_id = self.root.after(NAV_DEBOUNCE_MS, self._load_current_image)

    def _scale(self):
        return self.scale_var.get() / 100

    def _pick_source(self):
        path = filedialog.askdirectory(title='Carpeta con las imágenes')
        if path:
            self.src_var.set(path)

    def _on_src_var(self, *_args):
        value = self.src_var.get().strip()
        if not value:
            return
        path = Path(value)
        if path.is_dir():
            self.dest_var.set(str(core.default_output_dir(path)))

    def _pick_watermark(self):
        path = filedialog.askopenfilename(
            title='Marca de agua (PNG)',
            filetypes=[('PNG', '*.png'), ('Todos los archivos', '*.*')],
        )
        if path:
            self.wm_var.set(path)

    def _pick_dest(self):
        path = filedialog.askdirectory(title='Carpeta destino')
        if path:
            self.dest_var.set(path)

    def _set_position(self, position):
        self.current_position = position
        self._highlight_position(position)
        item = self._current_item()
        if not self._loading and self.state == 'working' and item is not None:
            item.position = position
        if self.state == 'working' and item is not None:
            self._cancel_timers()
            self._rebuild_composite()
        if self.state == 'working':
            self.carousel_canvas.focus_set()

    def _highlight_position(self, position):
        for pos, btn in self.position_buttons.items():
            if pos == position:
                btn.config(relief='sunken', bg=ACTIVE_BG, fg='white',
                           activebackground=ACTIVE_BG, activeforeground='white')
            else:
                btn.config(relief='raised', bg=self._btn_bg, fg=self._btn_fg,
                           activebackground=self._btn_bg, activeforeground=self._btn_fg)

    def _load_thumbnails(self):
        for item in self.items:
            try:
                thumb = core.load_thumbnail(item.path, THUMB_MAX).convert('RGB')
                item.thumb = ImageTk.PhotoImage(thumb)
            except Exception:
                item.thumb = None

    def _build_carousel_items(self):
        for child in self.carousel_inner.winfo_children():
            child.destroy()
        self._carousel_items = []

        for i, item in enumerate(self.items):
            frame = tk.Frame(self.carousel_inner, bd=2, relief='flat', bg=ITEM_BG, cursor='hand2')
            frame.pack(fill='x', padx=4, pady=3)

            thumb_label = tk.Label(frame, bg=ITEM_BG)
            if item.thumb is not None:
                thumb_label.config(image=item.thumb)
            else:
                thumb_label.config(text='?', width=16, height=4, fg='#999999')
            thumb_label.pack(pady=(2, 0))

            name = item.path.name
            if len(name) > 26:
                name = item.path.stem[:20] + '…' + item.path.suffix
            caption = tk.Label(
                frame, text=f'{i + 1:04d}  {name}', bg=ITEM_BG, fg='#333333',
                font=('', 8), wraplength=CAROUSEL_WIDTH - 36, justify='center',
            )
            caption.pack(fill='x', pady=(0, 2))

            for widget in (frame, thumb_label, caption):
                widget.bind('<Button-1>', lambda _e, idx=i: self._on_item_click(idx))
                self._bind_wheel(widget)

            self._carousel_items.append({'frame': frame, 'thumb': thumb_label, 'caption': caption})

        self._highlight_item()

    def _on_item_click(self, idx):
        self.carousel_canvas.focus_set()
        self._select(idx)

    def _highlight_item(self):
        for i, item in enumerate(self._carousel_items):
            selected = i == self.index
            bg = ITEM_SEL_BG if selected else ITEM_BG
            item['frame'].config(bg=bg, relief='solid' if selected else 'flat', bd=2)
            item['thumb'].config(bg=bg)
            item['caption'].config(bg=bg)

    def _scroll_to_selected(self):
        if not self._carousel_items:
            return
        self.carousel_canvas.update_idletasks()
        frame = self._carousel_items[self.index]['frame']
        total = self.carousel_inner.winfo_height()
        if total <= 0:
            return
        y = frame.winfo_y()
        height = frame.winfo_height()
        view_height = self.carousel_canvas.winfo_height()
        top = self.carousel_canvas.canvasy(0)
        if y < top:
            self.carousel_canvas.yview_moveto(y / total)
        elif y + height > top + view_height:
            self.carousel_canvas.yview_moveto((y + height - view_height) / total)

    def _select(self, idx, focus=True):
        if not self.items:
            return
        self.index = max(0, min(len(self.items) - 1, idx))
        self._highlight_item()
        self._scroll_to_selected()
        self._load_controls_for_current()
        self._schedule_nav_preview()
        self._refresh_info()
        self._update_buttons()
        if focus:
            self.carousel_canvas.focus_set()

    def _load_controls_for_current(self):
        item = self._current_item()
        if item is None:
            return
        self._loading = True
        self.scale_var.set(int(round(item.scale * 100)))
        self.scale_label.config(text=f'{self.scale_var.get()}%')
        self.current_position = item.position
        self._highlight_position(self.current_position)
        self._loading = False

    def _ensure_base(self, item: ImageItem) -> Image.Image:
        if item.base_preview is None:
            item.base_preview = core.load_thumbnail(item.path, (PREVIEW_MAX, PREVIEW_MAX))
        return item.base_preview

    def _ensure_preview(self, item: ImageItem) -> Image.Image:
        key = (item.position, item.scale)
        if item.preview is not None and item.preview_key == key:
            self._cache.touch(item)
            return item.preview

        base = self._ensure_base(item)
        ratio = 1.0
        if item.width and base.width:
            ratio = min(1.0, base.width / item.width)
        item.preview = core.apply_watermark(
            base, self.watermark_img, item.position, item.scale, shadow_scale=ratio
        ).convert('RGB')
        item.preview_key = key
        self._cache.touch(item)
        return item.preview

    def _invalidate_preview(self, item: ImageItem):
        item.drop_composite()

    def _nav(self, delta):
        if self.state != 'working':
            return 'break'
        self._select(self.index + delta)
        return 'break'

    def _move_selected(self, delta):
        if self.state != 'working':
            return 'break'
        target = self.index + delta
        if target < 0 or target >= len(self.items):
            return 'break'
        self.items[self.index], self.items[target] = self.items[target], self.items[self.index]
        self.index = target
        self._build_carousel_items()
        self._scroll_to_selected()
        self._refresh_info()
        self._update_buttons()
        self.carousel_canvas.focus_set()
        return 'break'

    def _on_delete_key(self, _event):
        if self.state != 'working' or self._modal_open:
            return None
        self._discard_selected()
        return 'break'

    def _on_undo_key(self, _event):
        if self.state != 'working' or self._modal_open:
            return None
        self._undo_discard()
        return 'break'

    def _discard_selected(self):
        if self.state != 'working' or not self.items:
            return
        idx = self.index
        item = self.items[idx]
        self._discarded_stack.append((idx, item))
        del self.items[idx]
        self._cache.remove(item)
        self._build_carousel_items()

        if self.items:
            self._select(min(idx, len(self.items) - 1))
            self._set_status(f'Descartada: {item.path.name}  (Ctrl+Z para deshacer)')
        else:
            self.index = 0
            self._render_preview()
            self._set_status('No quedan imágenes. Ctrl+Z para deshacer o Cancelar.', error=True)
        self._update_buttons()

    def _undo_discard(self):
        if self.state != 'working' or not self._discarded_stack:
            return
        idx, item = self._discarded_stack.pop()
        idx = max(0, min(idx, len(self.items)))
        self.items.insert(idx, item)
        self._build_carousel_items()
        self._select(idx)

    def _on_start(self):
        src = self.src_var.get().strip()
        wm = self.wm_var.get().strip()
        dest = self.dest_var.get().strip()

        src_path = Path(src).resolve() if src else None
        wm_path = Path(wm).resolve() if wm else None

        if not src_path or not src_path.is_dir():
            return self._set_status('Elegí una carpeta de origen válida.', error=True)
        if not wm_path or not wm_path.is_file():
            return self._set_status('Elegí un archivo PNG de marca de agua válido.', error=True)

        dest_dir = Path(dest).resolve() if dest else core.default_output_dir(src_path)
        if dest_dir.exists() and not dest_dir.is_dir():
            return self._set_status('La carpeta destino no es válida.', error=True)

        try:
            self.watermark_img = core.load_watermark(wm_path)
        except Exception as exc:
            return self._set_status(f'No se pudo abrir la marca de agua: {exc}', error=True)

        images = core.iter_supported_images(src_path)
        if not images:
            return self._set_status(
                f'No hay imágenes compatibles en {src_path.name}. '
                f'Extensiones: {", ".join(sorted(core.SUPPORTED_EXTENSIONS))}',
                error=True,
            )

        self.dest_dir = dest_dir
        default_position = self.current_position
        default_scale = self._scale()
        items = []
        for path in images:
            try:
                with Image.open(path) as img:
                    width, height = img.size
            except Exception:
                width, height = 0, 0
            items.append(ImageItem(
                path=path, position=default_position, scale=default_scale,
                width=width, height=height,
            ))
        self.items = items
        self.index = 0
        self._cache.clear()
        self._photo = None
        self._photo_source = None
        self._photo_size = None
        self.started = True
        self.writing = False
        self._cancel_requested = False
        self._discarded_stack = []

        self._load_thumbnails()
        self._build_carousel_items()
        self.state = 'working'
        self._set_ui_state('working')
        self._select(0)
        self._cancel_timers()
        self._load_current_image()
        self._set_status(
            f'{len(self.items)} imagen(es). Reordená con Ctrl+↑/↓ o los botones, '
            'y escribí todo cuando estés listo.',
        )

    def _load_current_image(self):
        self._nav_after_id = None
        item = self._current_item()
        if item is None or self.watermark_img is None:
            self._render_preview()
            return
        try:
            self._ensure_preview(item)
        except Exception as exc:
            item.preview = None
            self._set_status(f'Error al aplicar la marca: {exc}', error=True)
        self._render_preview()

    def _rebuild_composite(self):
        item = self._current_item()
        if item is None or self.watermark_img is None:
            self._render_preview()
            return
        self._invalidate_preview(item)
        try:
            self._ensure_preview(item)
        except Exception as exc:
            item.preview = None
            self._set_status(f'Error al aplicar la marca: {exc}', error=True)
        self._render_preview()

    def _render_preview(self):
        self.canvas.delete('all')
        item = self._current_item()
        preview = item.preview if item is not None else None
        if preview is None:
            w = self.canvas.winfo_width()
            h = self.canvas.winfo_height()
            if w > 1 and h > 1:
                self.canvas.create_text(
                    w // 2, h // 2, text='Sin preview', fill='#777777', font=('', 12)
                )
            return

        box_w = max(self.canvas.winfo_width(), 200)
        box_h = max(self.canvas.winfo_height(), 200)

        if self._photo_source is not preview or self._photo_size != (box_w, box_h):
            img = preview
            ratio = min(box_w / img.width, box_h / img.height, 1.0)
            if ratio < 1.0:
                new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self._photo_source = preview
            self._photo_size = (box_w, box_h)

        self.canvas.create_image(box_w // 2, box_h // 2, image=self._photo)

    def _refresh_info(self):
        item = self._current_item()
        if item is None:
            self.filename_var.set('—')
            self.counter_var.set('')
            return
        self.counter_var.set(f'Imagen {self.index + 1}/{len(self.items)}')
        self.filename_var.set(core.output_filename(item.path, self.index + 1))

    def _write_all(self):
        if self.state != 'working' or not self.items:
            return

        self._modal_open = True
        confirmed = messagebox.askyesno(
            'Aplicar y escribir todo',
            f'Se van a escribir {len(self.items)} imagen(es) en:\n{self.dest_dir}\n\n¿Continuar?',
        )
        self._modal_open = False
        self.carousel_canvas.focus_set()
        if not confirmed:
            return

        self.writing = True
        self._cancel_requested = False
        self.state = 'writing'
        self._set_ui_state('writing')
        self._set_status(f'Escribiendo en {self.dest_dir}…')

        try:
            self.dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._set_status(f'No se pudo crear la carpeta destino: {exc}', error=True)
            self._reset_session('done')
            return

        self.progress.grid()
        self.progress['maximum'] = len(self.items)
        self.progress['value'] = 0
        ok = 0
        errors = []

        for i, item in enumerate(self.items):
            if self._cancel_requested:
                break
            try:
                base = core.load_image(item.path)
                comp = core.apply_watermark(base, self.watermark_img, item.position, item.scale)
                name = core.output_filename(item.path, i + 1)
                core.save_image(comp, self.dest_dir / name)
                ok += 1
            except Exception as exc:
                errors.append(f'{item.path.name}: {exc}')
            self.progress['value'] = i + 1
            self.root.update()

        cancelled = self._cancel_requested
        self._cancel_requested = False
        self._reset_session('idle' if cancelled else 'done')

        if cancelled:
            self._set_status(f'Cancelado: se escribieron {ok} imagen(es).', error=True)
            return

        if errors:
            self._set_status(
                f'{ok} escritas en {self.dest_dir}. Errores: ' + ' | '.join(errors), error=True
            )
        else:
            self._set_status(
                f'¡Listo! {ok} imagen(es) escritas en {self.dest_dir}. '
                'Presioná Nueva sesión para empezar de nuevo.'
            )

    def _on_cancel(self):
        if self.state == 'working':
            self._reset_session('idle')
            self._set_status('Operación cancelada. Elegí otra carpeta/archivo.')
        elif self.state == 'writing':
            self._cancel_requested = True
            self._set_status('Cancelando…')

    def _reset_session(self, state):
        self.writing = False
        self.started = False
        self.progress.grid_remove()
        self.items = []
        self.index = 0
        self._cache.clear()
        self._photo = None
        self._photo_source = None
        self._photo_size = None
        self._discarded_stack = []
        self._build_carousel_items()
        self.filename_var.set('—')
        self.counter_var.set('')
        self._render_preview()
        self.state = state
        self._set_ui_state(state)

    def _set_ui_state(self, state):
        self.state = state
        nav_on = state == 'working'
        config_on = state in ('idle', 'done')

        self._cancel_timers()

        for widget in self.config_widgets:
            widget.config(state='normal' if config_on else 'disabled')

        for btn in self.position_buttons.values():
            btn.config(state='normal' if nav_on else 'disabled')

        for widget in self.scale_controls:
            widget.config(state='normal' if nav_on else 'disabled')

        if state == 'done':
            self.start_btn.config(text='Nueva sesión', state='normal', command=self._on_start)
        elif state in ('working', 'writing'):
            self.start_btn.config(text='Cancelar', state='normal', command=self._on_cancel)
        else:
            self.start_btn.config(text='Comenzar', state='normal', command=self._on_start)

        self._btn_bg = self._btn_bg or self.position_buttons['bottom-right'].cget('background')
        self._btn_fg = self._btn_fg or self.position_buttons['bottom-right'].cget('foreground')
        self._highlight_position(self.current_position)
        self._highlight_item()
        self._update_buttons()

    def _update_buttons(self):
        working = self.state == 'working'
        has_images = bool(self.items)
        self.up_btn.config(state='normal' if working and self.index > 0 else 'disabled')
        self.down_btn.config(
            state='normal' if working and self.index < len(self.items) - 1 else 'disabled'
        )
        self.discard_btn.config(state='normal' if working and has_images else 'disabled')
        self.write_btn.config(state='normal' if working and has_images else 'disabled')

    def _set_status(self, text, error=False):
        self.status_var.set(text)
        self._status_label.config(fg='#c62828' if error else '#333333')

    def run(self):
        self.root.mainloop()


def run_gui():
    hidpi.enable_dpi_awareness()
    root = tk.Tk()
    hidpi.apply_scaling(root)
    WatermarkApp(root)
    root.mainloop()
