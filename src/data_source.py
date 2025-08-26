# data_source.py
from abc import ABC, abstractmethod
from config_dialog import ConfigOption
from utils import populate_defaults_from_model
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib


class DataSource(ABC):
    """
    Abstract base class for all data sources. Each subclass is responsible for
    fetching a specific piece of system data (e.g., CPU temp, memory usage)
    and defining its own configuration options, including alarms.
    """
    def __init__(self, config):
        self.config = config
        if not hasattr(self, 'alarm_config_prefix'):
            self.alarm_config_prefix = "data_"
        populate_defaults_from_model(self.config, self.get_config_model())

    @abstractmethod
    def get_data(self):
        """
        Fetches and returns the specific data point (e.g., a float, string, dict).
        This method is designed to be called in a separate thread.
        Should return None on failure.
        """
        pass

    def get_display_string(self, value):
        """
        Returns a formatted string representation of the data for display.
        This base implementation is a safe fallback.
        """
        if value is None: return "N/A"
        
        # --- FIX: The original implementation would crash if 'value' was a dictionary. ---
        # This version safely attempts to get a numerical value first.
        # If that fails, it falls back to a simple string representation.
        try:
            numerical_value = self.get_numerical_value(value)
            if numerical_value is not None and isinstance(numerical_value, (int, float)):
                return f"{numerical_value:.1f}"
        except (TypeError, ValueError):
            pass

        # Fallback for non-numerical data or complex dicts
        if isinstance(value, dict):
             # Don't show a raw dictionary, return a placeholder
             return "..." 
        return str(value)
        
    def get_numerical_value(self, data):
        """
        Returns the primary numerical value from the data, used for graphing or calculations.
        This allows data to be returned as a dict, but still easily graphed.
        """
        if isinstance(data, dict): return data.get('percent')
        return data

    def get_tooltip_string(self, data): return ""

    def get_primary_label_string(self, data):
        """
        Optional: Returns a string for a primary, contextual label
        (e.g., a mount path for a disk or the name of a CPU core).
        By default, it returns the secondary display string if available, otherwise empty.
        """
        return self.get_secondary_display_string(data)
        
    @staticmethod
    def get_config_model():
        """
        Returns the configuration model (a dictionary of ConfigOption objects)
        for this data source, including update interval and alarm settings.
        """
        alarm_config_prefix = "data_"
        sound_file_filters = [{"name": "Audio Files", "patterns": ["*.mp3", "*.wav", "*.ogg", "*.flac"]}, {"name": "All Files", "patterns": ["*"]}]
        
        return {
            "Data Source & Update": [
                ConfigOption("update_interval_seconds", "scale", "Update Interval (sec):", "2.0", 0.1, 60, 0.1, 1),
            ],
            "Alarm": [
                ConfigOption(f"{alarm_config_prefix}enable_alarm", "bool", "Enable Value Alarm:", "False"),
                ConfigOption(f"{alarm_config_prefix}alarm_high_value", "scale", f"Alarm High Value ({DataSource.get_alarm_unit()}):", "80.0", 0.0, 150.0, 1.0, 1),
                ConfigOption(f"{alarm_config_prefix}alarm_color", "color", "Alarm Flash Color:", "rgba(255,0,0,0.6)"),
                ConfigOption(f"{alarm_config_prefix}alarm_sound_file", "file", "Alarm Sound File:", "", tooltip="Select a sound file (WAV, MP3, OGG)", file_filters=sound_file_filters)
            ]
        }
    
    def get_secondary_display_string(self, data): return ""
    
    def get_configure_callback(self):
        """A custom callback to dynamically show/hide alarm options."""
        def setup_dynamic_alarm_options(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            config_prefix = self.alarm_config_prefix
            enable_widget = widgets.get(f"{config_prefix}enable_alarm")
            
            alarm_widgets_to_toggle = []
            for key in widgets:
                if key.startswith(config_prefix) and key != f"{config_prefix}enable_alarm":
                    if widgets[key].get_parent():
                        alarm_widgets_to_toggle.append(widgets[key].get_parent())

            def on_alarm_toggled(switch, gparam):
                is_active = switch.get_active()
                for w in alarm_widgets_to_toggle:
                    w.set_visible(is_active)

            if enable_widget:
                enable_widget.connect("notify::active", on_alarm_toggled)
                GLib.idle_add(on_alarm_toggled, enable_widget, None)

        return setup_dynamic_alarm_options
    
    @staticmethod
    def get_alarm_unit(): return "value"

    def close(self):
        """Optional cleanup method for data sources."""
        pass
