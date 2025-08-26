# amd_manager.py
# A singleton manager for handling AMD GPU monitoring via the sysfs interface.

import os
import glob
import re

class AMDManager:
    """
    Manages the detection and data retrieval for AMD GPUs.
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
                
                # AMD's PCI vendor ID is 0x1002
                if vendor_id == "0x1002":
                    device_info = self._get_device_paths(card_path)
                    if device_info:
                        self.devices.append(device_info)
            except Exception as e:
                print(f"Could not probe {card_path} for AMD GPU: {e}")

        self.device_count = len(self.devices)
        if self.device_count > 0:
            self.amd_gpus_found = True
            print(f"AMDManager initialized successfully. Found {self.device_count} AMD GPU(s).")

    def _get_device_paths(self, card_path):
        """Gathers all necessary sysfs file paths for a given GPU."""
        device_path = os.path.join(card_path, "device")
        hwmon_paths = glob.glob(os.path.join(device_path, "hwmon/hwmon*"))
        if not hwmon_paths:
            return None
        hwmon_path = hwmon_paths[0]

        return {
            "name": f"AMD GPU {len(self.devices)}", # Simple name for now
            "paths": {
                "temp": os.path.join(hwmon_path, "temp1_input"),
                "utilization": os.path.join(device_path, "gpu_busy_percent"),
                "clocks": os.path.join(device_path, "pp_dpm_sclk"),
                "vram_used": os.path.join(device_path, "mem_info_vram_used"),
                "vram_total": os.path.join(device_path, "mem_info_vram_total"),
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
            print(f"Error reading sysfs file {path}: {e}")
            return None

    def get_gpu_names(self):
        """Returns a dictionary of GPU indices and their names."""
        return {i: dev["name"] for i, dev in enumerate(self.devices)}

    def get_temperature(self, gpu_index):
        """Gets temperature for a specific GPU in degrees Celsius."""
        if not (0 <= gpu_index < self.device_count): return None
        temp_str = self._read_sysfs_file(self.devices[gpu_index]["paths"]["temp"])
        return int(temp_str) / 1000.0 if temp_str else None

    def get_utilization(self, gpu_index):
        """Gets GPU utilization percentage."""
        if not (0 <= gpu_index < self.device_count): return None
        util_str = self._read_sysfs_file(self.devices[gpu_index]["paths"]["utilization"])
        return int(util_str) if util_str else None

    def get_graphics_clock(self, gpu_index):
        """Gets the current graphics clock speed in MHz."""
        if not (0 <= gpu_index < self.device_count): return None
        clocks_str = self._read_sysfs_file(self.devices[gpu_index]["paths"]["clocks"])
        if clocks_str:
            for line in clocks_str.splitlines():
                if line.endswith('*'): # The active clock level is marked with an asterisk
                    # --- BUG FIX: Make parsing more robust ---
                    # The original parsing was brittle and could fail if spacing or capitalization changed.
                    match = re.search(r':\s*(\d+)\s*Mhz', line, re.IGNORECASE)
                    if match:
                        return int(match.group(1))
        return None
        
    def get_vram_usage(self, gpu_index):
        """Gets VRAM usage statistics."""
        if not (0 <= gpu_index < self.device_count): return None
        
        used_bytes_str = self._read_sysfs_file(self.devices[gpu_index]["paths"]["vram_used"])
        total_bytes_str = self._read_sysfs_file(self.devices[gpu_index]["paths"]["vram_total"])

        if used_bytes_str and total_bytes_str:
            used_bytes = int(used_bytes_str)
            total_bytes = int(total_bytes_str)
            if total_bytes > 0:
                return {
                    "percent": (used_bytes / total_bytes) * 100,
                    "used_gb": used_bytes / (1024**3),
                    "total_gb": total_bytes / (1024**3)
                }
        return None

# Global instance
amd_manager = AMDManager()
