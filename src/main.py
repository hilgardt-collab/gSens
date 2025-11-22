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
# Import Gdk for monitor information
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

# --- Import config_dialog to pre-load the font dialog ---
import config_dialog

DEFAULT_PANEL_LAYOUT = [
    {'type': 'cpu', 'displayer_type': 'arc_gauge', 'width': '16', 'height': '16', 'grid_x': '0', 'grid_y': '0', 'title_text': 'CPU Usage', 'cpu_metric_to_display': 'usage'},
    {'type': 'cpu', 'displayer_type': 'arc_gauge', 'width': '16', 'height': '16', 'grid_x': '16', 'grid_y': '0', 'title_text': 'CPU Temperature', 'cpu_metric_to_display': 'temperature'},
    {'type': 'analog_clock', 'displayer_type': 'analog_clock', 'width': '16', 'height': '16', 'grid_x': '32', 'grid_y': '0', 'title_text': 'Clock'},
    {'type': 'memory_usage', 'displayer_type': 'arc_gauge', 'width': '16', 'height': '16', 'grid_x': '0', 'grid_y': '16', 'title_text': 'RAM'},
    {'type': 'disk_usage', 'displayer_type': 'arc_gauge', 'width': '16', 'height': '16', 'grid_x': '16', 'grid_y': '16', 'title_text': 'Disk'},
    {'type': 'gpu', 'displayer_type': 'level_bar', 'width': '16', 'height': '16', 'grid_x': '32', 'grid_y': '16', 'title_text': 'GPU TEMP', 'gpu_metric_to_display': 'temperature'},
]

class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, app, sensors_ready_event=None, cli_options=None):
        super().__init__(title="gSens System Monitor", application=app)
        self.app = app
        self.sensors_ready_event = sensors_ready_event
        # Store command-line options
        self.cli_options = cli_options or {}

        # --- NEW: Add a flag to prevent resize signal recursion ---
        self._is_snapping = False

        # Use the centrally loaded module data
        self.AVAILABLE_DATA_SOURCES = AVAILABLE_DATA_SOURCES
        self.AVAILABLE_DISPLAYERS = AVAILABLE_DISPLAYERS
        self.ALL_SOURCE_CLASSES = ALL_SOURCE_CLASSES
        
        # --- Apply borderless setting immediately on startup ---
        if config_manager.config.has_section("GridLayout"):
            grid_config = config_manager.config["GridLayout"]
            is_borderless = str(grid_config.get("window_borderless", "False")).lower() == 'true'
            self.set_decorated(not is_borderless)

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
        
        # Apply fullscreen settings based on CLI args and config
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

    def _fullscreen_on_monitor_index(self, monitor_index):
        """Helper function to fullscreen on a specific monitor index."""
        try:
            display = self.get_display()
            monitors = display.get_monitors()
            num_monitors = monitors.get_n_items()
            if 0 <= monitor_index < num_monitors:
                monitor = monitors.get_item(monitor_index)
                self.fullscreen_on_monitor(monitor)
            else:
                print(f"Warning: Monitor index {monitor_index} is out of range (0-{num_monitors-1}). Defaulting to primary.")
                self.fullscreen()
        except Exception as e:
            print(f"Error applying fullscreen to monitor {monitor_index}: {e}. Defaulting.")
            self.fullscreen()

    def _apply_startup_fullscreen_settings(self):
        """
        Applies fullscreen settings, prioritizing command-line arguments
        over saved configuration.
        """
        # 1. Check for --windowed override
        if 'windowed' in self.cli_options:
            return GLib.SOURCE_REMOVE # Do nothing, stay windowed

        # 2. Check for --fullscreen-monitor=N
        if 'fullscreen-monitor' in self.cli_options:
            try:
                monitor_index = int(self.cli_options['fullscreen-monitor'])
                self._fullscreen_on_monitor_index(monitor_index)
            except (ValueError, TypeError):
                print(f"Invalid monitor index: '{self.cli_options['fullscreen-monitor']}'. Defaulting to primary.")
                self.fullscreen()
            return GLib.SOURCE_REMOVE

        # 3. Check for -f or --fullscreen
        if 'fullscreen' in self.cli_options:
            self.fullscreen()
            return GLib.SOURCE_REMOVE

        # 4. If no CLI args, use config file settings
        grid_config = config_manager.config["GridLayout"] if config_manager.config.has_section("GridLayout") else {}
        if grid_config.get("launch_fullscreen", "False").lower() == 'true':
            try:
                monitor_index = int(grid_config.get("fullscreen_display_index", -1))
                if monitor_index == -1:
                    self.fullscreen()
                else:
                    self._fullscreen_on_monitor_index(monitor_index)
            except (ValueError, TypeError) as e:
                print(f"Error applying config fullscreen setting: {e}. Defaulting.")
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
            config_manager.save(immediate=True) # Explicit user action should save immediately
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
            # Force immediate save on exit to bypass debounce timer
            config_manager.save(immediate=True)
            self.app.quit()
        elif response == Gtk.ResponseType.NO:
            self.app.quit()
            
        return True

class SystemMonitorApp(Gtk.Application):
    def __init__(self, **kwargs):
        super().__init__(application_id="com.example.gtk-system-monitor", 
                         # Add HANDLES_COMMAND_LINE flag
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE | Gio.ApplicationFlags.NON_UNIQUE, 
                         **kwargs)
        self.window = None
        self.sensors_ready_event = threading.Event()
        self.command_line_options = {} # To store parsed options
        
        # --- FIX: Register options in __init__ ---
        # This must be done *before* app.run() is called.
        
        # Gtk automatically handles --help
        self.add_main_option(
            "fullscreen", ord("f"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE, 
            "Launch in fullscreen mode on the primary monitor", None)
        self.add_main_option(
            "fullscreen-monitor", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
            "Launch fullscreen on a specific monitor (e.g., '1')", "MONITOR_INDEX")
        self.add_main_option(
            "windowed", 0, GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Launch in windowed mode (overrides config file)", None)
        self.add_main_option(
            "list-monitors", ord("l"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "List available monitors and exit", None)
        self.add_main_option(
            "config", 0, GLib.OptionFlags.NONE, GLib.OptionArg.STRING,
            "Load a specific config file", "FILEPATH")
        self.add_main_option(
            "version", ord("v"), GLib.OptionFlags.NONE, GLib.OptionArg.NONE,
            "Show application version and exit", None)

    def do_activate(self):
        """
        Called when the application is activated without command-line args,
        or after do_command_line finishes.
        """
        if not self.window or not self.window.is_visible():
            self.window = MainWindow(self, 
                                     sensors_ready_event=self.sensors_ready_event,
                                     cli_options=self.command_line_options)
        self.window.present()
        # Clear options after passing them to the window
        self.command_line_options = {}

    def do_command_line(self, command_line):
        """Handles command-line argument processing."""
        options = command_line.get_options_dict()
        # Convert GVariantDict to a Python dict
        options = options.end().unpack()

        # Handle --version
        # --- FIX: Only check for the long name 'version' ---
        if 'version' in options:
            print("gSens System Monitor 1.0.0") # You can update this version
            return 0 # Exit successfully

        # Handle --list-monitors
        # --- FIX: Only check for the long name 'list-monitors' ---
        if 'list-monitors' in options:
            self._list_monitors()
            return 0 # Exit successfully
        
        # Gtk.Application handles --help and -h automatically
        
        # Handle --config
        if 'config' in options:
            config_path = options['config']
            if os.path.exists(config_path) and os.path.isfile(config_path):
                print(f"Loading configuration from: {config_path}")
                # Load the user-specified config. This will overwrite the default
                # one loaded by config_manager's __init__.
                if not config_manager.load(config_path):
                    print(f"Error: Could not parse config file: {config_path}. Exiting.")
                    return 1 # Exit with error
            else:
                print(f"Error: Config file not found: {config_path}. Exiting.")
                return 1 # Exit with error
        else:
            # No config specified, load default (which config_manager already did)
            pass

        # Store other options to be passed to MainWindow
        self.command_line_options = options
        
        # Call do_activate() to build and show the window
        self.activate()
        return 0

    def _list_monitors(self):
        """Prints available monitors to the console."""
        print("Available Monitors:")
        # We need a display to list monitors, Gtk.Application might not be
        # fully initialized, but Gdk.Display.get_default() should be safe.
        display = Gdk.Display.get_default()
        if not display:
            print("  Could not get display information.")
            return
        
        monitors = display.get_monitors()
        for i in range(monitors.get_n_items()):
            monitor = monitors.get_item(i)
            manufacturer = monitor.get_manufacturer() or "Unknown"
            model = monitor.get_model() or "Unknown"
            rect = monitor.get_geometry()
            print(f"  Monitor {i}: {manufacturer} {model} ({rect.width}x{rect.height} at {rect.x},{rect.y})")

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

        # --- NEW: Pre-load the font dialog in the background ---
        font_cache_thread = threading.Thread(target=self._initialize_font_dialog_background,
                                             daemon=True)
        font_cache_thread.start()
        # --- END NEW ---
        
        for sig in [signal.SIGINT, signal.SIGTERM]:
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, self.on_signal, sig)

        action = Gio.SimpleAction.new("quit", None)
        action.connect("activate", self.on_quit)
        self.add_action(action)
        self.set_accels_for_action("app.quit", ["<Control>q"])

    def _initialize_font_dialog_background(self):
        """
        In a background thread, creates the singleton font dialog.
        This pre-caches the system font list, so the first time
        the user clicks a font button, it appears instantly.
        """
        print("Starting background font cache initialization...")
        try:
            # Calling this function will create the singleton instance
            # in the background, triggering the initial (slow) font scan.
            # We pass None for the parent, which is fine for creation.
            config_dialog.get_global_font_dialog(None)
            print("Background font cache initialized.")
        except Exception as e:
            # This might fail in headless environments, but shouldn't crash the app
            print(f"Warning: Background font cache initialization failed: {e}")

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
