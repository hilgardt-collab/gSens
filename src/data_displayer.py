# /data_displayer.py
import gi
from abc import ABC, abstractmethod
import math
import cairo

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk

class DataDisplayer(ABC):
    def __init__(self, panel_ref, config):
 
        self._panel_ref = panel_ref
        self.config = config
        self.widget = self._create_widget()
        self.is_clock_source = False

    @property
    def panel_ref(self):
        return self._panel_ref

    @panel_ref.setter
    def panel_ref(self, value):
        self._panel_ref = value

    @abstractmethod
    def _create_widget(self):
        pass

    def get_widget(self):
        return self.widget
    def update_display(self, value):
        pass
    @staticmethod
    def get_config_model():
        return {}
    def get_configure_callback(self):
        return None
    def apply_styles(self):
        pass

    @staticmethod
    def get_config_key_prefixes():
        """
        Returns a list of unique prefixes used for dynamically generated
        config keys, e.g., ['speedo_', 'graph_']. The config manager uses
        this to find all relevant styles to save in the theme.
        """
        return []
        
    def get_all_style_keys(self):
        """
        Returns a set of all configuration keys that are considered part of
        this displayer's style. Used for copy/paste/save operations.
        By default, it derives keys from the config model.
        """
        model = self.get_config_model()
        return {opt.key for section in model.values() for opt in section}

    def reset_state(self):
        """Optional method to reset any internal state when config changes."""
        pass

    def close(self):
        """
        Breaks the reference cycle between the displayer and the panel
        to ensure proper garbage collection and prevent thread leaks.
        """
        self.panel_ref = None

    def _interpolate_color(self, factor, c1_str, c2_str):
        color1 = Gdk.RGBA(); color1.parse(c1_str)
        color2 = Gdk.RGBA(); color2.parse(c2_str)
        inter_color = Gdk.RGBA()
        inter_color.red = color1.red + factor * (color2.red - color1.red)
        inter_color.green = color1.green + factor * (color2.green - color1.green)
        inter_color.blue = color1.blue + factor * (color2.blue - color1.blue)
        inter_color.alpha = color1.alpha + factor * (color2.alpha - color1.alpha)
        return inter_color

    def _draw_alarm_icon(self, area, context, width, height):
        if self.panel_ref is None: return
        is_in_alarm_state = self.panel_ref.is_in_alarm_state
        is_any_alarm_set = False
        if self.is_clock_source and hasattr(self.panel_ref.data_source, 'get_active_alarms'):
            is_any_alarm_set = bool(self.panel_ref.data_source.get_active_alarms())
        icon_target_size = float(self.config.get("alarm_icon_size", 20))
        if is_in_alarm_state:
            color_str = self.config.get("alarm_icon_ringing_color", "rgba(255,0,0,1.0)")
        elif is_any_alarm_set:
            color_str = self.config.get("alarm_icon_set_color", "rgba(255,255,255,0.9)")
        else:
            color_str = self.config.get("alarm_icon_base_color", "rgba(128,128,128,0.7)")
        rgba = Gdk.RGBA(); rgba.parse(color_str)
        context.save()
        scale_factor = min(1.0, width / icon_target_size, height / icon_target_size)
        context.translate((width - icon_target_size * scale_factor) / 2, (height - icon_target_size * scale_factor) / 2)
        context.scale(scale_factor, scale_factor)
        center_x, center_y, radius = icon_target_size/2, icon_target_size/2, icon_target_size/2 * 0.9
        context.new_path(); context.arc(center_x, center_y, radius, 0, 2*math.pi); context.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha); context.set_line_width(1.5); context.stroke()
        h_len, m_len = radius*0.5, radius*0.7
        h_angle, m_angle = (10/12)*2*math.pi - math.pi/2, (2/12)*2*math.pi - math.pi / 2
        context.new_path(); context.move_to(center_x, center_y); context.line_to(center_x+h_len*math.cos(h_angle), center_y+h_len*math.sin(h_angle)); context.set_line_width(1.5); context.set_line_cap(cairo.LINE_CAP_ROUND); context.stroke()
        context.new_path(); context.move_to(center_x, center_y); context.line_to(center_x+m_len*math.cos(m_angle), center_y+m_len*math.sin(m_angle)); context.set_line_width(1.5); context.set_line_cap(cairo.LINE_CAP_ROUND); context.stroke()
        context.restore()
