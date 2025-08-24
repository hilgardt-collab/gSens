# panel_builder_dialog.py
import gi
import uuid
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from ui_helpers import CustomDialog, build_background_config_ui
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

class PanelBuilderDialog:
    """
    A comprehensive dialog for creating a new, fully configured panel from scratch.
    """
    def __init__(self, parent_window, grid_manager, available_sources, available_displayers):
        self.parent_window = parent_window
        self.grid_manager = grid_manager
        self.AVAILABLE_DATA_SOURCES = available_sources
        self.AVAILABLE_DISPLAYERS = available_displayers

        self.selected_source_key = None
        self.selected_displayer_key = None
        
        self.source_class = None
        self.displayer_class = None

        self.dialog = CustomDialog(parent=parent_window, title="Create New Panel", modal=False)
        self.dialog.set_default_size(500, 700)
        
        self.widgets = {}
        self.current_config = {}
        # --- BUG FIX ---
        # Initialize dynamic_models as a list to handle multiple model dictionaries.
        self.dialog.dynamic_models = []

        self._build_ui()
        self.dialog.present()

    def _create_scrolled_tab_box(self):
        """
        Helper to create a standard scrolled window and the box inside it for a notebook tab.
        Returns a tuple: (Gtk.ScrolledWindow, Gtk.Box)
        """
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        scroll.set_child(box)
        return scroll, box

    def _build_ui(self):
        """Constructs the entire UI for the dialog."""
        content_area = self.dialog.get_content_area()
        
        notebook = Gtk.Notebook(margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        content_area.append(notebook)

        # --- Tab 1: Main Type Selection ---
        main_tab_scroll, main_tab_box = self._create_scrolled_tab_box()
        self._build_main_tab(main_tab_box)
        notebook.append_page(main_tab_scroll, Gtk.Label(label="Type"))

        # --- Tab 2: Data Source Config ---
        source_scroll, self.source_config_box = self._create_scrolled_tab_box()
        notebook.append_page(source_scroll, Gtk.Label(label="Data Source"))

        # --- Tab 3: Displayer Config ---
        displayer_scroll, self.displayer_config_box = self._create_scrolled_tab_box()
        notebook.append_page(displayer_scroll, Gtk.Label(label="Display"))
        
        # --- Tab 4: General Panel Config ---
        general_scroll, self.general_config_box = self._create_scrolled_tab_box()
        notebook.append_page(general_scroll, Gtk.Label(label="General"))
        
        # --- Dialog Actions ---
        self.dialog.add_non_modal_button("_Cancel", style_class="destructive-action").connect("clicked", lambda w: self.dialog.destroy())
        self.create_button = self.dialog.add_non_modal_button("_Create Panel", style_class="suggested-action", is_default=True)
        self.create_button.connect("clicked", self._on_create_panel)
        self.create_button.set_sensitive(False)

    def _build_main_tab(self, main_box):
        """Builds the first tab with Data Source and Displayer selectors."""
        # Data Source Dropdown
        source_model = Gtk.ListStore(str, str)
        source_model.append(["Select a Data Source...", ""])
        # Use the sorted list of metadata to populate the dropdown
        for info in self.AVAILABLE_DATA_SOURCES:
            source_model.append([info['name'], info['key']])
        
        source_combo = Gtk.ComboBox.new_with_model(source_model)
        renderer_text = Gtk.CellRendererText()
        source_combo.pack_start(renderer_text, True)
        source_combo.add_attribute(renderer_text, "text", 0)
        source_combo.set_active(0)
        source_combo.connect("changed", self._on_source_changed)

        main_box.append(Gtk.Label(label="<b>1. Choose a Data Source</b>", use_markup=True, xalign=0, margin_bottom=5))
        main_box.append(source_combo)

        # Displayer Dropdown
        self.displayer_model = Gtk.ListStore(str, str)
        self.displayer_combo = Gtk.ComboBox.new_with_model(self.displayer_model)
        renderer_text_disp = Gtk.CellRendererText()
        self.displayer_combo.pack_start(renderer_text_disp, True)
        self.displayer_combo.add_attribute(renderer_text_disp, "text", 0)
        self.displayer_combo.connect("changed", self._on_displayer_changed)
        
        main_box.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=15, margin_bottom=10))
        main_box.append(Gtk.Label(label="<b>2. Choose a Display Style</b>", use_markup=True, xalign=0, margin_bottom=5))
        main_box.append(self.displayer_combo)
        
        self.displayer_combo.set_sensitive(False)

    def _on_source_changed(self, combo):
        """Handles when the user selects a different data source."""
        tree_iter = combo.get_active_iter()
        if tree_iter is None: return
        
        self.selected_source_key = combo.get_model()[tree_iter][1]
        
        self.selected_displayer_key = None
        self.displayer_class = None
        self.create_button.set_sensitive(False)

        self.displayer_model.clear()
        self.displayer_model.append(["Select a Display Style...", ""])
        
        if self.selected_source_key:
            source_info = next((s for s in self.AVAILABLE_DATA_SOURCES if s['key'] == self.selected_source_key), None)
            self.source_class = source_info['class']
            
            compatible_displayers = sorted(
                [d for d in self.AVAILABLE_DISPLAYERS if d['key'] in source_info['displayers']],
                key=lambda x: x['name']
            )

            for disp_info in compatible_displayers:
                self.displayer_model.append([disp_info['name'], disp_info['key']])
            
            self.displayer_combo.set_active(0)
            self.displayer_combo.set_sensitive(True)
        else:
            self.source_class = None
            self.displayer_combo.set_sensitive(False)
        
        self._rebuild_config_tabs()

    def _on_displayer_changed(self, combo):
        """Handles when the user selects a different displayer."""
        tree_iter = combo.get_active_iter()
        if tree_iter is None: return
        
        self.selected_displayer_key = combo.get_model()[tree_iter][1]
        
        if self.selected_displayer_key:
            self.displayer_class = next(d['class'] for d in self.AVAILABLE_DISPLAYERS if d['key'] == self.selected_displayer_key)
            self.create_button.set_sensitive(True)
        else:
            self.displayer_class = None
            self.create_button.set_sensitive(False)
            
        self._rebuild_config_tabs()

    def _clear_box(self, box):
        """Removes all children from a Gtk.Box."""
        child = box.get_first_child()
        while child:
            box.remove(child)
            child = box.get_first_child()

    def _rebuild_config_tabs(self):
        """Clears and rebuilds all configuration tabs based on current selections."""
        self.widgets.clear()
        self.current_config.clear()
        self.dialog.dynamic_models.clear()
        
        self._clear_box(self.source_config_box)
        self._clear_box(self.displayer_config_box)
        self._clear_box(self.general_config_box)

        if not self.source_class or not self.displayer_class:
            return

        source_info = next((s for s in self.AVAILABLE_DATA_SOURCES if s['key'] == self.selected_source_key), None)

        # --- Build Source Config Tab ---
        source_model = self.source_class.get_config_model()
        populate_defaults_from_model(self.current_config, source_model)
        build_ui_from_model(self.source_config_box, self.current_config, source_model, self.widgets)

        # --- Synchronize Displayer Range with Source Range ---
        source_min_val, source_max_val = None, None
        for section in source_model.values():
            for option in section:
                if option.key == 'graph_min_value':
                    source_min_val = option.default
                if option.key == 'graph_max_value':
                    source_max_val = option.default
        
        if source_min_val is not None and source_max_val is not None:
            if self.selected_displayer_key == 'arc_gauge':
                self.current_config['gauge_min_value'] = source_min_val
                self.current_config['gauge_max_value'] = source_max_val
            elif self.selected_displayer_key == 'speedometer':
                self.current_config['speedo_min_value'] = source_min_val
                self.current_config['speedo_max_value'] = source_max_val
            elif self.selected_displayer_key == 'level_bar':
                self.current_config['level_min_value'] = source_min_val
                self.current_config['level_max_value'] = source_max_val

        # --- Build Displayer Config Tab ---
        displayer_model = self.displayer_class.get_config_model()
        populate_defaults_from_model(self.current_config, displayer_model)
        build_ui_from_model(self.displayer_config_box, self.current_config, displayer_model, self.widgets)

        # --- Build General Config Tab ---
        def_w, def_h = source_info.get("default_size", (2, 2))
        
        general_model = { "General Panel Settings": [
            ConfigOption("title_text", "string", "Panel Title:", source_info["name"]),
            ConfigOption("width", "spinner", "Width (grid units):", def_w, 1, 128, 1),
            ConfigOption("height", "spinner", "Height (grid units):", def_h, 1, 128, 1)
        ]}
        populate_defaults_from_model(self.current_config, general_model)
        build_ui_from_model(self.general_config_box, self.current_config, general_model, self.widgets)
        
        build_background_config_ui(self.general_config_box, self.current_config, self.widgets, self.dialog)

    def _on_create_panel(self, button):
        """Gathers all data and tells the grid manager to create the panel."""
        if not self.source_class or not self.displayer_class:
            return

        source_info = next((s for s in self.AVAILABLE_DATA_SOURCES if s['key'] == self.selected_source_key), None)
        
        source_model = self.source_class.get_config_model()
        displayer_model = self.displayer_class.get_config_model()
        def_w, def_h = source_info.get("default_size", (2, 2))
        general_model = { "General Panel Settings": [
            ConfigOption("title_text", "string", "Panel Title:", source_info["name"]),
            ConfigOption("width", "spinner", "Width (grid units):", def_w, 1, 128, 1),
            ConfigOption("height", "spinner", "Height (grid units):", def_h, 1, 128, 1)
        ]}
        background_model = self.dialog.ui_models.get('background', {})
        
        # --- BUG FIX ---
        # Create a list of all models to prevent key collisions when merging.
        all_models = [source_model, displayer_model, general_model, background_model, *self.dialog.dynamic_models]
        final_config = get_config_from_widgets(self.widgets, all_models)
        
        final_config['id'] = f"panel_{uuid.uuid4().hex[:12]}"
        final_config['type'] = self.selected_source_key
        final_config['displayer_type'] = self.selected_displayer_key
        
        self.grid_manager.create_and_add_panel_from_config(final_config)
        
        self.dialog.destroy()
