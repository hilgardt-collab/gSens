# intel_manager.py
# A singleton manager for handling Intel GPU monitoring via the sysfs interface.

import os
import glob
import re

class IntelManager:
    """
    Manages the detection and data retrieval for Intel GPUs.
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
                
                # Intel's PCI vendor ID is 0x8086
                if vendor_id == "0x8086":
                    device_info = self._get_device_paths(card_path)
                    if device_info:
                        self.devices.append(device_info)
            except Exception as e:
                print(f"Could not probe {card_path} for Intel GPU: {e}")

        self.device_count = len(self.devices)
        if self.device_count > 0:
            self.intel_gpus_found = True
            print(f"IntelManager initialized successfully. Found {self.device_count} Intel GPU(s).")

    def _get_device_paths(self, card_path):
        """Gathers all necessary sysfs file paths for a given GPU."""
        # This will need to be implemented based on how Intel exposes metrics in sysfs
        return {
            "name": f"Intel GPU {len(self.devices)}", 
            "paths": {}
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

    # --- Placeholder Methods ---
    # These will need to be implemented with the correct sysfs paths for Intel GPUs

    def get_temperature(self, gpu_index):
        return None

    def get_utilization(self, gpu_index):
        return None

    def get_graphics_clock(self, gpu_index):
        return None
        
    def get_vram_usage(self, gpu_index):
        return None

# Global instance
intel_manager = IntelManager()
