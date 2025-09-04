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
        # --- FIX: Fetch all available metrics from the GPU manager ---
        return {
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
            # For VRAM, the primary numerical value is the percentage
            vram_data = data.get("vram")
            return vram_data.get("percent") if vram_data else None
        return data.get(metric)

    def get_display_string(self, data):
        """
        Formats the display string for the metric selected for display.
        """
        metric = self.config.get("gpu_metric_to_display", "utilization")
        value = data.get(metric)

        if value is None:
            return "N/A"

        if metric == "utilization":
            return f"{value:.0f}%"
        elif metric == "temperature":
            unit = self.config.get("display_unit_temp", "C")
            val_display, unit_suffix = value, "°C"
            if unit == "F": val_display, unit_suffix = (value * 9/5) + 32, "°F"
            elif unit == "K": val_display, unit_suffix = value + 273.15, "K"
            return f"{val_display:.1f}{unit_suffix}"
        elif metric == "frequency":
            unit = self.config.get("display_unit_freq", "GHz")
            if unit == "GHz":
                return f"{value / 1000:.2f} GHz"
            else:
                return f"{value:.0f} MHz"
        elif metric == "vram":
            if not isinstance(value, dict): return "N/A"
            style = self.config.get("text_content_style_vram", "gb_and_percent")
            if style == "gb_only": return f"{value['used_gb']:.1f}/{value['total_gb']:.1f} GB"
            if style == "percent_only": return f"{value['percent']:.1f}%"
            return f"{value['used_gb']:.1f}/{value['total_gb']:.1f} GB ({value['percent']:.1f}%)"
        # --- FIX: Add display formatting for the new metrics ---
        elif metric == "power":
            return f"{value:.1f} W"
        elif metric == "fan_speed":
            return f"{value:.0f}%"
        elif metric == "processes":
            # Handle pluralization
            return f"{value} Process{'es' if value != 1 else ''}"
        
        return "N/A"

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        
        gpu_opts = {name: str(i) for i, name in gpu_manager.get_gpu_names().items()}
        if not gpu_opts:
            gpu_opts = {"GPU 0": "0"}

        model["GPU Selection"] = [
            ConfigOption("gpu_index", "dropdown", "Monitored GPU:", "0", options_dict=gpu_opts)
        ]
        # --- FIX: Add all available metrics to the configuration dropdown ---
        model["Metric & Display"] = [
            ConfigOption("gpu_metric_to_display", "dropdown", "Metric to Display:", "utilization",
                         options_dict={
                             "Usage (%)": "utilization",
                             "Temperature": "temperature",
                             "Clock Frequency": "frequency",
                             "VRAM Usage": "vram",
                             "Power Draw (W)": "power",
                             "Fan Speed (%)": "fan_speed",
                             "Active Processes": "processes"
                         }),
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

            # --- BUG FIX: Robustly find section widgets by their keys instead of fragile text search ---
            # 1. Get the full config model for this data source.
            full_model = self.get_config_model()
            
            # 2. Map section titles to the widgets they contain.
            section_widgets = {}
            for section_title, options in full_model.items():
                if section_title.endswith(" Settings"): # Target only the dynamic sections
                    section_widgets[section_title] = []
                    
                    # Find the actual UI widgets associated with this section
                    for opt in options:
                        widget = widgets.get(opt.key)
                        if widget and widget.get_parent(): # Parent is the Gtk.Box row
                            section_widgets[section_title].append(widget.get_parent())
            
            # 3. Find the headers and separators associated with each section.
            all_children = list(content_box)
            for section_title, s_widgets in section_widgets.items():
                if s_widgets:
                    first_row_of_section = s_widgets[0]
                    try:
                        idx = all_children.index(first_row_of_section)
                        # The header and separator should be right before the first row
                        if idx > 1 and isinstance(all_children[idx-1], Gtk.Label) and isinstance(all_children[idx-2], Gtk.Separator):
                            s_widgets.insert(0, all_children[idx-1]) # Header
                            s_widgets.insert(0, all_children[idx-2]) # Separator
                    except ValueError:
                         print(f"Warning: Could not find row for section '{section_title}' to get header.")


            def on_metric_changed(combo):
                active_metric = combo.get_active_id()
                
                # 4. Show/hide the entire group of widgets for each section.
                for w in section_widgets.get("Temperature Settings", []): w.set_visible(active_metric == "temperature")
                for w in section_widgets.get("Frequency Settings", []): w.set_visible(active_metric == "frequency")
                for w in section_widgets.get("VRAM Settings", []): w.set_visible(active_metric == "vram")

            metric_combo.connect("changed", on_metric_changed)
            GLib.idle_add(on_metric_changed, metric_combo)

        return setup_dynamic_options

