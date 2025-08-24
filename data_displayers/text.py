import gi
from data_displayer import DataDisplayer
from config_dialog import ConfigOption
from ui_helpers import ScrollingLabel
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Pango

class TextDisplayer(DataDisplayer):
    def __init__(self, panel_ref, config):
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        self.overlay = Gtk.Overlay()
        self.text_widget = ScrollingLabel(hexpand=True, valign=Gtk.Align.CENTER)
        self.overlay.set_child(self.text_widget)
        self.alarm_icon_area = Gtk.DrawingArea(content_width=20, content_height=20, halign=Gtk.Align.END, valign=Gtk.Align.END, margin_end=5, margin_bottom=5, visible=False)
        self.alarm_icon_area.set_draw_func(self._draw_alarm_icon)
        self.overlay.add_overlay(self.alarm_icon_area)
        return self.overlay

    def update_display(self, value):
        if not self.panel_ref: return # Guard against race condition on close
        final_str = ""
        if self.is_clock_source and isinstance(value, dict) and "datetime" in value:
            display_mode = self.config.get("text_display_mode", "time_only") 
            time_str = self.panel_ref.data_source.get_display_string(value)
            date_str = self.panel_ref.data_source.get_secondary_display_string(value)
            tz_name = self.panel_ref.data_source.get_timezone_display_string(value)
            
            if display_mode == "time_only": final_str = time_str
            elif display_mode == "time_date": final_str = f"{time_str}\n{date_str}"
            elif display_mode == "time_date_tz": final_str = f"{time_str}\n{date_str}\n{tz_name}"
            else: final_str = time_str
            
            is_ringing = value.get("is_ringing", False)
            if is_ringing and not self.panel_ref.is_in_alarm_state: self.panel_ref.enter_alarm_state()
            elif not is_ringing and self.panel_ref.is_in_alarm_state: self.panel_ref.exit_alarm_state()
            
            is_any_alarm_set = bool(self.panel_ref.data_source.get_active_alarms())
            show_icon = str(self.config.get("show_alarm_icon", "True")).lower() == 'true'
            self.alarm_icon_area.set_visible(show_icon and (is_any_alarm_set or is_ringing))
        else:
            final_str = self.panel_ref.data_source.get_display_string(value)
            self.alarm_icon_area.set_visible(False)
            
        self.text_widget.set_text(final_str)
        if self.alarm_icon_area.get_visible(): self.alarm_icon_area.queue_draw()
        self.panel_ref.set_tooltip_text(self.panel_ref.data_source.get_tooltip_string(value))

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        model["Display"] = [
            ConfigOption("font", "font", "Content Font:", "Sans 10"),
            ConfigOption("text_color", "color", "Content Text Color:", "#E0E0E0"),
            ConfigOption("text_display_mode", "dropdown", "Text Content (for Clocks):", "time_only", 
                         options_dict={"Time Only": "time_only", "Time and Date": "time_date", "Time, Date & Timezone": "time_date_tz"}, 
                         tooltip="Select what information to display for clock panels.")
        ]
        model["Alarm Icon (for Clocks)"] = [
            ConfigOption("show_alarm_icon", "bool", "Show Alarm Icon:", "True"),
            ConfigOption("alarm_icon_size", "spinner", "Icon Size (px):", 20, 12, 48, 1, 0),
            ConfigOption("alarm_icon_base_color", "color", "Icon Base Color:", "rgba(128,128,128,0.7)"),
            ConfigOption("alarm_icon_set_color", "color", "Icon Set Color:", "rgba(255,255,255,0.9)"),
            ConfigOption("alarm_icon_ringing_color", "color", "Icon Ringing Color:", "rgba(255,0,0,1.0)"),
        ]
        return model

    def apply_styles(self):
        super().apply_styles()
        font_desc = Pango.FontDescription.from_string(self.config.get("font", "Sans 10"))
        self.text_widget.set_font_description(font_desc)
        rgba = Gdk.RGBA(); rgba.parse(self.config.get("text_color", "#E0E0E0")); self.text_widget.set_color(rgba)
        icon_size = int(self.config.get("alarm_icon_size", 20))
        self.alarm_icon_area.set_content_width(icon_size)
        self.alarm_icon_area.set_content_height(icon_size)
        self.alarm_icon_area.queue_draw()
