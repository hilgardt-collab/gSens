# /data_displayers/indicator.py
import gi
import math
import cairo
import time
import os
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from ui_helpers import build_background_config_ui, draw_cairo_background

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class IndicatorDisplayer(DataDisplayer):
    """
    Displays data as a single shape whose color dynamically changes based on
    a multi-stop gradient. Supports various shapes, aspect ratio correction,
    fill/stroke options, background styling, and a text overlay.
    """
    def __init__(self, panel_ref, config):
        self._current_value = 0.0
        self._cached_bg_pixbuf = None
        self._cached_image_path = None
        
        # Text overlay state
        self.primary_text = ""
        self.secondary_text = ""
        self._layout_primary = None
        self._layout_secondary = None

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        """Creates a Gtk.DrawingArea for custom rendering."""
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def update_display(self, value, **kwargs):
        """Updates the indicator's value and text labels, then queues a redraw."""
        source = kwargs.get('source_override', self.panel_ref.data_source if self.panel_ref else None)
        if source is None: return

        self._current_value = source.get_numerical_value(value) or 0.0
        
        # Update text labels
        self.primary_text = source.get_primary_label_string(value)
        self.secondary_text = source.get_display_string(value)

        self.widget.queue_draw()

        if self.panel_ref:
            self.panel_ref.set_tooltip_text(source.get_tooltip_string(value))

    def apply_styles(self):
        """Handles caching for background images and invalidates text layouts."""
        super().apply_styles()
        image_path = self.config.get("indicator_background_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            try:
                if image_path and os.path.exists(image_path):
                    self._cached_bg_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path)
                else:
                    self._cached_bg_pixbuf = None
            except GLib.Error as e:
                print(f"Error loading indicator background image: {e}")
                self._cached_bg_pixbuf = None
        
        # Invalidate Pango layouts to force recreation with new styles
        self._layout_primary = None
        self._layout_secondary = None
        self.widget.queue_draw()

    @staticmethod
    def get_config_model():
        """Returns the complete configuration model for the indicator."""
        model = DataDisplayer.get_config_model()
        model["Indicator Style"] = [
            ConfigOption("indicator_shape", "dropdown", "Shape:", "circle", 
                         options_dict={"Circle": "circle", "Square": "square", 
                                       "Rectangle": "rectangle", "Polygon": "polygon"}),
            # These are now built statically and their visibility is handled in the callback
            ConfigOption("indicator_polygon_sides", "spinner", "Number of Sides:", 6, 3, 20, 1, 0),
            ConfigOption("indicator_maintain_aspect_ratio", "bool", "Maintain Aspect Ratio:", "True",
                         tooltip="Keeps shapes like squares and polygons proportional. Circles are always proportional."),
            ConfigOption("indicator_fill_shape", "bool", "Fill Shape:", "True"),
            ConfigOption("indicator_line_width", "spinner", "Line Width:", 2.0, 1, 20, 1, 1,
                         tooltip="Sets the line thickness when 'Fill Shape' is off."),
        ]
        
        color_stops = [
            ConfigOption("indicator_color_gradient", "bool", "Enable Smooth Gradient:", "True"),
            ConfigOption("indicator_color_stop_count", "spinner", "Number of Colors:", 3, 2, 10, 1, 0)
        ]
        default_colors = ["rgba(0,255,0,1)", "rgba(255,255,0,1)", "rgba(255,0,0,1)", "rgba(0,255,255,1)","rgba(128,0,128,1)","rgba(255,165,0,1)","rgba(0,255,255,1)","rgba(255,105,180,1)","rgba(100,149,237,1)","rgba(255,255,255,1)"]
        for i in range(1, 11):
            label_suffix = " (Min)" if i == 1 else ""
            default_val = (i-1) * (100 / 2) if i <= 3 else (i-1) * (100/9)
            color_stops.extend([
                ConfigOption(f"indicator_percent{i}", "spinner", f"Percent for Color {i}{label_suffix}:", f"{default_val:.1f}", 0, 100, 1, 1),
                ConfigOption(f"indicator_color{i}", "color", f"Color {i}:", default_colors[i-1]),
            ])
        model["Indicator Colors"] = color_stops

        model["Text Overlay"] = [
            ConfigOption("indicator_show_primary_label", "bool", "Show Primary Label:", "True"),
            ConfigOption("indicator_primary_font", "font", "Primary Font:", "Sans 10"),
            ConfigOption("indicator_primary_color", "color", "Primary Color:", "rgba(255,255,255,1)"),
            ConfigOption("indicator_show_secondary_label", "bool", "Show Secondary Label:", "True"),
            ConfigOption("indicator_secondary_font", "font", "Secondary Font:", "Sans Bold 12"),
            ConfigOption("indicator_secondary_color", "color", "Secondary Color:", "rgba(255,255,255,1)"),
            ConfigOption("indicator_text_spacing", "spinner", "Line Spacing (px):", 2, 0, 50, 1, 0),
            ConfigOption("indicator_vertical_offset", "spinner", "Vertical Offset (px):", 0, -200, 200, 1, 0),
        ]
        return model

    @staticmethod
    def get_config_key_prefixes():
        """Returns unique prefixes for theme saving."""
        return ["indicator_", "indicator_bg_"]

    def get_configure_callback(self):
        """Adds the background options section and manages all dynamic UI visibility."""
        def build_indicator_config(dialog, content_box, widgets, available_sources, panel_config):
            build_background_config_ui(content_box, panel_config, widgets, dialog, 
                                       prefix="indicator_bg_", title="Indicator Background")
            
            # --- Handle dynamic visibility for Polygon Sides ---
            shape_combo = widgets.get("indicator_shape")
            sides_spinner = widgets.get("indicator_polygon_sides")
            if shape_combo and sides_spinner:
                sides_spinner_row = sides_spinner.get_parent()
                def on_shape_changed(combo):
                    is_polygon = combo.get_active_id() == "polygon"
                    if sides_spinner_row: sides_spinner_row.set_visible(is_polygon)
                shape_combo.connect("changed", on_shape_changed)
                GLib.idle_add(on_shape_changed, shape_combo)

            # --- Handle dynamic visibility for Line Width ---
            fill_switch = widgets.get("indicator_fill_shape")
            line_width_spinner = widgets.get("indicator_line_width")
            if fill_switch and line_width_spinner:
                line_width_row = line_width_spinner.get_parent()
                def on_fill_toggled(switch, gparam):
                    is_filled = switch.get_active()
                    if line_width_row: line_width_row.set_visible(not is_filled)
                fill_switch.connect("notify::active", on_fill_toggled)
                GLib.idle_add(on_fill_toggled, fill_switch, None)

            # --- Handle dynamic visibility for Color Stops ---
            color_count_spinner = widgets.get("indicator_color_stop_count")
            if color_count_spinner:
                stop_widgets = []
                for i in range(1, 11):
                    val_widget = widgets.get(f"indicator_percent{i}")
                    col_widget = widgets.get(f"indicator_color{i}")
                    if val_widget and col_widget:
                        stop_widgets.append({
                            "value_row": val_widget.get_parent(),
                            "color_row": col_widget.get_parent().get_parent(),
                        })

                def on_color_count_changed(spinner):
                    count = spinner.get_value_as_int()
                    for i, widget_group in enumerate(stop_widgets, 1):
                        is_visible = i <= count
                        widget_group["value_row"].set_visible(is_visible)
                        widget_group["color_row"].set_visible(is_visible)
                        value_label = widget_group["value_row"].get_first_child()
                        if value_label:
                            if i == 1: value_label.set_text(f"Percent for Color 1 (Min):")
                            elif i == count: value_label.set_text(f"Percent for Color {i} (Max):")
                            else: value_label.set_text(f"Percent for Color {i}:")

                color_count_spinner.connect("value-changed", on_color_count_changed)
                GLib.idle_add(on_color_count_changed, color_count_spinner)

        return build_indicator_config

    def _get_color_for_value(self):
        """Calculates the shape's color based on the current value and configured color stops."""
        min_v = float(self.config.get("graph_min_value", 0.0))
        max_v = float(self.config.get("graph_max_value", 100.0))
        v_range = max_v - min_v if max_v > min_v else 1.0
        
        num_stops = int(self.config.get("indicator_color_stop_count", 3))
        stops = []
        for i in range(1, num_stops + 1):
            try:
                percent = float(self.config.get(f"indicator_percent{i}"))
                val = min_v + (v_range * (percent / 100.0))
                col = self.config.get(f"indicator_color{i}")
                stops.append({'val': val, 'col': col})
            except (ValueError, TypeError): continue
        stops.sort(key=lambda s: s['val'])

        if not stops: return "rgba(128,128,128,1)"
        
        clamped_value = min(max(self._current_value, min_v), max_v)

        if clamped_value <= stops[0]['val']: return stops[0]['col']
        if clamped_value >= stops[-1]['val']: return stops[-1]['col']
        
        for i in range(len(stops) - 1):
            s1, s2 = stops[i], stops[i+1]
            if s1['val'] <= clamped_value < s2['val']:
                if str(self.config.get("indicator_color_gradient", "True")).lower() != 'true': return s1['col']
                stop_v_range = s2['val'] - s1['val']
                factor = (clamped_value - s1['val']) / stop_v_range if stop_v_range > 0 else 0
                return self._interpolate_color(factor, s1['col'], s2['col']).to_string()
        
        return stops[-1]['col']

    def on_draw(self, area, ctx, width, height):
        """Draws the background, the shape with its dynamic color, and the text overlay."""
        if width <= 0 or height <= 0: return

        # 1. Draw Background
        draw_cairo_background(ctx, width, height, self.config, "indicator_bg_", self._cached_bg_pixbuf)

        # 2. Draw Indicator Shape
        shape = self.config.get("indicator_shape", "circle")
        maintain_aspect = str(self.config.get("indicator_maintain_aspect_ratio", "True")).lower() == 'true'
        
        if shape == "circle" or (maintain_aspect and shape != 'rectangle'):
            size = min(width, height)
            x, y, w, h = (width - size) / 2, (height - size) / 2, size, size
        else: # Stretch to fill
            x, y, w, h = 0, 0, width, height
        
        color_str = self._get_color_for_value()
        color = Gdk.RGBA(); color.parse(color_str)
        ctx.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        
        # Define the shape's path
        if shape == "circle":
            radius = w / 2
            ctx.arc(x + radius, y + radius, radius, 0, 2 * math.pi)
        elif shape == "polygon":
            sides = int(self.config.get("indicator_polygon_sides", 6)); sides = max(3, sides)
            radius = w / 2; cx, cy = x + radius, y + radius
            ctx.new_path()
            for i in range(sides):
                angle = (i / sides) * 2 * math.pi - (math.pi / 2)
                ctx.line_to(cx + radius * math.cos(angle), cy + radius * math.sin(angle))
            ctx.close_path()
        else: # Square or Rectangle
            ctx.rectangle(x, y, w, h)

        # Fill or stroke the path
        is_filled = str(self.config.get("indicator_fill_shape", "True")).lower() == 'true'
        if is_filled:
            ctx.fill()
        else:
            line_width = float(self.config.get("indicator_line_width", 2.0))
            ctx.set_line_width(line_width)
            ctx.stroke()

        # 3. Draw Text Overlay
        self._draw_text_overlay(ctx, width, height)

    def _draw_text_overlay(self, ctx, width, height):
        """Renders the primary and secondary text labels."""
        show_primary = str(self.config.get("indicator_show_primary_label", "True")).lower() == 'true' and self.primary_text
        show_secondary = str(self.config.get("indicator_show_secondary_label", "True")).lower() == 'true' and self.secondary_text

        if not show_primary and not show_secondary: return

        if show_primary:
            if self._layout_primary is None: self._layout_primary = self.widget.create_pango_layout("")
            self._layout_primary.set_font_description(Pango.FontDescription.from_string(self.config.get("indicator_primary_font")))
            self._layout_primary.set_text(self.primary_text, -1)
        
        if show_secondary:
            if self._layout_secondary is None: self._layout_secondary = self.widget.create_pango_layout("")
            self._layout_secondary.set_font_description(Pango.FontDescription.from_string(self.config.get("indicator_secondary_font")))
            self._layout_secondary.set_text(self.secondary_text, -1)

        p_h = self._layout_primary.get_pixel_extents()[1].height if show_primary else 0
        s_h = self._layout_secondary.get_pixel_extents()[1].height if show_secondary else 0
        spacing = float(self.config.get("indicator_text_spacing", 2)) if (show_primary and show_secondary) else 0
        total_h = p_h + s_h + spacing
        
        v_offset = float(self.config.get("indicator_vertical_offset", 0))
        current_y = (height - total_h) / 2 + v_offset

        if show_primary:
            p_w = self._layout_primary.get_pixel_extents()[1].width
            p_color = Gdk.RGBA(); p_color.parse(self.config.get("indicator_primary_color"))
            ctx.set_source_rgba(p_color.red, p_color.green, p_color.blue, p_color.alpha)
            ctx.move_to((width - p_w) / 2, current_y)
            PangoCairo.show_layout(ctx, self._layout_primary)
            current_y += p_h + spacing

        if show_secondary:
            s_w = self._layout_secondary.get_pixel_extents()[1].width
            s_color = Gdk.RGBA(); s_color.parse(self.config.get("indicator_secondary_color"))
            ctx.set_source_rgba(s_color.red, s_color.green, s_color.blue, s_color.alpha)
            ctx.move_to((width - s_w) / 2, current_y)
            PangoCairo.show_layout(ctx, self._layout_secondary)

