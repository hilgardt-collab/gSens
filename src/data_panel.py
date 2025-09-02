# data_panel.py
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
from update_manager import update_manager # Import the new manager

class DataPanel(BasePanel):
    """
    A generic panel that is composed of a DataSource and a DataDisplayer.
    It orchestrates data fetching, display updates, and configuration management.
    It no longer manages its own thread, instead registering with the central UpdateManager.
    """
    def __init__(self, config, data_source, data_displayer, available_sources):
        self.data_source = data_source
        self.available_sources = available_sources
        
        self.is_clock_source = isinstance(data_source, AnalogClockDataSource)
        
        super().__init__(title=config.get("title_text", "Data Panel"), config=config)
        
        self.data_displayer = data_displayer
        self.data_displayer.panel_ref = self
        self.data_displayer.is_clock_source = self.is_clock_source

        self.set_displayer_widget()
        
        self.data_source.config = self.config
        if hasattr(self.data_source, 'setup_child_sources'):
            self.data_source.setup_child_sources(self.available_sources)

        self.apply_all_configurations()
        
        # Register with the central update manager instead of starting a new thread.
        update_manager.register_panel(self)

    def process_update(self, value):
        """
        This method is called by the UpdateManager on the main GTK thread
        with the data fetched from the background thread. It handles all UI-related updates.
        """
        # Ensure the panel hasn't been closed while the data was being fetched
        if not self.data_source or not self.data_displayer:
            return

        if value is not None:
            numerical_value = self.data_source.get_numerical_value(value)
            self.check_and_update_alarm_state(numerical_value, self.data_source.alarm_config_prefix)
        else:
            self.exit_alarm_state()
        
        if self.data_displayer:
            self.data_displayer.update_display(value)

    def set_displayer_widget(self):
        """Removes the old displayer widget and adds the new one."""
        if self.content_area.get_first_child():
            self.content_area.remove(self.content_area.get_first_child())
        
        self.content_area.append(self.data_displayer.get_widget())
        
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
        # Unregister from the central update manager to stop receiving updates.
        update_manager.unregister_panel(self)
        
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
        display_model = self.data_displayer.get_config_model()

        def on_display_type_changed(combo):
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

        # 1. Build Tab 1: General Panel Settings
        panel_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        panel_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        panel_scroll.set_child(panel_tab_box)
        notebook.append_page(panel_scroll, Gtk.Label(label="Panel"))
        build_ui_from_model(panel_tab_box, self.config, display_type_model, all_widgets)
        all_widgets['displayer_type'].connect('changed', on_display_type_changed)
        build_ui_from_model(panel_tab_box, self.config, panel_model, all_widgets)
        build_background_config_ui(panel_tab_box, self.config, all_widgets, dialog, prefix="panel_", title="Panel Background")

        # 2. Build Tab 2: Data Source Settings
        source_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        source_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        source_scroll.set_child(source_tab_box)
        notebook.append_page(source_scroll, Gtk.Label(label="Data Source"))
        build_ui_from_model(source_tab_box, self.config, source_model, all_widgets)

        # 3. Build Tab 3: Display Settings (Static Part)
        display_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        display_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        display_scroll.set_child(display_tab_box)
        notebook.append_page(display_scroll, Gtk.Label(label="Display"))
        build_ui_from_model(display_tab_box, self.config, display_model, all_widgets)

        # 4. AFTER all static widgets are created, call the custom callbacks to add dynamic behavior
        source_custom_builder = getattr(self.data_source, 'get_configure_callback', lambda: None)()
        if source_custom_builder:
            source_custom_builder(dialog, source_tab_box, all_widgets, AVAILABLE_DATA_SOURCES, self.config)
            
        display_custom_builder = getattr(self.data_displayer, 'get_configure_callback', lambda: None)()
        if display_custom_builder:
            display_custom_builder(dialog, display_tab_box, all_widgets, AVAILABLE_DATA_SOURCES, self.config)
        
        def apply_changes(widget=None):
            dialog_state['changes_applied'] = True 
            models_to_check = [ panel_model, display_type_model, source_model, self.data_displayer.get_config_model(), *dialog.dynamic_models ]
            if hasattr(dialog, 'ui_models'): models_to_check.extend(dialog.ui_models.values())
            new_conf = get_config_from_widgets(all_widgets, models_to_check)
            
            if hasattr(dialog, 'custom_value_getter') and callable(dialog.custom_value_getter):
                custom_values = dialog.custom_value_getter()
                if custom_values: new_conf.update(custom_values)

            final_displayer_key = new_conf.get('displayer_type', original_displayer_key_on_open)
            self.config.update(new_conf)
            self.config['displayer_type'] = final_displayer_key
            config_manager.update_panel_config(self.config["id"], self.config)
            if original_displayer_key_on_open != final_displayer_key:
                main_window.grid_manager.recreate_panel(self.config['id'])
            else:
                self.apply_all_configurations()

        cancel_button = dialog.add_non_modal_button("_Cancel", style_class="destructive-action")
        cancel_button.connect("clicked", lambda w: dialog.destroy())
        apply_button = dialog.add_non_modal_button("_Apply")
        apply_button.connect("clicked", apply_changes)
        accept_button = dialog.add_non_modal_button("_Accept", style_class="suggested-action", is_default=True)
        def on_accept(widget):
            apply_changes(widget)
            if dialog.is_visible(): dialog.destroy()
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
