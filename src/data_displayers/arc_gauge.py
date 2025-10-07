# data_displayers/arc_gauge.py
import gi
import math
import re
import cairo
import os
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from ui_helpers import build_background_config_ui, draw_cairo_background

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class ArcGaugeDisplayer(DataDisplayer):
    """
    A highly configurable gauge that supports multiple drawing styles (lines,
    segments, solid arc) and features a dynamic, multi-stop color gradient.
    """
    def __init__(self, panel_ref, config):
        self.current_value = 0.0
        self.display_value_text = "0.0"
        self.unit_text = ""
        self.caption_text = ""

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
        self._layout_caption = None
        
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        self.drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        self.drawing_area.set_draw_func(self.on_draw)
        return self.drawing_area

    def update_display(self, value, **kwargs):
        source = self.panel_ref.data_source if self.panel_ref else None
        if 'source_override' in kwargs and kwargs['source_override']:
            source = kwargs['source_override']
        
        if not source: return
            
        new_value = source.get_numerical_value(value) or 0.0
        
        if self._first_update:
            self._current_display_value = new_value
            self._first_update = False

        self._target_value = new_value
        
        self.caption_text = kwargs.get('caption', '')
        
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

        style_controller_key = "gauge_style"
        model["Gauge Visual Style"] = [
            ConfigOption(style_controller_key, "dropdown", "Style:", "lines", 
                         options_dict={"Lines": "lines", "Segments": "segments", "Solid Arc": "solid"}),
            ConfigOption("gauge_num_lines", "spinner", "Number of Lines:", 60, 12, 360, 1, 0,
                         dynamic_group=style_controller_key, dynamic_show_on="lines"),
            ConfigOption("gauge_num_segments", "spinner", "Number of Segments:", 30, 2, 360, 1, 0,
                         dynamic_group=style_controller_key, dynamic_show_on="segments"),
            ConfigOption("gauge_segment_fill", "bool", "Fill Segments:", "True",
                         dynamic_group=style_controller_key, dynamic_show_on="segments"),
            ConfigOption("gauge_segment_gap", "spinner", "Segment Gap (deg):", 1.0, 0, 20, 0.5, 1,
                         dynamic_group=style_controller_key, dynamic_show_on="segments"),
            ConfigOption("gauge_solid_arc_width", "spinner", "Solid Arc Width (px):", 15, 1, 100, 1, 0,
                         dynamic_group=style_controller_key, dynamic_show_on="solid"),
            ConfigOption("gauge_line_cap_style", "dropdown", "Line/Segment Cap Style:", "round",
                         options_dict={"Round": "round", "Square": "square", "Flat": "butt"})
        ]
        
        color_stops = [
            ConfigOption("gauge_color_gradient", "bool", "Enable Smooth Gradient:", "False"),
            ConfigOption("gauge_color_stop_count", "spinner", "Number of Colors:", 3, 2, 10, 1, 0)
        ]
        default_colors = ["rgba(0,255,0,0.8)", "rgba(255,255,0,0.8)", "rgba(255,0,0,0.8)", "rgba(0,255,255,1)","rgba(128,0,128,1)","rgba(255,165,0,1)","rgba(0,255,255,1)","rgba(255,105,180,1)","rgba(100,149,237,1)","rgba(255,255,255,1)"]
        for i in range(1, 11):
            label_suffix = " (Min)" if i == 1 else ""
            default_val = (i-1) * (100 / 2) if i <= 3 else (i-1) * (100/9)
            color_stops.extend([
                ConfigOption(f"gauge_percent{i}", "spinner", f"Percent for Color {i}{label_suffix}:", f"{default_val:.1f}", 0, 100, 1, 1),
                ConfigOption(f"gauge_color{i}", "color", f"Color {i}:", default_colors[i-1]),
            ])
        model["Gauge Colors & Stops"] = color_stops

        model["Gauge Geometry"] = [
            ConfigOption("gauge_start_angle", "spinner", "Start Angle (deg):", 135, 0, 359, 1, 0),
            ConfigOption("gauge_end_angle", "spinner", "End Angle (deg):", 45, 0, 359, 1, 0),
            ConfigOption("gauge_bg_radius_factor", "spinner", "BG Radius (% of Panel):", 0.85, 0.1, 1.5, 0.05, 2),
            ConfigOption("gauge_inner_radius_factor", "spinner", "Inner Radius (% of Panel):", 0.6, 0.1, 1.0, 0.05, 2),
            ConfigOption("gauge_outer_radius_factor", "spinner", "Outer Radius (% of Panel):", 0.8, 0.1, 1.0, 0.05, 2),
            ConfigOption("gauge_active_line_width", "spinner", "Active Stroke Width:", 2.5, 0.5, 10, 0.5, 1),
            ConfigOption("gauge_inactive_line_width", "spinner", "Inactive Stroke Width:", 1.5, 0.5, 10, 0.5, 1),
            ConfigOption("gauge_inactive_color", "color", "Inactive Color:", "rgba(80, 80, 80, 0.8)")
        ]
        model["Gauge Text"] = [
            ConfigOption("gauge_show_caption", "bool", "Show Caption Text:", "True"),
            ConfigOption("gauge_caption_font", "font", "Caption Font:", "Sans 12"),
            ConfigOption("gauge_caption_color", "color", "Caption Color:", "rgba(200,200,200,1)"),
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
        def build_gauge_config(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            key_prefix = f"{prefix}_" if prefix else ""
            
            if prefix is None:
                build_background_config_ui(content_box, panel_config, widgets, dialog, prefix="gauge_", title="Gauge Dial Background")

            color_count_spinner = widgets.get(f"{key_prefix}gauge_color_stop_count")
            if color_count_spinner:
                stop_widgets = []
                for i in range(1, 11):
                    val_widget = widgets.get(f"{key_prefix}gauge_percent{i}")
                    col_widget = widgets.get(f"{key_prefix}gauge_color{i}")
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
        self._layout_caption = None
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

    def _get_color_for_value(self, value):
        min_v = float(self.config.get("graph_min_value", 0.0)); max_v = float(self.config.get("graph_max_value", 100.0))
        v_range = max_v - min_v if max_v > min_v else 1.0
        
        num_stops = int(self.config.get("gauge_color_stop_count", 3))
        stops = []
        for i in range(1, num_stops + 1):
            try:
                percent = float(self.config.get(f"gauge_percent{i}")); val = min_v + (v_range * (percent / 100.0))
                col = self.config.get(f"gauge_color{i}"); stops.append({'val': val, 'col': col})
            except (ValueError, TypeError): continue
        stops.sort(key=lambda s: s['val'])

        if not stops: return "rgba(255,255,255,1)"
        
        clamped_value = min(max(value, min_v), max_v)

        if clamped_value <= stops[0]['val']: return stops[0]['col']
        if clamped_value >= stops[-1]['val']: return stops[-1]['col']
        
        for i in range(len(stops) - 1):
            s1, s2 = stops[i], stops[i+1]
            if s1['val'] <= clamped_value < s2['val']:
                if str(self.config.get("gauge_color_gradient", "False")).lower() != 'true': return s1['col']
                stop_v_range = s2['val'] - s1['val']
                factor = (clamped_value - s1['val']) / stop_v_range if stop_v_range > 0 else 0
                return self._interpolate_color(factor, s1['col'], s2['col']).to_string()
        
        return stops[-1]['col']

    def on_draw(self, area, ctx, width_float, height_float):
        width, height = int(width_float), int(height_float)
        if width <= 0 or height <= 0: return

        if not self._static_surface or self._last_draw_width != width or self._last_draw_height != height:
            self._static_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            static_ctx = cairo.Context(self._static_surface)
            cx, cy = width / 2, height / 2; min_dim = min(width, height)
            bg_radius = min_dim / 2 * float(self.config.get("gauge_bg_radius_factor", 0.85))
            if bg_radius > 0:
                static_ctx.save(); static_ctx.arc(cx, cy, bg_radius, 0, 2 * math.pi); static_ctx.clip()
                draw_cairo_background(static_ctx, width, height, self.config, "gauge_", self._cached_bg_pixbuf, {'type': 'circle', 'cx': cx, 'cy': cy, 'radius': bg_radius})
                static_ctx.restore()
            self._draw_inactive_arc(static_ctx, width, height)
            self._last_draw_width, self._last_draw_height = width, height
        ctx.set_source_surface(self._static_surface, 0, 0); ctx.paint()
        self._draw_active_arc(ctx, width, height)
        self._draw_text(ctx, width, height)

    def _draw_inactive_arc(self, ctx, width, height):
        cx, cy = width / 2, height / 2; min_dim = min(width, height)
        inner_r = min_dim / 2 * float(self.config.get("gauge_inner_radius_factor", 0.6))
        outer_r = min_dim / 2 * float(self.config.get("gauge_outer_radius_factor", 0.8))
        start_angle = math.radians(float(self.config.get("gauge_start_angle", 135))); end_angle = math.radians(float(self.config.get("gauge_end_angle", 45)))
        inactive_c = Gdk.RGBA(); inactive_c.parse(self.config.get("gauge_inactive_color")); inactive_width = float(self.config.get("gauge_inactive_line_width", 1.5))
        ctx.set_source_rgba(inactive_c.red, inactive_c.green, inactive_c.blue, inactive_c.alpha)
        
        style = self.config.get("gauge_style", "lines")
        num_items = int(self.config.get("gauge_num_lines" if style == "lines" else "gauge_num_segments", 60))
        total_angle = end_angle - start_angle; 
        if total_angle <= 0: total_angle += 2 * math.pi
        
        if style == "lines":
            ctx.set_line_width(inactive_width)
            angle_step = total_angle / (num_items - 1) if num_items > 1 else 0
            ctx.new_path()
            for i in range(num_items):
                angle = start_angle + i * angle_step
                ctx.move_to(cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r); ctx.line_to(cx + math.cos(angle) * outer_r, cy + math.sin(angle) * outer_r)
            ctx.stroke()
        elif style == "segments":
            ctx.set_line_width(inactive_width)
            segment_gap_rad = math.radians(float(self.config.get("gauge_segment_gap", 1.0)))
            total_gap_angle = (num_items - 1) * segment_gap_rad if num_items > 1 else 0
            angle_for_one_segment = (total_angle - total_gap_angle) / num_items if num_items > 0 else 0
            if angle_for_one_segment <= 0: return
            angle_step = angle_for_one_segment + segment_gap_rad
            for i in range(num_items):
                seg_start_angle = start_angle + i * angle_step
                seg_end_angle = seg_start_angle + angle_for_one_segment
                self._draw_segment_path(ctx, cx, cy, inner_r, outer_r, seg_start_angle, seg_end_angle)
                if str(self.config.get("gauge_segment_fill", "True")).lower() == 'true': ctx.fill()
                else: ctx.stroke()
        else: # Solid
            solid_width = float(self.config.get("gauge_solid_arc_width", 15))
            ctx.set_line_width(solid_width)
            ctx.new_path()
            ctx.arc(cx, cy, (inner_r + outer_r) / 2, start_angle, end_angle); ctx.stroke()
            
    def _draw_segment_path(self, ctx, cx, cy, inner_r, outer_r, start_a, end_a):
        ctx.new_path()
        ctx.arc(cx, cy, outer_r, start_a, end_a)
        ctx.line_to(cx + math.cos(end_a) * inner_r, cy + math.sin(end_a) * inner_r)
        ctx.arc_negative(cx, cy, inner_r, end_a, start_a)
        ctx.close_path()

    def _draw_active_arc(self, ctx, width, height):
        cx, cy = width / 2, height / 2; min_dim = min(width, height)
        inner_r = min_dim / 2 * float(self.config.get("gauge_inner_radius_factor", 0.6)); outer_r = min_dim / 2 * float(self.config.get("gauge_outer_radius_factor", 0.8))
        start_angle = math.radians(float(self.config.get("gauge_start_angle", 135))); end_angle = math.radians(float(self.config.get("gauge_end_angle", 45)))
        total_angle = end_angle - start_angle; 
        if total_angle <= 0: total_angle += 2 * math.pi
        min_v = float(self.config.get("graph_min_value", 0)); max_v = float(self.config.get("graph_max_value", 100)); v_range = max_v - min_v if max_v > min_v else 1
        value_ratio = (min(max(self._current_display_value, min_v), max_v) - min_v) / v_range
        
        style = self.config.get("gauge_style", "lines")
        num_items = int(self.config.get("gauge_num_lines" if style == "lines" else "gauge_num_segments", 60))
        active_items = int(round(value_ratio * num_items))
        
        active_width = float(self.config.get("gauge_active_line_width", 2.5))
        line_cap_map = {"square": cairo.LINE_CAP_SQUARE, "butt": cairo.LINE_CAP_BUTT, "round": cairo.LINE_CAP_ROUND}; line_cap_style = self.config.get("gauge_line_cap_style", "round")
        ctx.set_line_cap(line_cap_map.get(line_cap_style, cairo.LINE_CAP_ROUND))

        if style == "lines":
            ctx.set_line_width(active_width)
            angle_step = total_angle / (num_items - 1) if num_items > 1 else 0
            for i in range(active_items):
                segment_value = min_v + (i / (num_items - 1 if num_items > 1 else 1)) * v_range
                color_str = self._get_color_for_value(segment_value); color_rgba = Gdk.RGBA(); color_rgba.parse(color_str)
                ctx.set_source_rgba(color_rgba.red, color_rgba.green, color_rgba.blue, color_rgba.alpha)
                angle = start_angle + i * angle_step
                ctx.new_path()
                ctx.move_to(cx + math.cos(angle) * inner_r, cy + math.sin(angle) * inner_r); ctx.line_to(cx + math.cos(angle) * outer_r, cy + math.sin(angle) * outer_r); ctx.stroke()
        elif style == "segments":
            ctx.set_line_width(active_width)
            segment_gap_rad = math.radians(float(self.config.get("gauge_segment_gap", 1.0)))
            total_gap_angle = (num_items - 1) * segment_gap_rad if num_items > 1 else 0
            angle_for_one_segment = (total_angle - total_gap_angle) / num_items if num_items > 0 else 0
            if angle_for_one_segment <= 0: return
            angle_step = angle_for_one_segment + segment_gap_rad
            for i in range(active_items):
                segment_value = min_v + (i / (num_items - 1 if num_items > 1 else 1)) * v_range
                color_str = self._get_color_for_value(segment_value); color_rgba = Gdk.RGBA(); color_rgba.parse(color_str)
                ctx.set_source_rgba(color_rgba.red, color_rgba.green, color_rgba.blue, color_rgba.alpha)
                seg_start_angle = start_angle + i * angle_step
                seg_end_angle = seg_start_angle + angle_for_one_segment
                self._draw_segment_path(ctx, cx, cy, inner_r, outer_r, seg_start_angle, seg_end_angle)
                if str(self.config.get("gauge_segment_fill", "True")).lower() == 'true': ctx.fill_preserve()
                ctx.stroke()
        else: # Solid arc
            solid_width = float(self.config.get("gauge_solid_arc_width", 15))
            ctx.set_line_width(solid_width)
            is_gradient = str(self.config.get("gauge_color_gradient", "False")).lower() == 'true'
            if is_gradient:
                steps = 100; current_angle = start_angle
                angle_step = (total_angle * value_ratio) / steps if steps > 0 else 0
                for i in range(steps):
                    segment_value = min_v + ((i / (steps-1 if steps > 1 else 1)) * (value_ratio * v_range))
                    color_str = self._get_color_for_value(segment_value); color_rgba = Gdk.RGBA(); color_rgba.parse(color_str)
                    ctx.set_source_rgba(color_rgba.red, color_rgba.green, color_rgba.blue, color_rgba.alpha)
                    ctx.new_path()
                    ctx.arc(cx, cy, (inner_r + outer_r) / 2, current_angle, current_angle + angle_step); ctx.stroke()
                    current_angle += angle_step
            else:
                color_str = self._get_color_for_value(self._current_display_value); color_rgba = Gdk.RGBA(); color_rgba.parse(color_str)
                ctx.set_source_rgba(color_rgba.red, color_rgba.green, color_rgba.blue, color_rgba.alpha)
                ctx.new_path()
                ctx.arc(cx, cy, (inner_r + outer_r) / 2, start_angle, start_angle + total_angle * value_ratio); ctx.stroke()

    def _draw_text(self, ctx, width, height):
        cx, cy = width / 2, height / 2; v_offset = float(self.config.get("gauge_text_vertical_offset", "0")); spacing = float(self.config.get("gauge_text_spacing", "5"))
        if self._layout_value is None: self._layout_value = self.widget.create_pango_layout("")
        self._layout_value.set_font_description(Pango.FontDescription.from_string(self.config.get("gauge_value_font", "Sans Bold 48"))); self._layout_value.set_text(self.display_value_text, -1); _, log_v = self._layout_value.get_pixel_extents()
        if self._layout_unit is None: self._layout_unit = self.widget.create_pango_layout("")
        self._layout_unit.set_font_description(Pango.FontDescription.from_string(self.config.get("gauge_unit_font", "Sans 24"))); self._layout_unit.set_text(self.unit_text, -1); _, log_u = self._layout_unit.get_pixel_extents()
        if self._layout_caption is None: self._layout_caption = self.widget.create_pango_layout("")
        self._layout_caption.set_font_description(Pango.FontDescription.from_string(self.config.get("gauge_caption_font", "Sans 12"))); self._layout_caption.set_text(self.caption_text, -1); _, log_c = self._layout_caption.get_pixel_extents()
        show_caption = str(self.config.get("gauge_show_caption", "True")).lower() == 'true' and bool(self.caption_text); show_val = True; show_unit = bool(self.unit_text)
        total_h = sum(h for h, show in [(log_c.height, show_caption), (log_v.height, show_val), (log_u.height, show_unit)] if show)
        active_elements = sum([show_caption, show_val, show_unit]); 
        if active_elements > 1: total_h += (active_elements - 1) * spacing
        start_y = (cy - (total_h / 2)) + v_offset
        if show_caption:
            cap_c = Gdk.RGBA(); cap_c.parse(self.config.get("gauge_caption_color")); ctx.set_source_rgba(cap_c.red, cap_c.green, cap_c.blue, cap_c.alpha)
            ctx.move_to(cx - log_c.width / 2, start_y); PangoCairo.show_layout(ctx, self._layout_caption); start_y += log_c.height + spacing
        val_c = Gdk.RGBA(); val_c.parse(self.config.get("gauge_value_color")); ctx.set_source_rgba(val_c.red, val_c.green, val_c.blue, val_c.alpha)
        ctx.move_to(cx - log_v.width / 2, start_y); PangoCairo.show_layout(ctx, self._layout_value); start_y += log_v.height + spacing
        if show_unit:
            unit_c = Gdk.RGBA(); unit_c.parse(self.config.get("gauge_unit_color")); ctx.set_source_rgba(unit_c.red, unit_c.green, unit_c.blue, unit_c.alpha)
            ctx.move_to(cx - log_u.width / 2, start_y); PangoCairo.show_layout(ctx, self._layout_unit)

    def close(self):
        self._stop_animation_timer()
        super().close()

