# /data_sources/network_source.py
from data_source import DataSource
from config_dialog import ConfigOption
import psutil
import time

class NetworkDataSource(DataSource):
    """
    Data source for monitoring network interface throughput (download/upload speed).
    """
    def __init__(self, config):
        super().__init__(config)
        self.last_time = 0
        self.last_bytes_sent = 0
        self.last_bytes_recv = 0
        self._init_counters()

    def _get_interfaces(self):
        """Gets a list of network interfaces available on the system."""
        try:
            # Get stats for all interfaces to find active ones
            stats = psutil.net_if_stats()
            # Get counters to ensure we can read them
            counters = psutil.net_io_counters(pernic=True)
            # An interface is valid if it has stats, is up, and has counters
            valid_interfaces = {iface for iface, stat in stats.items() if stat.isup and iface in counters}
            return {"All Interfaces": "all", **{iface: iface for iface in sorted(list(valid_interfaces))}}
        except Exception as e:
            print(f"NetworkDataSource: Could not list network interfaces: {e}")
            return {"All Interfaces": "all"}

    def _init_counters(self):
        """Initializes or resets the byte counters for speed calculation."""
        interface = self.config.get("network_interface", "all")
        counters = None
        try:
            if interface == "all":
                counters = psutil.net_io_counters()
            else:
                all_counters = psutil.net_io_counters(pernic=True)
                counters = all_counters.get(interface)
            
            if counters:
                self.last_bytes_sent = counters.bytes_sent
                self.last_bytes_recv = counters.bytes_recv
            else: # Interface might not exist or be down
                self.last_bytes_sent = 0
                self.last_bytes_recv = 0
        except Exception:
            self.last_bytes_sent = 0
            self.last_bytes_recv = 0
            
        self.last_time = time.monotonic()

    def get_data(self):
        """Calculates and returns the current download and upload speed in Mbps."""
        interface = self.config.get("network_interface", "all")
        counters = None
        try:
            if interface == "all":
                counters = psutil.net_io_counters()
            else:
                all_counters = psutil.net_io_counters(pernic=True)
                counters = all_counters.get(interface)
        except Exception as e:
            return {"error": str(e)}

        if not counters:
             # This can happen if an interface is unplugged. Reset and return 0.
            self._init_counters()
            return {"download_mbps": 0.0, "upload_mbps": 0.0}

        current_time = time.monotonic()
        time_delta = current_time - self.last_time

        if time_delta == 0:
            return {"download_mbps": 0.0, "upload_mbps": 0.0}

        # Calculate bytes delta
        recv_delta = counters.bytes_recv - self.last_bytes_recv
        sent_delta = counters.bytes_sent - self.last_bytes_sent

        # Calculate speed in Mbps (Megabits per second)
        # Bytes to bits (* 8), then to Megabits (/ 1024 / 1024)
        download_mbps = (recv_delta / time_delta * 8) / (1024 * 1024)
        upload_mbps = (sent_delta / time_delta * 8) / (1024 * 1024)
        
        # Update last known values for the next calculation
        self.last_time = current_time
        self.last_bytes_sent = counters.bytes_sent
        self.last_bytes_recv = counters.bytes_recv

        return {"download_mbps": download_mbps, "upload_mbps": upload_mbps}

    def get_numerical_value(self, data):
        """
        Returns the numerical value for the metric selected for display.
        This is the location of the bug fix.
        """
        # --- BUG FIX: Handle the case where data is None on initial setup ---
        if data is None:
            return 0.0
            
        metric = self.config.get("network_metric_to_display", "download")
        if metric == "upload":
            return data.get("upload_mbps", 0.0)
        return data.get("download_mbps", 0.0)

    def get_display_string(self, data):
        """Returns the formatted download and upload speeds."""
        if not isinstance(data, dict) or "download_mbps" not in data:
            return "Down: N/A\nUp: N/A"

        down_speed = data["download_mbps"]
        up_speed = data["upload_mbps"]

        return f"Down: {down_speed:.2f} Mbps\nUp: {up_speed:.2f} Mbps"

    def get_primary_label_string(self, data):
        """Returns the name of the monitored network interface."""
        interface = self.config.get("network_interface", "all")
        return f"Net: {interface.capitalize()}"

    def get_secondary_display_string(self, data):
        return "" # No secondary string for this source

    @staticmethod
    def get_config_model():
        """Returns the configuration model for this data source."""
        # Note: self._get_interfaces() can't be called here as it's a static method.
        # The callback will populate the dropdown dynamically.
        interface_opts = {"Scanning...": "all"}
        
        model = DataSource.get_config_model()
        model["Data Source & Update"].append(
            ConfigOption("network_interface", "dropdown", "Network Interface:", "all", options_dict=interface_opts)
        )
        model["Data Source & Update"].append(
            ConfigOption("network_metric_to_display", "dropdown", "Metric to Graph:", "download", 
                         options_dict={"Download": "download", "Upload": "upload"})
        )
        
        # Remove default alarm as it's not very useful for network speed
        model.pop("Alarm", None)

        model["Graph Range (Mbps)"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min Value (Mbps):", "0.0", 0.0, 1000.0, 1.0, 1),
            ConfigOption("graph_max_value", "spinner", "Graph Max Value (Mbps):", "100.0", 0.0, 10000.0, 10.0, 1)
        ]
        return model

    def get_configure_callback(self):
        """Provides a callback to dynamically populate the interface dropdown."""
        def populate_interfaces(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            interface_combo = widgets.get("network_interface")
            if not interface_combo:
                return

            # This can be slow, so run it once and cache if needed, but for a config dialog it's fine
            interfaces = self._get_interfaces()
            
            interface_combo.remove_all()
            for name, key in interfaces.items():
                interface_combo.append(id=key, text=name)
            
            current_selection = panel_config.get("network_interface", "all")
            if not interface_combo.set_active_id(current_selection):
                interface_combo.set_active(0)

        return populate_interfaces
