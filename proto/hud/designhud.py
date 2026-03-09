import json
import tkinter as tk
from tkinter import ttk
from tkinter import colorchooser
from pathlib import Path
import numpy as np
import cv2
from PIL import Image, ImageTk, ImageFont, ImageDraw
import math
try:
    from .base import HudPanel
except ImportError:
    from base import HudPanel

def _hex_points(cx, cy, r):
    pts = []
    for i in range(6):
        a = math.radians(60 * i + 30)
        px = int(cx + r * math.cos(a))
        py = int(cy + r * math.sin(a))
        pts.append([px, py])
    return np.array(pts, np.int32).reshape((-1, 1, 2))

def _draw_text_bgr(frame, text, pos, font_path, size_px, color_bgr, bold=False):
    if font_path:
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            draw = ImageDraw.Draw(img)
            f = ImageFont.truetype(font_path, max(8, int(size_px)))
            color_rgb = (int(color_bgr[2]), int(color_bgr[1]), int(color_bgr[0]))
            x, y = pos
            if bold:
                draw.text((x+1, y+1), text, fill=color_rgb, font=f)
            draw.text((x, y), text, fill=color_rgb, font=f)
            frame[:] = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
            return
        except Exception:
            pass
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.3, size_px / 24.0)
    thickness = max(1, int(scale * (3 if bold else 1.6)))
    cv2.putText(frame, text, pos, font, scale, color_bgr, thickness, cv2.LINE_AA)

def _measure_text(text, font_path, size_px, thickness_hint=1):
    if font_path:
        try:
            # Use PIL to get precise bbox
            f = ImageFont.truetype(font_path, max(8, int(size_px)))
            dummy_img = Image.new("RGB", (10, 10))
            draw = ImageDraw.Draw(dummy_img)
            bbox = draw.textbbox((0, 0), text, font=f)
            tw = int(bbox[2] - bbox[0])
            th = int(bbox[3] - bbox[1])
            return tw, th
        except Exception:
            pass
    # Fallback to OpenCV metrics
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.3, size_px / 24.0)
    thickness = max(1, int(scale * (2.0 if thickness_hint >= 2 else 1.6)))
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    return int(tw), int(th)

def _draw_corner_box(frame, bbox, color=(0, 255, 255), thickness=2, corner_len=16):
    x1, y1, x2, y2 = bbox
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    cl = int(corner_len)
    # Top-left
    cv2.line(frame, (x1, y1), (x1 + cl, y1), color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x1, y1), (x1, y1 + cl), color, thickness, cv2.LINE_AA)
    # Top-right
    cv2.line(frame, (x2, y1), (x2 - cl, y1), color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x2, y1), (x2, y1 + cl), color, thickness, cv2.LINE_AA)
    # Bottom-left
    cv2.line(frame, (x1, y2), (x1 + cl, y2), color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x1, y2), (x1, y2 - cl), color, thickness, cv2.LINE_AA)
    # Bottom-right
    cv2.line(frame, (x2, y2), (x2 - cl, y2), color, thickness, cv2.LINE_AA)
    cv2.line(frame, (x2, y2), (x2, y2 - cl), color, thickness, cv2.LINE_AA)

def draw_design(frame, rect, design):
    x, y, w, h = rect
    if w < 10 or h < 10:
        return {}
    font_path = design.get("font_path")
    title = design.get("title", {})
    digital = design.get("digital", {})
    hex_conf = design.get("hex", {})
    title_text = str(title.get("text", "TITLE"))
    digital_text = str(digital.get("text", "123"))
    title_color = tuple(title.get("color", [255, 255, 255]))
    digital_color = tuple(digital.get("color", [255, 255, 255]))
    title_bold = bool(title.get("bold", False))
    digital_bold = bool(digital.get("bold", False))
    title_size_mult = float(title.get("size_mult", 1.0))
    digital_size_mult = float(digital.get("size_mult", 1.0))
    border_color = tuple(hex_conf.get("border_color", [255, 255, 255]))
    fill_colors = hex_conf.get("fill_colors", [[200, 200, 200], [200, 200, 200], [200, 200, 200]])
    fill_colors = [tuple(c) for c in fill_colors]
    radius_ratio = float(hex_conf.get("radius_ratio", 0.18))
    spacing_ratio = float(hex_conf.get("spacing_ratio", 0.35))
    y_offset_ratio = float(hex_conf.get("y_offset_ratio", 0.0))
    r = int(min(w, h) * radius_ratio)
    cx = x + w // 2
    cy = y + h // 2
    if isinstance(hex_conf.get("positions"), list) and len(hex_conf["positions"]) == 3:
        centers = []
        for nx, ny in hex_conf["positions"]:
            centers.append((int(x + nx * w), int(y + ny * h)))
    else:
        cy2 = y + h // 2 + int(h * y_offset_ratio)
        dist = int(min(w, h) * spacing_ratio)
        centers = [(cx - dist, cy2), (cx, cy2), (cx + dist, cy2)]
    for i, c in enumerate(centers):
        pts = _hex_points(c[0], c[1], r)
        overlay = frame.copy()
        cv2.fillPoly(overlay, [pts], fill_colors[i % 3])
        cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)
        cv2.polylines(frame, [pts], True, border_color, 2, cv2.LINE_AA)
    title_size = int(h * 0.06 * title_size_mult)
    digital_size = int(h * 0.12 * digital_size_mult)
    is_pil = bool(font_path)
    tw_title, th_title = _measure_text(title_text, font_path, title_size, thickness_hint=1)
    if isinstance(title.get("pos"), (list, tuple)) and len(title["pos"]) == 2:
        tnx, tny = title["pos"]
        tx = int(x + tnx * w)
        ty = int(y + tny * h)
    else:
        tx = x + 20
        ty = y + 20
    _draw_text_bgr(frame, title_text, (tx, ty if is_pil else ty + th_title), font_path, title_size, title_color, title_bold)
    tw_dig, th_dig = _measure_text(digital_text, font_path, digital_size, thickness_hint=2)
    if isinstance(digital.get("pos"), (list, tuple)) and len(digital["pos"]) == 2:
        dnx, dny = digital["pos"]
        dx = int(x + dnx * w)
        dy = int(y + dny * h)
    else:
        dx = x + w - tw_dig - 20
        dy = y + 20
    _draw_text_bgr(frame, digital_text, (dx, dy if is_pil else dy + th_dig), font_path, digital_size, digital_color, digital_bold)
    layout = {
        "title_bbox": (tx, ty, tx + max(1, tw_title), ty + max(1, th_title)),
        "digital_bbox": (dx, dy, dx + max(1, tw_dig), dy + max(1, th_dig)),
        "hex_centers": centers,
        "hex_radius": r,
        "rect": rect
    }
    return layout

def save_design(path, design):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(design, f, ensure_ascii=False, indent=2)

def load_design(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

class DesignHUDPanel(HudPanel):
    def _draw_impl(self, frame, data_context):
        rect = data_context.get("rect", (0, 0, frame.shape[1], frame.shape[0]))
        design = data_context.get("design")
        if not design and data_context.get("design_file_path"):
            try:
                design = load_design(data_context.get("design_file_path"))
            except Exception:
                design = None
        if not design:
            design = {
                "title": {"text": "TITLE", "color": [255, 255, 255], "bold": False, "size_mult": 1.0},
                "digital": {"text": "123", "color": [255, 255, 255], "bold": True, "size_mult": 1.0},
                "font_path": None,
                "hex": {
                    "radius_ratio": 0.18,
                    "fill_colors": [[200, 200, 200], [200, 200, 200], [200, 200, 200]],
                    "border_color": [255, 255, 255],
                    "spacing_ratio": 0.35,
                    "y_offset_ratio": 0.0
                }
            }
        draw_design(frame, rect, design)

class DesignerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Design HUD")
        self.frame_w = 1280
        self.frame_h = 720
        self.bg_color = (32, 32, 32)
        self.design = {
            "title": {"text": "TITLE", "color": [255, 255, 255], "bold": False, "size_mult": 1.0},
            "digital": {"text": "123", "color": [255, 255, 255], "bold": True, "size_mult": 1.0},
            "font_path": None,
            "hex": {
                "radius_ratio": 0.18,
                "fill_colors": [[200, 200, 200], [200, 200, 200], [200, 200, 200]],
                "border_color": [255, 255, 255],
                "spacing_ratio": 0.35,
                "y_offset_ratio": 0.0
            }
        }
        self._build_ui()
        self._update_preview()

    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(top, text="Title").pack(side=tk.LEFT)
        self.title_entry = ttk.Entry(top)
        self.title_entry.insert(0, self.design["title"]["text"])
        self.title_entry.pack(side=tk.LEFT, padx=6)
        self.title_color_btn = ttk.Button(top, text="Title Color", command=lambda: self._pick_color("title"))
        self.title_color_btn.pack(side=tk.LEFT, padx=6)
        self.title_bold_var = tk.BooleanVar(value=self.design["title"]["bold"])
        ttk.Checkbutton(top, text="Bold", variable=self.title_bold_var, command=self._on_change).pack(side=tk.LEFT, padx=6)
        ttk.Label(top, text="Title Size").pack(side=tk.LEFT, padx=6)
        self.title_size = tk.DoubleVar(value=self.design["title"]["size_mult"])
        ttk.Scale(top, from_=0.3, to=3.0, orient=tk.HORIZONTAL, variable=self.title_size, command=lambda v: self._on_change()).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        mid = ttk.Frame(self.root)
        mid.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(mid, text="Digital").pack(side=tk.LEFT)
        self.digital_entry = ttk.Entry(mid)
        self.digital_entry.insert(0, self.design["digital"]["text"])
        self.digital_entry.pack(side=tk.LEFT, padx=6)
        self.digital_color_btn = ttk.Button(mid, text="Digital Color", command=lambda: self._pick_color("digital"))
        self.digital_color_btn.pack(side=tk.LEFT, padx=6)
        self.digital_bold_var = tk.BooleanVar(value=self.design["digital"]["bold"])
        ttk.Checkbutton(mid, text="Bold", variable=self.digital_bold_var, command=self._on_change).pack(side=tk.LEFT, padx=6)
        ttk.Label(mid, text="Digital Size").pack(side=tk.LEFT, padx=6)
        self.digital_size = tk.DoubleVar(value=self.design["digital"]["size_mult"])
        ttk.Scale(mid, from_=0.3, to=3.0, orient=tk.HORIZONTAL, variable=self.digital_size, command=lambda v: self._on_change()).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        font_frame = ttk.Frame(self.root)
        font_frame.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(font_frame, text="系统字体").pack(side=tk.LEFT)
        self.font_combo = ttk.Combobox(font_frame, state="readonly")
        self.font_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.font_map = self._list_system_fonts()
        self.font_combo['values'] = list(self.font_map.keys())
        if self.font_combo['values']:
            self.font_combo.current(0)
        self.font_combo.bind('<<ComboboxSelected>>', lambda e: self._apply_selected_font(self.font_combo.get()))
        hex_frame = ttk.LabelFrame(self.root, text="Hexagon")
        hex_frame.pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(hex_frame, text="Radius").pack(side=tk.LEFT)
        self.hex_radius = tk.DoubleVar(value=self.design["hex"]["radius_ratio"])
        ttk.Scale(hex_frame, from_=0.05, to=0.4, orient=tk.HORIZONTAL, variable=self.hex_radius, command=lambda v: self._on_change()).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Label(hex_frame, text="Spacing").pack(side=tk.LEFT)
        self.hex_spacing = tk.DoubleVar(value=self.design["hex"]["spacing_ratio"])
        ttk.Scale(hex_frame, from_=0.1, to=0.6, orient=tk.HORIZONTAL, variable=self.hex_spacing, command=lambda v: self._on_change()).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        ttk.Label(hex_frame, text="Vertical Offset").pack(side=tk.LEFT)
        self.hex_yoff = tk.DoubleVar(value=self.design["hex"]["y_offset_ratio"])
        ttk.Scale(hex_frame, from_=-0.4, to=0.4, orient=tk.HORIZONTAL, variable=self.hex_yoff, command=lambda v: self._on_change()).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=6)
        self.hex_color_btns = []
        for i in range(3):
            b = ttk.Button(hex_frame, text=f"Hex {i+1} Color", command=lambda idx=i: self._pick_hex_color(idx))
            b.pack(side=tk.LEFT, padx=6)
            self.hex_color_btns.append(b)
        ttk.Label(hex_frame, text="Border").pack(side=tk.LEFT)
        self.hex_border_btn = ttk.Button(hex_frame, text="Border Color", command=lambda: self._pick_hex_border())
        self.hex_border_btn.pack(side=tk.LEFT, padx=6)
        bottom = ttk.Frame(self.root)
        bottom.pack(fill=tk.X, padx=8, pady=6)
        ttk.Button(bottom, text="Save JSON", command=self._save_json).pack(side=tk.LEFT, padx=6)
        ttk.Button(bottom, text="Load JSON", command=self._load_json).pack(side=tk.LEFT, padx=6)
        self.canvas = tk.Canvas(self.root, bg="black")
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        self.canvas.bind("<Configure>", lambda e: self._update_preview())
        self.title_entry.bind("<KeyRelease>", lambda e: self._on_change())
        self.digital_entry.bind("<KeyRelease>", lambda e: self._on_change())
        if self.font_combo['values']:
            self._apply_selected_font(self.font_combo.get())

    def _pick_color(self, which):
        c = colorchooser.askcolor(title="Pick Color")
        if not c or not c[0]:
            return
        rgb = [int(c[0][0]), int(c[0][1]), int(c[0][2])]
        self.design[which]["color"] = rgb
        self._on_change()

    def _pick_hex_color(self, idx):
        c = colorchooser.askcolor(title=f"Pick Hex {idx+1} Color")
        if not c or not c[0]:
            return
        rgb = [int(c[0][0]), int(c[0][1]), int(c[0][2])]
        self.design["hex"]["fill_colors"][idx] = rgb
        self._on_change()

    def _pick_hex_border(self):
        c = colorchooser.askcolor(title="Pick Border Color")
        if not c or not c[0]:
            return
        rgb = [int(c[0][0]), int(c[0][1]), int(c[0][2])]
        self.design["hex"]["border_color"] = rgb
        self._on_change()

    def _on_change(self):
        self.design["title"]["text"] = self.title_entry.get()
        self.design["title"]["bold"] = bool(self.title_bold_var.get())
        self.design["title"]["size_mult"] = float(self.title_size.get())
        self.design["digital"]["text"] = self.digital_entry.get()
        self.design["digital"]["bold"] = bool(self.digital_bold_var.get())
        self.design["digital"]["size_mult"] = float(self.digital_size.get())
        self.design["hex"]["radius_ratio"] = float(self.hex_radius.get())
        self.design["hex"]["spacing_ratio"] = float(self.hex_spacing.get())
        self.design["hex"]["y_offset_ratio"] = float(self.hex_yoff.get())
        self._update_preview()

    def _update_preview(self):
        cw = self.canvas.winfo_width() or 800
        ch = self.canvas.winfo_height() or 450
        frame = np.full((self.frame_h, self.frame_w, 3), self.bg_color, dtype=np.uint8)
        rect = (40, 40, self.frame_w - 80, self.frame_h - 80)
        self.last_layout = draw_design(frame, rect, self.design)
        # Selection overlay
        sel = getattr(self, "selected_target", None)
        if sel and self.last_layout:
            if sel == "title":
                _draw_corner_box(frame, self.last_layout["title_bbox"], (0, 255, 255), 2, 20)
            elif sel == "digital":
                _draw_corner_box(frame, self.last_layout["digital_bbox"], (0, 255, 255), 2, 20)
            elif sel.startswith("hex_"):
                idx = int(sel.split("_")[1])
                centers = self.last_layout.get("hex_centers", [])
                r = int(self.last_layout.get("hex_radius", 0))
                if 0 <= idx < len(centers) and r > 0:
                    cx, cy = centers[idx]
                    pts = _hex_points(cx, cy, r)
                    xs = [p[0][0] for p in pts]
                    ys = [p[0][1] for p in pts]
                    bbox = (min(xs), min(ys), max(xs), max(ys))
                    _draw_corner_box(frame, bbox, (0, 255, 255), 2, 20)
        scale = min(cw / self.frame_w, ch / self.frame_h)
        new_w = max(1, int(self.frame_w * scale))
        new_h = max(1, int(self.frame_h * scale))
        resized = cv2.resize(frame, (new_w, new_h))
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(rgb)
        self.photo = ImageTk.PhotoImage(image=img)
        self.canvas.delete("all")
        self.view_x = (cw - new_w) // 2
        self.view_y = (ch - new_h) // 2
        self.view_scale = scale
        self.canvas.create_image(self.view_x, self.view_y, anchor=tk.NW, image=self.photo)
        if not hasattr(self, "drag_target"):
            self.drag_target = None
        self.canvas.bind("<Button-1>", self._on_mouse_down)
        self.canvas.bind("<B1-Motion>", self._on_mouse_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_mouse_up)

    def _save_json(self):
        p = Path.home() / "designhud.json"
        save_design(str(p), self.design)

    def _load_json(self):
        p = Path.home() / "designhud.json"
        if p.exists():
            d = load_design(str(p))
            self.design = d
            self.title_entry.delete(0, tk.END)
            self.title_entry.insert(0, self.design["title"].get("text", ""))
            self.title_bold_var.set(bool(self.design["title"].get("bold", False)))
            self.title_size.set(float(self.design["title"].get("size_mult", 1.0)))
            self.digital_entry.delete(0, tk.END)
            self.digital_entry.insert(0, self.design["digital"].get("text", ""))
            self.digital_bold_var.set(bool(self.design["digital"].get("bold", False)))
            self.digital_size.set(float(self.design["digital"].get("size_mult", 1.0)))
            fp = self.design.get("font_path")
            if fp:
                name = Path(fp).stem
                if name in self.font_map:
                    idx = list(self.font_map.keys()).index(name)
                    self.font_combo.current(idx)
                    self._apply_selected_font(name)
            self.hex_radius.set(float(self.design["hex"].get("radius_ratio", 0.18)))
            self.hex_spacing.set(float(self.design["hex"].get("spacing_ratio", 0.35)))
            self.hex_yoff.set(float(self.design["hex"].get("y_offset_ratio", 0.0)))
            self._update_preview()
    
    def _list_system_fonts(self):
        paths = [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path.home() / "Library" / "Fonts"
        ]
        font_map = {}
        exts = {".ttf", ".otf", ".ttc"}
        for p in paths:
            if p.exists():
                for fp in p.glob("**/*"):
                    if fp.is_file() and fp.suffix.lower() in exts:
                        name = fp.stem
                        if name not in font_map:
                            font_map[name] = str(fp)
        return font_map
    
    def _apply_selected_font(self, display_name):
        path = self.font_map.get(display_name)
        if not path:
            return
        self.design["font_path"] = path
        self._update_preview()
    
    def _canvas_to_frame(self, x, y):
        fx = (x - self.view_x) / (self.view_scale or 1.0)
        fy = (y - self.view_y) / (self.view_scale or 1.0)
        return int(fx), int(fy)
    
    def _on_mouse_down(self, event):
        fx, fy = self._canvas_to_frame(event.x, event.y)
        if not self.last_layout:
            return
        tx1, ty1, tx2, ty2 = self.last_layout["title_bbox"]
        dx1, dy1, dx2, dy2 = self.last_layout["digital_bbox"]
        if tx1 <= fx <= tx2 and ty1 <= fy <= ty2:
            self.drag_target = ("title", fx - tx1, fy - ty1)
            self.selected_target = "title"
            return
        if dx1 <= fx <= dx2 and dy1 <= fy <= dy2:
            self.drag_target = ("digital", fx - dx1, fy - dy1)
            self.selected_target = "digital"
            return
        centers = self.last_layout["hex_centers"]
        r = self.last_layout["hex_radius"]
        for i, (cx, cy) in enumerate(centers):
            if (fx - cx) ** 2 + (fy - cy) ** 2 <= (r + 10) ** 2:
                self.drag_target = (f"hex_{i}", fx - cx, fy - cy)
                self.selected_target = f"hex_{i}"
                return
        self.drag_target = None
        self.selected_target = None
    
    def _on_mouse_drag(self, event):
        if not self.drag_target:
            return
        fx, fy = self._canvas_to_frame(event.x, event.y)
        name, ox, oy = self.drag_target
        rect = self.last_layout["rect"]
        rx, ry, rw, rh = rect
        nx = max(0.0, min(1.0, (fx - ox - rx) / rw))
        ny = max(0.0, min(1.0, (fy - oy - ry) / rh))
        if name == "title":
            self.design.setdefault("title", {})["pos"] = [nx, ny]
        elif name == "digital":
            self.design.setdefault("digital", {})["pos"] = [nx, ny]
        else:
            idx = int(name.split("_")[1])
            pos_list = self.design.setdefault("hex", {}).get("positions")
            if not isinstance(pos_list, list) or len(pos_list) != 3:
                cx = rx + rw // 2
                cy = ry + rh // 2
                dist = int(min(rw, rh) * float(self.design["hex"].get("spacing_ratio", 0.35)))
                pos_list = [
                    [(cx - dist - rx) / rw, (cy - ry) / rh],
                    [(cx - rx) / rw, (cy - ry) / rh],
                    [(cx + dist - rx) / rw, (cy - ry) / rh],
                ]
            pos_list[idx] = [nx, ny]
            self.design["hex"]["positions"] = pos_list
        self._update_preview()
    
    def _on_mouse_up(self, event):
        self.drag_target = None

def run_designer():
    root = tk.Tk()
    DesignerApp(root)
    root.mainloop()

if __name__ == "__main__":
    run_designer()
