# data_sources/process_source.py
import psutil
from data_source import DataSource
from config_dialog import ConfigOption

class ProcessDataSource(DataSource):
    """
    Data source for listing the top N processes by CPU or memory usage.
    """
    def get_data(self):
        """
        Returns a list of dictionaries, each representing a process.
        """
        try:
            processes = []
            for proc in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent']):
                try:
                    processes.append(proc.info)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            sort_by = self.config.get("process_sort_by", "cpu_percent")
            processes.sort(key=lambda p: p.get(sort_by, 0), reverse=True)
            
            count = int(self.config.get("process_count", 5))
            return processes[:count]
        except Exception as e:
            print(f"ProcessDataSource error: {e}")
            return []

    def get_display_string(self, data):
        """
        Formats the process list into a multi-line string for the text displayer.
        """
        if not data:
            return "No process data."
            
        sort_by = self.config.get("process_sort_by", "cpu_percent")
        
        header = f"{'PID':>6} {'USER':<10} {'%CPU' if sort_by == 'cpu_percent' else '%MEM'} {'NAME'}\n"
        header += f"{'-'*6} {'-'*10} {'-'*5} {'-'*20}\n"
        
        lines = []
        for p in data:
            pid = p.get('pid', 'N/A')
            user = p.get('username', 'N/A')[:10]
            metric = p.get(sort_by, 0)
            name = p.get('name', 'N/A')[:20]
            lines.append(f"{pid:>6} {user:<10} {metric:>5.1f} {name}")
            
        return header + "\n".join(lines)

    def get_numerical_value(self, data):
        # This source is not numerical, so it's not suitable for graph/bar displayers.
        return None

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Process Monitor Settings"] = [
            ConfigOption("process_count", "spinner", "Number of Processes:", 5, 1, 50, 1, 0),
            ConfigOption("process_sort_by", "dropdown", "Sort By:", "cpu_percent",
                         options_dict={"CPU Usage": "cpu_percent", "Memory Usage": "memory_percent"})
        ]
        # Remove the alarm section as it doesn't apply to this non-numerical source
        model.pop("Alarm", None)
        return model
