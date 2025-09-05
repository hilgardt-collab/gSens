# data_sources/gpu_source.py
from data_source import DataSource
from config_dialog import ConfigOption, build_ui_from_model
from gpu_managers import gpu_manager
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

class GPUDataSource(DataSource):
    """
    A unified data source for all GPU metrics.
    The specific metric to display is determined by the panel's configuration.
    """
    def get_data(self):
        """
        Fetches a dictionary of all metrics for the selected GPU.
        """
        gpu_index = int(self.config.get("gpu_index", "0"))
        return {
            "name": gpu_manager.get_gpu_names().get(gpu_index, f"GPU {gpu_index}"),
            "temperature": gpu_manager.get_temperature(gpu_index),
            "utilization": gpu_manager.get_utilization(gpu_index),
            "frequency": gpu_manager.get_graphics_clock(gpu_index),
            "vram": gpu_manager.get_vram_usage(gpu_index),
            "power": gpu_manager.get_power_usage(gpu_index),
            "fan_speed": gpu_manager.get_fan_speed(gpu_index),
            "processes": gpu_manager.get_running_processes_count(gpu_index)
        }

    def get_numerical_value(self, data):
        """
        Returns the numerical value for the metric selected for display.
        """
        metric = self.config.get("gpu_metric_to_display", "utilization")
        if metric == "vram":
            vram_data = data.get("vram")
            return vram_data.get("percent") if vram_data else None
        return data.get(metric)

    def _format_metric(self, metric_key, data):
        """Helper to format any given metric based on its type and config."""
        value = data.get(metric_key)
        if value is None: return "N/A"

        if metric_key == "utilization":
            return f"{value:.0f}%"
        elif metric_key == "temperature":
            unit = self.config.get("display_unit_temp", "C")
            val_display, unit_suffix = value, "°C"
            if unit == "F": val_display, unit_suffix = (value * 9/5) + 32, "°F"
            elif unit == "K": val_display, unit_suffix = value + 273.15, "K"
            return f"{val_display:.1f}{unit_suffix}"
        elif metric_key == "frequency":
            unit = self.config.get("display_unit_freq", "GHz")
            return f"{value / 1000:.2f} GHz" if unit == "GHz" else f"{value:.0f} MHz"
        elif metric_key == "vram":
            if not isinstance(value, dict): return "N/A"
            return f"{value['used_gb']:.1f}/{value['total_gb']:.1f}GB ({value['percent']:.1f}%)"
        elif metric_key == "power":
            return f"{value:.1f} W"
        elif metric_key == "fan_speed":
            return f"{value:.0f}%"
        elif metric_key == "processes":
            return f"{value} Proc"
        return "N/A"

    def get_display_string(self, data):
        """Formats the main display string for the primary metric."""
        metric = self.config.get("gpu_metric_to_display", "utilization")
        # For VRAM, the text style is user-configurable.
        if metric == "vram":
            value = data.get("vram")
            if not isinstance(value, dict): return "N/A"
            style = self.config.get("text_content_style_vram", "gb_and_percent")
            if style == "gb_only": return f"{value['used_gb']:.1f}/{value['total_gb']:.1f} GB"
            if style == "percent_only": return f"{value['percent']:.1f}%"
            return f"{value['used_gb']:.1f}/{value['total_gb']:.1f} GB ({value['percent']:.1f}%)"
        
        return self._format_metric(metric, data)

    def get_primary_label_string(self, data):
        """Returns the GPU name and the primary metric being monitored."""
        metric_map = {
            "utilization": "Usage", "temperature": "Temp", "frequency": "Clock",
            "vram": "VRAM", "power": "Power", "fan_speed": "Fan", "processes": "Processes"
        }
        metric_key = self.config.get("gpu_metric_to_display", "utilization")
        metric_label = metric_map.get(metric_key, "GPU")
        gpu_name = data.get("name", "Unknown GPU")
        return f"{gpu_name}: {metric_label}"

    def get_secondary_display_string(self, data):
        """Returns a formatted string for a user-selected secondary metric."""
        secondary_metric = self.config.get("gpu_secondary_metric", "none")
        if secondary_metric == "none":
            return ""
        
        metric_map = {
            "utilization": "Usage", "temperature": "Temp", "frequency": "Clock",
            "vram": "VRAM", "power": "Power", "fan_speed": "Fan", "processes": "Processes"
        }
        metric_label = metric_map.get(secondary_metric, "")
        formatted_value = self._format_metric(secondary_metric, data)
        return f"{metric_label}: {formatted_value}"

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        
        gpu_opts = {name: str(i) for i, name in gpu_manager.get_gpu_names().items()}
        if not gpu_opts:
            gpu_opts = {"GPU 0": "0"}

        metric_opts = {
            "Usage (%)": "utilization", "Temperature": "temperature", "Clock Frequency": "frequency",
            "VRAM Usage": "vram", "Power Draw (W)": "power", "Fan Speed (%)": "fan_speed",
            "Active Processes": "processes"
        }
        secondary_metric_opts = {"None": "none", **metric_opts}

        model["GPU Selection"] = [
            ConfigOption("gpu_index", "dropdown", "Monitored GPU:", "0", options_dict=gpu_opts)
        ]
        model["Metric & Display"] = [
            ConfigOption("gpu_metric_to_display", "dropdown", "Primary Metric:", "utilization", options_dict=metric_opts),
            ConfigOption("gpu_secondary_metric", "dropdown", "Secondary Metric:", "none", options_dict=secondary_metric_opts,
                         tooltip="Display an additional metric as a secondary label.")
        ]
        model["Temperature Settings"] = [
            ConfigOption("display_unit_temp", "dropdown", "Temp. Unit:", "C", 
                         options_dict={"Celsius (°C)": "C", "Fahrenheit (°F)": "F", "Kelvin (K)": "K"}),
        ]
        model["Frequency Settings"] = [
            ConfigOption("display_unit_freq", "dropdown", "Freq. Unit:", "GHz",
                         options_dict={"Gigahertz (GHz)": "GHz", "Megahertz (MHz)": "MHz"}),
        ]
        model["VRAM Settings"] = [
            ConfigOption("text_content_style_vram", "dropdown", "VRAM Text Style:", "gb_and_percent", 
                         options_dict={"GB and %": "gb_and_percent", "GB Only": "gb_only", "% Only": "percent_only"})
        ]
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min Value:", "0.0", 0.0, 10000.0, 1.0, 0),
            ConfigOption("graph_max_value", "spinner", "Graph Max Value:", "100.0", 0.0, 10000.0, 1.0, 0)
        ]
        model["Alarm"][1] = ConfigOption("data_alarm_high_value", "scale", "Alarm High Value:", "90.0", 0.0, 10000.0, 1.0, 1)
        return model

    def get_configure_callback(self):
        """Dynamically shows/hides UI sections based on the selected metric."""
        def setup_dynamic_options(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            metric_combo = widgets.get("gpu_metric_to_display")
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
                    first_row_of_section = s_widgets[0]
                    try:
                        idx = all_children.index(first_row_of_section)
                        if idx > 1 and isinstance(all_children[idx-1], Gtk.Label) and isinstance(all_children[idx-2], Gtk.Separator):
                            s_widgets.insert(0, all_children[idx-1]) # Header
                            s_widgets.insert(0, all_children[idx-2]) # Separator
                    except ValueError:
                         print(f"Warning: Could not find row for section '{section_title}' to get header.")


            def on_metric_changed(combo):
                active_metric = combo.get_active_id()
                
                for w in section_widgets.get("Temperature Settings", []): w.set_visible(active_metric == "temperature")
                for w in section_widgets.get("Frequency Settings", []): w.set_visible(active_metric == "frequency")
                for w in section_widgets.get("VRAM Settings", []): w.set_visible(active_metric == "vram")

            metric_combo.connect("changed", on_metric_changed)
            GLib.idle_add(on_metric_changed, metric_combo)

        return setup_dynamic_options
