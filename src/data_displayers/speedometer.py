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

class SpeedometerDisplayer(DataDisplayer):
    """
    Displays data as a classic car speedometer with a needle, tick marks,
    and configurable text labels.
    """
    def __init__(self, panel_ref, config):
        self.current_value = 0.0
        self.display_value_text = "0"
        self.unit_text = ""
        
        # Animation state
        self._animation_timer_id = None
        self._current_display_value = float(config.get("graph_min_value", 0.0))
        self._target_value = self._current_display_value
        
        # Caching state
        self._static_surface = None
        self._last_draw_width, self._last_draw_height = -1, -1
        self._cached_bg_pixbuf = None
        self._cached_image_path = None
        self._layout_value = None
        self._layout_unit = None
        self._layout_tick_numbers = None # For static drawing
        
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def update_display(self, value, **kwargs):
        source = self.panel_ref.data_source
        if 'source_override' in kwargs and kwargs['source_override']:
            source = kwargs['source_override']
            
        new_value = source.get_numerical_value(value) or 0.0
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

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        model["Speedometer Geometry"] = [
            ConfigOption("speedo_start_angle", "spinner", "Start Angle (deg):", 135, 0, 359, 1, 0),
            ConfigOption("speedo_end_angle", "spinner", "End Angle (deg):", 45, 0, 359, 1, 0),
            ConfigOption("speedo_padding", "spinner", "Padding (px):", 10, 0, 100, 1, 0)
        ]
        model["Speedometer Style"] = [
            ConfigOption("speedo_needle_color", "color", "Needle Color:", "rgba(255,50,50,1)"),
            ConfigOption("speedo_tick_color", "color", "Tick Mark Color:", "rgba(255,255,255,0.7)"),
            ConfigOption("speedo_number_color", "color", "Number Color:", "rgba(255,255,255,0.9)")
        ]
        model["Ticks & Numbers"] = [
            ConfigOption("speedo_major_tick_count", "spinner", "Major Ticks:", 9, 2, 50, 1, 0),
            ConfigOption("speedo_minor_ticks_per_major", "spinner", "Minor Ticks:", 5, 0, 10, 1, 0),
            ConfigOption("speedo_show_numbers", "bool", "Show Numbers:", "True"),
            ConfigOption("speedo_number_position", "dropdown", "Number Position:", "inside", 
                         options_dict={"Inside Dial": "inside", "Outside Dial": "outside"}),
            ConfigOption("speedo_number_font", "font", "Number Font:", "Sans Bold 12"),
        ]
        model["Speedometer Text"] = [
            ConfigOption("speedo_show_value_text", "bool", "Show Digital Value:", "True"),
            ConfigOption("speedo_value_font", "font", "Value Font:", "Monospace Bold 28"),
            ConfigOption("speedo_value_color", "color", "Value Color:", "rgba(255,255,255,1)"),
            ConfigOption("speedo_show_unit_text", "bool", "Show Unit Text:", "True"),
            ConfigOption("speedo_unit_font", "font", "Unit Font:", "Sans 14"),
            ConfigOption("speedo_unit_color", "color", "Unit Color:", "rgba(200,200,200,1)"),
            ConfigOption("speedo_text_spacing", "spinner", "Text Spacing (px):", 5, 0, 50, 1, 0),
            ConfigOption("speedo_text_vertical_offset", "spinner", "V. Offset:", 0, -100, 100, 1, 0)
        ]
        return model

    def get_configure_callback(self):
        def build_dial_config(dialog, content_box, widgets, available_sources, panel_config):
            build_background_config_ui(content_box, panel_config, widgets, dialog, prefix="speedo_", title="Dial Background")
        return build_dial_config

    def apply_styles(self):
        super().apply_styles()
        image_path = self.config.get("speedo_background_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            try:
                self._cached_bg_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
            except GLib.Error as e:
                print(f"Error loading speedometer image: {e}")
                self._cached_bg_pixbuf = None

        self._static_surface = None # Invalidate cache
        self._layout_value = None
        self._layout_unit = None
        self._layout_tick_numbers = None
        self.widget.queue_draw()

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

        needs_redraw = False
        diff = self._target_value - self._current_display_value
        
        if abs(diff) < 0.1:
            if self._current_display_value != self._target_value:
                self._current_display_value = self._target_value
                needs_redraw = True
        else:
            self._current_display_value += diff * 0.1
            needs_redraw = True

        if needs_redraw:
            self.widget.queue_draw()
            
        return GLib.SOURCE_CONTINUE

    def on_draw(self, area, ctx, width_float, height_float):
        width, height = int(width_float), int(height_float)
        if width <= 0 or height <= 0: return

        if not self._static_surface or self._last_draw_width != width or self._last_draw_height != height:
            self._static_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            static_ctx = cairo.Context(self._static_surface)
            
            static_ctx.set_source_rgba(0, 0, 0, 0); static_ctx.set_operator(cairo.OPERATOR_SOURCE); static_ctx.paint()
            static_ctx.set_operator(cairo.OPERATOR_OVER)

            cx, cy = width / 2, height / 2
            padding = float(self.config.get("speedo_padding", 10))
            number_position = self.config.get("speedo_number_position", "inside")
            show_numbers = str(self.config.get("speedo_show_numbers", "True")).lower() == 'true'
            available_radius = min(width, height) / 2
            
            if number_position == "outside" and show_numbers:
                font_size = 12 
                try:
                    font_desc = Pango.FontDescription.from_string(self.config.get("speedo_number_font", "Sans Bold 12"))
                    font_size = font_desc.get_size() / Pango.SCALE 
                except: pass 
                padding += font_size * 1.5
            
            radius = available_radius - padding
            if radius > 0:
                static_ctx.save(); static_ctx.arc(cx, cy, radius, 0, 2 * math.pi); static_ctx.clip()
                
                shape_info = {'type': 'circle', 'cx': cx, 'cy': cy, 'radius': radius}
                draw_cairo_background(static_ctx, width, height, self.config, "speedo_",
                                      self._cached_bg_pixbuf, shape_info)

                static_ctx.restore()

                start_angle = math.radians(float(self.config.get("speedo_start_angle", 135))); end_angle = math.radians(float(self.config.get("speedo_end_angle", 45)))
                total_angle = end_angle - start_angle; 
                if total_angle <= 0: total_angle += 2 * math.pi
                min_v = float(self.config.get("graph_min_value", 0)); max_v = float(self.config.get("graph_max_value", 100)); v_range = max_v - min_v if max_v > min_v else 1
                num_major_ticks = int(self.config.get("speedo_major_tick_count", 9)); num_minor_ticks = int(self.config.get("speedo_minor_ticks_per_major", 5))
                tick_color = Gdk.RGBA(); tick_color.parse(self.config.get("speedo_tick_color")); static_ctx.set_source_rgba(tick_color.red, tick_color.green, tick_color.blue, tick_color.alpha)
                
                for i in range(num_major_ticks):
                    angle = start_angle + (i / (num_major_ticks - 1)) * total_angle; static_ctx.set_line_width(3)
                    static_ctx.move_to(cx + math.cos(angle) * (radius * 0.9), cy + math.sin(angle) * (radius * 0.9)); static_ctx.line_to(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius); static_ctx.stroke()
                    if i < num_major_ticks - 1 and num_minor_ticks > 0:
                        for j in range(1, num_minor_ticks + 1):
                            minor_angle = angle + (j / (num_minor_ticks * (num_major_ticks - 1))) * total_angle; static_ctx.set_line_width(1)
                            static_ctx.move_to(cx + math.cos(minor_angle) * (radius * 0.95), cy + math.sin(minor_angle) * (radius * 0.95)); static_ctx.line_to(cx + math.cos(minor_angle) * radius, cy + math.sin(minor_angle) * radius); static_ctx.stroke()
                
                if show_numbers:
                    number_color = Gdk.RGBA(); number_color.parse(self.config.get("speedo_number_color")); static_ctx.set_source_rgba(number_color.red, number_color.green, number_color.blue, number_color.alpha)
                    if self._layout_tick_numbers is None:
                        self._layout_tick_numbers = self.widget.create_pango_layout("")
                    self._layout_tick_numbers.set_font_description(Pango.FontDescription.from_string(self.config.get("speedo_number_font", "Sans Bold 12")))
                    num_radius = radius * (0.8 if number_position == "inside" else 1.15)
                    for i in range(num_major_ticks):
                        angle = start_angle + (i / (num_major_ticks - 1)) * total_angle
                        value = int(min_v + (i / (num_major_ticks - 1)) * v_range)
                        self._layout_tick_numbers.set_text(str(value), -1); _, log = self._layout_tick_numbers.get_pixel_extents()
                        static_ctx.move_to(cx + math.cos(angle) * num_radius - log.width/2, cy + math.sin(angle) * num_radius - log.height/2); PangoCairo.show_layout(static_ctx, self._layout_tick_numbers)

            self._last_draw_width, self._last_draw_height = width, height

        ctx.set_source_surface(self._static_surface, 0, 0); ctx.paint()

        cx, cy = width / 2, height / 2
        padding = float(self.config.get("speedo_padding", 10))
        if self.config.get("speedo_number_position", "inside") == "outside" and str(self.config.get("speedo_show_numbers", "True")).lower() == 'true':
            font_size = 12; 
            try: font_size = Pango.FontDescription.from_string(self.config.get("speedo_number_font")).get_size() / Pango.SCALE
            except: pass
            padding += font_size * 1.5
        radius = (min(width, height) / 2) - padding
        if radius <= 0: return

        v_offset = float(self.config.get("speedo_text_vertical_offset", 0))
        
        if self._layout_value is None: self._layout_value = self.widget.create_pango_layout("")
        self._layout_value.set_font_description(Pango.FontDescription.from_string(self.config.get("speedo_value_font"))); self._layout_value.set_text(self.display_value_text, -1); _, log_v = self._layout_value.get_pixel_extents()
        
        if self._layout_unit is None: self._layout_unit = self.widget.create_pango_layout("")
        self._layout_unit.set_font_description(Pango.FontDescription.from_string(self.config.get("speedo_unit_font"))); self._layout_unit.set_text(self.unit_text, -1); _, log_u = self._layout_unit.get_pixel_extents()
        
        spacing = float(self.config.get("speedo_text_spacing", 5)); total_text_height = 0
        if str(self.config.get("speedo_show_value_text", "True")).lower() == 'true': total_text_height += log_v.height
        if str(self.config.get("speedo_show_unit_text", "True")).lower() == 'true': total_text_height += log_u.height
        if str(self.config.get("speedo_show_value_text", "True")).lower() == 'true' and str(self.config.get("speedo_show_unit_text", "True")).lower() == 'true': total_text_height += spacing
        start_y = (cy - total_text_height / 2) + v_offset
        if str(self.config.get("speedo_show_value_text", "True")).lower() == 'true':
            val_color = Gdk.RGBA(); val_color.parse(self.config.get("speedo_value_color")); ctx.set_source_rgba(val_color.red, val_color.green, val_color.blue, val_color.alpha)
            ctx.move_to(cx - log_v.width/2, start_y); PangoCairo.show_layout(ctx, self._layout_value); start_y += log_v.height + spacing
        if str(self.config.get("speedo_show_unit_text", "True")).lower() == 'true':
            unit_color = Gdk.RGBA(); unit_color.parse(self.config.get("speedo_unit_color")); ctx.set_source_rgba(unit_color.red, unit_color.green, unit_color.blue, unit_color.alpha)
            ctx.move_to(cx - log_u.width/2, start_y); PangoCairo.show_layout(ctx, self._layout_unit)

        min_v = float(self.config.get("graph_min_value", 0)); max_v = float(self.config.get("graph_max_value", 100)); v_range = max_v - min_v if max_v > min_v else 1
        start_angle = math.radians(float(self.config.get("speedo_start_angle", 135))); end_angle = math.radians(float(self.config.get("speedo_end_angle", 45)))
        total_angle = end_angle - start_angle;
        if total_angle <= 0: total_angle += 2 * math.pi
        
        value_ratio = (min(max(self._current_display_value, min_v), max_v) - min_v) / v_range
        needle_angle = start_angle + value_ratio * total_angle
        
        needle_color = Gdk.RGBA(); needle_color.parse(self.config.get("speedo_needle_color")); ctx.set_source_rgba(needle_color.red, needle_color.green, needle_color.blue, needle_color.alpha)
        ctx.set_line_width(3); ctx.save(); ctx.translate(cx, cy); ctx.rotate(needle_angle)
        ctx.move_to(-radius * 0.1, 0); ctx.line_to(radius * 0.85, 0); ctx.stroke(); ctx.restore()
        
        ctx.arc(cx, cy, radius * 0.05, 0, 2 * math.pi); ctx.fill()

    def close(self):
        self._stop_animation_timer()
        super().close()

