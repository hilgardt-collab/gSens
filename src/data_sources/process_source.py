# /data_sources/process_source.py
from data_source import DataSource
from config_dialog import ConfigOption
import psutil

class ProcessDataSource(DataSource):
    """
    Data source for fetching a list of running processes, sorted by a specific metric.
    """
    def get_data(self):
        """
        Fetches and returns a list of process information dictionaries.
        """
        processes = []
        try:
            for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
                try:
                    processes.append(p.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            print(f"ProcessDataSource: Failed to iterate processes: {e}")
            return []

        sort_key = self.config.get("process_sort_by", "cpu_percent")
        try:
            processes.sort(key=lambda x: x.get(sort_key, 0), reverse=True)
        except TypeError:
            # Handle cases where a value might be None
            processes.sort(key=lambda x: (x.get(sort_key) is not None, x.get(sort_key)), reverse=True)


        process_count = int(self.config.get("process_count", 10))
        return processes[:process_count]

    def get_display_string(self, data):
        """Returns a summary string, as the full data is handled by the table."""
        if isinstance(data, list):
            return f"Top {len(data)} Processes"
        return "Process Info"
        
    @staticmethod
    def get_config_model():
        """Returns configuration options for the process source."""
        model = DataSource.get_config_model()
        model["Data Source & Update"] = [
            ConfigOption("update_interval_seconds", "scale", "Update Interval (sec):", "2.0", 0.5, 60, 0.5, 1),
            ConfigOption("process_count", "spinner", "Number of Processes:", "10", 1, 100, 1, 0),
            ConfigOption("process_sort_by", "dropdown", "Sort By:", "cpu_percent", 
                         options_dict={"CPU Usage": "cpu_percent", "Memory Usage": "memory_percent", "Name": "name", "PID": "pid"})
        ]
        # Process source doesn't have a single numerical value, so remove alarm options
        model.pop("Alarm", None)
        return model
