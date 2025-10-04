# data_sources/cpu_source.py
from data_source import DataSource
from config_dialog import ConfigOption, build_ui_from_model
import psutil
import time
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
from sensor_cache import SENSOR_CACHE
from update_manager import update_manager

class CPUDataSource(DataSource):
    """
    A unified data source for all CPU metrics: usage, temperature, and frequency.
    The specific metric to display is determined by the panel's configuration.
    """
    def __init__(self, config):
        super().__init__(config)
        # The initial psutil call is now handled by the UpdateManager

    @staticmethod
    def _discover_cpu_temp_sensors_statically():
        """
        Statically discovers available CPU temperature sensors using psutil.
        This method is moved from the old cpu_temp.py and is called once at startup.
        """
        if not hasattr(psutil, "sensors_temperatures"):
            return {"": {"display_name": "psutil temperatures not supported"}}
            
        sensors = {}
        try:
            temp_data = psutil.sensors_temperatures()
            if not temp_data:
                return {"": {"display_name": "No temperature sensors found"}}
            
            # Prioritize common CPU temperature sensor chip names
            cpu_chips = [chip for chip in ['coretemp', 'k10temp', 'zenpower', 'acpitz'] if chip in temp_data]
            
            for chip in cpu_chips:
                for i, sensor in enumerate(temp_data[chip]):
                    label = sensor.label if sensor.label else f"Sensor {i+1}"
                    unique_key = f"{chip}::{label}"
                    display_name = f"{chip} / {label}"
                    sensors[unique_key] = {"display_name": display_name}
        except Exception as e:
            print(f"CPUDataSource: Error discovering sensors with psutil: {e}")
            return {"": {"display_name": "Error reading temperature data"}}
            
        return sensors if sensors else {"": {"display_name": "No CPU sensors found"}}

    def get_data(self):
        """
        Fetches all relevant CPU data points at once from the UpdateManager's cache
        and returns them in a dictionary.
        """
        return {
            "usage": self._get_usage_data(),
            "temperature": self._get_temperature_data(),
            "frequency": self._get_frequency_data()
        }

    def _get_usage_data(self):
        """Returns a dictionary: {'overall': value, 'per_core': [val1, val2, ...]}"""
        # --- PERF OPT: Get data from the central cache ---
        per_cpu = update_manager.get_psutil_data('cpu_percent_percpu')
        if per_cpu is None:
            return {'overall': 0.0, 'per_core': []}
        overall = sum(per_cpu) / len(per_cpu) if per_cpu else 0.0
        return {'overall': overall, 'per_core': per_cpu}

    def _get_temperature_data(self):
        """
        Returns the temperature value for the selected sensor from the central cache.
        If no sensor is selected, it defaults to the first available sensor.
        """
        # --- PERF OPT: Get data from the central cache ---
        temp_data = update_manager.get_psutil_data('sensors_temperatures')
        if not temp_data: return None
        
        selected_key = self.config.get("cpu_temp_sensor_key", "")
        
        if not selected_key or '::' not in selected_key:
            cached_sensors = SENSOR_CACHE.get('cpu_temp', {})
            if cached_sensors:
                first_valid_key = next((k for k in cached_sensors if k), None)
                if first_valid_key:
                    selected_key = first_valid_key
                    self.config["cpu_temp_sensor_key"] = selected_key

        if '::' not in selected_key: return None

        try:
            chip, label = selected_key.split('::', 1)
            if chip in temp_data:
                for sensor in temp_data[chip]:
                    current_label = sensor.label if sensor.label else f"Sensor {temp_data[chip].index(sensor)+1}"
                    if current_label == label:
                        return sensor.current
        except Exception as e:
            print(f"CPUDataSource: Could not read temp for key '{selected_key}': {e}")
        return None

    def _get_frequency_data(self):
        """Returns a dictionary: {'overall': value, 'per_core': [val1, val2, ...]}"""
        # --- PERF OPT: Get data from the central cache ---
        result = update_manager.get_psutil_data('cpu_freq_percpu')
        if not result: return {'overall': None, 'per_core': []}
        
        per_core_freqs = [f.current for f in result]
        overall_freq = sum(per_core_freqs) / len(per_core_freqs) if per_core_freqs else 0.0
        return {'overall': overall_freq, 'per_core': per_core_freqs}

    def get_numerical_value(self, data):
        """Extracts the specific numerical value based on the panel's configuration."""
        if data is None:
            return None
            
        metric = self.config.get("cpu_metric_to_display", "usage")
        
        if metric == "usage":
            mode = self.config.get("cpu_usage_mode", "overall")
            usage_data = data.get("usage", {})
            if "core_" in mode:
                try:
                    index = int(mode.split('_')[1])
                    return usage_data.get("per_core", [])[index]
                except (ValueError, IndexError):
                    return usage_data.get("overall")
            return usage_data.get("overall")
            
        elif metric == "temperature":
            return data.get("temperature")

        elif metric == "frequency":
            mode = self.config.get("cpu_freq_mode", "overall")
            freq_data = data.get("frequency", {})
            if "core_" in mode:
                try:
                    index = int(mode.split('_')[1])
                    return freq_data.get("per_core", [])[index]
                except (ValueError, IndexError):
                    return freq_data.get("overall")
            return freq_data.get("overall")
        return None

    @staticmethod
    def _format_metric(metric_key, value, config):
        """Static helper to format any given CPU metric value."""
        if value is None: return "N/A"
        
        if metric_key == "usage":
            return f"{value:.1f}%"
        elif metric_key == "temperature":
            unit = config.get("display_unit_temp", "C")
            if unit == "F": value = (value * 9/5) + 32
            elif unit == "K": value = value + 273.15
            unit_suffix = "°F" if unit == "F" else "K" if unit == "K" else "°C"
            return f"{value:.1f}{unit_suffix}"
        elif metric_key == "frequency":
            unit = config.get("display_unit_freq", "GHz")
            if unit == "GHz":
                return f"{value / 1000:.2f} GHz"
            return f"{value:.0f} MHz"
        return "N/A"

    def get_display_string(self, data):
        """Formats the display string for the selected primary metric."""
        primary_metric = self.config.get("cpu_metric_to_display", "usage")
        value = self.get_numerical_value(data)
        return CPUDataSource._format_metric(primary_metric, value, self.config)

    def get_primary_label_string(self, data):
        """Returns a descriptive label for the currently displayed metric."""
        metric = self.config.get("cpu_metric_to_display", "usage")
        
        if metric == "usage":
            mode = self.config.get("cpu_usage_mode", "overall")
            if "core_" in mode:
                return f"Core {mode.split('_')[1]} Usage"
            return "Overall CPU Usage"
            
        elif metric == "temperature":
            sensor_key = self.config.get("cpu_temp_sensor_key", "")
            cached_sensors = SENSOR_CACHE.get('cpu_temp', {})
            sensor_info = cached_sensors.get(sensor_key, {})
            label = sensor_info.get('display_name', 'CPU Temp').split('/')[-1].strip()
            return f"{label} Temp"

        elif metric == "frequency":
            mode = self.config.get("cpu_freq_mode", "overall")
            if "core_" in mode:
                return f"Core {mode.split('_')[1]} Freq"
            return "Average Frequency"
        return "CPU"

    def get_secondary_display_string(self, data):
        """Returns a formatted string for a user-selected secondary metric."""
        secondary_metric = self.config.get("cpu_secondary_metric", "none")
        if secondary_metric == "none" or data is None:
            return ""

        value = None
        if secondary_metric == "usage":
            usage_data = data.get("usage", {})
            value = usage_data.get("overall")
        elif secondary_metric == "temperature":
            value = data.get("temperature")
        elif secondary_metric == "frequency":
            freq_data = data.get("frequency", {})
            value = freq_data.get("overall")
            
        formatted_value = CPUDataSource._format_metric(secondary_metric, value, self.config)
        
        metric_map = {"usage": "Usage", "temperature": "Temp", "frequency": "Freq"}
        metric_label = metric_map.get(secondary_metric, "")
        
        return f"{metric_label}: {formatted_value}"

    @staticmethod
    def get_config_model():
        """Returns a combined and declarative configuration model for all CPU metrics."""
        base_model = DataSource.get_config_model()
        
        metric_opts = {"Usage": "usage", "Temperature": "temperature", "Frequency": "frequency"}
        secondary_metric_opts = {"None": "none", **metric_opts}
        core_opts = {"Overall": "overall", **{f"Core {i}": f"core_{i}" for i in range(psutil.cpu_count(logical=True))}}
        temp_sensors = SENSOR_CACHE.get('cpu_temp', {"": {"display_name": "Scanning..."}})
        temp_opts = {v['display_name']: k for k, v in sorted(temp_sensors.items(), key=lambda i:i[1]['display_name'])}
        
        # This is the controller dropdown
        controller_key = "cpu_metric_to_display"

        base_model["Metric & Display"] = [
            ConfigOption(controller_key, "dropdown", "Primary Metric:", "usage", options_dict=metric_opts),
            ConfigOption("cpu_secondary_metric", "dropdown", "Secondary Metric:", "none",
                         options_dict=secondary_metric_opts,
                         tooltip="Display an additional metric as a secondary label.")
        ]
        
        # These sections are now dynamic and controlled by the dropdown above
        base_model["Metric Specific Settings"] = [
            # --- Usage Options ---
            ConfigOption("cpu_usage_mode", "dropdown", "Monitor:", "overall", options_dict=core_opts,
                         dynamic_group=controller_key, dynamic_show_on="usage"),
            # --- Temperature Options ---
            ConfigOption("cpu_temp_sensor_key", "dropdown", "Sensor:", "", options_dict=temp_opts,
                         dynamic_group=controller_key, dynamic_show_on="temperature"),
            ConfigOption("display_unit_temp", "dropdown", "Display Unit:", "C",
                         options_dict={"Celsius (°C)": "C", "Fahrenheit (°F)": "F", "Kelvin (K)": "K"},
                         dynamic_group=controller_key, dynamic_show_on="temperature"),
            # --- Frequency Options ---
            ConfigOption("cpu_freq_mode", "dropdown", "Monitor:", "overall", options_dict=core_opts,
                         dynamic_group=controller_key, dynamic_show_on="frequency"),
            ConfigOption("display_unit_freq", "dropdown", "Display Unit:", "GHz",
                         options_dict={"Gigahertz (GHz)": "GHz", "Megahertz (MHz)": "MHz"},
                         dynamic_group=controller_key, dynamic_show_on="frequency")
        ]
        
        base_model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min Value:", "0.0", 0.0, 10000.0, 1.0, 0),
            ConfigOption("graph_max_value", "spinner", "Graph Max Value:", "100.0", 0.0, 10000.0, 1.0, 0)
        ]
        base_model["Alarm"][1] = ConfigOption("data_alarm_high_value", "scale", "Alarm High Value:", "90.0", 0.0, 10000.0, 1.0, 1)
        
        return base_model

    def get_configure_callback(self):
        """
        No longer needed for dynamic UI. The base alarm callback is still inherited.
        We only need to provide a simple callback to adjust the ranges of the
        min/max/alarm spinners based on the selected metric.
        """
        def setup_range_adjustments(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            metric_combo = widgets.get("cpu_metric_to_display")
            if not metric_combo: return

            min_widget = widgets.get("graph_min_value")
            max_widget = widgets.get("graph_max_value")
            alarm_widget = widgets.get("data_alarm_high_value")
            
            if not all([min_widget, max_widget, alarm_widget]): return

            def on_metric_changed(combo):
                active_metric = combo.get_active_id()
                
                # Configure adjustment ranges based on metric
                if active_metric == "usage":
                    min_widget.get_adjustment().configure(0.0, 0.0, 100.0, 1.0, 10.0, 0)
                    max_widget.get_adjustment().configure(100.0, 0.0, 100.0, 1.0, 10.0, 0)
                    alarm_widget.get_adjustment().configure(90.0, 0.0, 100.0, 1.0, 10.0, 0)
                elif active_metric == "temperature":
                    min_widget.get_adjustment().configure(0.0, 0.0, 200.0, 1.0, 10.0, 0)
                    max_widget.get_adjustment().configure(120.0, 0.0, 200.0, 1.0, 10.0, 0)
                    alarm_widget.get_adjustment().configure(95.0, 0.0, 200.0, 1.0, 10.0, 0)
                elif active_metric == "frequency":
                    min_widget.get_adjustment().configure(0.0, 0.0, 10000.0, 100.0, 1000.0, 0)
                    max_widget.get_adjustment().configure(5000.0, 0.0, 10000.0, 100.0, 1000.0, 0)
                    alarm_widget.get_adjustment().configure(5500.0, 0.0, 10000.0, 100.0, 1000.0, 0)

            metric_combo.connect("changed", on_metric_changed)
            GLib.idle_add(on_metric_changed, metric_combo)

        return setup_range_adjustments
