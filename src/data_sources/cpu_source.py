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
        """
        Returns the temperature value for the selected sensor.
        If no sensor is selected, it defaults to the first available sensor.
        """
        if not hasattr(psutil, "sensors_temperatures"): return None
        
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
            temp_data = psutil.sensors_temperatures()
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
            if sensor_key and '::' in sensor_key:
                return f"{sensor_key.split('::')[1]} Temp"
            return "CPU Temperature"

        elif metric == "frequency":
            mode = self.config.get("cpu_freq_mode", "overall")
            if "core_" in mode:
                return f"Core {mode.split('_')[1]} Freq"
            return "Average Frequency"
        return "CPU"

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
        temp_sensors = SENSOR_CACHE.get('cpu_temp', {"": {"display_name": "Scanning..."}})
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
            ConfigOption("graph_min_value", "spinner", "Graph Min Value:", "0.0", 0.0, 10000.0, 1.0, 0),
            ConfigOption("graph_max_value", "spinner", "Graph Max Value:", "5000.0", 0.0, 10000.0, 1.0, 0)
        ]
        model["Alarm"][1] = ConfigOption("data_alarm_high_value", "scale", "Alarm High Value:", "90.0", 0.0, 10000.0, 1.0, 1)
        
        return model

    def get_configure_callback(self):
        """Provides a callback to dynamically show/hide UI sections in the config dialog."""
        def setup_dynamic_options(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            
            is_combo_child = prefix is not None
            config = panel_config if is_combo_child else self.config
            
            if is_combo_child:
                temp_state = {
                    "cpu_metric_to_display": config.get("cpu_metric_to_display", "usage"),
                    "cpu_usage_mode": config.get("cpu_usage_mode", "overall"),
                    "cpu_temp_sensor_key": config.get("cpu_temp_sensor_key", ""),
                    "cpu_freq_mode": config.get("cpu_freq_mode", "overall"),
                    "graph_min_value": config.get("graph_min_value", "0.0"),
                    "graph_max_value": config.get("graph_max_value", "100.0")
                }
                
                def custom_getter():
                    opt_prefix = f"{prefix}opt_"
                    return { f"{opt_prefix}{k}": v for k, v in temp_state.items() }

                if not hasattr(dialog, 'custom_value_getters'):
                    dialog.custom_value_getters = []
                dialog.custom_value_getters.append(custom_getter)

            metric_combo = widgets.get("cpu_metric_to_display")
            if not metric_combo: return

            full_model = self.get_config_model()
            section_widgets = {}
            for section_title, options in full_model.items():
                if section_title.endswith(" Settings"):
                    section_widgets[section_title] = []
                    for opt in options:
                        widget = widgets.get(opt.key)
                        if widget and widget.get_parent():
                            section_widgets[section_title].append(widget.get_parent())

            all_children = list(content_box)
            for section_title, s_widgets in section_widgets.items():
                if s_widgets:
                    first_row = s_widgets[0]
                    try:
                        idx = all_children.index(first_row)
                        if idx > 1 and isinstance(all_children[idx-1], Gtk.Label) and isinstance(all_children[idx-2], Gtk.Separator):
                            s_widgets.insert(0, all_children[idx-1])
                            s_widgets.insert(0, all_children[idx-2])
                    except ValueError:
                        pass

            def on_metric_changed(combo):
                active_metric = combo.get_active_id()
                if is_combo_child:
                    temp_state["cpu_metric_to_display"] = active_metric
                
                for w_list in section_widgets.get("Usage Settings", []): w_list.set_visible(active_metric == "usage")
                for w_list in section_widgets.get("Temperature Settings", []): w_list.set_visible(active_metric == "temperature")
                for w_list in section_widgets.get("Frequency Settings", []): w_list.set_visible(active_metric == "frequency")
            
            metric_combo.connect("changed", on_metric_changed)
            
            if is_combo_child:
                widgets_to_track = {
                    "cpu_usage_mode": "changed",
                    "cpu_temp_sensor_key": "changed",
                    "cpu_freq_mode": "changed",
                    "graph_min_value": "value-changed",
                    "graph_max_value": "value-changed"
                }
                for key, signal in widgets_to_track.items():
                    widget = widgets.get(key)
                    if widget:
                        handler = (lambda c, k=key: temp_state.update({k: c.get_active_id()})) \
                                  if signal == "changed" else \
                                  (lambda s, k=key: temp_state.update({k: str(s.get_value())}))
                        widget.connect(signal, handler)

            GLib.idle_add(on_metric_changed, metric_combo)

        return setup_dynamic_options

