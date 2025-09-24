# update_manager.py
# A centralized manager to handle data source updates in a single worker thread.

import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from gi.repository import GLib
# --- PERF OPT 1: Import the unified GPU manager ---
from gpu_managers import gpu_manager

def _fetch_data_for_panel(panel):
    """
    Worker function to be run in a thread pool. Fetches data for a single panel.
    Returns the panel and its new data value.
    """
    try:
        if hasattr(panel, 'data_source') and panel.data_source:
            value = panel.data_source.get_data()
            return panel, value
    except Exception as e:
        print(f"Error fetching data for panel {panel.config.get('id', 'N/A')}: {e}")
    return panel, None


class UpdateManager:
    """
    A singleton that manages a background worker thread to poll all active
    data sources. It now uses a thread pool to fetch data concurrently,
    preventing slow sources from blocking faster ones.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UpdateManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._panels = {}  # {panel_id: panel_instance}
        self._last_update_times = {}  # {panel_id: timestamp}
        self._lock = threading.Lock()
        self._worker_thread = None
        self._stop_event = threading.Event()
        
        # --- FIX: Use a thread pool for non-blocking data fetching ---
        self._executor = ThreadPoolExecutor(max_workers=(os.cpu_count() or 2) + 2, thread_name_prefix='gSens_DataSource_')
        self._pending_futures = set()

        self._initialized = True
        self.TICK_INTERVAL = 0.1  # seconds
        self._sensor_cache = {} # Cache for one update cycle
        self._sensor_cache_time = 0

    def start(self):
        """Starts the central update worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._worker_thread.start()
        print("UpdateManager started.")

    def stop(self):
        """Stops the central update worker thread and shuts down the executor."""
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            # Cancel any pending futures
            for future in self._pending_futures:
                future.cancel()
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._worker_thread.join(timeout=2.0)
            print("UpdateManager stopped.")
        self._worker_thread = None

    def register_panel(self, panel):
        """Adds a panel to be managed for updates."""
        with self._lock:
            panel_id = panel.config.get("id")
            if panel_id and panel_id not in self._panels:
                self._panels[panel_id] = panel
                self._last_update_times[panel_id] = 0

    def unregister_panel(self, panel):
        """Removes a panel from the update manager."""
        with self._lock:
            panel_id = panel.config.get("id")
            if panel_id:
                self._panels.pop(panel_id, None)
                self._last_update_times.pop(panel_id, None)
    
    def get_sensor_adapter_data(self, adapter_name, command):
        """
        Efficiently fetches and caches sensor data for one update cycle.
        """
        now = time.monotonic()
        # Invalidate cache if we are on a new update tick
        if now - self._sensor_cache_time > self.TICK_INTERVAL:
            self._sensor_cache.clear()
            self._sensor_cache_time = now
        
        if adapter_name not in self._sensor_cache:
            from utils import safe_subprocess
            self._sensor_cache[adapter_name] = safe_subprocess(command)
            
        return self._sensor_cache[adapter_name]


    def _update_loop(self):
        """
        The main loop for the worker thread. Submits tasks to the thread pool
        and processes results as they complete.
        """
        while not self._stop_event.is_set():
            now = time.monotonic()
            
            with self._lock:
                gpu_manager.update() # Bulk update for supported GPUs
                
                # --- SUBMIT TASKS ---
                panels_to_update = []
                for panel_id, panel in list(self._panels.items()):
                    try:
                        interval = float(panel.config.get("update_interval_seconds", 2.0))
                        last_update = self._last_update_times.get(panel_id, 0)
                        
                        if (now - last_update) >= interval:
                            panels_to_update.append(panel)
                            self._last_update_times[panel_id] = now
                    except (ValueError, TypeError, AttributeError):
                        continue
                
                for panel in panels_to_update:
                    future = self._executor.submit(_fetch_data_for_panel, panel)
                    self._pending_futures.add(future)

            # --- PROCESS COMPLETED TASKS ---
            if self._pending_futures:
                done, self._pending_futures = as_completed(self._pending_futures), set()
                for future in done:
                    try:
                        panel, value = future.result()
                        if panel and value is not None:
                            # --- FIX: Race condition fix. Check if panel is still registered before dispatching UI update ---
                            panel_id = panel.config.get("id")
                            with self._lock:
                                if panel_id in self._panels:
                                    GLib.idle_add(panel.process_update, value)
                    except Exception as e:
                        print(f"UpdateManager: Error processing future result: {e}")

            time.sleep(self.TICK_INTERVAL)

# --- FIX: Re-add the global instance creation for the singleton pattern ---
update_manager = UpdateManager()

