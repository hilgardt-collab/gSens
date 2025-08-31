# update_manager.py
# A centralized manager to handle data source updates in a single worker thread.

import threading
import time
from gi.repository import GLib

class UpdateManager:
    """
    A singleton that manages a single background worker thread to poll all
    active data sources at their configured intervals, dispatching UI updates
    back to the main GTK thread. This avoids the overhead of creating a
    separate thread for each panel.
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
        self._initialized = True
        # The tick interval determines how frequently the worker thread wakes up
        # to check if any panels need an update. A smaller value provides more
        # accurate update timing at the cost of slightly higher CPU usage.
        self.TICK_INTERVAL = 0.1  # seconds

    def start(self):
        """Starts the central update worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            return
        
        self._stop_event.clear()
        self._worker_thread = threading.Thread(target=self._update_loop, daemon=True)
        self._worker_thread.start()
        print("UpdateManager started.")

    def stop(self):
        """Stops the central update worker thread."""
        if self._worker_thread and self._worker_thread.is_alive():
            self._stop_event.set()
            self._worker_thread.join(timeout=2.0)
            print("UpdateManager stopped.")
        self._worker_thread = None

    def register_panel(self, panel):
        """Adds a panel to be managed for updates."""
        with self._lock:
            panel_id = panel.config.get("id")
            if panel_id and panel_id not in self._panels:
                self._panels[panel_id] = panel
                # Set last update time to 0 to trigger an immediate first update
                self._last_update_times[panel_id] = 0

    def unregister_panel(self, panel):
        """Removes a panel from the update manager."""
        with self._lock:
            panel_id = panel.config.get("id")
            if panel_id:
                self._panels.pop(panel_id, None)
                self._last_update_times.pop(panel_id, None)

    def _update_loop(self):
        """The main loop for the worker thread."""
        while not self._stop_event.is_set():
            now = time.monotonic()
            panels_to_update = []
            
            with self._lock:
                # Create a list of panels that need updating. This is done inside the lock
                # to safely access the shared panel dictionaries, but the list is processed
                # outside the lock to avoid blocking registration/unregistration during
                # potentially slow data fetching.
                for panel_id, panel in list(self._panels.items()):
                    try:
                        interval = float(panel.config.get("update_interval_seconds", 2.0))
                        last_update = self._last_update_times.get(panel_id, 0)
                        
                        if (now - last_update) >= interval:
                            panels_to_update.append(panel)
                            self._last_update_times[panel_id] = now
                    except (ValueError, TypeError, AttributeError):
                        # Handle cases where config might be malformed or panel is closing
                        continue
            
            # Now, outside the lock, fetch data for the panels that need it
            for panel in panels_to_update:
                if self._stop_event.is_set():
                    break
                
                # Check if panel still has a data_source before fetching
                if hasattr(panel, 'data_source') and panel.data_source:
                    value = panel.data_source.get_data()
                    # Dispatch the result to the main GTK thread for UI processing
                    GLib.idle_add(panel.process_update, value)

            time.sleep(self.TICK_INTERVAL)

# Global instance
update_manager = UpdateManager()
