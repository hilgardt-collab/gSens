# intel_manager.py
# A singleton manager for handling Intel GPU monitoring via the sysfs interface.

import os
import glob
import re

class IntelManager:
    """
    Manages the detection and data retrieval for Intel GPUs. Caches data once
    per update cycle to minimize expensive I/O operations.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(IntelManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.intel_gpus_found = False
        self.device_count = 0
        self.devices = []
        # --- PERF OPT 1: Add a cache for sensor data ---
        self.cached_data = []
        self._initialized = True

    def init(self):
        """Initializes the manager by scanning for Intel GPUs."""
        drm_path = "/sys/class/drm/"
        if not os.path.isdir(drm_path):
            return

        card_paths = sorted(glob.glob(os.path.join(drm_path, "card[0-9]*")))
        
        for card_path in card_paths:
            try:
                vendor_path = os.path.join(card_path, "device/vendor")
                with open(vendor_path, 'r') as f:
                    vendor_id = f.read().strip()
                
                if vendor_id == "0x8086": # Intel's PCI vendor ID
                    device_info = self._get_device_paths(card_path)
                    if device_info:
                        self.devices.append(device_info)
            except Exception as e:
                print(f"Could not probe {card_path} for Intel GPU: {e}")

        self.device_count = len(self.devices)
        if self.device_count > 0:
            self.intel_gpus_found = True
            # --- PERF OPT 1: Initialize cache structure ---
            self.cached_data = [{} for _ in range(self.device_count)]
            print(f"IntelManager initialized successfully. Found {self.device_count} Intel GPU(s).")

    # --- PERF OPT 1: New method to perform a bulk update of all sensor data ---
    def update(self):
        """
        Reads all sensor files for all detected Intel GPUs at once and caches
        the results. This is called by the unified GPUManager.
        """
        if not self.intel_gpus_found:
            return

        for i, device_info in enumerate(self.devices):
            self.cached_data[i] = {
                'temperature': self._get_temp_from_file(device_info["paths"].get("temp")),
                'utilization': self._get_util_from_files(device_info["paths"].get("utilization_cur"), device_info["paths"].get("utilization_max")),
                'graphics_clock': self._get_clock_from_file(device_info["paths"].get("utilization_cur")),
                'vram_usage': None, # Not yet supported for Intel
                'power_usage': None, # Not yet supported for Intel
                'fan_speed': None, # Not yet supported for Intel
            }

    # --- PERF OPT 1: Helper methods for the update() function ---
    def _get_temp_from_file(self, path):
        temp_str = self._read_sysfs_file(path)
        return int(temp_str) / 1000.0 if temp_str else None

    def _get_util_from_files(self, cur_path, max_path):
        cur_freq_str = self._read_sysfs_file(cur_path)
        max_freq_str = self._read_sysfs_file(max_path)
        if cur_freq_str and max_freq_str:
            try:
                cur_freq, max_freq = int(cur_freq_str), int(max_freq_str)
                if max_freq > 0:
                    return (cur_freq / max_freq) * 100.0
            except (ValueError, TypeError): pass
        return None

    def _get_clock_from_file(self, path):
        clock_str = self._read_sysfs_file(path)
        return int(clock_str) if clock_str else None

    def _get_device_paths(self, card_path):
        """Gathers all necessary sysfs file paths for a given GPU."""
        device_path = os.path.join(card_path, "device")
        hwmon_paths = glob.glob(os.path.join(device_path, "hwmon/hwmon*"))
        hwmon_path = hwmon_paths[0] if hwmon_paths else None
        gt_path = os.path.join(card_path, "gt")
        if not os.path.isdir(gt_path):
             gt_path = os.path.join(device_path, "drm", os.path.basename(card_path), "gt")
             if not os.path.isdir(gt_path): gt_path = None

        name = f"Intel GPU {len(self.devices)}"
        try:
            with open(os.path.join(card_path, "device/label"), 'r') as f: name = f.read().strip()
        except Exception: pass

        return { "name": name, "paths": {
            "temp": os.path.join(hwmon_path, "temp1_input") if hwmon_path else None,
            "utilization_cur": os.path.join(gt_path, "gt_cur_freq_mhz") if gt_path else None,
            "utilization_max": os.path.join(gt_path, "gt_max_freq_mhz") if gt_path else None,
        }}

    def _read_sysfs_file(self, path):
        """Safely reads a value from a sysfs file."""
        if not path or not os.path.exists(path):
            return None
        try:
            with open(path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            return None

    def get_gpu_names(self):
        """Returns a dictionary of GPU indices and their names."""
        return {i: dev["name"] for i, dev in enumerate(self.devices)}

    # --- PERF OPT 1: All 'get' methods now read from the cache ---
    def get_temperature(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get("temperature")

    def get_utilization(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get("utilization")

    def get_graphics_clock(self, gpu_index):
        if not (0 <= gpu_index < self.device_count): return None
        return self.cached_data[gpu_index].get("graphics_clock")
        
    def get_vram_usage(self, gpu_index):
        return None # Placeholder

    def get_power_usage(self, gpu_index):
        return None # Placeholder

    def get_fan_speed(self, gpu_index):
        return None # Placeholder

# Global instance
intel_manager = IntelManager()
