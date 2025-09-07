# data_panel.py
import gi
import threading
import time
import datetime

from panel_base import BasePanel
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from ui_helpers import build_background_config_ui, CustomDialog

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib
from config_manager import config_manager

from data_sources.analog_clock import AnalogClockDataSource
from update_manager import update_manager

class DataPanel(BasePanel):
    """
    A generic panel that is composed of a DataSource and a DataDisplayer.
    It orchestrates data fetching, display updates, and configuration management.
    """
    def __init__(self, config, data_source, data_displayer, available_sources):
        self.data_source = data_source
        self.available_sources = available_sources
        
        self.is_clock_source = isinstance(data_source, AnalogClockDataSource)
        self._clock_timer_id = None
        
        source_type = config.get('type')
        default_title = "Data Panel"
        if source_type and source_type in self.available_sources:
            default_title = self.available_sources[source_type].get('name', default_title)
        
        super().__init__(title=config.get("title_text", default_title), config=config)
        
        self.data_displayer = data_displayer
        self.data_displayer.panel_ref = self
        self.data_displayer.is_clock_source = self.is_clock_source

        self.set_displayer_widget()
        
        self.data_source.config = self.config
        if hasattr(self.data_source, 'setup_child_sources'):
            self.data_source.setup_child_sources(self.available_sources)

        self.apply_all_configurations()
        
        if self.is_clock_source:
            self._clock_timer_id = GLib.idle_add(self._clock_tick)
        else:
            update_manager.register_panel(self)

    def _clock_tick(self):
        if not self.data_source or not self.get_ancestor(Gtk.Window):
            self._clock_timer_id = None
            return GLib.SOURCE_REMOVE

        value = self.data_source.get_data()
        self.process_update(value)
        
        now = datetime.datetime.now()
        delay = 1000 - (now.microsecond // 1000)
        
        self._clock_timer_id = GLib.timeout_add(max(50, delay), self._clock_tick)
        
        return GLib.SOURCE_REMOVE

    def process_update(self, value):
        if not self.data_source or not self.data_displayer:
            return

        # --- DYNAMIC TITLE LOGIC ---
        # If the user has NOT set a custom title override, update the panel title
        # dynamically from the data source's primary label.
        user_set_title = self.config.get("title_text", "").strip()
        
        source_type = self.config.get('type')
        default_source_name = self.available_sources.get(source_type, {}).get('name', 'Data Panel')

        # We can dynamically update if the user title is blank or is the same as the default source name
        can_dynamically_update = not user_set_title or user_set_title == default_source_name

        if can_dynamically_update and value is not None:
            dynamic_title = self.data_source.get_primary_label_string(value)
            if dynamic_title and self.title_label.get_text() != dynamic_title:
                self.title_label.set_text(dynamic_title)
        # --- END DYNAMIC TITLE LOGIC ---

        if value is not None:
            numerical_value = self.data_source.get_numerical_value(value)
            self.check_and_update_alarm_state(numerical_value, self.data_source.alarm_config_prefix)
        else:
            self.exit_alarm_state()
        
        if self.data_displayer:
            self.data_displayer.update_display(value)

    def set_displayer_widget(self):
        if self.content_area.get_first_child():
            self.content_area.remove(self.content_area.get_first_child())
        
        self.content_area.append(self.data_displayer.get_widget())
        
    def apply_all_configurations(self):
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
        if self._clock_timer_id:
            GLib.source_remove(self._clock_timer_id)
            self._clock_timer_id = None
            
        update_manager.unregister_panel(self)
        
        if self.data_displayer:
            self.data_displayer.close()
            self.data_displayer = None
            
        if self.data_source:
            if hasattr(self.data_source, 'close'):
                self.data_source.close()
            self.data_source = None
            
        super().close_panel(widget)

    def on_load_defaults_clicked(self, button):
        """Loads defaults and forces the config dialog to refresh."""
        self.popover.popdown()
        displayer_key = self.config.get('displayer_type')
        if not displayer_key: return
        
        defaults = config_manager.get_displayer_defaults(displayer_key)
        if not defaults: return
            
        if self._config_dialog and self._config_dialog.get_visible():
            self._update_widgets_from_config(self._config_dialog.all_widgets, defaults)
            self._config_dialog.apply_button.emit("clicked")
        else:
            self.config.update(defaults)
            self.apply_all_configurations()
            config_manager.update_panel_config(self.config["id"], self.config)

    def _update_widgets_from_config(self, widgets, new_config):
        """Directly updates the values of widgets in an open dialog."""
        for key, value in new_config.items():
            widget = widgets.get(key)
            if not widget: continue
            
            if isinstance(widget, Gtk.Switch):
                widget.set_active(str(value).lower() == 'true')
            elif isinstance(widget, Gtk.Entry):
                widget.set_text(str(value))
            elif isinstance(widget, (Gtk.SpinButton, Gtk.Scale)):
                widget.set_value(float(value))
            elif isinstance(widget, Gtk.ColorButton):
                rgba = Gdk.RGBA()
                if rgba.parse(str(value)):
                    widget.set_rgba(rgba)
            elif isinstance(widget, Gtk.FontButton):
                widget.set_font(str(value))
            elif isinstance(widget, Gtk.ComboBoxText):
                widget.set_active_id(str(value))


    def on_save_defaults_clicked(self, button):
        """Saves the current panel's style as the new default for its displayer type."""
        self.popover.popdown()
        displayer_key = self.config.get('displayer_type')
        if not displayer_key:
            print("Warning: Cannot save defaults, no displayer type found.")
            return

        if self.data_displayer:
            if config_manager.save_displayer_defaults(displayer_key, self.config, self.data_displayer.__class__):
                print(f"Saved current style as the default for '{displayer_key}'.")
            else:
                print(f"Error: Could not save default style for '{displayer_key}'.")

    def configure(self, *args):
        if self._config_dialog and self._config_dialog.get_visible():
            self._config_dialog.present()
            return

        parent_window = self.get_ancestor(Gtk.Window)
        
        # Determine initial title for the dialog
        source_type = self.config.get('type')
        default_source_name = self.available_sources.get(source_type, {}).get('name', 'Data Panel')
        initial_dialog_title = self.config.get('title_text', default_source_name)

        dialog = CustomDialog(parent=parent_window, title=f"Configure: {initial_dialog_title}", modal=False)
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
        dialog.all_widgets = all_widgets
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
            ConfigOption("title_text", "string", "Panel Title:", self.config.get("title_text", ""), 
                         tooltip="Leave blank to use the dynamic title from the data source."),
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

        panel_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC)
        panel_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        panel_scroll.set_child(panel_tab_box)
        notebook.append_page(panel_scroll, Gtk.Label(label="Panel"))
        build_ui_from_model(panel_tab_box, self.config, display_type_model, all_widgets)
        all_widgets['displayer_type'].connect('changed', on_display_type_changed)
        build_ui_from_model(panel_tab_box, self.config, panel_model, all_widgets)
        build_background_config_ui(panel_tab_box, self.config, all_widgets, dialog, prefix="panel_", title="Panel Background")

        source_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        source_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        source_scroll.set_child(source_tab_box)
        notebook.append_page(source_scroll, Gtk.Label(label="Data Source"))
        build_ui_from_model(source_tab_box, self.config, source_model, all_widgets)

        display_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        display_tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        display_scroll.set_child(display_tab_box)
        notebook.append_page(display_scroll, Gtk.Label(label="Display"))
        build_ui_from_model(display_tab_box, self.config, display_model, all_widgets)

        source_custom_builder = self.data_source.get_configure_callback()
        if source_custom_builder:
            source_custom_builder(dialog, source_tab_box, all_widgets, AVAILABLE_DATA_SOURCES, self.config)
            
        display_custom_builder = self.data_displayer.get_configure_callback()
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
            
            # --- TITLE LOGIC: If title is now blank, set it from dynamic label ---
            if not self.config.get("title_text", "").strip():
                # We need data to get the dynamic label, so we just apply the blank
                # title for now, and process_update will fix it on the next tick.
                self.title_label.set_text("")
            else:
                self.title_label.set_text(self.config.get("title_text"))
            
            config_manager.update_panel_config(self.config["id"], self.config)
            if original_displayer_key_on_open != final_displayer_key:
                main_window.grid_manager.recreate_panel(self.config['id'])
            else:
                self.apply_all_configurations()

        theme_box = Gtk.Box(spacing=6, halign=Gtk.Align.START, hexpand=True)
        load_btn = Gtk.Button(label="Load Default Style")
        load_btn.connect("clicked", self.on_load_defaults_clicked)
        theme_box.append(load_btn)
        save_btn = Gtk.Button(label="Save Style as Default")
        save_btn.connect("clicked", self.on_save_defaults_clicked)
        theme_box.append(save_btn)
        dialog.action_area.prepend(theme_box)

        cancel_button = dialog.add_non_modal_button("_Cancel", style_class="destructive-action")
        cancel_button.connect("clicked", lambda w: dialog.destroy())
        apply_button = dialog.add_non_modal_button("_Apply")
        dialog.apply_button = apply_button
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

