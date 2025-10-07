# update_manager.py
# A centralized manager to handle data source updates in a single worker thread.

import threading
import time
import os
import psutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from gi.repository import GLib
from gpu_managers import gpu_manager
from utils import safe_subprocess

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
    data sources. It now uses a unified, thread-safe cache for all data
    fetched within a single update cycle.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(UpdateManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized: return

        self._panels = {}
        self._last_update_times = {}
        self._lock = threading.Lock()
        self._worker_thread = None
        self._stop_event = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=(os.cpu_count() or 2) + 4, thread_name_prefix='gSens_DataSource_')
        self._pending_futures = set()

        self._cache_lock = threading.Lock()
        self._cycle_cache = {}

        self._initialized = True
        self.TICK_INTERVAL = 0.1

    def start(self):
        if self._worker_thread and self._worker_thread.is_alive(): return
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._worker_thread.start()
        print("UpdateManager started.")

    def stop(self):
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            # The executor will be shut down gracefully, allowing pending tasks to complete.
            # We don't cancel futures here to avoid leaving the app in an inconsistent state.
            self._executor.shutdown(wait=True, cancel_futures=False)
            self._worker_thread.join(timeout=2.0)
            print("UpdateManager stopped.")
        self._worker_thread = None

    def register_panel(self, panel):
        with self._lock:
            panel_id = panel.config.get("id")
            if panel_id and panel_id not in self._panels:
                self._panels[panel_id] = panel
                self._last_update_times[panel_id] = 0

    def unregister_panel(self, panel):
        with self._lock:
            panel_id = panel.config.get("id")
            if panel_id:
                self._panels.pop(panel_id, None)
                self._last_update_times.pop(panel_id, None)
    
    def get_cached_data(self, key, data_fetch_func):
        """
        Thread-safe method to get data from the current cycle's cache.
        If the data is not in the cache, it calls the provided function to fetch it.
        """
        if key in self._cycle_cache:
            return self._cycle_cache[key]

        with self._cache_lock:
            if key in self._cycle_cache:
                return self._cycle_cache[key]
            
            data = data_fetch_func()
            self._cycle_cache[key] = data
            return data

    def _update_loop(self):
        """
        Main loop: Caches system-wide data, then dispatches panel-specific
        update tasks to a thread pool.
        """
        psutil.cpu_percent(interval=None, percpu=True)
        
        while not self._stop_event.is_set():
            now = time.monotonic()
            
            with self._cache_lock:
                self._cycle_cache.clear()
                self._cycle_cache['cpu_percent'] = psutil.cpu_percent(interval=None, percpu=True)
                self._cycle_cache['virtual_memory'] = psutil.virtual_memory()
                self._cycle_cache['sensors_fans'] = psutil.sensors_fans() if hasattr(psutil, "sensors_fans") else {}
                self._cycle_cache['temperatures'] = psutil.sensors_temperatures() if hasattr(psutil, "sensors_temperatures") else {}
                try:
                    self._cycle_cache['cpu_freq'] = psutil.cpu_freq(percpu=True)
                except Exception:
                    self._cycle_cache['cpu_freq'] = None

            with self._lock:
                gpu_manager.update()
                
                panels_to_update = []
                for panel_id, panel in list(self._panels.items()):
                    try:
                        interval = float(panel.config.get("update_interval_seconds", 2.0))
                        last_update = self._last_update_times.get(panel_id, 0)
                        if (now - last_update) >= interval:
                            panels_to_update.append(panel)
                            self._last_update_times[panel_id] = now
                    except (ValueError, TypeError, AttributeError): continue
                
                # --- FIX: Handle RuntimeError on shutdown ---
                for panel in panels_to_update:
                    try:
                        future = self._executor.submit(_fetch_data_for_panel, panel)
                        self._pending_futures.add(future)
                    except RuntimeError:
                        # This occurs if shutdown begins while we are submitting tasks.
                        # It's safe to break and let the thread exit gracefully.
                        print("UpdateManager is shutting down; no new tasks will be submitted.")
                        break

            if self._pending_futures:
                done, self._pending_futures = as_completed(self._pending_futures), set()
                for future in done:
                    try:
                        panel, value = future.result()
                        if panel and value is not None:
                            panel_id = panel.config.get("id")
                            with self._lock:
                                if panel_id in self._panels:
                                    GLib.idle_add(panel.process_update, value)
                    except Exception as e:
                        print(f"UpdateManager: Error processing future result: {e}")

            time.sleep(self.TICK_INTERVAL)

update_manager = UpdateManager()

