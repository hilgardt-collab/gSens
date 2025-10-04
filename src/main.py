# main.py
import os
import sys
import signal
import uuid 
import importlib
import threading

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import gi
gi.require_version("Gtk", "4.0")
gi.require_version('GdkPixbuf', '2.0')
from gi.repository import Gtk, Gio, GLib, Gdk, GdkPixbuf

# --- Centralized Module & Data Loading ---
import module_registry
module_registry.discover_and_load_modules()
from module_registry import AVAILABLE_DATA_SOURCES, AVAILABLE_DISPLAYERS, ALL_SOURCE_CLASSES
# ----------------------------------------- 

from config_manager import config_manager
from grid_layout_manager import GridLayoutManager, CELL_SIZE
from utils import show_confirmation_dialog
from ui_helpers import CustomDialog
from panel_builder_dialog import PanelBuilderDialog
from data_panel import DataPanel
from gpu_managers import gpu_manager
from update_manager import update_manager 

# --- Import sensor data sources for background discovery ---
from data_sources.cpu_source import CPUDataSource
from data_sources.fan_speed import FanSpeedDataSource
from data_sources.system_temp import SystemTempDataSource
from sensor_cache import SENSOR_CACHE

DEFAULT_PANEL_LAYOUT = [
    {'type': 'cpu', 'displayer_type': 'arc_gauge', 'width': '16', 'height': '16', 'grid_x': '0', 'grid_y': '0', 'title_text': 'CPU Usage', 'cpu_metric_to_display': 'usage'},
    {'type': 'cpu', 'displayer_type': 'arc_gauge', 'width': '16', 'height': '16', 'grid_x': '16', 'grid_y': '0', 'title_text': 'CPU Temperature', 'cpu_metric_to_display': 'temperature'},
    {'type': 'analog_clock', 'displayer_type': 'analog_clock', 'width': '16', 'height': '16', 'grid_x': '32', 'grid_y': '0', 'title_text': 'Clock'},
    {'type': 'memory_usage', 'displayer_type': 'arc_gauge', 'width': '16', 'height': '16', 'grid_x': '0', 'grid_y': '16', 'title_text': 'RAM'},
    {'type': 'disk_usage', 'displayer_type': 'arc_gauge', 'width': '16', 'height': '16', 'grid_x': '16', 'grid_y': '16', 'title_text': 'Disk'},
    {'type': 'gpu', 'displayer_type': 'level_bar', 'width': '16', 'height': '16', 'grid_x': '32', 'grid_y': '16', 'title_text': 'GPU TEMP', 'gpu_metric_to_display': 'temperature'},
]

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, sensors_ready_event=None):
        super().__init__(title="gSens System Monitor", application=app)
        self.app = app
        self.sensors_ready_event = sensors_ready_event

        # --- NEW: Add a flag to prevent resize signal recursion ---
        self._is_snapping = False

        # Use the centrally loaded module data
        self.AVAILABLE_DATA_SOURCES = AVAILABLE_DATA_SOURCES
        self.AVAILABLE_DISPLAYERS = AVAILABLE_DISPLAYERS
        self.ALL_SOURCE_CLASSES = ALL_SOURCE_CLASSES

        self.load_window_dimensions()
        
        self.grid_manager = GridLayoutManager(
            available_sources=self.AVAILABLE_DATA_SOURCES,
            available_displayers=self.AVAILABLE_DISPLAYERS,
            all_source_classes=self.ALL_SOURCE_CLASSES
        )
        
        self.scrolled_window = Gtk.ScrolledWindow(child=self.grid_manager)
        self.scrolled_window.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        self.grid_manager.set_scroll_adjustments(self.scrolled_window.get_hadjustment(), self.scrolled_window.get_vadjustment())

        main_overlay = Gtk.Overlay(child=self.scrolled_window)
        main_overlay.add_overlay(self.grid_manager.drag_preview_overlay_area)
        self.grid_manager.drag_preview_overlay_area.set_valign(Gtk.Align.FILL)
        self.grid_manager.drag_preview_overlay_area.set_halign(Gtk.Align.FILL)
        self.set_child(main_overlay)
        
        self.build_header_bar_and_actions()
        
        if hasattr(self.grid_manager, '_load_and_apply_grid_config'):
            self.grid_manager._load_and_apply_grid_config()
            
        self.connect("notify::fullscreened", self._on_fullscreen_changed)
        # --- NEW: Connect to size change signals for snapping ---
        self.connect("notify::default-width", self._on_window_resize_snap)
        self.connect("notify::default-height", self._on_window_resize_snap)
        self._setup_key_press_controller()
        GLib.timeout_add(100, self._check_sensors_ready)
        
        GLib.idle_add(self._apply_startup_fullscreen_settings)
        
    def _check_sensors_ready(self):
        """Periodically checks if the sensor discovery thread is done."""
        if self.sensors_ready_event and self.sensors_ready_event.is_set():
            self._on_sensors_ready()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE 

    def _on_sensors_ready(self):
        """Called when the background sensor discovery is complete."""
        # Now that sensors are discovered, we can safely load the panels.
        self.grid_manager.load_panels_from_config()
        self.add_panel_button.set_sensitive(True)
        return GLib.SOURCE_REMOVE

    def _setup_key_press_controller(self):
        key_controller = Gtk.EventControllerKey.new()
        key_controller.connect("key-pressed", self._on_key_pressed)
        self.add_controller(key_controller)

    def _on_key_pressed(self, controller, keyval, keycode, modifier):
        if keyval == Gdk.KEY_Delete:
            if self.grid_manager:
                self.grid_manager.delete_selected_panels()
                return True
        return False

    # --- NEW: Snapping logic ---
    def _reset_snapping_flag(self):
        """Resets the recursion guard flag."""
        self._is_snapping = False
        return GLib.SOURCE_REMOVE

    def _on_window_resize_snap(self, *args):
        """Callback to snap the window size to the nearest grid cell multiple."""
        if self._is_snapping or self.is_fullscreen():
            return

        self._is_snapping = True
        
        current_width = self.get_width()
        current_height = self.get_height()
        
        # Calculate the new size rounded to the nearest CELL_SIZE
        snapped_width = round(current_width / CELL_SIZE) * CELL_SIZE
        snapped_height = round(current_height / CELL_SIZE) * CELL_SIZE
        
        # Only resize if the size has actually changed to avoid unnecessary events
        if current_width != snapped_width or current_height != snapped_height:
            # --- FIX: Use set_default_size for GTK4 ---
            self.set_default_size(snapped_width, snapped_height)

        # Reset the flag after the current GTK main loop iteration is done
        GLib.idle_add(self._reset_snapping_flag)

    def _apply_startup_fullscreen_settings(self):
        grid_config = config_manager.config["GridLayout"] if config_manager.config.has_section("GridLayout") else {}
        if grid_config.get("launch_fullscreen", "False").lower() == 'true':
            try:
                monitor_index = int(grid_config.get("fullscreen_display_index", -1))
                display = self.get_display()
                monitors = display.get_monitors()
                num_monitors = monitors.get_n_items()
                if 0 <= monitor_index < num_monitors:
                    monitor = monitors.get_item(monitor_index)
                    self.fullscreen_on_monitor(monitor)
                else:
                    self.fullscreen()
            except (ValueError, TypeError) as e:
                print(f"Error applying fullscreen setting: {e}. Defaulting to current monitor.")
                self.fullscreen()
        return GLib.SOURCE_REMOVE

    def _on_fullscreen_changed(self, window, pspec):
        is_fullscreen = self.is_fullscreen()
        
        if self.grid_manager:
            if hasattr(self.grid_manager, '_update_fullscreen_menu_item_label'):
                self.grid_manager._update_fullscreen_menu_item_label(self)
            
            # --- MODIFIED: Delegate scrolling logic to the central method ---
            self.grid_manager.check_and_update_scrolling_state()

    def toggle_fullscreen_mode(self, action=None, parameter=None):
        if self.is_fullscreen(): self.unfullscreen()
        else: self.fullscreen()

    def save_window_dimensions(self):
        if not self.is_fullscreen():
            config_manager.save_window_config({"width": str(self.get_width()), "height": str(self.get_height())})

    def load_window_dimensions(self):
        window_cfg = config_manager.get_window_config()
        self.set_default_size(int(window_cfg.get("width", CELL_SIZE * 48)), int(window_cfg.get("height", CELL_SIZE * 32)))

    def on_add_panel_activate(self, *args):
        """Opens the new Panel Builder dialog."""
        sorted_sources = sorted(list(self.AVAILABLE_DATA_SOURCES.values()), key=lambda x: x['name'])
        sorted_displayers = sorted(list(self.AVAILABLE_DISPLAYERS.values()), key=lambda x: x['name'])
        
        PanelBuilderDialog(self, self.grid_manager, sorted_sources, sorted_displayers)

    def build_header_bar_and_actions(self):
        header = Gtk.HeaderBar(); self.set_titlebar(header)
        
        self.add_panel_button = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Add Panel")
        self.add_panel_button.set_action_name("win.add_panel")
        self.add_panel_button.set_sensitive(False) # Initially disabled while scanning
        header.pack_start(self.add_panel_button)

        menu_btn = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu")
        main_menu = Gio.Menu()
        main_menu.append("Save current layout...", "win.save_layout_as")
        main_menu.append("Load layout...", "win.load_layout_from")
        main_menu.append_section(None, Gio.Menu.new())
        main_menu.append("Reset to Default", "win.reset_panels")
        main_menu.append("Clear All Panels", "win.clear_panels")
        main_menu.append_section(None, Gio.Menu.new())
        main_menu.append("Quit", "app.quit")
        menu_btn.set_menu_model(main_menu)
        header.pack_end(menu_btn)

        actions = {"add_panel": self.on_add_panel_activate,
                   "save_layout_as": self.on_save_layout_as, 
                   "load_layout_from": self.on_load_layout_from, 
                   "reset_panels": self.on_reset_panels, 
                   "clear_panels": self.on_clear_panels, 
                   "toggle_fullscreen": self.toggle_fullscreen_mode}
        for name, cb in actions.items():
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", cb)
            self.add_action(action)

        def save_layout_now_cb(action, parameter):
            self.save_window_dimensions()
            config_manager.save()
            print("Layout saved.")
        
        save_now_action = Gio.SimpleAction.new("save_layout_now", None)
        save_now_action.connect("activate", save_layout_now_cb)
        self.add_action(save_now_action)

    def on_clear_panels(self, *args):
        if show_confirmation_dialog(self, "Clear All?", "This will delete all panels.", "This action cannot be undone.", "_Delete", "destructive-action") == Gtk.ResponseType.OK:
            self.grid_manager.clear_all_panels()
            config_manager.save()

    def on_reset_panels(self, *args):
        if show_confirmation_dialog(self, "Reset Layout?", "This will replace the current layout with the default one.", "This action cannot be undone.", "_Reset", "destructive-action") == Gtk.ResponseType.OK:
            self.grid_manager.clear_all_panels()
            for cfg_template in DEFAULT_PANEL_LAYOUT:
                self.grid_manager.create_and_add_panel_from_config(cfg_template.copy())
            config_manager.save()

    def on_save_layout_as(self, *args):
        chooser = Gtk.FileChooserNative.new("Save Layout", self, Gtk.FileChooserAction.SAVE, "_Save", "_Cancel")
        chooser.set_current_name("my_layout.ini")
        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                self.save_window_dimensions()
                config_manager.save(dialog.get_file().get_path())
            dialog.destroy()
        chooser.connect("response", on_response)
        chooser.show()

    def on_load_layout_from(self, *args):
        chooser = Gtk.FileChooserNative.new("Load Layout", self, Gtk.FileChooserAction.OPEN, "_Open", "_Cancel")
        def on_response(dialog, response):
            if response == Gtk.ResponseType.ACCEPT:
                self.grid_manager.clear_all_panels()
                if config_manager.load(dialog.get_file().get_path()):
                    self.load_window_dimensions()
                    self.grid_manager.load_panels_from_config()
            dialog.destroy()
        chooser.connect("response", on_response)
        chooser.show()

    def do_close_request(self):
        dialog = CustomDialog(self, "Quit Application", "Save current layout before quitting?", icon_name="dialog-question-symbolic")
        dialog.add_styled_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_styled_button("_Quit Without Saving", Gtk.ResponseType.NO, "destructive-action")
        dialog.add_styled_button("_Save and Quit", Gtk.ResponseType.YES, "suggested-action", is_default=True)
        response = dialog.run()
        
        if response == Gtk.ResponseType.YES:
            self.save_window_dimensions()
            config_manager.save()
            self.app.quit()
        elif response == Gtk.ResponseType.NO:
            self.app.quit()
            
        return True

class SystemMonitorApp(Gtk.Application):
    def __init__(self, **kwargs):
        super().__init__(application_id="com.example.gtk-system-monitor", 
                         flags=Gio.ApplicationFlags.NON_UNIQUE, **kwargs)
        self.window = None
        self.sensors_ready_event = threading.Event()

    def do_activate(self):
        if not self.window or not self.window.is_visible():
            self.window = MainWindow(self, sensors_ready_event=self.sensors_ready_event)
        self.window.present()

    def do_command_line(self, command_line):
        self.activate()
        return 0

    def do_startup(self):
        Gtk.Application.do_startup(self)
        
        try:
            icon_name = self.get_application_id()
            if icon_name:
                Gtk.Window.set_default_icon_name(icon_name)
        except Exception as e:
            print(f"Warning: Could not set default icon by name: {e}")

        gpu_manager.init()
        update_manager.start()
        
        sensor_discovery_thread = threading.Thread(target=self._discover_sensors_background, 
                                                   args=(self.sensors_ready_event,), 
                                                   daemon=True)
        sensor_discovery_thread.start()
        
        for sig in [signal.SIGINT, signal.SIGTERM]:
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.on_signal, sig)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def _discover_sensors_background(self, ready_event):
        """
        Worker function to discover all hardware sensors in the background.
        """
        print("Starting background sensor discovery...")
        try:
            SENSOR_CACHE['cpu_temp'] = CPUDataSource._discover_cpu_temp_sensors_statically()
            print(f"Background discovery: Found {len(SENSOR_CACHE.get('cpu_temp', []))} CPU temperature sensors.")
            
            SENSOR_CACHE['fan_speed'] = FanSpeedDataSource._discover_fans_statically()
            print(f"Background discovery: Found {len(SENSOR_CACHE.get('fan_speed', []))} fans.")

            SENSOR_CACHE['system_temp'] = SystemTempDataSource._discover_temp_sensors_statically()
            print(f"Background discovery: Found {len(SENSOR_CACHE.get('system_temp', []))} general system temperature sensors.")

        except Exception as e:
            print(f"Error during background sensor discovery: {e}")
        finally:
            print("Background sensor discovery finished.")
            ready_event.set()

    def do_shutdown(self):
        update_manager.stop()
        gpu_manager.shutdown()
        Gtk.Application.do_shutdown(self)

    def on_quit(self, *args):
        if self.window and self.window.is_visible():
            if not self.window.do_close_request():
                return
        self.quit()

    def on_signal(self, signum):
        print(f"Caught signal {signum}, attempting graceful shutdown.")
        self.quit()
        return True

if __name__ == "__main__":
    app = SystemMonitorApp()
    sys.exit(app.run(sys.argv))

