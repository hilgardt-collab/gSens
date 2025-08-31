# data_sources/systemd_source.py
from data_source import DataSource
from config_dialog import ConfigOption
from utils import safe_subprocess

class SystemdDataSource(DataSource):
    """
    Data source for monitoring the status of one or more systemd services.
    """
    def get_data(self):
        """
        Checks the status of each configured service and returns a list of results.
        """
        services_str = self.config.get("systemd_services", "")
        if not services_str:
            return [{"name": "No services configured", "status": "N/A"}]

        services = [s.strip() for s in services_str.split(',') if s.strip()]
        results = []
        for service in services:
            status = safe_subprocess(["systemctl", "is-active", service], fallback="error")
            results.append({"name": service, "status": status})
        return results

    def get_display_string(self, data):
        """
        Formats the service status list into a multi-line string.
        """
        if not data:
            return "No service data."
        
        lines = []
        for service in data:
            name = service.get("name", "Unknown")
            status = service.get("status", "N/A").upper()
            # A simple visual indicator
            indicator = "●" if status == "ACTIVE" else "○" if status == "INACTIVE" else "!"
            lines.append(f"{indicator} {name:<25} {status}")
        
        return "\n".join(lines)

    def get_numerical_value(self, data):
        # This source is not numerical.
        return None

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Systemd Settings"] = [
            ConfigOption("systemd_services", "string", "Services to Monitor:", "nginx.service,docker.service",
                         tooltip="Enter a comma-separated list of service names.")
        ]
        model.pop("Alarm", None)
        return model
