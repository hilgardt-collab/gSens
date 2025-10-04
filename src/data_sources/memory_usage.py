# data_sources/memory_usage.py
from data_source import DataSource
from config_dialog import ConfigOption
from update_manager import update_manager

class MemoryUsageDataSource(DataSource):
    """Data source for fetching virtual memory statistics."""
    def get_data(self):
        try: 
            # --- PERF OPT: Get data from the central cache ---
            mem = update_manager.get_psutil_data('virtual_memory')
            if mem is None:
                return {"error": "Could not retrieve memory data"}
            return {"percent":mem.percent, "used_gb":mem.used/(1024**3), "total_gb":mem.total/(1024**3)}
        except Exception as e: 
            return {"error": str(e)}
        
    def get_display_string(self, data):
        """Returns the main display string, configurable by the user."""
        if not isinstance(data, dict) or data.get("error"): return "N/A"
        
        style = self.config.get("main_text_content_style", "percent_only")
        if style == "gb_only": return f"{data['used_gb']:.1f}/{data['total_gb']:.1f} GB"
        if style == "gb_and_percent": return f"{data['used_gb']:.1f}/{data['total_gb']:.1f} GB ({data['percent']:.1f}%)"
        return f"{data['percent']:.1f}%"

    def get_primary_label_string(self, data):
        """Returns the static primary label for this data source."""
        return "RAM Usage"

    def get_secondary_display_string(self, data):
        """Returns the secondary display string, configurable by the user."""
        if not isinstance(data, dict) or data.get("error"): return ""
        
        style = self.config.get("secondary_text_content_style", "gb_only")
        if style == "gb_and_percent": return f"{data['used_gb']:.1f}/{data['total_gb']:.1f} GB ({data['percent']:.1f}%)"
        if style == "percent_only": return f"{data['percent']:.1f}%"
        if style == "gb_only": return f"{data['used_gb']:.1f}/{data['total_gb']:.1f} GB"
        return "" # Return empty string if style is 'none'

    def get_tooltip_string(self, data):
        # BUG FIX: Add a check to handle None data gracefully
        if data is None or not isinstance(data, dict) or data.get("error"): 
            return f"Memory\nError: {data.get('error', 'N/A') if isinstance(data, dict) else 'No data'}"
        return f"Memory Usage\nUsed: {data['used_gb']:.1f} GB ({data['percent']:.1f}%)\nTotal: {data['total_gb']:.1f} GB"

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        
        main_text_opts = {
            "Percentage Only": "percent_only",
            "GB Only": "gb_only",
            "GB and Percentage": "gb_and_percent"
        }
        secondary_text_opts = {
            "None": "none",
            "GB Only": "gb_only",
            "Percentage Only": "percent_only",
            "GB and Percentage": "gb_and_percent"
        }

        model["Data Source & Update"].extend([
            ConfigOption("main_text_content_style", "dropdown", "Main Text Style:", "percent_only", options_dict=main_text_opts),
            ConfigOption("secondary_text_content_style", "dropdown", "Secondary Text Style:", "gb_only", options_dict=secondary_text_opts)
        ])
        
        model["Alarm"][1] = ConfigOption(f"data_alarm_high_value", "scale", "Alarm High Value (%):", "90.0", 0.0, 100.0, 1.0, 1)
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min Value (%):", "0.0", 0.0, 100.0, 1.0, 0),
            ConfigOption("graph_max_value", "spinner", "Graph Max Value (%):", "100.0", 0.0, 100.0, 1.0, 0)
        ]
        return model

    @staticmethod
    def get_alarm_unit(): return "%"
