# /ui_color_dialog.py
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango
from ui_helpers import CustomDialog
from config_manager import config_manager

class ColorChooserDialog(Gtk.Window):
    """
    A singleton custom color chooser dialog featuring:
    - Quick Stock Colors
    - 32 Persistent Custom Color Slots
    - RGBA Sliders for precise control (especially Alpha)
    - Hex Entry
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
        self.set_default_size(500, 550)
        self.set_resizable(False)
        self.set_hide_on_close(True)
        
        self._current_rgba = Gdk.RGBA(1, 1, 1, 1)
        self._callback_func = None
        self._active_button_ref = None
        
        self._build_ui()
        self._load_custom_colors()
        
        self.connect("close-request", self._on_close_request)
        self._initialized = True

    def present_for_widget(self, widget, current_color_str, callback):
        """
        Opens the dialog for a specific widget/button.
        :param widget: The button that opened the dialog (for context)
        :param current_color_str: The current color string (rgba(...) or hex)
        :param callback: Function(new_color_str) to call on apply
        """
        self._active_button_ref = widget
        self._callback_func = callback
        
        # Parse and set current color
        try:
            rgba = Gdk.RGBA()
            if rgba.parse(current_color_str):
                self._set_color_internal(rgba, update_inputs=True)
        except:
            pass # Keep default if parse fails
            
        self.set_transient_for(widget.get_ancestor(Gtk.Window))
        self.present()

    def _on_close_request(self, *args):
        self.hide()
        return True

    def _build_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=15, margin_bottom=15, margin_start=15, margin_end=15)
        self.set_child(main_box)

        # --- Preview Area ---
        preview_frame = Gtk.Frame(label="Preview")
        self.preview_area = Gtk.DrawingArea()
        self.preview_area.set_content_height(50)
        self.preview_area.set_draw_func(self._draw_preview)
        preview_frame.set_child(self.preview_area)
        main_box.append(preview_frame)

        # --- Palette Area (Notebook) ---
        notebook = Gtk.Notebook()
        main_box.append(notebook)

        # Tab 1: Stock & Custom Colors
        palette_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        
        # Stock Colors
        palette_box.append(Gtk.Label(label="<b>Stock Colors</b>", use_markup=True, xalign=0))
        stock_grid = Gtk.FlowBox(max_children_per_line=8, selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=8)
        self._add_stock_colors(stock_grid)
        palette_box.append(stock_grid)
        
        # Custom Colors
        palette_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        custom_label_box = Gtk.Box(spacing=10)
        custom_label_box.append(Gtk.Label(label="<b>Saved Custom Colors</b>", use_markup=True, xalign=0, hexpand=True))
        save_btn = Gtk.Button(label="Save Current")
        save_btn.connect("clicked", self._on_save_custom_clicked)
        custom_label_box.append(save_btn)
        palette_box.append(custom_label_box)
        
        self.custom_grid = Gtk.FlowBox(max_children_per_line=8, selection_mode=Gtk.SelectionMode.NONE, min_children_per_line=8)
        palette_box.append(self.custom_grid)
        
        notebook.append_page(palette_box, Gtk.Label(label="Palette"))

        # --- Sliders & Hex Area ---
        sliders_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        
        # Hex Entry
        hex_box = Gtk.Box(spacing=10)
        hex_box.append(Gtk.Label(label="Hex Code:"))
        self.hex_entry = Gtk.Entry(hexpand=True)
        self.hex_entry.connect("activate", self._on_hex_entry_changed)
        
        # FIX: Use EventControllerFocus for focus-leave (GTK4)
        focus_controller = Gtk.EventControllerFocus()
        focus_controller.connect("leave", lambda c: self._on_hex_entry_changed(self.hex_entry))
        self.hex_entry.add_controller(focus_controller)
        
        hex_box.append(self.hex_entry)
        sliders_box.append(hex_box)
        
        # RGBA Sliders
        self.sliders = {}
        for channel in ['Red', 'Green', 'Blue', 'Alpha']:
            row = Gtk.Box(spacing=10)
            label = Gtk.Label(label=f"{channel}:", xalign=1)
            label.set_size_request(50, -1)
            
            adj = Gtk.Adjustment(value=0, lower=0, upper=255 if channel != 'Alpha' else 100, step_increment=1, page_increment=10)
            scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
            scale.set_hexpand(True)
            scale.set_digits(0)
            scale.set_draw_value(True)
            scale.set_value_pos(Gtk.PositionType.RIGHT)
            
            scale.connect("value-changed", self._on_slider_changed, channel)
            
            row.append(label)
            row.append(scale)
            sliders_box.append(row)
            self.sliders[channel] = adj

        main_box.append(sliders_box)

        # --- Action Buttons ---
        action_box = Gtk.Box(spacing=10, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda b: self.hide())
        select_btn = Gtk.Button(label="Select")
        select_btn.add_css_class("suggested-action")
        select_btn.connect("clicked", self._on_select_clicked)
        
        action_box.append(cancel_btn)
        action_box.append(select_btn)
        main_box.append(action_box)

    def _add_stock_colors(self, flowbox):
        # A good selection of UI colors
        stock_colors = [
            "#FFFFFF", "#000000", "#808080", "#C0C0C0", "#FF0000", "#00FF00", "#0000FF", "#FFFF00",
            "#00FFFF", "#FF00FF", "#800000", "#008000", "#000080", "#808000", "#008080", "#800080",
            "#FFA500", "#A52A2A", "#FFC0CB", "#ADD8E6", "#90EE90", "#F0E68C", "#E6E6FA", "#FFD700"
        ]
        for color_str in stock_colors:
            btn = Gtk.Button()
            btn.set_size_request(32, 32)
            btn.add_css_class("flat")
            area = Gtk.DrawingArea()
            area.set_draw_func(self._draw_swatch, color_str)
            btn.set_child(area)
            btn.connect("clicked", lambda b, c=color_str: self._set_color_from_string(c))
            flowbox.append(btn)

    def _load_custom_colors(self):
        # Clear existing
        child = self.custom_grid.get_first_child()
        while child:
            self.custom_grid.remove(child)
            child = self.custom_grid.get_first_child()
            
        saved_colors = config_manager.get_custom_colors()
        self._custom_color_data = saved_colors # Keep reference to list
        
        for i, color_str in enumerate(saved_colors):
            btn = Gtk.Button()
            btn.set_size_request(32, 32)
            # Store index to update later
            btn.custom_index = i 
            
            area = Gtk.DrawingArea()
            area.set_draw_func(self._draw_swatch, color_str)
            btn.set_child(area)
            
            # Left click to load
            btn.connect("clicked", lambda b, c=color_str: self._set_color_from_string(c))
            
            self.custom_grid.append(btn)

    def _on_save_custom_clicked(self, btn):
        # Shift colors: Newest at index 0, drop last
        current_str = self._current_rgba.to_string()
        self._custom_color_data.insert(0, current_str)
        self._custom_color_data.pop() # Remove last
        
        config_manager.save_custom_colors(self._custom_color_data)
        self._load_custom_colors() # Rebuild UI

    def _draw_swatch(self, area, ctx, w, h, color_str):
        rgba = Gdk.RGBA()
        rgba.parse(color_str)
        
        # Checkerboard for alpha
        ctx.set_source_rgb(0.8, 0.8, 0.8)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()
        ctx.set_source_rgb(0.6, 0.6, 0.6)
        ctx.rectangle(0, 0, w/2, h/2)
        ctx.rectangle(w/2, h/2, w/2, h/2)
        ctx.fill()
        
        ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()
        
        # Border
        ctx.set_source_rgba(0, 0, 0, 0.3)
        ctx.set_line_width(1)
        ctx.rectangle(0.5, 0.5, w-1, h-1)
        ctx.stroke()

    def _draw_preview(self, area, ctx, w, h):
        # Checkerboard
        ctx.set_source_rgb(0.8, 0.8, 0.8)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()
        ctx.set_source_rgb(0.6, 0.6, 0.6)
        ctx.rectangle(0, 0, w/2, h/2)
        ctx.rectangle(w/2, h/2, w/2, h/2)
        ctx.fill()
        
        # Color
        ctx.set_source_rgba(self._current_rgba.red, self._current_rgba.green, self._current_rgba.blue, self._current_rgba.alpha)
        ctx.rectangle(0, 0, w, h)
        ctx.fill()

    def _set_color_from_string(self, color_str):
        rgba = Gdk.RGBA()
        if rgba.parse(color_str):
            self._set_color_internal(rgba, update_inputs=True)

    def _set_color_internal(self, rgba, update_inputs=False):
        self._current_rgba = rgba
        self.preview_area.queue_draw()
        
        if update_inputs:
            # Block signals if needed, but simple set_value is fine usually if we check value
            self.sliders['Red'].set_value(rgba.red * 255)
            self.sliders['Green'].set_value(rgba.green * 255)
            self.sliders['Blue'].set_value(rgba.blue * 255)
            self.sliders['Alpha'].set_value(rgba.alpha * 100)
            
            # Format hex
            r, g, b = int(rgba.red*255), int(rgba.green*255), int(rgba.blue*255)
            if rgba.alpha >= 0.99:
                self.hex_entry.set_text(f"#{r:02X}{g:02X}{b:02X}")
            else:
                a = int(rgba.alpha * 255)
                self.hex_entry.set_text(f"#{r:02X}{g:02X}{b:02X}{a:02X}")

    def _on_slider_changed(self, scale, channel):
        val = scale.get_value()
        if channel == 'Red': self._current_rgba.red = val / 255.0
        elif channel == 'Green': self._current_rgba.green = val / 255.0
        elif channel == 'Blue': self._current_rgba.blue = val / 255.0
        elif channel == 'Alpha': self._current_rgba.alpha = val / 100.0
        
        self._set_color_internal(self._current_rgba, update_inputs=False) # Don't loop update sliders
        
        # Update hex only
        r, g, b = int(self._current_rgba.red*255), int(self._current_rgba.green*255), int(self._current_rgba.blue*255)
        if self._current_rgba.alpha >= 0.99:
            self.hex_entry.set_text(f"#{r:02X}{g:02X}{b:02X}")
        else:
            a = int(self._current_rgba.alpha * 255)
            self.hex_entry.set_text(f"#{r:02X}{g:02X}{b:02X}{a:02X}")

    def _on_hex_entry_changed(self, entry):
        text = entry.get_text()
        rgba = Gdk.RGBA()
        if rgba.parse(text):
            self._set_color_internal(rgba, update_inputs=True)

    def _on_select_clicked(self, btn):
        if self._callback_func:
            self._callback_func(self._current_rgba.to_string())
        self.hide()
