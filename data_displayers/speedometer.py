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
        self._is_first_update = True
        self._current_display_value = 0.0
        self._target_value = 0.0
        
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())
        
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw_speedometer)
        return drawing_area

    def update_display(self, value):
        if not self.panel_ref: return # Guard against race condition on close
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
        model["Speedometer Range & Geometry"] = [
            ConfigOption("speedo_min_value", "spinner", "Min Value:", 0, 0, 10000, 1, 0),
            ConfigOption("speedo_max_value", "spinner", "Max Value:", 240, 1, 10000, 1, 0),
            ConfigOption("speedo_start_angle", "spinner", "Start Angle (deg):", 135, 0, 359, 1, 0),
            ConfigOption("speedo_end_angle", "spinner", "End Angle (deg):", 45, 0, 359, 1, 0),
            ConfigOption("speedo_padding", "spinner", "Padding (px):", 10, 0, 100, 1, 0)
        ]
        model["Speedometer Style"] = [
            ConfigOption("speedo_bg_color", "color", "Background Color:", "rgba(10,10,10,1)"),
            ConfigOption("speedo_dial_color", "color", "Dial Color:", "rgba(20,20,20,1)"),
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

    def apply_styles(self):
        super().apply_styles()
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

        diff = self._target_value - self._current_display_value
        if abs(diff) < 0.1:
            self._current_display_value = self._target_value
        else:
            # Simple easing for smoother animation
            self._current_display_value += diff * 0.1

        self.widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def on_draw_speedometer(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        # Background
        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("speedo_bg_color"))
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
        ctx.paint()

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
            except:
                pass 
            padding += font_size * 1.5

        radius = available_radius - padding
        if radius <= 0: return

        # Dial Face
        dial_color = Gdk.RGBA(); dial_color.parse(self.config.get("speedo_dial_color"))
        ctx.set_source_rgba(dial_color.red, dial_color.green, dial_color.blue, dial_color.alpha)
        ctx.arc(cx, cy, radius, 0, 2 * math.pi)
        ctx.fill()

        # Ticks and Numbers
        start_angle = math.radians(float(self.config.get("speedo_start_angle", 135)))
        end_angle = math.radians(float(self.config.get("speedo_end_angle", 45)))
        total_angle = end_angle - start_angle
        if total_angle <= 0: total_angle += 2 * math.pi
        
        min_v = float(self.config.get("speedo_min_value", 0))
        max_v = float(self.config.get("speedo_max_value", 240))
        v_range = max_v - min_v if max_v > min_v else 1

        num_major_ticks = int(self.config.get("speedo_major_tick_count", 9))
        num_minor_ticks = int(self.config.get("speedo_minor_ticks_per_major", 5))

        # Draw Ticks
        tick_color = Gdk.RGBA(); tick_color.parse(self.config.get("speedo_tick_color"))
        ctx.set_source_rgba(tick_color.red, tick_color.green, tick_color.blue, tick_color.alpha)
        
        for i in range(num_major_ticks):
            angle = start_angle + (i / (num_major_ticks - 1)) * total_angle
            ctx.set_line_width(3)
            ctx.move_to(cx + math.cos(angle) * (radius * 0.9), cy + math.sin(angle) * (radius * 0.9))
            ctx.line_to(cx + math.cos(angle) * radius, cy + math.sin(angle) * radius)
            ctx.stroke()

            if i < num_major_ticks - 1 and num_minor_ticks > 0:
                for j in range(1, num_minor_ticks + 1):
                    minor_angle = angle + (j / (num_minor_ticks * (num_major_ticks - 1))) * total_angle
                    ctx.set_line_width(1)
                    ctx.move_to(cx + math.cos(minor_angle) * (radius * 0.95), cy + math.sin(minor_angle) * (radius * 0.95))
                    ctx.line_to(cx + math.cos(minor_angle) * radius, cy + math.sin(minor_angle) * radius)
                    ctx.stroke()

        layout = PangoCairo.create_layout(ctx)

        # Draw Numbers
        if show_numbers:
            number_color = Gdk.RGBA(); number_color.parse(self.config.get("speedo_number_color"))
            ctx.set_source_rgba(number_color.red, number_color.green, number_color.blue, number_color.alpha)
            font_desc = Pango.FontDescription.from_string(self.config.get("speedo_number_font", "Sans Bold 12"))
            layout.set_font_description(font_desc)
            
            num_radius_factor = 0.8 if number_position == "inside" else 1.15
            num_radius = radius * num_radius_factor

            for i in range(num_major_ticks):
                angle = start_angle + (i / (num_major_ticks - 1)) * total_angle
                value = int(min_v + (i / (num_major_ticks - 1)) * v_range)
                layout.set_text(str(value), -1)
                _, log = layout.get_pixel_extents()
                ctx.move_to(cx + math.cos(angle) * num_radius - log.width/2, 
                            cy + math.sin(angle) * num_radius - log.height/2)
                PangoCairo.show_layout(ctx, layout)

        # Draw Digital Text
        v_offset = float(self.config.get("speedo_text_vertical_offset", 0))
        
        # Prepare text layouts to get their sizes
        layout_v = PangoCairo.create_layout(ctx)
        layout_v.set_font_description(Pango.FontDescription.from_string(self.config.get("speedo_value_font")))
        layout_v.set_text(self.display_value_text, -1)
        _, log_v = layout_v.get_pixel_extents()

        layout_u = PangoCairo.create_layout(ctx)
        layout_u.set_font_description(Pango.FontDescription.from_string(self.config.get("speedo_unit_font")))
        layout_u.set_text(self.unit_text, -1)
        _, log_u = layout_u.get_pixel_extents()

        spacing = float(self.config.get("speedo_text_spacing", 5))
        total_text_height = 0
        if str(self.config.get("speedo_show_value_text", "True")).lower() == 'true':
            total_text_height += log_v.height
        if str(self.config.get("speedo_show_unit_text", "True")).lower() == 'true':
            total_text_height += log_u.height
        if str(self.config.get("speedo_show_value_text", "True")).lower() == 'true' and \
           str(self.config.get("speedo_show_unit_text", "True")).lower() == 'true':
            total_text_height += spacing
        
        start_y = (cy - total_text_height / 2) + v_offset

        if str(self.config.get("speedo_show_value_text", "True")).lower() == 'true':
            val_color = Gdk.RGBA(); val_color.parse(self.config.get("speedo_value_color"))
            ctx.set_source_rgba(val_color.red, val_color.green, val_color.blue, val_color.alpha)
            ctx.move_to(cx - log_v.width/2, start_y)
            PangoCairo.show_layout(ctx, layout_v)
            start_y += log_v.height + spacing

        if str(self.config.get("speedo_show_unit_text", "True")).lower() == 'true':
            unit_color = Gdk.RGBA(); unit_color.parse(self.config.get("speedo_unit_color"))
            ctx.set_source_rgba(unit_color.red, unit_color.green, unit_color.blue, unit_color.alpha)
            ctx.move_to(cx - log_u.width/2, start_y)
            PangoCairo.show_layout(ctx, layout_u)

        # Draw Needle
        value_ratio = (min(max(self._current_display_value, min_v), max_v) - min_v) / v_range
        needle_angle = start_angle + value_ratio * total_angle
        
        needle_color = Gdk.RGBA(); needle_color.parse(self.config.get("speedo_needle_color"))
        ctx.set_source_rgba(needle_color.red, needle_color.green, needle_color.blue, needle_color.alpha)
        ctx.set_line_width(3)
        
        ctx.save()
        ctx.translate(cx, cy)
        ctx.rotate(needle_angle)
        ctx.move_to(-radius * 0.1, 0)
        ctx.line_to(radius * 0.85, 0)
        ctx.stroke()
        ctx.restore()
        
        # Center Hub
        ctx.arc(cx, cy, radius * 0.05, 0, 2 * math.pi)
        ctx.fill()
