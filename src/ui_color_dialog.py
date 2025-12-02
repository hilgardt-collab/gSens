# /ui_color_dialog.py
import gi
import math
import cairo
import colorsys
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, Gio
from ui_helpers import CustomDialog
from config_manager import config_manager

class ColorChooserDialog(Gtk.Window):
    """
    A unified custom color chooser featuring:
    - Compact 8x8 Stock Color Grid
    - 32 Persistent Custom Color Slots (8x4 Grid)
    - Interactive Saturation/Value Color Map
    - RGBA Sliders & Hex Entry
    """
    _instance = None

    def __new__(cls, parent=None):
        if cls._instance is None:
            cls._instance = super(ColorChooserDialog, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, parent=None):
        if self._initialized:
            if parent: self.set_transient_for(parent)
            return

        super().__init__(title="Select Color", modal=True)
        if parent: self.set_transient_for(parent)
        # Reduced height to fit content snugly without empty space
        self.set_default_size(650, 380)
        self.set_resizable(False)
        self.set_hide_on_close(True)
        
        self._current_rgba = Gdk.RGBA(1, 1, 1, 1)
        self._current_hsv = (0, 0, 1) # H, S, V
        self._callback_func = None
        self._active_button_ref = None
        self._updating_inputs = False
        
        self._build_ui()
        self._load_custom_colors()
        
        self.connect("close-request", self._on_close_request)
        self._initialized = True

    def present_for_widget(self, widget, current_color_str, callback):
        self._active_button_ref = widget
        self._callback_func = callback
        try:
            rgba = Gdk.RGBA()
            if rgba.parse(current_color_str):
                self._set_color_internal(rgba, update_inputs=True)
        except: pass 
        self.set_transient_for(widget.get_ancestor(Gtk.Window))
        self.present()

    def _on_close_request(self, *args):
        self.hide()
        return True

    def _build_ui(self):
        # Main Horizontal Layout - Reduced padding/spacing
        main_hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12, margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
        self.set_child(main_hbox)

        # --- LEFT COLUMN: PALETTES ---
        left_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        main_hbox.append(left_vbox)

        # Stock Colors
        left_vbox.append(Gtk.Label(label="<b>Stock Colors</b>", use_markup=True, xalign=0))
        
        # Use min_children_per_line=8 to ensure grid shape
        stock_grid = Gtk.FlowBox(max_children_per_line=8, min_children_per_line=8, selection_mode=Gtk.SelectionMode.NONE)
        stock_grid.set_row_spacing(1)
        stock_grid.set_column_spacing(1)
        stock_grid.set_valign(Gtk.Align.START)
        self._add_stock_colors(stock_grid)
        left_vbox.append(stock_grid)
        
        # Custom Colors
        left_vbox.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=8, margin_bottom=8))
        custom_header_box = Gtk.Box(spacing=5)
        custom_header_box.append(Gtk.Label(label="<b>Custom Colors</b>", use_markup=True, xalign=0, hexpand=True))
        save_btn = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save Current Color to Palette")
        save_btn.add_css_class("flat")
        save_btn.connect("clicked", self._on_save_custom_clicked)
        custom_header_box.append(save_btn)
        left_vbox.append(custom_header_box)
        
        self.custom_grid = Gtk.FlowBox(max_children_per_line=8, min_children_per_line=8, selection_mode=Gtk.SelectionMode.NONE)
        self.custom_grid.set_row_spacing(1)
        self.custom_grid.set_column_spacing(1)
        self.custom_grid.set_valign(Gtk.Align.START)
        left_vbox.append(self.custom_grid)

        # --- RIGHT COLUMN: MAP & SLIDERS ---
        right_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        main_hbox.append(right_vbox)

        # Color Map Area
        self.map_area = Gtk.DrawingArea()
        self.map_area.set_size_request(256, 140)
        self.map_area.set_draw_func(self._draw_color_map)
        
        click_gesture = Gtk.GestureClick.new()
        click_gesture.connect("pressed", self._on_map_input)
        drag_gesture = Gtk.GestureDrag.new()
        drag_gesture.connect("drag-update", self._on_map_drag)
        self.map_area.add_controller(click_gesture)
        self.map_area.add_controller(drag_gesture)
        
        map_frame = Gtk.Frame()
        map_frame.set_child(self.map_area)
        right_vbox.append(map_frame)
        
        # Hue Bar
        hue_adj = Gtk.Adjustment(value=0, lower=0, upper=360, step_increment=1, page_increment=10, page_size=0)
        self.hue_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=hue_adj)
        self.hue_scale.set_draw_value(False)
        self.hue_scale.add_css_class("hue-slider")
        self.hue_scale.connect("value-changed", self._on_hue_changed)
        right_vbox.append(self.hue_scale)

        # Sliders
        self.sliders = {}
        grid = Gtk.Grid(row_spacing=4, column_spacing=8)
        right_vbox.append(grid)
        
        for i, channel in enumerate(['Red', 'Green', 'Blue', 'Alpha']):
            label = Gtk.Label(label=f"{channel[0]}:", xalign=1)
            adj = Gtk.Adjustment(value=0, lower=0, upper=255 if channel != 'Alpha' else 100, step_increment=1, page_increment=10)
            scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
            scale.set_hexpand(True)
            scale.set_size_request(140, -1)
            scale.set_draw_value(True)
            scale.set_value_pos(Gtk.PositionType.RIGHT)
            scale.connect("value-changed", self._on_slider_changed, channel)
            
            grid.attach(label, 0, i, 1, 1)
            grid.attach(scale, 1, i, 1, 1)
            self.sliders[channel] = adj

        # Hex & Preview Row
        bottom_row = Gtk.Box(spacing=8)
        right_vbox.append(bottom_row)
        
        # Screen Picker Button
        picker_btn = Gtk.Button(icon_name="color-picker-symbolic", tooltip_text="Pick from Screen")
        picker_btn.connect("clicked", self._on_pick_screen_color)
        bottom_row.append(picker_btn)

        # Preview
        self.preview_area = Gtk.DrawingArea()
        self.preview_area.set_size_request(40, 30)
        self.preview_area.set_draw_func(self._draw_preview)
        frame_prev = Gtk.Frame(); frame_prev.set_child(self.preview_area)
        bottom_row.append(frame_prev)

        # Hex
        self.hex_entry = Gtk.Entry(hexpand=True, placeholder_text="#RRGGBB")
        focus_controller = Gtk.EventControllerFocus()
        focus_controller.connect("leave", lambda c: self._on_hex_entry_changed(self.hex_entry))
        self.hex_entry.add_controller(focus_controller)
        self.hex_entry.connect("activate", self._on_hex_entry_changed)
        bottom_row.append(self.hex_entry)

        # Action Buttons
        action_box = Gtk.Box(spacing=10, halign=Gtk.Align.END, margin_top=5)
        cancel_btn = Gtk.Button(label="Cancel"); cancel_btn.connect("clicked", lambda b: self.hide())
        select_btn = Gtk.Button(label="Select"); select_btn.add_css_class("suggested-action")
        select_btn.connect("clicked", self._on_select_clicked)
        action_box.append(cancel_btn); action_box.append(select_btn)
        
        right_vbox.append(action_box)

    def _on_pick_screen_color(self, btn):
        """Attempts to launch the system color picker via Gtk.ColorDialog (GTK 4.10+)."""
        try:
            if hasattr(Gtk, "ColorDialog"):
                dialog = Gtk.ColorDialog()
                # FIX: Explicitly pass None for cancellable to match signature
                dialog.choose_rgba(self, None, self._on_system_pick_finish)
            else:
                print("System screen picker not available (Requires GTK 4.10+)")
        except Exception as e:
            print(f"Error launching system picker: {e}")

    def _on_system_pick_finish(self, source, result):
        try:
            rgba = source.choose_rgba_finish(result)
            if rgba:
                self._set_color_internal(rgba, update_inputs=True)
        except GLib.Error as e:
            # 19 is G_IO_ERROR_CANCELLED, often returned if user cancels pick
            if e.code != 19: 
                print(f"Picker failed: {e}")

    def _add_stock_colors(self, flowbox):
        # 8 Columns: Purple, Blue, Cyan, Green, Yellow, Orange, Red, Gray
        hues = [270, 240, 180, 120, 60, 30, 0, -1]
        
        for row in range(8):
            # Lightness 0.95 down to 0.25
            lightness = 0.95 - (row * 0.1)
            for hue in hues:
                if hue == -1:
                    g = 0.98 - (row * (0.98 / 7.0)) # White to black
                    rgba = Gdk.RGBA(g, g, g, 1.0)
                else:
                    r, g, b = self._hsl_to_rgb(hue/360.0, 0.85, lightness)
                    rgba = Gdk.RGBA(r, g, b, 1.0)
                
                self._create_swatch_button(flowbox, rgba)

    def _create_swatch_button(self, container, rgba):
        btn = Gtk.Button()
        btn.set_size_request(30, 22) 
        btn.add_css_class("flat")
        area = Gtk.DrawingArea()
        area.set_draw_func(self._draw_swatch, rgba)
        btn.set_child(area)
        btn.connect("clicked", lambda b: self._set_color_internal(rgba, update_inputs=True))
        container.append(btn)

    def _load_custom_colors(self):
        child = self.custom_grid.get_first_child()
        while child: self.custom_grid.remove(child); child = self.custom_grid.get_first_child()
        saved_colors = config_manager.get_custom_colors()
        self._custom_color_data = saved_colors
        for color_str in saved_colors:
            rgba = Gdk.RGBA(); rgba.parse(color_str)
            self._create_swatch_button(self.custom_grid, rgba)

    def _on_save_custom_clicked(self, btn):
        current_str = self._current_rgba.to_string()
        self._custom_color_data.insert(0, current_str)
        self._custom_color_data.pop()
        config_manager.save_custom_colors(self._custom_color_data)
        self._load_custom_colors()

    def _draw_swatch(self, area, ctx, w, h, rgba):
        ctx.set_source_rgb(0.7, 0.7, 0.7); ctx.rectangle(0, 0, w, h); ctx.fill()
        ctx.set_source_rgb(1.0, 1.0, 1.0); ctx.rectangle(0, 0, w/2, h/2); ctx.rectangle(w/2, h/2, w/2, h/2); ctx.fill()
        ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha); ctx.rectangle(0, 0, w, h); ctx.fill()
        ctx.set_source_rgba(0, 0, 0, 0.2); ctx.set_line_width(1); ctx.rectangle(0.5, 0.5, w-1, h-1); ctx.stroke()

    def _draw_preview(self, area, ctx, w, h):
        self._draw_swatch(area, ctx, w, h, self._current_rgba)

    def _draw_color_map(self, area, ctx, w, h):
        hue = self._current_hsv[0]
        r, g, b = self._hsl_to_rgb(hue, 1.0, 0.5)
        
        pat = cairo.MeshPattern()
        pat.begin_patch()
        pat.move_to(0, 0); pat.line_to(w, 0); pat.line_to(w, h); pat.line_to(0, h)
        pat.set_corner_color_rgb(0, 1, 1, 1) # TL
        pat.set_corner_color_rgb(1, r, g, b) # TR
        pat.set_corner_color_rgb(2, 0, 0, 0) # BR
        pat.set_corner_color_rgb(3, 0, 0, 0) # BL
        pat.end_patch()
        
        ctx.set_source(pat)
        ctx.paint()
        
        s, v = self._current_hsv[1], self._current_hsv[2]
        sel_x, sel_y = s * w, (1.0 - v) * h
        ctx.set_source_rgb(1, 1, 1) if v < 0.5 else ctx.set_source_rgb(0, 0, 0)
        ctx.arc(sel_x, sel_y, 4, 0, 2*math.pi); ctx.stroke()

    def _hsl_to_rgb(self, h, s, l):
        def hue_to_rgb(p, q, t):
            if t < 0: t += 1
            if t > 1: t -= 1
            if t < 1/6: return p + (q - p) * 6 * t
            if t < 1/2: return q
            if t < 2/3: return p + (q - p) * (2/3 - t) * 6
            return p
        if s == 0: r, g, b = l, l, l
        else:
            q = l * (1 + s) if l < 0.5 else l + s - l * s
            p = 2 * l - q
            r = hue_to_rgb(p, q, h + 1/3)
            g = hue_to_rgb(p, q, h)
            b = hue_to_rgb(p, q, h - 1/3)
        return r, g, b

    def _rgb_to_hsv(self, r, g, b):
        return colorsys.rgb_to_hsv(r, g, b)
        
    def _hsv_to_rgb(self, h, s, v):
        return colorsys.hsv_to_rgb(h, s, v)

    def _update_from_rgba(self):
        self._updating_inputs = True
        self.sliders['Red'].set_value(self._current_rgba.red * 255)
        self.sliders['Green'].set_value(self._current_rgba.green * 255)
        self.sliders['Blue'].set_value(self._current_rgba.blue * 255)
        self.sliders['Alpha'].set_value(self._current_rgba.alpha * 100)
        
        r, g, b = int(self._current_rgba.red*255), int(self._current_rgba.green*255), int(self._current_rgba.blue*255)
        if self._current_rgba.alpha >= 0.99: self.hex_entry.set_text(f"#{r:02X}{g:02X}{b:02X}")
        else: a = int(self._current_rgba.alpha * 255); self.hex_entry.set_text(f"#{r:02X}{g:02X}{b:02X}{a:02X}")
        
        h, s, v = self._rgb_to_hsv(self._current_rgba.red, self._current_rgba.green, self._current_rgba.blue)
        self._current_hsv = (h, s, v)
        self.hue_scale.set_value(h * 360)
        
        self.preview_area.queue_draw()
        self.map_area.queue_draw()
        self._updating_inputs = False

    def _set_color_internal(self, rgba, update_inputs=False):
        self._current_rgba = rgba
        if update_inputs: self._update_from_rgba()
        else:
            self.preview_area.queue_draw()
            self.map_area.queue_draw()

    def _on_slider_changed(self, scale, channel):
        if self._updating_inputs: return
        val = scale.get_value()
        if channel == 'Red': self._current_rgba.red = val / 255.0
        elif channel == 'Green': self._current_rgba.green = val / 255.0
        elif channel == 'Blue': self._current_rgba.blue = val / 255.0
        elif channel == 'Alpha': self._current_rgba.alpha = val / 100.0
        
        h, s, v = self._rgb_to_hsv(self._current_rgba.red, self._current_rgba.green, self._current_rgba.blue)
        self._current_hsv = (h, s, v)
        self._updating_inputs = True
        self.hue_scale.set_value(h * 360)
        self._updating_inputs = False
        
        self._set_color_internal(self._current_rgba, update_inputs=False)
        
        r, g, b = int(self._current_rgba.red*255), int(self._current_rgba.green*255), int(self._current_rgba.blue*255)
        hex_str = f"#{r:02X}{g:02X}{b:02X}" if self._current_rgba.alpha >= 0.99 else f"#{r:02X}{g:02X}{b:02X}{int(self._current_rgba.alpha*255):02X}"
        self.hex_entry.set_text(hex_str)

    def _on_hue_changed(self, scale):
        if self._updating_inputs: return
        h_val = scale.get_value() / 360.0
        s, v = self._current_hsv[1], self._current_hsv[2]
        self._current_hsv = (h_val, s, v)
        r, g, b = self._hsv_to_rgb(h_val, s, v)
        self._current_rgba.red, self._current_rgba.green, self._current_rgba.blue = r, g, b
        self._update_from_rgba()

    def _on_map_input(self, gesture, n_press, x, y):
        self._update_from_map(x, y)
    
    def _on_map_drag(self, gesture, offset_x, offset_y):
        res, start_x, start_y = gesture.get_start_point()
        if res: self._update_from_map(start_x + offset_x, start_y + offset_y)

    def _update_from_map(self, x, y):
        w, h = self.map_area.get_width(), self.map_area.get_height()
        if w <= 0 or h <= 0: return
        s = max(0, min(1, x / w))
        v = max(0, min(1, 1 - (y / h)))
        self._current_hsv = (self._current_hsv[0], s, v)
        r, g, b = self._hsv_to_rgb(self._current_hsv[0], s, v)
        self._current_rgba.red, self._current_rgba.green, self._current_rgba.blue = r, g, b
        self._update_from_rgba()

    def _on_hex_entry_changed(self, entry):
        text = entry.get_text()
        rgba = Gdk.RGBA()
        if rgba.parse(text): self._set_color_internal(rgba, update_inputs=True)

    def _on_select_clicked(self, btn):
        if self._callback_func: self._callback_func(self._current_rgba.to_string())
        self.hide()
