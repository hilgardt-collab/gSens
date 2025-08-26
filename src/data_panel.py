import gi
import threading
import time

from panel_base import BasePanel
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from ui_helpers import build_background_config_ui, CustomDialog

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib
from config_manager import config_manager

from data_sources.analog_clock import AnalogClockDataSource

class DataPanel(BasePanel):
    """
    A generic panel that is composed of a DataSource and a DataDisplayer.
    It orchestrates data fetching, display updates, and configuration management.
    """
    def __init__(self, config, data_source, data_displayer, available_sources):
        self.data_source = data_source
        self.available_sources = available_sources
        
        self.is_clock_source = isinstance(data_source, AnalogClockDataSource)

        self._update_thread = None
        self._stop_thread_event = threading.Event()
        
        super().__init__(title=config.get("title_text", "Data Panel"), config=config)
        
        self.data_displayer = data_displayer
        self.data_displayer.panel_ref = self
        self.data_displayer.is_clock_source = self.is_clock_source

        self.set_displayer_widget()
        
        self.data_source.config = self.config
        if hasattr(self.data_source, 'setup_child_sources'):
            self.data_source.setup_child_sources(self.available_sources)

        self.apply_all_configurations()
        
        self.start_update_thread()

    def set_displayer_widget(self):
        """Removes the old displayer widget and adds the new one."""
        if self.content_area.get_first_child():
            self.content_area.remove(self.content_area.get_first_child())
        
        self.content_area.append(self.data_displayer.get_widget())

    def _update_worker(self):
        """The target function for the dedicated background thread."""
        while not self._stop_thread_event.is_set():
            if self.data_source is None:
                break
            
            value = self.data_source.get_data()
            
            if self._stop_thread_event.is_set() or self.data_source is None:
                break

            if value is not None:
                numerical_value = self.data_source.get_numerical_value(value)
                self.check_and_update_alarm_state(numerical_value, self.data_source.alarm_config_prefix)
            else:
                self.exit_alarm_state()
            
            if self.data_displayer:
                GLib.idle_add(self.data_displayer.update_display, value)
            
            update_interval = float(self.config.get("update_interval_seconds", "2.0"))
            self._stop_thread_event.wait(timeout=update_interval)

    def start_update_thread(self):
        """Stops any existing thread and starts a new one."""
        self.stop_update_thread()
        
        self._stop_thread_event.clear()
        self._update_thread = threading.Thread(target=self._update_worker, daemon=True)
        self._update_thread.start()

    def stop_update_thread(self):
        """Signals the worker thread to stop and waits for it to terminate."""
        if self._update_thread and self._update_thread.is_alive():
            self._stop_thread_event.set()
            self._update_thread.join(timeout=2.0)
        self._update_thread = None
        
    def apply_all_configurations(self):
        """Applies all configurations from the config dictionary to the panel and its components."""
        self.data_source.config = self.config
        
        if hasattr(self.data_source, 'setup_child_sources'):
            self.data_source.setup_child_sources(self.available_sources)

        self.data_displayer.config = self.config
        self.data_displayer.is_clock_source = isinstance(self.data_source, AnalogClockDataSource)

        super().apply_all_configurations()
        
        if self.data_displayer and hasattr(self.data_displayer, 'reset_state'):
            self.data_displayer.reset_state()
            
        self.data_displayer.apply_styles()
        
    def close_panel(self, widget=None):
        """
        Handles the complete cleanup of the panel and its components,
        ensuring all references are broken to prevent memory leaks.
        """
        self.stop_update_thread()
        
        if self.data_displayer:
            self.data_displayer.close()
            self.data_displayer = None
            
        if self.data_source:
            if hasattr(self.data_source, 'close'):
                self.data_source.close()
            self.data_source = None
            
        super().close_panel(widget)

    def configure(self, *args):
        """Opens a comprehensive configuration dialog for the panel."""
        if self._config_dialog and self._config_dialog.get_visible():
            self._config_dialog.present()
            return

        parent_window = self.get_ancestor(Gtk.Window)
        dialog = CustomDialog(parent=parent_window, title=f"Configure: {self.config.get('title_text', self.original_title)}", modal=False)
        self._config_dialog = dialog
        dialog.ui_models = {}
        dialog.dynamic_models = []
        dialog.set_default_size(480, 750)

        original_config_on_open = self.config.copy()
        original_displayer_on_open = self.data_displayer 
        dialog_state = {'changes_applied': False}

        content_area = dialog.get_content_area()
        notebook = Gtk.Notebook()
        content_area.append(notebook)
        
        main_window = self.get_ancestor(Gtk.Window)
        AVAILABLE_DATA_SOURCES = self.available_sources
        AVAILABLE_DISPLAYERS = getattr(main_window, 'AVAILABLE_DISPLAYERS', {})
        
        all_widgets = {}
        original_displayer_key_on_open = self.config.get('displayer_type')

        source_type = self.config.get('type')
        compatible_displayers = {}
        if source_type and source_type in AVAILABLE_DATA_SOURCES:
            compatible_keys = AVAILABLE_DATA_SOURCES[source_type].get('displayers', [])
            for key in compatible_keys:
                if key in AVAILABLE_DISPLAYERS:
                    compatible_displayers[key] = AVAILABLE_DISPLAYERS[key]

        displayer_options = {info['name']: key for key, info in compatible_displayers.items()}
        display_type_model = {"Display Type": [ConfigOption("displayer_type", "dropdown", "Display Style:", self.config.get('displayer_type'), options_dict=displayer_options)]}
        
        panel_model = { "General Panel Settings": [
            ConfigOption("title_text", "string", "Panel Title:", self.config.get("title_text", self.original_title)),
            ConfigOption("show_title", "bool", "Show Title:", str(self.config.get("show_title", True))),
            ConfigOption("title_font", "font", "Title Font:", self.config.get("title_font", "Sans Bold 10")),
            ConfigOption("title_color", "color", "Title Color:", self.config.get("title_color", "#FFFFFF")),
            ConfigOption("width", "spinner", "Width (grid units):", self.config.get("width", 2), 1, 128, 1),
            ConfigOption("height", "spinner", "Height (grid units):", self.config.get("height", 2), 1, 128, 1)
        ]}
        source_model = self.data_source.get_config_model()
        
        has_custom_displayer_ui = hasattr(self.data_displayer, 'get_configure_callback') and self.data_displayer.get_configure_callback() is not None

        def build_new_display_tab():
            """Builds or rebuilds the 'Display' tab in the config notebook."""
            scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
            tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            scroll.set_child(tab_box)
            scroll.set_vexpand(True)
            
            custom_builder_callback = getattr(self.data_displayer, 'get_configure_callback', lambda: None)()
            if custom_builder_callback:
                custom_builder_callback(dialog, tab_box, all_widgets, AVAILABLE_DATA_SOURCES, self.config)
            else:
                display_model = self.data_displayer.get_config_model()
                build_ui_from_model(tab_box, self.config, display_model, all_widgets)

            notebook.append_page(scroll, Gtk.Label(label="Display"))

        def on_display_type_changed(combo):
            """Handles changing the displayer type."""
            selected_displayer_key = combo.get_active_id()
            
            if not selected_displayer_key or self.config.get('displayer_type') == selected_displayer_key:
                return

            self.config['displayer_type'] = selected_displayer_key
            config_manager.update_panel_config(self.config["id"], self.config)
            
            if main_window and hasattr(main_window, 'grid_manager'):
                 main_window.grid_manager.recreate_panel(self.config['id'])
            
            dialog.destroy()
            
            print("INFO: Panel display type changed. Please re-open configuration for the new panel.")
            return

        # Build Notebook Tab 1: General Panel Settings
        panel_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        panel_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        panel_scroll.set_child(panel_tab_box)
        notebook.append_page(panel_scroll, Gtk.Label(label="Panel"))
        build_ui_from_model(panel_tab_box, self.config, display_type_model, all_widgets)
        all_widgets['displayer_type'].connect('changed', on_display_type_changed)
        build_ui_from_model(panel_tab_box, self.config, panel_model, all_widgets)
        
        build_background_config_ui(panel_tab_box, self.config, all_widgets, dialog, prefix="panel_", title="Panel Background")

        # Build Notebook Tab 2: Data Source Settings
        source_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        source_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        source_scroll.set_child(source_tab_box)
        notebook.append_page(source_scroll, Gtk.Label(label="Data Source"))
        build_ui_from_model(source_tab_box, self.config, source_model, all_widgets)

        source_custom_builder = getattr(self.data_source, 'get_configure_callback', lambda: None)()
        if source_custom_builder:
            source_custom_builder(dialog, source_tab_box, all_widgets, AVAILABLE_DATA_SOURCES, self.config)

        # Build Notebook Tab 3: Display Settings (initial build)
        build_new_display_tab()
        
        def apply_changes(widget=None):
            """Gathers all values from UI widgets and applies them to the config."""
            dialog_state['changes_applied'] = True 
            
            models_to_check = [
                panel_model,
                display_type_model,
                source_model,
                self.data_displayer.get_config_model(), 
                *dialog.dynamic_models
            ]

            if hasattr(dialog, 'ui_models'):
                models_to_check.extend(dialog.ui_models.values())
            
            new_conf = get_config_from_widgets(all_widgets, models_to_check)
            
            if hasattr(dialog, 'custom_value_getter') and callable(dialog.custom_value_getter):
                custom_values = dialog.custom_value_getter()
                if custom_values:
                    new_conf.update(custom_values)
                    
            final_displayer_key = new_conf.get('displayer_type', original_displayer_key_on_open)
            
            self.config.update(new_conf)
            self.config['displayer_type'] = final_displayer_key
            
            config_manager.update_panel_config(self.config["id"], self.config)

            if original_displayer_key_on_open != final_displayer_key:
                main_window.grid_manager.recreate_panel(self.config['id'])
            else:
                self.apply_all_configurations()

            self.start_update_thread()

        # Dialog Actions
        cancel_button = dialog.add_non_modal_button("_Cancel", style_class="destructive-action")
        cancel_button.connect("clicked", lambda w: dialog.destroy())
        apply_button = dialog.add_non_modal_button("_Apply")
        apply_button.connect("clicked", apply_changes)
        accept_button = dialog.add_non_modal_button("_Accept", style_class="suggested-action", is_default=True)
        def on_accept(widget):
            apply_changes(widget)
            if dialog.is_visible():
                dialog.destroy()
        accept_button.connect("clicked", on_accept)

        def on_dialog_destroy(d):
            if not dialog_state['changes_applied']:
                if self.data_displayer is not original_displayer_on_open:
                    self.data_displayer.close()
                    self.data_displayer = original_displayer_on_open
                
                self.config = original_config_on_open
                self.set_displayer_widget()
                self.apply_all_configurations()
            
            self.on_config_dialog_destroy(d)

        dialog.connect("destroy", on_dialog_destroy)
        dialog.present()
