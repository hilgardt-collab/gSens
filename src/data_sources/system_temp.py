from data_source import DataSource
from utils import safe_subprocess
from config_dialog import ConfigOption
import json
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib

# --- BUG FIX ---
# Import the global sensor cache directly to avoid a circular dependency with main.py.
from sensor_cache import SENSOR_CACHE

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
        if not self._available_sensors_cache: self._discover_temp_sensors() 
        if sensor_key and sensor_key in self._available_sensors_cache:
            sensor_info = self._available_sensors_cache[sensor_key]
            adapter, input_name = sensor_info.get("adapter"), sensor_info.get("input_raw")
            if adapter and input_name:
                try:
                    sensors_output = safe_subprocess(["sensors", "-u", adapter], timeout=3)
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

    @staticmethod
    def get_alarm_unit(): return "°C"

    @staticmethod
    def get_config_model():
        # Read the discovered sensors from the global cache instead of re-discovering.
        discovered_sensors = SENSOR_CACHE.get('system_temp', {"": {"display_name": "Cache not ready"}})
        sensor_options = {v['display_name']: k for k, v in sorted(discovered_sensors.items(), key=lambda item: item[1]['display_name'])}
        
        model = DataSource.get_config_model()
        model["Data Source & Update"] = [ConfigOption("update_interval_seconds", "scale", "Update Interval (sec):", 3, 1, 60, 1, 0),
                                         ConfigOption("display_unit", "dropdown", "Display Unit:", "C", options_dict={"Celsius (°C)": "C", "Fahrenheit (°F)": "F", "Kelvin (K)": "K"})]
        model["Sensor Selection"] = [ConfigOption("selected_sensor_key", "dropdown", "Monitored Sensor:", "", options_dict=sensor_options)]
        model["Alarm"][1] = ConfigOption(f"sys_temp_alarm_high_value", "scale", f"Alarm High Value (°C):", "85.0", 0.0, 150.0, 1.0, 1)
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min Temp (°C):", "0.0", -50.0, 200.0, 1.0, 1),
            ConfigOption("graph_max_value", "spinner", "Graph Max Temp (°C):", "100.0", -50.0, 200.0, 1.0, 1)
        ]
        return model

    def get_configure_callback(self):
        """Provides a callback to dynamically update panel title based on selected sensor."""
        def setup_auto_title_logic(dialog, content_box, widgets, available_sources, panel_config):
            try: 
                sensor_combo = widgets["selected_sensor_key"]
                title_entry = widgets["title_text"]
            except KeyError: 
                return

            def on_sensor_changed(combo):
                display_name = combo.get_active_text()
                if display_name and "No sensors" not in display_name:
                    title_entry.set_text(display_name)
                else:
                    title_entry.set_text("System Temperature")

            sensor_combo.connect("changed", on_sensor_changed)
            GLib.idle_add(on_sensor_changed, sensor_combo)

        return setup_auto_title_logic
