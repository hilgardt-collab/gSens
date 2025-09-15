import gi
import math
import re
import cairo
import os
from data_displayer import DataDisplayer
from config_dialog import ConfigOption
from utils import populate_defaults_from_model
from ui_helpers import build_background_config_ui, draw_cairo_background

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class ArcGaugeDisplayer(DataDisplayer):
    """
    A highly configurable gauge that combines features from a dial and a radial gauge.
    It supports color zones, custom angles, segmented lines, and detailed text formatting.
    """
    def __init__(self, panel_ref, config):
        self.current_value = 0.0
        self.display_value_text = "0.0"
        self.unit_text = ""

        # --- Animation State ---
        self._animation_timer_id = None
        self._current_display_value = 0.0
        self._target_value = 0.0
        self._first_update = True
        
        # --- Caching State ---
        self._static_surface = None
        self._last_draw_width, self._last_draw_height = -1, -1
        self._cached_bg_pixbuf = None
        self._cached_image_path = None
        self._layout_value = None
        self._layout_unit = None
        
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        self.drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.drawing_area.set_draw_func(self.on_draw)
        return self.drawing_area

    def update_display(self, value, **kwargs):
        source = self.panel_ref.data_source
        if 'source_override' in kwargs and kwargs['source_override']:
            source = kwargs['source_override']
            
        new_value = source.get_numerical_value(value) or 0.0
        
        # --- BUG FIX: Instantaneously set the first value to avoid slow startup animation ---
        if self._first_update:
            self._current_display_value = new_value
            self._first_update = False

        self._target_value = new_value
        
        display_string = source.get_display_string(value)
        
        if display_string and display_string != "N/A":
            match = re.match(r'\s*([+-]?\d+\.?\d*)\s*(.*)', display_string)
            if match:
                self.display_value_text = match.group(1)
                self.unit_text = match.group(2).strip()
            else:
                self.display_value_text = display_string
                self.unit_text = ""
        else:
            self.display_value_text = "N/A"
            self.unit_text = ""
            
    def reset_state(self):
        """Resets the animation state when the panel is reconfigured."""
        self._first_update = True
        self._target_value = 0.0
        self._current_display_value = 0.0

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        model["Gauge Color Zones"] = [
            ConfigOption("gauge_green_zone_percent", "spinner", "Green Zone End (%):", 60, 0, 100, 1, 0),
            ConfigOption("gauge_yellow_zone_percent", "spinner", "Yellow Zone End (%):", 80, 0, 100, 1, 0)
        ]
        model["Gauge Colors"] = [
            ConfigOption("gauge_green_color", "color", "Green Zone Color:", "rgba(0, 255, 0, 0.8)"),
            ConfigOption("gauge_yellow_color", "color", "Yellow Zone Color:", "rgba(255, 255, 0, 0.8)"),
            ConfigOption("gauge_red_color", "color", "Red Zone Color:", "rgba(255, 0, 0, 0.8)"),
            ConfigOption("gauge_inactive_color", "color", "Inactive Line Color:", "rgba(80, 80, 80, 0.8)")
        ]
        model["Gauge Geometry"] = [
            ConfigOption("gauge_num_lines", "spinner", "Number of Lines:", 60, 12, 200, 1, 0),
            ConfigOption("gauge_start_angle", "spinner", "Start Angle (deg):", 135, 0, 359, 1, 0),
            ConfigOption("gauge_end_angle", "spinner", "End Angle (deg):", 45, 0, 359, 1, 0),
            ConfigOption("gauge_bg_radius_factor", "spinner", "BG Radius (% of Panel):", 0.85, 0.1, 1.5, 0.05, 2),
            ConfigOption("gauge_inner_radius_factor", "spinner", "Inner Radius (% of Panel):", 0.6, 0.1, 1.0, 0.05, 2),
            ConfigOption("gauge_outer_radius_factor", "spinner", "Outer Radius (% of Panel):", 0.8, 0.1, 1.0, 0.05, 2),
            ConfigOption("gauge_active_line_width", "spinner", "Active Line Width:", 2.5, 0.5, 10, 0.5, 1),
            ConfigOption("gauge_inactive_line_width", "spinner", "Inactive Line Width:", 1.5, 0.5, 10, 0.5, 1)
        ]
        model["Gauge Text"] = [
            ConfigOption("gauge_value_font", "font", "Value Font:", "Sans Bold 48"),
            ConfigOption("gauge_value_color", "color", "Value Color:", "rgba(255,255,255,1)"),
            ConfigOption("gauge_unit_font", "font", "Unit Font:", "Sans 24"),
            ConfigOption("gauge_unit_color", "color", "Unit Color:", "rgba(200,200,200,1)"),
            ConfigOption("gauge_text_spacing", "spinner", "Spacing:", 5, 0, 50, 1, 0),
            ConfigOption("gauge_text_vertical_offset", "spinner", "V. Offset:", 0, -100, 100, 1, 0)
        ]
        model["Animation"] = [
            ConfigOption("gauge_animation_enabled", "bool", "Enable Animation:", "True"),
            ConfigOption("gauge_animation_duration", "spinner", "Animation Duration (ms):", "400", 50, 2000, 50, 0, tooltip="How long the needle takes to travel the full arc.")
        ]
        return model
        
    @staticmethod
    def get_config_key_prefixes():
        return ["gauge_"]

    def get_configure_callback(self):
        def build_gauge_config(dialog, content_box, widgets, available_sources, panel_config):
            build_background_config_ui(content_box, panel_config, widgets, dialog, prefix="gauge_", title="Gauge Dial Background")
        return build_gauge_config

    def apply_styles(self):
        super().apply_styles()
        image_path = self.config.get("gauge_background_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            try:
                self._cached_bg_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
            except GLib.Error as e:
                print(f"Error loading gauge image: {e}")
                self._cached_bg_pixbuf = None
        self._static_surface = None 
        self._layout_value = None
        self._layout_unit = None
        self.drawing_area.queue_draw()

    def _start_animation_timer(self, widget=None):
        self._stop_animation_timer()
        self._animation_timer_id = GLib.timeout_add(16, self._animation_tick)

    def _stop_animation_timer(self, widget=None):
        if self._animation_timer_id is not None:
            GLib.source_remove(self._animation_timer_id)
            self._animation_timer_id = None

    def _animation_tick(self):
        if not self.widget.get_realized():
            self._animation_timer_id = None
            return GLib.SOURCE_REMOVE

        animation_enabled = str(self.config.get("gauge_animation_enabled", "True")).lower() == 'true'

        if not animation_enabled:
            if self._current_display_value != self._target_value:
                self._current_display_value = self._target_value
                self.drawing_area.queue_draw()
            return GLib.SOURCE_CONTINUE

        diff = self._target_value - self._current_display_value
        
        if abs(diff) < 0.01:
            if self._current_display_value != self._target_value:
                self._current_display_value = self._target_value
                self.drawing_area.queue_draw()
            return GLib.SOURCE_CONTINUE

        duration_ms = float(self.config.get("gauge_animation_duration", "400"))
        min_v = float(self.config.get("graph_min_value", 0))
        max_v = float(self.config.get("graph_max_value", 100))
        v_range = max_v - min_v if max_v > min_v else 1
        
        total_steps = duration_ms / 16.0
        step_size = v_range / total_steps if total_steps > 0 else v_range

        if diff > 0:
            self._current_display_value = min(self._target_value, self._current_display_value + step_size)
        else:
            self._current_display_value = max(self._target_value, self._current_display_value - step_size)

        self.drawing_area.queue_draw()
        return GLib.SOURCE_CONTINUE

    def on_draw(self, area, ctx, width_float, height_float):
        width, height = int(width_float), int(height_float)
        if width <= 0 or height <= 0: return

        if not self._static_surface or self._last_draw_width != width or self._last_draw_height != height:
            self._static_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            static_ctx = cairo.Context(self._static_surface)
            
            cx, cy = width / 2, height / 2
            min_dim = min(width, height)
            
            bg_radius = min_dim / 2 * float(self.config.get("gauge_bg_radius_factor", 0.85))
            
            if bg_radius > 0:
                static_ctx.save()
                static_ctx.arc(cx, cy, bg_radius, 0, 2 * math.pi)
                static_ctx.clip()
                
                shape_info = {'type': 'circle', 'cx': cx, 'cy': cy, 'radius': bg_radius}
                
                draw_cairo_background(static_ctx, width, height, self.config, "gauge_",
                                      self._cached_bg_pixbuf, shape_info)
                
                static_ctx.restore()
            
            inner_r = min_dim / 2 * float(self.config.get("gauge_inner_radius_factor", 0.6))
            outer_r = min_dim / 2 * float(self.config.get("gauge_outer_radius_factor", 0.8))
            start_angle = math.radians(float(self.config.get("gauge_start_angle", 135)))
            end_angle = math.radians(float(self.config.get("gauge_end_angle", 45)))
            num_lines = int(self.config.get("gauge_num_lines", 60))
            total_angle = end_angle - start_angle
            if total_angle <= 0: total_angle += 2 * math.pi
            angle_step = total_angle / (num_lines - 1) if num_lines > 1 else 0

            inactive_c = Gdk.RGBA(); inactive_c.parse(self.config.get("gauge_inactive_color"))
            inactive_width = float(self.config.get("gauge_inactive_line_width", 1.5))
            static_ctx.set_line_width(inactive_width)
            static_ctx.set_source_rgba(inactive_c.red, inactive_c.green, inactive_c.blue, inactive_c.alpha)
            
            for i in range(num_lines):
                angle = start_angle + i * angle_step
                x1, y1 = cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r
                x2, y2 = cx + math.cos(angle) * outer_r, cy + math.sin(angle) * outer_r
                static_ctx.move_to(x1, y1); static_ctx.line_to(x2, y2); static_ctx.stroke()

            self._last_draw_width, self._last_draw_height = width, height

        ctx.set_source_surface(self._static_surface, 0, 0); ctx.paint()

        cx, cy = width / 2, height / 2
        min_dim = min(width, height)
        inner_r = min_dim / 2 * float(self.config.get("gauge_inner_radius_factor", 0.6))
        outer_r = min_dim / 2 * float(self.config.get("gauge_outer_radius_factor", 0.8))
        start_angle = math.radians(float(self.config.get("gauge_start_angle", 135)))
        end_angle = math.radians(float(self.config.get("gauge_end_angle", 45)))
        num_lines = int(self.config.get("gauge_num_lines", 60))
        total_angle = end_angle - start_angle
        if total_angle <= 0: total_angle += 2 * math.pi
        angle_step = total_angle / (num_lines - 1) if num_lines > 1 else 0

        min_v = float(self.config.get("graph_min_value", 0))
        max_v = float(self.config.get("graph_max_value", 100))
        v_range = max_v - min_v if max_v > min_v else 1
        
        green_zone_percent = float(self.config.get("gauge_green_zone_percent", 60))
        yellow_zone_percent = float(self.config.get("gauge_yellow_zone_percent", 80))
        
        green_end_v = min_v + (v_range * (green_zone_percent / 100.0))
        yellow_end_v = min_v + (v_range * (yellow_zone_percent / 100.0))
        
        value_ratio = (min(max(self._current_display_value, min_v), max_v) - min_v) / v_range
        active_line_count = int(round(value_ratio * num_lines))

        green_c = Gdk.RGBA(); green_c.parse(self.config.get("gauge_green_color"))
        yellow_c = Gdk.RGBA(); yellow_c.parse(self.config.get("gauge_yellow_color"))
        red_c = Gdk.RGBA(); red_c.parse(self.config.get("gauge_red_color"))
        active_width = float(self.config.get("gauge_active_line_width", 2.5))

        ctx.set_line_width(active_width)
        for i in range(active_line_count):
            segment_value = min_v + (i / (num_lines -1)) * v_range if num_lines > 1 else min_v
            if segment_value <= green_end_v:
                ctx.set_source_rgba(green_c.red, green_c.green, green_c.blue, green_c.alpha)
            elif segment_value <= yellow_end_v:
                ctx.set_source_rgba(yellow_c.red, yellow_c.green, yellow_c.blue, yellow_c.alpha)
            else:
                ctx.set_source_rgba(red_c.red, red_c.green, red_c.blue, red_c.alpha)
            
            angle = start_angle + i * angle_step
            x1, y1 = cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r
            x2, y2 = cx + math.cos(angle) * outer_r, cy + math.sin(angle) * outer_r
            ctx.move_to(x1, y1); ctx.line_to(x2, y2); ctx.stroke()

        if self._layout_value is None:
            self._layout_value = self.widget.create_pango_layout("")
        self._layout_value.set_font_description(Pango.FontDescription.from_string(self.config.get("gauge_value_font", "Sans Bold 48")))
        self._layout_value.set_text(self.display_value_text, -1)
        _, log_v = self._layout_value.get_pixel_extents()

        if self._layout_unit is None:
            self._layout_unit = self.widget.create_pango_layout("")
        self._layout_unit.set_font_description(Pango.FontDescription.from_string(self.config.get("gauge_unit_font", "Sans 24")))
        self._layout_unit.set_text(self.unit_text, -1)
        _, log_u = self._layout_unit.get_pixel_extents()

        spacing = float(self.config.get("gauge_text_spacing", "5"))
        v_off = float(self.config.get("gauge_text_vertical_offset", "0"))
        total_h = log_v.height + spacing + log_u.height
        start_y = (cy - (total_h / 2)) + v_off

        val_c = Gdk.RGBA(); val_c.parse(self.config.get("gauge_value_color", "rgba(255,255,255,1)"))
        ctx.set_source_rgba(val_c.red, val_c.green, val_c.blue, val_c.alpha)
        ctx.move_to(cx - log_v.width / 2, start_y)
        PangoCairo.show_layout(ctx, self._layout_value)

        unit_c = Gdk.RGBA(); unit_c.parse(self.config.get("gauge_unit_color", "rgba(200,200,200,1)"))
        ctx.set_source_rgba(unit_c.red, unit_c.green, unit_c.blue, unit_c.alpha)
        ctx.move_to(cx - log_u.width / 2, start_y + log_v.height + spacing)
        PangoCairo.show_layout(ctx, self._layout_unit)

    def close(self):
        self._stop_animation_timer()
        super().close()

