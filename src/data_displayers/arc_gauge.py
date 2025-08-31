import gi
import math
import re
import cairo
from data_displayer import DataDisplayer
from config_dialog import ConfigOption
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

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
        self._is_first_update = True
        self._current_display_value = 0.0
        self._target_value = 0.0
        
        # --- Caching State ---
        self._static_surface = None
        self._last_draw_width, self._last_draw_height = -1, -1
        
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        self.drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.drawing_area.set_draw_func(self.on_draw_gauge)
        return self.drawing_area

    def update_display(self, value):
        if not self.panel_ref: return
        new_value = self.panel_ref.data_source.get_numerical_value(value) or 0.0
        
        if self._is_first_update:
            self._current_display_value = new_value
            self._is_first_update = False

        self._target_value = new_value
        
        display_string = self.panel_ref.data_source.get_display_string(value)
        
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
            
    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        model["Gauge Range & Zones"] = [
            ConfigOption("gauge_min_value", "spinner", "Min Value:", 0, -100000, 100000, 1, 1),
            ConfigOption("gauge_max_value", "spinner", "Max Value:", 100, -100000, 100000, 1, 1),
            ConfigOption("gauge_green_zone_end", "spinner", "Green Zone End:", 60, -100000, 100000, 1, 1),
            ConfigOption("gauge_yellow_zone_end", "spinner", "Yellow Zone End:", 80, -100000, 100000, 1, 1)
        ]
        model["Gauge Colors"] = [
            ConfigOption("gauge_bg_color", "color", "Background Color:", "rgba(40, 40, 40, 1.0)"),
            ConfigOption("gauge_green_color", "color", "Green Zone Color:", "rgba(0, 255, 0, 0.8)"),
            ConfigOption("gauge_yellow_color", "color", "Yellow Zone Color:", "rgba(255, 255, 0, 0.8)"),
            ConfigOption("gauge_red_color", "color", "Red Zone Color:", "rgba(255, 0, 0, 0.8)"),
            ConfigOption("gauge_inactive_color", "color", "Inactive Line Color:", "rgba(80, 80, 80, 0.8)")
        ]
        model["Gauge Geometry"] = [
            ConfigOption("gauge_num_lines", "spinner", "Number of Lines:", 60, 12, 200, 1, 0),
            ConfigOption("gauge_start_angle", "spinner", "Start Angle (deg):", 135, 0, 359, 1, 0),
            ConfigOption("gauge_end_angle", "spinner", "End Angle (deg):", 45, 0, 359, 1, 0),
            ConfigOption("gauge_inner_radius_factor", "scale", "Inner Radius (% of Panel):", 0.6, 0.1, 1.0, 0.05, 2),
            ConfigOption("gauge_outer_radius_factor", "scale", "Outer Radius (% of Panel):", 0.8, 0.1, 1.0, 0.05, 2),
            ConfigOption("gauge_active_line_width", "scale", "Active Line Width:", 2.5, 0.5, 10, 0.5, 1),
            ConfigOption("gauge_inactive_line_width", "scale", "Inactive Line Width:", 1.5, 0.5, 10, 0.5, 1)
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
            ConfigOption("gauge_animation_duration", "scale", "Animation Duration (ms):", "400", 50, 2000, 50, 0, tooltip="How long the needle takes to travel the full arc.")
        ]
        return model

    def apply_styles(self):
        super().apply_styles()
        self._static_surface = None # Invalidate cache on style change
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
        min_v = float(self.config.get("gauge_min_value", 0))
        max_v = float(self.config.get("gauge_max_value", 100))
        v_range = max_v - min_v if max_v > min_v else 1
        
        total_steps = duration_ms / 16.0
        step_size = v_range / total_steps if total_steps > 0 else v_range

        if diff > 0:
            self._current_display_value = min(self._target_value, self._current_display_value + step_size)
        else:
            self._current_display_value = max(self._target_value, self._current_display_value - step_size)

        self.drawing_area.queue_draw()
        return GLib.SOURCE_CONTINUE

    def on_draw_gauge(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        # Regenerate static surface if needed
        if not self._static_surface or self._last_draw_width != width or self._last_draw_height != height:
            self._static_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            static_ctx = cairo.Context(self._static_surface)
            
            # Draw static background
            bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("gauge_bg_color", "rgba(40,40,40,1.0)"))
            static_ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha); static_ctx.paint()
            
            # Geometry for static drawing
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

            # Draw all segments in INACTIVE state
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

        # Paint the cached surface
        ctx.set_source_surface(self._static_surface, 0, 0)
        ctx.paint()

        # --- DYNAMIC DRAWING ---

        # Geometry Calculations
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

        # Value & Zone Calculations
        min_v = float(self.config.get("gauge_min_value", 0))
        max_v = float(self.config.get("gauge_max_value", 100))
        v_range = max_v - min_v if max_v > min_v else 1
        green_end_v = float(self.config.get("gauge_green_zone_end", 60))
        yellow_end_v = float(self.config.get("gauge_yellow_zone_end", 80))
        
        value_ratio = (min(max(self._current_display_value, min_v), max_v) - min_v) / v_range
        active_line_count = int(round(value_ratio * num_lines))

        # Colors & Line Widths
        green_c = Gdk.RGBA(); green_c.parse(self.config.get("gauge_green_color"))
        yellow_c = Gdk.RGBA(); yellow_c.parse(self.config.get("gauge_yellow_color"))
        red_c = Gdk.RGBA(); red_c.parse(self.config.get("gauge_red_color"))
        active_width = float(self.config.get("gauge_active_line_width", 2.5))

        # Draw ACTIVE Segments
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

        # Draw Text
        layout_v = PangoCairo.create_layout(ctx)
        layout_v.set_font_description(Pango.FontDescription.from_string(self.config.get("gauge_value_font", "Sans Bold 48")))
        layout_v.set_text(self.display_value_text, -1)
        _, log_v = layout_v.get_pixel_extents()

        layout_u = PangoCairo.create_layout(ctx)
        layout_u.set_font_description(Pango.FontDescription.from_string(self.config.get("gauge_unit_font", "Sans 24")))
        layout_u.set_text(self.unit_text, -1)
        _, log_u = layout_u.get_pixel_extents()

        spacing = float(self.config.get("gauge_text_spacing", "5"))
        v_off = float(self.config.get("gauge_text_vertical_offset", "0"))
        total_h = log_v.height + spacing + log_u.height
        start_y = (cy - (total_h / 2)) + v_off

        val_c = Gdk.RGBA(); val_c.parse(self.config.get("gauge_value_color", "rgba(255,255,255,1)"))
        ctx.set_source_rgba(val_c.red, val_c.green, val_c.blue, val_c.alpha)
        ctx.move_to(cx - log_v.width / 2, start_y)
        PangoCairo.show_layout(ctx, layout_v)

        unit_c = Gdk.RGBA(); unit_c.parse(self.config.get("gauge_unit_color", "rgba(200,200,200,1)"))
        ctx.set_source_rgba(unit_c.red, unit_c.green, unit_c.blue, unit_c.alpha)
        ctx.move_to(cx - log_u.width / 2, start_y + log_v.height + spacing)
        PangoCairo.show_layout(ctx, layout_u)

    def close(self):
        self._stop_animation_timer()
        super().close()
