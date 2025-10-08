#data_sources/fan_speed.py
from data_source import DataSource
from config_dialog import ConfigOption
from update_manager import update_manager
import psutil
import threading
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from sensor_cache import SENSOR_CACHE

class FanSpeedDataSource(DataSource):
    """Data source for fetching fan RPM using psutil for efficiency."""
    def __init__(self, config):
        super().__init__(config)
        self._available_fans_cache = None

    @staticmethod
    def _discover_fans_statically():
        """Statically discovers available fans using psutil, creating robust keys."""
        if not hasattr(psutil, "sensors_fans"):
            return {"": {"display_name": "psutil fans not supported"}}
            
        fans = {}
        try:
            fan_data = psutil.sensors_fans()
            if not fan_data:
                return {"": {"display_name": "No fans found by psutil"}}
            
            for chip, entries in fan_data.items():
                for i, fan in enumerate(entries):
                    unique_key = f"{chip}::{i}"
                    label = fan.label if fan.label else f"Fan {i+1}"
                    display_name = f"{chip} / {label}"
                    fans[unique_key] = {"display_name": display_name}
        except Exception as e:
            print(f"FanSpeedDataSource: Error discovering fans with psutil: {e}")
            return {"": {"display_name": "Error reading fan data"}}
        return fans

    def get_data(self):
        """Fetches the current RPM for the selected fan using an index-based key."""
        # --- OPTIMIZATION: Get data from the central psutil cache ---
        fan_data = update_manager.get_cached_data('sensors_fans', lambda: {})
        if not fan_data:
            return {"rpm": None}

        selected_key = self.config.get("selected_fan_key", "")
        if '::' not in selected_key:
            # If no key is selected, try to select the first available one
            cached_fans = SENSOR_CACHE.get('fan_speed', {})
            first_valid_key = next((k for k in cached_fans if k), None)
            if first_valid_key:
                selected_key = first_valid_key
                self.config["selected_fan_key"] = selected_key
            else:
                return {"rpm": None}
            
        try:
            chip, index_str = selected_key.split('::', 1)
            index = int(index_str)
            
            if chip in fan_data and 0 <= index < len(fan_data[chip]):
                return {"rpm": fan_data[chip][index].current}
        except (ValueError, IndexError, Exception) as e:
            print(f"FanSpeedDataSource: Could not read RPM for key '{selected_key}': {e}")

        return {"rpm": None}

    def get_display_string(self, data):
        """Returns the formatted RPM value."""
        if not isinstance(data, dict) or data.get('rpm') is None:
            return "N/A"
        return f"{data.get('rpm'):.0f} RPM"

    def get_primary_label_string(self, data):
        """Returns the display name of the currently monitored fan."""
        selected_key = self.config.get("selected_fan_key", "")
        
        cached_fans = SENSOR_CACHE.get('fan_speed', {})
        fan_info = cached_fans.get(selected_key, {})
        
        display_name = fan_info.get('display_name', 'Fan Speed')
        
        simple_name = display_name.split('/')[-1].strip()
        return f"Fan: {simple_name}"

    def get_secondary_display_string(self, data):
        """Returns an empty string as there is no secondary metric for fans."""
        return ""

    def get_numerical_value(self, data): 
        """Returns the raw RPM value from the data dictionary."""
        if data is None:
            return None
        return data.get("rpm")
    
    @staticmethod
    def get_config_model():
        opts = {"Scanning...": ""}
        
        model = DataSource.get_config_model()
        model["Fan Selection"] = [ConfigOption("selected_fan_key", "dropdown", "Monitored Fan:", "", options_dict=opts, tooltip="Which fan to monitor.\\nNote: After updating, you may need to re-select your fan here.")]
        model["Alarm"][1] = ConfigOption(f"data_alarm_high_value", "scale", "Alarm High RPM:", "3000.0", 0.0, 10000.0, 100.0, 0)
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min RPM:", "0.0", 0.0, 5000.0, 10.0, 0),
            ConfigOption("graph_max_value", "spinner", "Graph Max RPM:", "3000.0", 100.0, 10000.0, 100.0, 0)
        ]
        return model
    
    @staticmethod
    def get_alarm_unit(): return "RPM"

    def get_configure_callback(self):
        
        def _repopulate_sensor_dropdown(widgets, panel_config, prefix):
            """Helper to fill the sensor dropdown once data is available."""
            key_prefix = f"{prefix}opt_" if prefix else ""
            try:
                sensor_combo_key = f"{key_prefix}selected_fan_key"
                sensor_combo = widgets.get(sensor_combo_key)
                if not sensor_combo: return

                sensor_combo.remove_all()
                
                fans = SENSOR_CACHE.get('fan_speed', {})
                if not fans or all(k == "" for k in fans):
                    sensor_combo.append(id="", text="No fans found")
                else:
                    sorted_fans = sorted(fans.items(), key=lambda i: i[1]['display_name'])
                    for key, data in sorted_fans:
                        sensor_combo.append(id=key, text=data['display_name'])

                current_selection = panel_config.get(sensor_combo_key)
                if not current_selection or not sensor_combo.set_active_id(current_selection):
                    sensor_combo.set_active(0)
                    new_active_id = sensor_combo.get_active_id()
                    if new_active_id:
                        panel_config[sensor_combo_key] = new_active_id
            except KeyError as e:
                print(f"FanSpeedDataSource _repopulate_sensor_dropdown KeyError: {e}")

        def setup_dynamic_title_logic(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            # This function now only handles repopulating the dropdown.
            # The title logic is centralized in data_panel.py.
            _repopulate_sensor_dropdown(widgets, panel_config, prefix)

        return setup_dynamic_title_logic
