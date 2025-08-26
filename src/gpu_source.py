# data_sources/gpu_source.py
from data_source import DataSource
from config_dialog import ConfigOption
from gpu_managers import gpu_manager

class GPUDataSource(DataSource):
    """
    A unified data source for all GPU metrics: usage, temperature, frequency, and VRAM.
    The specific metric to display is determined by the panel's configuration.
    """
    def get_data(self):
        """
        Fetches a dictionary of all metrics for the selected GPU.
        """
        gpu_index = int(self.config.get("gpu_index", "0"))
        return {
            "temperature": gpu_manager.get_temperature(gpu_index),
            "utilization": gpu_manager.get_utilization(gpu_index),
            "frequency": gpu_manager.get_graphics_clock(gpu_index),
            "vram": gpu_manager.get_vram_usage(gpu_index) # This itself returns a dict
        }

    def get_numerical_value(self, data):
        """
        Returns the numerical value for the metric selected for display.
        """
        metric = self.config.get("gpu_metric_to_display", "utilization")
        if metric == "vram":
            return data.get("vram", {}).get("percent")
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
        model["Metric & Display"] = [
            ConfigOption("gpu_metric_to_display", "dropdown", "Metric to Display:", "utilization",
                         options_dict={
                             "Usage (%)": "utilization",
                             "Temperature": "temperature",
                             "Clock Frequency": "frequency",
                             "VRAM Usage": "vram"
                         }),
            ConfigOption("display_unit_temp", "dropdown", "Temp. Unit:", "C", 
                         options_dict={"Celsius (°C)": "C", "Fahrenheit (°F)": "F", "Kelvin (K)": "K"}),
            ConfigOption("display_unit_freq", "dropdown", "Freq. Unit:", "GHz",
                         options_dict={"Gigahertz (GHz)": "GHz", "Megahertz (MHz)": "MHz"}),
            ConfigOption("text_content_style_vram", "dropdown", "VRAM Text Style:", "gb_and_percent", 
                         options_dict={"GB and %": "gb_and_percent", "GB Only": "gb_only", "% Only": "percent_only"})
        ]
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "scale", "Graph Min Value:", "0.0", 0.0, 10000.0, 1.0, 0),
            ConfigOption("graph_max_value", "scale", "Graph Max Value:", "100.0", 0.0, 10000.0, 1.0, 0)
        ]
        model["Alarm"][1] = ConfigOption("data_alarm_high_value", "scale", "Alarm High Value:", "90.0", 0.0, 10000.0, 1.0, 1)
        return model
