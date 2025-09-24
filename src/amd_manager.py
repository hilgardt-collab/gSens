# amd_manager.py
# A singleton manager for handling AMD GPU monitoring via the sysfs interface.

import os
import glob
import re

class AMDManager:
    """
    Manages the detection and data retrieval for AMD GPUs. Caches data once
    per update cycle to minimize expensive I/O operations.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AMDManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.amd_gpus_found = False
        self.device_count = 0
        self.devices = []
        self.cached_data = []
        self._initialized = True

    def init(self):
        """Initializes the manager by scanning for AMD GPUs."""
        drm_path = "/sys/class/drm/"
        if not os.path.isdir(drm_path):
            return

        card_paths = sorted(glob.glob(os.path.join(drm_path, "card[0-9]*")))
        
        for card_path in card_paths:
            try:
                vendor_path = os.path.join(card_path, "device/vendor")
                with open(vendor_path, 'r') as f:
                    vendor_id = f.read().strip()
                
                if vendor_id == "0x1002": # AMD's PCI vendor ID
                    device_info = self._get_device_paths(card_path)
                    if device_info:
                        self.devices.append(device_info)
            except Exception as e:
                print(f"Could not probe {card_path} for AMD GPU: {e}")

        self.device_count = len(self.devices)
        if self.device_count > 0:
            self.amd_gpus_found = True
            self.cached_data = [{} for _ in range(self.device_count)]
            print(f"AMDManager initialized successfully. Found {self.device_count} AMD GPU(s).")

    def update(self):
        """
        Reads all sensor files for all detected AMD GPUs at once and caches
        the results. This is called by the unified GPUManager.
        """
        if not self.amd_gpus_found:
            return

        for i, device_info in enumerate(self.devices):
            self.cached_data[i] = {
                'temperature': self._get_temp_from_file(device_info["paths"]["temp"]),
                'utilization': self._get_util_from_file(device_info["paths"]["utilization"]),
                'graphics_clock': self._get_clock_from_file(device_info["paths"]["clocks"]),
                'vram_usage': self._get_vram_from_files(device_info["paths"]["vram_used"], device_info["paths"]["vram_total"]),
                'power_usage': self._get_power_from_file(device_info["paths"]["power"]),
                'fan_speed': self._get_fan_from_files(device_info["paths"]["fan_rpm"], device_info["paths"]["fan_max_rpm"]),
            }

    def _get_temp_from_file(self, path):
        temp_str = self._read_sysfs_file(path)
        return int(temp_str) / 1000.0 if temp_str else None

    def _get_util_from_file(self, path):
        util_str = self._read_sysfs_file(path)
        return int(util_str) if util_str else None

    def _get_clock_from_file(self, path):
        clocks_str = self._read_sysfs_file(path)
        if clocks_str:
            for line in clocks_str.splitlines():
                if line.endswith('*'):
                    match = re.search(r':\s*(\d+)\s*M[Hh][Zz]', line, re.IGNORECASE)
                    if match:
                        return int(match.group(1))
        return None

    def _get_vram_from_files(self, used_path, total_path):
        used_bytes_str = self._read_sysfs_file(used_path)
        total_bytes_str = self._read_sysfs_file(total_path)
        if used_bytes_str and total_bytes_str:
            used_bytes, total_bytes = int(used_bytes_str), int(total_bytes_str)
            if total_bytes > 0:
                return {"percent": (used_bytes/total_bytes)*100, "used_gb": used_bytes/(1024**3), "total_gb": total_bytes/(1024**3)}
        return None

    def _get_power_from_file(self, path):
        power_str = self._read_sysfs_file(path)
        return int(power_str) / 1000000.0 if power_str else None

    def _get_fan_from_files(self, rpm_path, max_rpm_path):
        rpm_str, max_rpm_str = self._read_sysfs_file(rpm_path), self._read_sysfs_file(max_rpm_path)
        if rpm_str and max_rpm_str:
            try:
                rpm, max_rpm = int(rpm_str), int(max_rpm_str)
                if max_rpm > 0:
                    return (rpm / max_rpm) * 100.0
            except (ValueError, TypeError): pass
        return None

    def _get_device_paths(self, card_path):
        """Gathers all necessary sysfs file paths for a given GPU."""
        device_path = os.path.join(card_path, "device")
        hwmon_paths = glob.glob(os.path.join(device_path, "hwmon/hwmon*"))
        if not hwmon_paths:
            return None
        hwmon_path = hwmon_paths[0]

        return {
            "name": f"AMD GPU {len(self.devices)}",
            "paths": {
                "temp": os.path.join(hwmon_path, "temp1_input"),
                "utilization": os.path.join(device_path, "gpu_busy_percent"),
                "clocks": os.path.join(device_path, "pp_dpm_sclk"),
                "vram_used": os.path.join(device_path, "mem_info_vram_used"),
                "vram_total": os.path.join(device_path, "mem_info_vram_total"),
                "power": os.path.join(hwmon_path, "power1_average"),
                "fan_rpm": os.path.join(hwmon_path, "fan1_input"),
                "fan_max_rpm": os.path.join(hwmon_path, "fan1_max"),
            }
        }

    def _read_sysfs_file(self, path):
        """Safely reads a value from a sysfs file."""
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            # Suppress frequent errors for optional files (e.g., fan speed on laptops)
            # print(f"Error reading sysfs file {path}: {e}")
            return None

    def get_gpu_names(self):
        """Returns a dictionary of GPU indices and their names."""
        return {i: dev["name"] for i, dev in enumerate(self.devices)}
    
    # --- PERF OPT 1: All 'get' methods now read from the cache ---
    def get_temperature(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get('temperature')

    def get_utilization(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get('utilization')

    def get_graphics_clock(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get('graphics_clock')
        
    def get_vram_usage(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get('vram_usage')

    def get_power_usage(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get('power_usage')

    def get_fan_speed(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get('fan_speed')

# Global instance
amd_manager = AMDManager()
