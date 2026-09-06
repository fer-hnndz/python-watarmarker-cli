from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

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


class WatermarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Marcador de Agua')
        self.root.geometry('1220x760')
        self.root.minsize(1000, 640)

        self.src_var = tk.StringVar()
        self.wm_var = tk.StringVar()
        self.dest_var = tk.StringVar()
        self.scale_var = tk.IntVar(value=int(core.DEFAULT_SCALE * 100))
        self.correl_var = tk.StringVar(value='0001')
        self.status_var = tk.StringVar(value='Elegí carpeta origen, marca de agua y destino, y presioná Comenzar.')
        self.nextname_var = tk.StringVar(value='')
        self.counter_var = tk.StringVar(value='')

        self.state = 'idle'
        self.started = False
        self.writing = False

        self.image_paths = []
        self.index = 0
        self.decisions = []
        self.used_numbers = set()
        self.current_position = 'bottom-right'

        self.watermark_img = None
        self.base_img = None
        self.composite = None
        self._photo = None
        self._btn_bg = None
        self._btn_fg = None
        self._after_id = None

        self._build_widgets()
        self._bind_keys()
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
        self.minus_btn = tk.Button(
            bar, text='−', width=3, command=self._scale_down, takefocus=0,
        )
        self.minus_btn.grid(row=0, column=1, padx=(4, 2))
        self.scale_slider = tk.Scale(
            bar, from_=SCALE_MIN, to=SCALE_MAX, orient='horizontal', showvalue=False,
            length=150, variable=self.scale_var, command=self._on_scale,
        )
        self.scale_slider.grid(row=0, column=2, padx=2)
        self.plus_btn = tk.Button(
            bar, text='+', width=3, command=self._scale_up, takefocus=0,
        )
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

        side = tk.Frame(body, padx=4, pady=4)
        side.grid(row=0, column=0, sticky='n', pady=6)
        tk.Label(side, text='Posición de la marca', font=('', 10, 'bold')).pack(pady=(0, 6))

        grid = tk.Frame(side)
        grid.pack()

        self.position_buttons = {}
        for pos, (row, col) in POSITION_GRID.items():
            btn = tk.Button(grid, text=POSITION_LABELS[pos], width=8, takefocus=0)
            btn.grid(row=row, column=col, padx=3, pady=3, sticky='ew')
            btn.config(command=lambda p=pos: self._set_position(p))
            self.position_buttons[pos] = btn

        self.canvas = tk.Canvas(body, bg='#232323', highlightthickness=0)
        self.canvas.grid(row=0, column=1, sticky='nsew')
        self.canvas.bind('<Configure>', lambda _e: self._render_preview())

        bottom = tk.Frame(self.root, padx=10, pady=6)
        bottom.grid(row=2, column=0, sticky='ew')
        bottom.columnconfigure(4, weight=1)

        tk.Label(bottom, text='Nº correlativo  (Tab → editar · Enter → confirmar):').grid(
            row=0, column=0
        )
        self.correl_entry = tk.Entry(
            bottom, width=6, justify='center', font=('', 14, 'bold'),
            textvariable=self.correl_var,
        )
        self.correl_entry.grid(row=0, column=1, padx=(6, 4), pady=4)

        self.next_label = tk.Label(bottom, textvariable=self.nextname_var, fg='#2e7d32')
        self.next_label.grid(row=0, column=2, padx=(0, 10))

        tk.Label(bottom, textvariable=self.counter_var).grid(row=0, column=3, padx=(4, 8))

        self.confirm_btn = tk.Button(
            bottom, text='Confirmar (Enter)', command=self._confirm_and_advance,
            takefocus=0, bg='#2e7d32', fg='white', activebackground='#256b2b',
            activeforeground='white', padx=12,
        )
        self.confirm_btn.grid(row=0, column=4, sticky='e', padx=(8, 0))

        self.progress = ttk.Progressbar(self.root, mode='determinate')
        self.progress.grid(row=3, column=0, sticky='ew', padx=10, pady=(2, 8))
        self.progress.grid_remove()

    def _add_path_row(self, parent, row, label, var, command):
        tk.Label(parent, text=label).grid(row=row, column=0, sticky='w', pady=2)
        entry = tk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        btn = tk.Button(parent, text='…', width=3, command=command, takefocus=0)
        btn.grid(row=row, column=2, padx=(0, 4))
        self.config_widgets.extend([entry, btn])

    def _bind_keys(self):
        self.root.bind_all('<Tab>', self._on_tab)
        self.root.bind_all('<Return>', self._on_return)

    def _on_tab(self, _event):
        if self.state == 'working':
            self._focus_correl()
            return 'break'
        return None

    def _on_return(self, _event):
        if self.state == 'working':
            self._confirm_and_advance()
        return 'break'

    def _focus_correl(self):
        self.correl_entry.focus_set()
        self.correl_entry.select_range(0, 'end')

    def _on_scale(self, _value=None):
        self.scale_label.config(text=f'{self.scale_var.get()}%')
        self._schedule_preview()

    def _scale_down(self):
        self._set_scale_value(self.scale_var.get() - SCALE_STEP)

    def _scale_up(self):
        self._set_scale_value(self.scale_var.get() + SCALE_STEP)

    def _set_scale_value(self, value):
        self.scale_var.set(max(SCALE_MIN, min(SCALE_MAX, value)))
        self.scale_label.config(text=f'{self.scale_var.get()}%')
        self._schedule_preview()

    def _schedule_preview(self):
        if self.state != 'working' or self.base_img is None:
            return
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        self._after_id = self.root.after(SCALE_DEBOUNCE_MS, self._apply_scale_preview)

    def _apply_scale_preview(self):
        self._after_id = None
        if self.state == 'working' and self.base_img is not None:
            self._rebuild_composite()

    def _scale(self):
        return self.scale_var.get() / 100

    def _pick_source(self):
        path = filedialog.askdirectory(title='Carpeta con las imágenes')
        if path:
            self.src_var.set(path)
            if not self.dest_var.get().strip():
                self.dest_var.set(str(core.default_output_dir(Path(path))))

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
        if self.state == 'working' and self.base_img is not None:
            self._rebuild_composite()
        self.root.focus_set()

    def _highlight_position(self, position):
        for pos, btn in self.position_buttons.items():
            if pos == position:
                btn.config(relief='sunken', bg=ACTIVE_BG, fg='white',
                           activebackground=ACTIVE_BG, activeforeground='white')
            else:
                btn.config(relief='raised', bg=self._btn_bg, fg=self._btn_fg,
                           activebackground=self._btn_bg, activeforeground=self._btn_fg)

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
        self.image_paths = images
        self.index = 0
        self.decisions = []
        self.used_numbers = set()
        self._set_correl(1)
        self.started = True
        self.writing = False
        self.state = 'working'
        self._set_ui_state('working')
        self._load_current_image()
        self._set_status(
            f'{len(images)} imagen(es) listas. Elegí la posición y confirmá con Enter.',
        )
        self.root.focus_set()

    def _set_correl(self, number):
        self.correl_var.set(f'{number:04d}')

    def _load_current_image(self):
        path = self.image_paths[self.index]
        try:
            self.base_img = core.load_image(path)
        except Exception as exc:
            self.base_img = None
            self.composite = None
            self._set_status(f'No se pudo abrir {path.name}: {exc}', error=True)
        self._rebuild_composite()
        self._refresh_info()

    def _rebuild_composite(self):
        if self.base_img is not None and self.watermark_img is not None:
            try:
                self.composite = core.apply_watermark(
                    self.base_img, self.watermark_img, self.current_position, self._scale()
                )
            except Exception as exc:
                self.composite = None
                self._set_status(f'Error al aplicar la marca: {exc}', error=True)
        self._render_preview()

    def _render_preview(self):
        self.canvas.delete('all')
        if self.composite is None:
            w = self.canvas.winfo_width()
            h = self.canvas.winfo_height()
            if w > 1 and h > 1:
                self.canvas.create_text(
                    w // 2, h // 2, text='Sin preview', fill='#777777', font=('', 12)
                )
            return

        box_w = max(self.canvas.winfo_width(), 200)
        box_h = max(self.canvas.winfo_height(), 200)
        img = self.composite.convert('RGB')
        ratio = min(box_w / img.width, box_h / img.height, 1.0)
        if ratio < 1.0:
            new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
            img = img.resize(new_size, Image.Resampling.LANCZOS)

        self._photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(box_w // 2, box_h // 2, image=self._photo)

    def _refresh_info(self):
        path = self.image_paths[self.index]
        self.counter_var.set(f'Imagen {self.index + 1}/{len(self.image_paths)}')
        try:
            number = int(self.correl_var.get().strip() or 0)
        except ValueError:
            number = 0
        self.nextname_var.set(f'→ {core.output_filename(path, number)}')

    def _confirm_and_advance(self):
        if self.state != 'working':
            return

        raw = self.correl_var.get().strip()
        try:
            number = int(raw)
        except ValueError:
            self._set_status(f"'{raw}' no es un número válido.", error=True)
            self._focus_correl()
            return
        if number < 0:
            self._set_status('El número correlativo no puede ser negativo.', error=True)
            self._focus_correl()
            return
        if number in self.used_numbers:
            self._set_status(
                f'El número {number:04d} ya se usó para otra imagen. Ingresá otro.', error=True
            )
            self._focus_correl()
            return

        path = self.image_paths[self.index]
        self.decisions.append({
            'path': path,
            'position': self.current_position,
            'number': number,
            'scale': self._scale(),
        })
        self.used_numbers.add(number)

        if self.index == len(self.image_paths) - 1:
            self._write_all()
            return

        self.index += 1
        self._set_correl(number + 1)
        self._load_current_image()
        self._set_status(
            f'Imagen {self.index + 1}/{len(self.image_paths)} lista. Enter para confirmar.'
        )
        self.root.focus_set()

    def _write_all(self):
        self.writing = True
        self.state = 'writing'
        self._set_ui_state('writing')
        self._set_status(f'Escribiendo en {self.dest_dir}…')

        try:
            self.dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._set_status(f'No se pudo crear la carpeta destino: {exc}', error=True)
            self._reset_after_write()
            return

        self.progress.grid()
        self.progress['maximum'] = len(self.decisions)
        self.progress['value'] = 0
        ok = 0
        errors = []

        for i, decision in enumerate(self.decisions):
            try:
                base = core.load_image(decision['path'])
                comp = core.apply_watermark(
                    base, self.watermark_img, decision['position'], decision['scale']
                )
                name = core.output_filename(decision['path'], decision['number'])
                core.save_image(comp, self.dest_dir / name)
                ok += 1
            except Exception as exc:
                errors.append(f"{decision['path'].name}: {exc}")
            self.progress['value'] = i + 1
            self.root.update_idletasks()

        self._reset_after_write()

        if errors:
            self._set_status(
                f'{ok} escritas en {self.dest_dir}. Errores: ' + ' | '.join(errors), error=True
            )
        else:
            self._set_status(
                f'¡Listo! {ok} imagen(es) escritas en {self.dest_dir}. '
                'Presioná Nueva sesión para empezar de nuevo.'
            )

    def _reset_after_write(self):
        self.writing = False
        self.started = False
        self.progress.grid_remove()
        self.base_img = None
        self.composite = None
        self.image_paths = []
        self.decisions = []
        self.used_numbers = set()
        self.correl_var.set('0001')
        self.nextname_var.set('')
        self.counter_var.set('')
        self._render_preview()
        self.state = 'done'
        self._set_ui_state('done')

    def _set_ui_state(self, state):
        self.state = state
        nav_on = state == 'working'
        config_on = state in ('idle', 'done')

        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None

        for widget in self.config_widgets:
            widget.config(state='normal' if config_on else 'disabled')

        for btn in self.position_buttons.values():
            btn.config(state='normal' if nav_on else 'disabled')

        for widget in self.scale_controls:
            widget.config(state='normal' if nav_on else 'disabled')

        self.correl_entry.config(state='normal' if nav_on else 'disabled')
        self.confirm_btn.config(state='normal' if nav_on else 'disabled')

        if state == 'done':
            self.start_btn.config(text='Nueva sesión', state='normal')
        elif state == 'writing':
            self.start_btn.config(text='Comenzar', state='disabled')
        else:
            self.start_btn.config(text='Comenzar', state='normal')

        self._btn_bg = self._btn_bg or self.position_buttons['bottom-right'].cget('background')
        self._btn_fg = self._btn_fg or self.position_buttons['bottom-right'].cget('foreground')
        self._highlight_position(self.current_position)

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
