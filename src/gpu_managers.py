# gpu_managers.py
# Provides a unified interface for GPU monitoring, supporting NVIDIA, AMD, and Intel.

from nvidia_manager import nvml_manager
from amd_manager import amd_manager
from intel_manager import intel_manager

class GPUManager:
    """
    A unified singleton manager that detects and delegates to the appropriate
    vendor-specific manager (NVIDIA, AMD, or Intel).
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GPUManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.nvml_manager = nvml_manager
        self.amd_manager = amd_manager
        self.intel_manager = intel_manager
        
        self.all_gpus = []
        self.device_count = 0
        self._initialized = True

    def init(self):
        """Initializes all available vendor managers and builds a unified device list."""
        self.nvml_manager.init()
        self.amd_manager.init()
        self.intel_manager.init()
        
        # Build a unified list of all detected GPUs
        if self.nvml_manager.nvml_is_available:
            for i in range(self.nvml_manager.device_count):
                self.all_gpus.append({"vendor": "nvidia", "original_index": i})
        
        if self.amd_manager.amd_gpus_found:
            for i in range(self.amd_manager.device_count):
                self.all_gpus.append({"vendor": "amd", "original_index": i})

        if self.intel_manager.intel_gpus_found:
            for i in range(self.intel_manager.device_count):
                self.all_gpus.append({"vendor": "intel", "original_index": i})
                
        self.device_count = len(self.all_gpus)
        print(f"Unified GPUManager initialized. Found {self.device_count} total GPU(s).")

    def shutdown(self):
        """Shuts down all vendor-specific managers."""
        self.nvml_manager.shutdown()
        # AMD and Intel managers do not require a shutdown call

    def get_gpu_names(self):
        """Returns a dictionary of combined GPU indices and their names."""
        names = {}
        nvidia_names = self.nvml_manager.get_gpu_names()
        amd_names = self.amd_manager.get_gpu_names()
        intel_names = self.intel_manager.get_gpu_names()
        
        current_index = 0
        for i in range(self.nvml_manager.device_count):
            raw_name = nvidia_names.get(i, "Unknown NVIDIA GPU")
            if isinstance(raw_name, bytes):
                names[current_index] = raw_name.decode('utf-8')
            else:
                names[current_index] = raw_name
            current_index += 1
            
        for i in range(self.amd_manager.device_count):
            names[current_index] = amd_names.get(i, "Unknown AMD GPU")
            current_index += 1

        for i in range(self.intel_manager.device_count):
            names[current_index] = intel_names.get(i, "Unknown Intel GPU")
            current_index += 1
            
        return names

    def _get_gpu_info(self, unified_index):
        """Helper to get the vendor and original index for a GPU."""
        if not (0 <= unified_index < self.device_count):
            return None, None
        return self.all_gpus[unified_index]["vendor"], self.all_gpus[unified_index]["original_index"]

    def get_temperature(self, gpu_index):
        """Gets temperature for a specific GPU, delegating to the correct manager."""
        vendor, original_index = self._get_gpu_info(gpu_index)
        if vendor == "nvidia":
            return self.nvml_manager.get_temperature(original_index)
        elif vendor == "amd":
            return self.amd_manager.get_temperature(original_index)
        elif vendor == "intel":
            return self.intel_manager.get_temperature(original_index)
        return None

    def get_utilization(self, gpu_index):
        """Gets GPU utilization, delegating to the correct manager."""
        vendor, original_index = self._get_gpu_info(gpu_index)
        if vendor == "nvidia":
            return self.nvml_manager.get_utilization(original_index)
        elif vendor == "amd":
            return self.amd_manager.get_utilization(original_index)
        elif vendor == "intel":
            return self.intel_manager.get_utilization(original_index)
        return None

    def get_graphics_clock(self, gpu_index):
        """Gets graphics clock speed, delegating to the correct manager."""
        vendor, original_index = self._get_gpu_info(gpu_index)
        if vendor == "nvidia":
            return self.nvml_manager.get_graphics_clock(original_index)
        elif vendor == "amd":
            return self.amd_manager.get_graphics_clock(original_index)
        elif vendor == "intel":
            return self.intel_manager.get_graphics_clock(original_index)
        return None

    def get_vram_usage(self, gpu_index):
        """Gets VRAM usage, delegating to the correct manager."""
        vendor, original_index = self._get_gpu_info(gpu_index)
        if vendor == "nvidia":
            return self.nvml_manager.get_vram_usage(original_index)
        elif vendor == "amd":
            return self.amd_manager.get_vram_usage(original_index)
        elif vendor == "intel":
            return self.intel_manager.get_vram_usage(original_index)
        return None

    def get_power_usage(self, gpu_index):
        """Gets power usage, delegating to the correct manager."""
        vendor, original_index = self._get_gpu_info(gpu_index)
        if vendor == "nvidia":
            return self.nvml_manager.get_power_usage(original_index)
        elif vendor == "amd":
            return self.amd_manager.get_power_usage(original_index)
        elif vendor == "intel":
            return self.intel_manager.get_power_usage(original_index)
        return None 

    def get_fan_speed(self, gpu_index):
        """Gets fan speed, delegating to the correct manager."""
        vendor, original_index = self._get_gpu_info(gpu_index)
        if vendor == "nvidia":
            return self.nvml_manager.get_fan_speed(original_index)
        elif vendor == "amd":
            return self.amd_manager.get_fan_speed(original_index)
        elif vendor == "intel":
            return self.intel_manager.get_fan_speed(original_index)
        return None 

    def get_running_processes_count(self, gpu_index):
        """Gets running processes count, delegating to the correct manager."""
        vendor, original_index = self._get_gpu_info(gpu_index)
        if vendor == "nvidia":
            return self.nvml_manager.get_running_processes_count(original_index)
        return None

# Create a single global instance of the unified manager
gpu_manager = GPUManager()

