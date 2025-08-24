# data_sources/cpu_source.py
from data_source import DataSource
from config_dialog import ConfigOption, build_ui_from_model
import psutil
import time
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
from sensor_cache import SENSOR_CACHE

class CPUDataSource(DataSource):
    """
    A unified data source for all CPU metrics: usage, temperature, and frequency.
    The specific metric to display is determined by the panel's configuration.
    """
    _last_freq_poll_time = 0
    _last_percpu_freq_result = []
    _freq_cache_duration = 0.5 

    def __init__(self, config):
        super().__init__(config)
        # Initial call to setup for psutil.cpu_percent
        psutil.cpu_percent(interval=None, percpu=True)

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
        Fetches all relevant CPU data points at once and returns them in a dictionary.
        This is more efficient than polling for each metric separately.
        """
        return {
            "usage": self._get_usage_data(),
            "temperature": self._get_temperature_data(),
            "frequency": self._get_frequency_data()
        }

    def _get_usage_data(self):
        """Returns a dictionary: {'overall': value, 'per_core': [val1, val2, ...]}"""
        per_cpu = psutil.cpu_percent(interval=None, percpu=True)
        overall = sum(per_cpu) / len(per_cpu) if per_cpu else 0.0
        return {'overall': overall, 'per_core': per_cpu}

    def _get_temperature_data(self):
        """Returns the temperature value for the selected sensor."""
        if not hasattr(psutil, "sensors_temperatures"): return None
        selected_key = self.config.get("cpu_temp_sensor_key", "")
        if '::' not in selected_key: return None
        try:
            chip, label = selected_key.split('::', 1)
            temp_data = psutil.sensors_temperatures()
            if chip in temp_data:
                for sensor in temp_data[chip]:
                    # Construct a label for matching, as psutil doesn't always provide one
                    current_label = sensor.label if sensor.label else f"Sensor {temp_data[chip].index(sensor)+1}"
                    if current_label == label:
                        return sensor.current
        except Exception as e:
            print(f"CPUDataSource: Could not read temp for key '{selected_key}': {e}")
        return None

    def _get_frequency_data(self):
        """Returns a dictionary: {'overall': value, 'per_core': [val1, val2, ...]}"""
        now = time.monotonic()
        if (now - CPUDataSource._last_freq_poll_time) > CPUDataSource._freq_cache_duration:
            try:
                CPUDataSource._last_percpu_freq_result = psutil.cpu_freq(percpu=True)
            except Exception:
                CPUDataSource._last_percpu_freq_result = []
            CPUDataSource._last_freq_poll_time = now
        
        result = CPUDataSource._last_percpu_freq_result
        if not result: return {'overall': None, 'per_core': []}
        
        per_core_freqs = [f.current for f in result]
        overall_freq = sum(per_core_freqs) / len(per_core_freqs) if per_core_freqs else 0.0
        return {'overall': overall_freq, 'per_core': per_core_freqs}

    def get_numerical_value(self, data):
        """Extracts the specific numerical value based on the panel's configuration."""
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

    def get_display_string(self, data):
        """Formats the display string for the selected metric."""
        value = self.get_numerical_value(data)
        if value is None: return "N/A"
        
        metric = self.config.get("cpu_metric_to_display", "usage")
        if metric == "usage":
            return f"{value:.1f}%"
        elif metric == "temperature":
            unit = self.config.get("display_unit_temp", "C")
            if unit == "F": value = (value * 9/5) + 32
            elif unit == "K": value = value + 273.15
            unit_suffix = "°F" if unit == "F" else "K" if unit == "K" else "°C"
            return f"{value:.1f}{unit_suffix}"
        elif metric == "frequency":
            unit = self.config.get("display_unit_freq", "GHz")
            if unit == "GHz":
                return f"{value / 1000:.2f} GHz"
            return f"{value:.0f} MHz"
        return "N/A"

    @staticmethod
    def get_config_model():
        """Returns a combined configuration model for all CPU metrics."""
        model = DataSource.get_config_model()
        
        model["Metric & Display"] = [
            ConfigOption("cpu_metric_to_display", "dropdown", "Metric to Display:", "usage",
                         options_dict={"Usage": "usage", "Temperature": "temperature", "Frequency": "frequency"})
        ]

        # --- Usage Options ---
        core_opts_usage = {"Overall": "overall", **{f"Core {i}": f"core_{i}" for i in range(psutil.cpu_count(logical=True))}}
        model["Usage Settings"] = [
            ConfigOption("cpu_usage_mode", "dropdown", "Monitor:", "overall", options_dict=core_opts_usage)
        ]
        
        # --- Temperature Options ---
        temp_sensors = SENSOR_CACHE.get('cpu_temp', {"": {"display_name": "Cache not ready"}})
        temp_opts = {v['display_name']: k for k, v in sorted(temp_sensors.items(), key=lambda i:i[1]['display_name'])}
        model["Temperature Settings"] = [
            ConfigOption("cpu_temp_sensor_key", "dropdown", "Sensor:", "", options_dict=temp_opts),
            ConfigOption("display_unit_temp", "dropdown", "Display Unit:", "C",
                         options_dict={"Celsius (°C)": "C", "Fahrenheit (°F)": "F", "Kelvin (K)": "K"})
        ]
        
        # --- Frequency Options ---
        core_opts_freq = {"Overall": "overall", **{f"Core {i}": f"core_{i}" for i in range(psutil.cpu_count(logical=True))}}
        model["Frequency Settings"] = [
            ConfigOption("cpu_freq_mode", "dropdown", "Monitor:", "overall", options_dict=core_opts_freq),
            ConfigOption("display_unit_freq", "dropdown", "Display Unit:", "GHz",
                         options_dict={"Gigahertz (GHz)": "GHz", "Megahertz (MHz)": "MHz"})
        ]
        
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "scale", "Graph Min Value:", "0.0", 0.0, 10000.0, 1.0, 0),
            ConfigOption("graph_max_value", "scale", "Graph Max Value:", "100.0", 0.0, 10000.0, 1.0, 0)
        ]
        model["Alarm"][1] = ConfigOption("data_alarm_high_value", "scale", "Alarm High Value:", "90.0", 0.0, 10000.0, 1.0, 1)
        
        return model

    def get_configure_callback(self):
        """Provides a callback to dynamically show/hide UI sections in the config dialog."""
        def setup_dynamic_options(dialog, content_box, widgets, available_sources, panel_config):
            metric_combo = widgets.get("cpu_metric_to_display")
            if not metric_combo: return

            all_children = list(content_box)
            section_widgets = {}
            section_titles = ["Usage Settings", "Temperature Settings", "Frequency Settings"]
            
            for title in section_titles:
                try:
                    header_label = next(c for c in all_children if isinstance(c, Gtk.Label) and c.get_label() == f"<b>{title}</b>")
                    header_index = all_children.index(header_label)
                    separator = all_children[header_index - 1]
                    
                    section_content = [separator, header_label]
                    for child in all_children[header_index + 1:]:
                        if isinstance(child, Gtk.Separator): break
                        section_content.append(child)
                    section_widgets[title] = section_content
                except (StopIteration, IndexError):
                    print(f"Warning: Could not find UI section for '{title}'")

            def on_metric_changed(combo):
                active_metric = combo.get_active_id()
                
                for w_list in section_widgets.get("Usage Settings", []): w_list.set_visible(active_metric == "usage")
                for w_list in section_widgets.get("Temperature Settings", []): w_list.set_visible(active_metric == "temperature")
                for w_list in section_widgets.get("Frequency Settings", []): w_list.set_visible(active_metric == "frequency")

                graph_min_label = widgets.get("graph_min_value").get_parent().get_first_child()
                graph_max_label = widgets.get("graph_max_value").get_parent().get_first_child()
                alarm_label = widgets.get("data_alarm_high_value").get_parent().get_first_child()
                
                if active_metric == "usage":
                    graph_min_label.set_text("Graph Min Value (%):")
                    graph_max_label.set_text("Graph Max Value (%):")
                    alarm_label.set_text("Alarm High Value (%):")
                elif active_metric == "temperature":
                    graph_min_label.set_text("Graph Min Temp (°C):")
                    graph_max_label.set_text("Graph Max Temp (°C):")
                    alarm_label.set_text("Alarm High Value (°C):")
                elif active_metric == "frequency":
                    graph_min_label.set_text("Graph Min Freq (MHz):")
                    graph_max_label.set_text("Graph Max Freq (MHz):")
                    alarm_label.set_text("Alarm High Value (MHz):")

            metric_combo.connect("changed", on_metric_changed)
            GLib.idle_add(on_metric_changed, metric_combo)

        return setup_dynamic_options
