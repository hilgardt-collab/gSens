# nvidia_manager.py
# A singleton manager for handling all NVML (NVIDIA Management Library) interactions.
import os
import glob

try:
    import pynvml
    PYNML_AVAILABLE = True
except ImportError:
    PYNML_AVAILABLE = False

class NVMLManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NVMLManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.nvml_is_available = False
        self.device_count = 0
        self.device_handles = []
        self._initialized = True

    def init(self):
        """Initializes the manager, first checking for physical hardware
        via sysfs and then attempting to connect via the NVML library."""
        
        # --- NEW: Robust hardware check using sysfs ---
        sysfs_device_count = 0
        drm_path = "/sys/class/drm/"
        if os.path.isdir(drm_path):
            card_paths = sorted(glob.glob(os.path.join(drm_path, "card[0-9]*")))
            for card_path in card_paths:
                try:
                    vendor_path = os.path.join(card_path, "device/vendor")
                    with open(vendor_path, 'r') as f:
                        vendor_id = f.read().strip()
                    # NVIDIA's PCI vendor ID is 0x10de
                    if vendor_id == "0x10de":
                        sysfs_device_count += 1
                except Exception:
                    continue # Ignore errors on non-GPU devices

        # --- MODIFIED: NVML initialization ---
        if not PYNML_AVAILABLE:
            print("pynvml library not found. NVIDIA GPU monitoring is disabled.")
            self.device_count = sysfs_device_count # Still report presence
            self.nvml_is_available = False
            return

        try:
            pynvml.nvmlInit()
            self.device_count = pynvml.nvmlDeviceGetCount()
            self.device_handles = [pynvml.nvmlDeviceGetHandleByIndex(i) for i in range(self.device_count)]
            self.nvml_is_available = True
            print(f"NVML initialized successfully. Found {self.device_count} NVIDIA GPU(s).")
        except pynvml.NVMLError as e:
            print(f"Failed to initialize NVML: {e}. NVIDIA GPU data will be unavailable.")
            self.nvml_is_available = False
            # --- FALLBACK: Use sysfs count if NVML fails but hardware exists ---
            if sysfs_device_count > 0:
                self.device_count = sysfs_device_count
                print(f"Detected {sysfs_device_count} NVIDIA GPU(s) via sysfs, but NVML failed. The card might be in a low-power state.")
            else:
                self.device_count = 0

    def shutdown(self):
        """Shuts down the NVML library."""
        if self.nvml_is_available:
            try:
                pynvml.nvmlShutdown()
                print("NVML shut down successfully.")
            except pynvml.NVMLError as e:
                print(f"Failed to shut down NVML: {e}")
            self.nvml_is_available = False

    def get_gpu_names(self):
        """Returns a dictionary of GPU indices and their names."""
        if not self.nvml_is_available:
            return {}
        return {i: pynvml.nvmlDeviceGetName(handle) for i, handle in enumerate(self.device_handles)}

    def get_temperature(self, gpu_index):
        """Gets temperature for a specific GPU."""
        if not self.nvml_is_available or not (0 <= gpu_index < self.device_count):
            return None
        try:
            return pynvml.nvmlDeviceGetTemperature(self.device_handles[gpu_index], pynvml.NVML_TEMPERATURE_GPU)
        except pynvml.NVMLError:
            return None

    def get_utilization(self, gpu_index):
        """Gets GPU utilization for a specific GPU."""
        if not self.nvml_is_available or not (0 <= gpu_index < self.device_count):
            return None
        try:
            return pynvml.nvmlDeviceGetUtilizationRates(self.device_handles[gpu_index]).gpu
        except pynvml.NVMLError:
            return None

    def get_graphics_clock(self, gpu_index):
        """Gets current graphics clock speed for a specific GPU."""
        if not self.nvml_is_available or not (0 <= gpu_index < self.device_count):
            return None
        try:
            return pynvml.nvmlDeviceGetClockInfo(self.device_handles[gpu_index], pynvml.NVML_CLOCK_GRAPHICS)
        except pynvml.NVMLError:
            return None

    def get_vram_usage(self, gpu_index):
        """Gets VRAM usage statistics for a specific GPU."""
        if not self.nvml_is_available or not (0 <= gpu_index < self.device_count):
            return None
        try:
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.device_handles[gpu_index])
            if mem_info.total > 0:
                return {
                    "percent": (mem_info.used / mem_info.total) * 100,
                    "used_gb": mem_info.used / (1024**3),
                    "total_gb": mem_info.total / (1024**3)
                }
        except pynvml.NVMLError:
            return None
        return None

    def get_power_usage(self, gpu_index):
        """Gets current power usage in Watts for a specific GPU."""
        if not self.nvml_is_available or not (0 <= gpu_index < self.device_count):
            return None
        try:
            # Power is returned in milliwatts, so we convert to watts.
            return pynvml.nvmlDeviceGetPowerUsage(self.device_handles[gpu_index]) / 1000.0
        except pynvml.NVMLError:
            return None

    def get_fan_speed(self, gpu_index):
        """Gets current fan speed as a percentage for a specific GPU."""
        if not self.nvml_is_available or not (0 <= gpu_index < self.device_count):
            return None
        try:
            # This might fail on passively cooled cards, which is fine.
            return pynvml.nvmlDeviceGetFanSpeed(self.device_handles[gpu_index])
        except pynvml.NVMLError:
            return None

    def get_running_processes_count(self, gpu_index):
        """Gets the number of running compute processes on a specific GPU."""
        if not self.nvml_is_available or not (0 <= gpu_index < self.device_count):
            return None
        try:
            procs = pynvml.nvmlDeviceGetComputeRunningProcesses(self.device_handles[gpu_index])
            return len(procs)
        except pynvml.NVMLError:
            return None

# Create a single global instance of the manager
nvml_manager = NVMLManager()
