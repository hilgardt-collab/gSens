# data_sources/network_source.py
import time
import psutil
from data_source import DataSource
from config_dialog import ConfigOption

class NetworkDataSource(DataSource):
    """
    Data source for monitoring network interface upload and download speeds.
    """
    def __init__(self, config):
        super().__init__(config)
        self._last_time = time.monotonic()
        self._last_io = psutil.net_io_counters(pernic=True)

    def get_data(self):
        """
        Calculates and returns the current upload and download speed in Mbps.
        """
        current_time = time.monotonic()
        current_io = psutil.net_io_counters(pernic=True)
        
        time_delta = current_time - self._last_time
        if time_delta == 0:
            return {"upload_mbps": 0, "download_mbps": 0}

        interface = self.config.get("network_interface", "all")
        
        last_sent = 0
        last_recv = 0
        current_sent = 0
        current_recv = 0

        if interface == "all":
            for if_name, if_io in self._last_io.items():
                last_sent += if_io.bytes_sent
                last_recv += if_io.bytes_recv
            for if_name, if_io in current_io.items():
                current_sent += if_io.bytes_sent
                current_recv += if_io.bytes_recv
        else:
            if interface in self._last_io:
                last_sent = self._last_io[interface].bytes_sent
                last_recv = self._last_io[interface].bytes_recv
            if interface in current_io:
                current_sent = current_io[interface].bytes_sent
                current_recv = current_io[interface].bytes_recv

        self._last_time = current_time
        self._last_io = current_io

        bytes_sent = current_sent - last_sent
        bytes_recv = current_recv - last_recv

        # Convert bytes per second to Megabits per second (Mbps)
        # 1 byte = 8 bits, 1 Megabit = 1,000,000 bits
        upload_mbps = (bytes_sent * 8) / (time_delta * 1000000)
        download_mbps = (bytes_recv * 8) / (time_delta * 1000000)

        return {"upload_mbps": upload_mbps, "download_mbps": download_mbps}

    def get_numerical_value(self, data):
        """Returns the primary numerical value based on display mode."""
        mode = self.config.get("network_display_mode", "download")
        if mode == "upload":
            return data.get("upload_mbps", 0)
        return data.get("download_mbps", 0)

    def get_display_string(self, data):
        """Formats the text display for network speeds."""
        up = data.get('upload_mbps', 0)
        down = data.get('download_mbps', 0)
        return f"Up: {up:.2f} Mbps\nDown: {down:.2f} Mbps"

    def get_primary_label_string(self, data):
        interface = self.config.get("network_interface", "all")
        return f"Interface: {interface.capitalize()}"

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        
        interfaces = {"All Interfaces": "all"}
        try:
            interfaces.update({if_name: if_name for if_name in psutil.net_if_addrs().keys()})
        except Exception as e:
            print(f"Could not enumerate network interfaces: {e}")

        model["Network Settings"] = [
            ConfigOption("network_interface", "dropdown", "Interface:", "all", options_dict=interfaces),
            ConfigOption("network_display_mode", "dropdown", "Primary Value for Graphs:", "download",
                         options_dict={"Download Speed": "download", "Upload Speed": "upload"})
        ]
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min Value (Mbps):", "0.0", 0.0, 10000.0, 1.0, 0),
            ConfigOption("graph_max_value", "spinner", "Graph Max Value (Mbps):", "100.0", 0.0, 10000.0, 1.0, 0)
        ]
        model["Alarm"][1] = ConfigOption("data_alarm_high_value", "scale", "Alarm High Value (Mbps):", "100.0", 0.0, 1000.0, 10.0, 1)
        return model
