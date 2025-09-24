# /data_sources/system_temp.py
from data_source import DataSource
from utils import safe_subprocess
from config_dialog import ConfigOption
import json
import threading
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

from sensor_cache import SENSOR_CACHE
from update_manager import update_manager

class SystemTempDataSource(DataSource):
    """Data source for fetching system temperature (CPU/GPU/other sensors)."""
    def __init__(self, config):
        self.alarm_config_prefix = "sys_temp_"
        super().__init__(config)
        self._available_sensors_cache = None

    @staticmethod
    def _discover_temp_sensors_statically():
        """Static version of sensor discovery to avoid recursion."""
        sensors_data = {}
        try:
            sensors_json_output = safe_subprocess(["sensors", "-j"], timeout=5)
            if not sensors_json_output or sensors_json_output == "N/A":
                return {"": {"display_name": "No sensors found"}}
            all_chips_data = json.loads(sensors_json_output)
            for adapter, adapter_data in all_chips_data.items():
                for block, block_data in adapter_data.items():
                    if block == "Adapter" or not isinstance(block_data, dict): continue
                    for key, value in block_data.items():
                        if key.startswith("temp") and key.endswith("_input"):
                            label = block_data.get(key.replace("_input", "_label"), block).strip()
                            unique_key = f"{adapter}//{key}"
                            if unique_key not in sensors_data:
                                sensors_data[unique_key] = {"display_name": f"{adapter} / {label}", "adapter": adapter, "input_raw": key}
        except (json.JSONDecodeError, Exception) as e:
            print(f"SystemTempDataSource: Static error discovering sensors: {e}")
        return sensors_data if sensors_data else {"": {"display_name": "No sensors found"}}


    def _discover_temp_sensors(self):
        if self._available_sensors_cache is not None: return self._available_sensors_cache
        self._available_sensors_cache = self._discover_temp_sensors_statically()
        return self._available_sensors_cache

    def get_data(self):
        temp_val_c = None
        sensor_key = self.config.get("selected_sensor_key", "")
        # Use the global cache populated at startup
        self._available_sensors_cache = SENSOR_CACHE.get('system_temp', {})
        
        if sensor_key and sensor_key in self._available_sensors_cache:
            sensor_info = self._available_sensors_cache[sensor_key]
            adapter, input_name = sensor_info.get("adapter"), sensor_info.get("input_raw")
            if adapter and input_name:
                try:
                    # FIX: Pass the full command to the UpdateManager's caching function
                    command_to_run = ["sensors", "-u", adapter]
                    sensors_output = update_manager.get_sensor_adapter_data(adapter, command_to_run)
                    
                    if sensors_output and sensors_output != "N/A":
                        for line in sensors_output.splitlines():
                            if line.strip().startswith(input_name + ":"):
                                temp_val_c = float(line.split(":")[1].strip()); break
                except Exception as e:
                    print(f"SystemTempDataSource: Error fetching temp for {sensor_info.get('display_name')}: {e}")
        return temp_val_c

    def get_display_string(self, value):
        if not isinstance(value, (int, float)):
            return "N/A"
            
        unit, val_display, unit_suffix = self.config.get("display_unit", "C"), value, "°C"
        if unit == "F": val_display, unit_suffix = (value * 9/5) + 32, "°F"
        elif unit == "K": val_display, unit_suffix = value + 273.15, "K"
        return f"{val_display:.1f}{unit_suffix}"

    def get_numerical_value(self, data):
        """Returns the raw temperature value for graphing and alarms."""
        return data

    def get_primary_label_string(self, data):
        """Returns the display name of the currently monitored sensor."""
        sensor_key = self.config.get("selected_sensor_key", "")
        self._available_sensors_cache = SENSOR_CACHE.get('system_temp', {})
        
        if sensor_key and self._available_sensors_cache and sensor_key in self._available_sensors_cache:
            return self._available_sensors_cache[sensor_key].get("display_name", "Temperature")
        return "Temperature"

    @staticmethod
    def get_alarm_unit(): return "°C"

    @staticmethod
    def get_config_model():
        sensor_options = {"Scanning...": ""}
        
        model = DataSource.get_config_model()
        model["Data Source & Update"] = [ConfigOption("update_interval_seconds", "scale", "Update Interval (sec):", "3.0", 0.1, 60, 0.1, 1),
                                         ConfigOption("display_unit", "dropdown", "Display Unit:", "C", options_dict={"Celsius (°C)": "C", "Fahrenheit (°F)": "F", "Kelvin (K)": "K"})]
        model["Sensor Selection"] = [ConfigOption("selected_sensor_key", "dropdown", "Monitored Sensor:", "", options_dict=sensor_options)]
        model["Alarm"][1] = ConfigOption(f"sys_temp_alarm_high_value", "scale", f"Alarm High Value (°C):", "85.0", 0.0, 150.0, 1.0, 1)
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min Temp (°C):", "0.0", -50.0, 200.0, 1.0, 1),
            ConfigOption("graph_max_value", "spinner", "Graph Max Temp (°C):", "100.0", -50.0, 200.0, 1.0, 1)
        ]
        return model

    def get_configure_callback(self):
        """Provides a callback to dynamically update panel title and populate sensors."""

        def _repopulate_sensor_dropdown(widgets, panel_config, prefix):
            """Helper to fill the sensor dropdown once data is available."""
            key_prefix = f"{prefix}opt_" if prefix else ""
            try:
                sensor_combo_key = f"{key_prefix}selected_sensor_key"
                sensor_combo = widgets.get(sensor_combo_key)
                if not sensor_combo: return

                sensor_combo.remove_all()
                
                sensors = SENSOR_CACHE.get('system_temp', {})
                if not sensors or all(k == "" for k in sensors):
                    sensor_combo.append(id="", text="No sensors found")
                else:
                    sorted_sensors = sorted(sensors.items(), key=lambda i: i[1]['display_name'])
                    for key, data in sorted_sensors:
                        sensor_combo.append(id=key, text=data['display_name'])

                current_selection = panel_config.get(sensor_combo_key)
                if not current_selection or not sensor_combo.set_active_id(current_selection):
                    sensor_combo.set_active(0)
                    new_active_id = sensor_combo.get_active_id()
                    if new_active_id:
                        panel_config[sensor_combo_key] = new_active_id

            except KeyError as e:
                print(f"SystemTempDataSource _repopulate_sensor_dropdown KeyError: {e}")

        def setup_auto_title_logic(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            is_combo_child = prefix is not None
            key_prefix = f"{prefix}opt_" if is_combo_child else ""
            
            sensor_combo_key = f"{key_prefix}selected_sensor_key"
            sensor_combo = widgets.get(sensor_combo_key)
            if not sensor_combo: return

            caption_key = f"{prefix}caption" if is_combo_child else "title_text"
            title_entry = widgets.get(caption_key)
            if title_entry:
                def on_sensor_changed(combo):
                    display_name = combo.get_active_text()
                    if not title_entry.get_text() or title_entry.get_text() == "System Temperature":
                        if display_name and "No sensors" not in display_name:
                            title_entry.set_text(display_name)
                        else:
                            title_entry.set_text("System Temperature")
                
                sensor_combo.connect("changed", on_sensor_changed)
                GLib.idle_add(on_sensor_changed, sensor_combo)

            _repopulate_sensor_dropdown(widgets, panel_config, prefix)

        return setup_auto_title_logic

