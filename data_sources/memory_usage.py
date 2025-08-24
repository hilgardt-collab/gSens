# data_sources/memory_usage.py
from data_source import DataSource
from config_dialog import ConfigOption
import psutil

class MemoryUsageDataSource(DataSource):
    """Data source for fetching virtual memory statistics."""
    def get_data(self):
        try: 
            mem=psutil.virtual_memory()
            return {"percent":mem.percent, "used_gb":mem.used/(1024**3), "total_gb":mem.total/(1024**3)}
        except Exception as e: 
            return {"error": str(e)}
        
    def get_display_string(self, data):
        # --- BUG FIX ---
        # Add a type check for robustness. If data is not a dictionary, it's likely
        # the raw numerical value (percentage) being passed from a compound displayer.
        # Format it appropriately to prevent a crash.
        if not isinstance(data, dict):
            if isinstance(data, (int, float)):
                return f"{data:.1f}%"
            return "N/A"

        if data.get("error"): return "N/A"
        style = self.config.get("text_content_style", "gb_and_percent")
        if style == "gb_only": return f"{data['used_gb']:.1f}/{data['total_gb']:.1f} GB"
        if style == "percent_only": return f"{data['percent']:.1f}%"
        return f"{data['used_gb']:.1f}/{data['total_gb']:.1f} GB ({data['percent']:.1f}%)"

    def get_tooltip_string(self, data):
        if not isinstance(data, dict) or data.get("error"): 
            return f"Memory\nError: {data.get('error', 'N/A')}"
        return f"Memory Usage\nUsed: {data['used_gb']:.1f} GB ({data['percent']:.1f}%)\nTotal: {data['total_gb']:.1f} GB"

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Data Source & Update"].append(ConfigOption("text_content_style", "dropdown", "Text Style:", "gb_and_percent", options_dict={"GB and Percentage": "gb_and_percent", "GB Only": "gb_only", "Percentage Only": "percent_only"}))
        model["Alarm"][1] = ConfigOption(f"data_alarm_high_value", "scale", "Alarm High Value (%):", "90.0", 0.0, 100.0, 1.0, 1)
        # Add an explicit graph range so displayers know how to scale the data.
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "scale", "Graph Min Value (%):", "0.0", 0.0, 100.0, 1.0, 0),
            ConfigOption("graph_max_value", "scale", "Graph Max Value (%):", "100.0", 0.0, 100.0, 1.0, 0)
        ]
        return model

    @staticmethod
    def get_alarm_unit(): return "%"
