# /data_displayers/graph.py
import gi
import time
import os
import cairo
import math
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from ui_helpers import build_background_config_ui, draw_cairo_background

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class GraphDisplayer(DataDisplayer):
    """
    A highly configurable data displayer that shows a value as a line graph
    or bar chart with optional smoothing, fill, and text overlays.
    """
    def __init__(self, panel_ref, config):
        self.history, self.secondary_text = [], ""
        self._cached_bg_pixbuf = None
        self._cached_image_path = None
        self._layout_overlay = None
        self.alarm_config_prefix = "data_" # Default prefix
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        self.graph_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.graph_area.set_draw_func(self.on_draw)
        return self.graph_area

    def update_display(self, value, **kwargs):
        source = kwargs.get('source_override', self.panel_ref.data_source if self.panel_ref else None)
        if source is None: return
        
        # Store the alarm prefix from the specific source for this update cycle
        self.alarm_config_prefix = getattr(source, 'alarm_config_prefix', 'data_')

        raw_data = value
        num_val = source.get_numerical_value(raw_data)
        
        max_hist = int(self.config.get("max_history_points", 100))
        if num_val is not None:
            self.history.append((time.time(), num_val))
            if len(self.history) > max_hist: self.history = self.history[-max_hist:]
            
        caption_text = kwargs.get('caption', source.get_primary_label_string(raw_data))
        value_text = source.get_display_string(raw_data)
        
        self.secondary_text = f"{caption_text}: {value_text}" if caption_text and value_text else caption_text or value_text
            
        self.graph_area.queue_draw()

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        model["Graph Visuals"] = [
            ConfigOption("graph_type", "dropdown", "Graph Type:", "line", 
                         options_dict={"Line Chart": "line", "Bar Chart": "bar"}),
            ConfigOption("graph_line_color", "color", "Line/Border Color:", "rgba(255,0,0,0.8)"),
            ConfigOption("graph_line_width", "scale", "Line/Border Width:", "2.0", 0.5, 10.0, 0.5, 1),
            ConfigOption("graph_line_style", "dropdown", "Line Style:", "sharp", 
                         options_dict={"Sharp": "sharp", "Smooth": "smooth"}),
            ConfigOption("graph_fill_enabled", "bool", "Fill (Line/Bar):", "True"),
            ConfigOption("graph_fill_color", "color", "Fill Color:", "rgba(255,0,0,0.2)")
        ]
        model["Graph Data"] = [ConfigOption("max_history_points", "scale", "History Points:", "100", 10, 1000, 10, 0)]
        model["Text Overlay"] = [
            ConfigOption("show_overlay", "bool", "Show Value Text:", "True"),
            ConfigOption("overlay_position", "dropdown", "Text Position:", "top_right",
                         options_dict={"Top Right": "top_right", "Top Left": "top_left", 
                                       "Bottom Right": "bottom_right", "Bottom Left": "bottom_left",
                                       "Center": "center"}),
            ConfigOption("overlay_text_color", "color", "Text Color:", "#FFFFFF"),
            ConfigOption("overlay_font", "font", "Text Font:", "Sans 10")
        ]
        model["Grid Lines"] = [
            ConfigOption("graph_grid_enabled", "bool", "Show Grid:", "False"),
            ConfigOption("graph_grid_x_divisions", "spinner", "Vertical Divisions:", 5, 1, 50, 1, 0),
            ConfigOption("graph_grid_y_divisions", "spinner", "Horizontal Divisions:", 4, 1, 50, 1, 0),
            ConfigOption("graph_grid_color", "color", "Grid Color:", "rgba(128,128,128,0.3)"),
            ConfigOption("graph_grid_width", "scale", "Grid Line Width:", 1.0, 0.5, 5.0, 0.5, 1)
        ]
        return model

    @staticmethod
    def get_config_key_prefixes():
        return ["graph_"]

    def get_configure_callback(self):
        def setup_dynamic_options(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            # If a prefix is passed, it means we are a child of a combo.
            # The combo builder will handle the background UI with the correct full prefix.
            if prefix is None:
                build_background_config_ui(content_box, panel_config, widgets, dialog, prefix="graph_", title="Graph Background")
            
            graph_type_combo = widgets.get("graph_type")
            line_style_widget = widgets.get("graph_line_style")

            if not graph_type_combo or not line_style_widget:
                return

            line_style_box = line_style_widget.get_parent()

            def on_type_changed(combo):
                is_line = combo.get_active_id() == "line"
                line_style_box.set_visible(is_line)

            graph_type_combo.connect("changed", on_type_changed)
            GLib.idle_add(on_type_changed, graph_type_combo)

        return setup_dynamic_options

    def apply_styles(self):
        super().apply_styles()
        image_path = self.config.get("graph_background_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            self._cached_bg_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
        self._layout_overlay = None
        self.graph_area.queue_draw()

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        is_alarm = self.panel_ref is not None and self.panel_ref.is_in_alarm_state and self.panel_ref._alarm_flash_on
        if is_alarm:
            bg_color_str = self.config.get(self.alarm_config_prefix + "alarm_color", "rgba(255,0,0,0.6)")
            bg_rgba = Gdk.RGBA(); bg_rgba.parse(bg_color_str)
            ctx.set_source_rgba(bg_rgba.red, bg_rgba.green, bg_rgba.blue, bg_rgba.alpha)
            ctx.paint()
        else:
            draw_cairo_background(ctx, width, height, self.config, "graph_", self._cached_bg_pixbuf)

        if str(self.config.get("graph_grid_enabled", "False")).lower() == 'true':
            grid_rgba = Gdk.RGBA(); grid_rgba.parse(self.config.get("graph_grid_color"))
            ctx.set_source_rgba(grid_rgba.red, grid_rgba.green, grid_rgba.blue, grid_rgba.alpha)
            ctx.set_line_width(float(self.config.get("graph_grid_width", 1.0)))
            
            x_divs = int(self.config.get("graph_grid_x_divisions", 5))
            y_divs = int(self.config.get("graph_grid_y_divisions", 4))

            if x_divs > 0:
                x_step = width / x_divs
                for i in range(1, x_divs):
                    ctx.move_to(i * x_step, 0)
                    ctx.line_to(i * x_step, height)
                    ctx.stroke()
            
            if y_divs > 0:
                y_step = height / y_divs
                for i in range(1, y_divs):
                    ctx.move_to(0, i * y_step)
                    ctx.line_to(width, i * y_step)
                    ctx.stroke()

        if len(self.history) >= 2:
            timestamps, values = zip(*self.history)
            min_y, max_y = float(self.config.get("graph_min_value", 0.0)), float(self.config.get("graph_max_value", 100.0))
            y_range = max_y - min_y if max_y > min_y else 1
            
            max_hist = int(self.config.get("max_history_points", 100))
            num_points = len(values)
            
            x_step = width / (max_hist - 1) if max_hist > 1 else width
            start_x = width - ((num_points - 1) * x_step)

            points = []
            for i, v in enumerate(values):
                x = start_x + (i * x_step)
                y = height - ((max(min_y, min(v, max_y)) - min_y) / y_range * height)
                points.append((x, y))

            graph_type = self.config.get("graph_type", "line")
            
            if graph_type == "bar":
                bar_width = x_step
                fill_rgba = Gdk.RGBA(); fill_rgba.parse(self.config.get("graph_fill_color"))
                line_rgba = Gdk.RGBA(); line_rgba.parse(self.config.get("graph_line_color"))
                line_width = float(self.config.get("graph_line_width", 2.0))

                for p in points:
                    bar_x = p[0] - (bar_width / 2)
                    if str(self.config.get("graph_fill_enabled", "False")).lower() == 'true':
                        ctx.set_source_rgba(fill_rgba.red, fill_rgba.green, fill_rgba.blue, fill_rgba.alpha)
                        ctx.rectangle(bar_x, p[1], bar_width, height - p[1]); ctx.fill()
                    if line_width > 0:
                        ctx.set_source_rgba(line_rgba.red, line_rgba.green, line_rgba.blue, line_rgba.alpha)
                        ctx.set_line_width(line_width)
                        ctx.rectangle(bar_x, p[1], bar_width, height - p[1]); ctx.stroke()
            else: # Line Chart
                ctx.new_path(); ctx.move_to(points[0][0], points[0][1])
                line_style = self.config.get("graph_line_style", "sharp")
                if line_style == "smooth" and len(points) > 2:
                    for i in range(len(points) - 1):
                        p0, p1, p2 = points[i-1] if i > 0 else points[i], points[i], points[i+1]
                        p3 = points[i+2] if i < len(points) - 2 else p2
                        cp1x, cp1y = p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6
                        cp2x, cp2y = p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6
                        ctx.curve_to(cp1x, cp1y, cp2x, cp2y, p2[0], p2[1])
                else: # Sharp
                    for p in points[1:]: ctx.line_to(p[0], p[1])
                
                if str(self.config.get("graph_fill_enabled", "False")).lower() == 'true':
                    fill_rgba = Gdk.RGBA(); fill_rgba.parse(self.config.get("graph_fill_color"))
                    ctx.set_source_rgba(fill_rgba.red, fill_rgba.green, fill_rgba.blue, fill_rgba.alpha)
                    ctx.line_to(points[-1][0], height); ctx.line_to(points[0][0], height); ctx.close_path(); ctx.fill_preserve()
                
                line_rgba = Gdk.RGBA(); line_rgba.parse(self.config.get("graph_line_color"))
                ctx.set_source_rgba(line_rgba.red, line_rgba.green, line_rgba.blue, line_rgba.alpha)
                ctx.set_line_width(float(self.config.get("graph_line_width", 2.0))); ctx.stroke()

        if str(self.config.get("show_overlay", "True")).lower() == 'true':
            if self._layout_overlay is None:
                self._layout_overlay = self.widget.create_pango_layout("")
            self._layout_overlay.set_font_description(Pango.FontDescription.from_string(self.config.get("overlay_font")))
            self._layout_overlay.set_text(self.secondary_text, -1)
            _, log_rect = self._layout_overlay.get_pixel_extents()
            margin = 6
            
            pos = self.config.get("overlay_position", "top_right")
            if pos == "top_right": text_x, text_y = width - log_rect.width - margin, margin
            elif pos == "top_left": text_x, text_y = margin, margin
            elif pos == "bottom_right": text_x, text_y = width - log_rect.width - margin, height - log_rect.height - margin
            elif pos == "bottom_left": text_x, text_y = margin, height - log_rect.height - margin
            else: text_x, text_y = (width - log_rect.width) / 2, (height - log_rect.height) / 2

            text_rgba = Gdk.RGBA(); text_rgba.parse(self.config.get("overlay_text_color"))
            ctx.set_source_rgba(text_rgba.red, text_rgba.green, text_rgba.blue, text_rgba.alpha)
            ctx.move_to(text_x, text_y); PangoCairo.show_layout(ctx, self._layout_overlay)
