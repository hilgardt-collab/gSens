# /data_displayers/lcars_combo.py
import gi
import math
import cairo
import os
import time
from .combo_base import ComboBase
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from .level_bar import LevelBarDisplayer
from .graph import GraphDisplayer
from ui_helpers import build_background_config_ui


gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class LCARSComboDisplayer(ComboBase):
    """
    A displayer that renders multiple data sources in the iconic LCARS style,
    featuring a highly configurable frame and a main content area.
    """
    def __init__(self, panel_ref, config):
        self._level_bar_drawer = LevelBarDisplayer(None, config)
        self._graph_drawer = GraphDisplayer(None, config)
        self._graph_drawer.is_drawer = True
        self._cached_primary_image = None
        self._cached_primary_image_path = None
        
        self._animation_timer_id = None
        self._bar_values = {}
        self._history_buffers = {}

        # --- OPTIMIZATION: Caching for Pango Layouts ---
        self._static_layout_cache = {}
        
        # --- NEW: Text overlay data for graphs ---
        self._text_overlay_lines = {}

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self._get_full_config_model())
        
        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    @property
    def panel_ref(self):
        return self._panel_ref

    @panel_ref.setter
    def panel_ref(self, value):
        self._panel_ref = value
        if self._level_bar_drawer:
            self._level_bar_drawer.panel_ref = value
        if self._graph_drawer:
            self._graph_drawer.panel_ref = value
        
    @staticmethod
    def get_config_model():
        return {}

    @staticmethod
    def _get_segment_model(i):
        """Helper to generate a config model for a single side bar segment."""
        default_color = "rgba(255, 153, 102, 1)" if i % 2 != 0 else "rgba(204, 153, 255, 1)"
        return {
            f"Segment {i} Style": [
                ConfigOption(f"segment_{i}_height_weight", "spinner", "Height Weight:", 1, 1, 10, 1, 0),
                ConfigOption(f"segment_{i}_color", "color", "BG Color:", default_color),
            ],
            f"Segment {i} Label": [
                ConfigOption(f"segment_{i}_label", "string", "Label Text:", f"SEGMENT {i}"),
                ConfigOption(f"segment_{i}_font", "font", "Font:", "Swiss 911 Ultra Compressed 14"),
                ConfigOption(f"segment_{i}_label_color", "color", "Text Color:", "rgba(0,0,0,1)"),
            ]
        }

    @staticmethod
    def _get_content_item_model(prefix):
        """Helper to generate a config model for a single content item (primary or secondary)."""
        model = {
            "Content": [
                ConfigOption(f"{prefix}_display_as", "dropdown", "Display As:", "bar", 
                             options_dict={"Bar with Text": "bar", "Text Only": "text", 
                                           "Level Bar": "level_bar", "Graph": "graph"}),
                ConfigOption(f"{prefix}_item_height", "spinner", "Item Height (px):", 60, 20, 500, 5, 0),
            ],
            "Text Style": [
                ConfigOption(f"{prefix}_show_label", "bool", "Show Label:", "True"),
                ConfigOption(f"{prefix}_label_font", "font", "Label Font:", "Swiss 911 Ultra Compressed 16"),
                ConfigOption(f"{prefix}_label_color", "color", "Label Color:", "rgba(255,153,102,1)"),
                ConfigOption(f"{prefix}_show_value", "bool", "Show Value:", "True"),
                ConfigOption(f"{prefix}_value_font", "font", "Value Font:", "Swiss 911 Ultra Compressed 16"),
                ConfigOption(f"{prefix}_value_color", "color", "Value Color:", "rgba(255,204,153,1)"),
            ],
            "Bar Style": [
                ConfigOption(f"{prefix}_bar_bg_color", "color", "Bar BG Color:", "rgba(0,0,0,0.5)"),
                ConfigOption(f"{prefix}_bar_fg_color", "color", "Bar FG Color:", "rgba(255,153,102,1)"),
                ConfigOption(f"{prefix}_bar_corner_radius", "spinner", "Bar Corner Radius (px):", 8, 0, 50, 1, 0),
                ConfigOption(f"{prefix}_bar_text_layout", "dropdown", "Text Layout:", "superimposed",
                             options_dict={"Superimposed": "superimposed", "Text Left, Bar Right": "left", "Bar Left, Text Right": "right"}),
                ConfigOption(f"{prefix}_bar_text_split_ratio", "scale", "Text/Bar Split Ratio:", "0.4", 0.1, 0.9, 0.05, 2,
                             tooltip="The proportion of space given to the text when layout is not superimposed."),
            ]
        }
        
        lb_model = LevelBarDisplayer.get_config_model()
        model["Level Bar Style"] = [ConfigOption(f"{prefix}_{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for section in lb_model.values() for opt in section if section != "Level Bar Range"]
        
        g_model = GraphDisplayer._get_graph_config_model_definition()
        graph_style_options = [ConfigOption(f"{prefix}_{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for section in g_model.values() for opt in section]
        graph_style_options.insert(0, ConfigOption(f"{prefix}_graph_lcars_bg_color", "color", "Background Color:", "rgba(0,0,0,1)"))
        model["Graph Style"] = graph_style_options
        
        # --- NEW: Add text overlay configuration for graphs ---
        model["Graph Text Overlay"] = [
            ConfigOption(f"{prefix}_text_overlay_enabled", "bool", "Enable Text Overlay:", "False"),
            ConfigOption(f"{prefix}_text_line_count", "spinner", "Number of Lines:", 2, 1, 10, 1, 0),
            ConfigOption(f"{prefix}_text_horizontal_align", "dropdown", "Horizontal Align:", "center", 
                         options_dict={"Left": "start", "Center": "center", "Right": "end"}),
            ConfigOption(f"{prefix}_text_vertical_align", "dropdown", "Vertical Align:", "center", 
                         options_dict={"Top": "start", "Center": "center", "Bottom": "end"}),
            ConfigOption(f"{prefix}_text_spacing", "spinner", "Spacing (px):", 4, 0, 50, 1, 0),
        ]
        
        return model

    @classmethod
    def _get_full_config_model(cls):
        """
        Defines ALL possible style options with defaults to prevent crashes.
        This comprehensive model is used to populate the initial config.
        """
        model = {
            "Frame Style": [
                ConfigOption("lcars_sidebar_extension_mode", "dropdown", "Sidebar Extension:", "top",
                             options_dict={"Top Only": "top", "Bottom Only": "bottom", "Top and Bottom": "both"}),
                ConfigOption("lcars_top_bar_height", "spinner", "Top Bar Height (px):", 40, 10, 200, 2, 0),
                ConfigOption("lcars_bottom_extension_height", "spinner", "Bottom Extension Height (px):", 40, 0, 500, 5, 0),
                ConfigOption("lcars_sidebar_width", "spinner", "Side Bar Width (px):", 150, 20, 500, 5, 0),
                ConfigOption("lcars_corner_radius", "spinner", "Corner Radius (px):", 60, 10, 500, 5, 0),
                ConfigOption("lcars_extension_corner_style", "dropdown", "Extension Corner Style:", "square", options_dict={"Square": "square", "Round": "round"}),
                ConfigOption("lcars_extension_corner_radius", "spinner", "Extension Corner Radius (px):", 20, 0, 100, 1, 0),
                ConfigOption("lcars_frame_color", "color", "Frame Color:", "rgba(255,153,102,1)"),
                ConfigOption("lcars_content_bg_color", "color", "Content BG Color:", "rgba(0,0,0,1)"),
                ConfigOption("lcars_content_padding", "spinner", "Content Padding (px):", 5, 0, 100, 1, 0),
                ConfigOption("lcars_secondary_spacing_mode", "dropdown", "Secondary Item Spacing:", "auto", options_dict={"Automatic": "auto", "Manual": "manual"}),
                ConfigOption("lcars_secondary_spacing_value", "spinner", "Manual Spacing (px):", 5, 0, 50, 1, 0),
            ],
            "Header Bar (Top)": [
                ConfigOption("lcars_top_header_position", "dropdown", "Header Position:", "top", options_dict={"Top Bar": "top", "None": "none"}),
                ConfigOption("lcars_top_header_text", "string", "Header Text:", "U.S.S. ENTERPRISE"),
                ConfigOption("lcars_top_header_font", "font", "Header Font:", "Swiss 911 Ultra Compressed 18"),
                ConfigOption("lcars_top_header_color", "color", "Header Color:", "rgba(0,0,0,1)"),
                ConfigOption("lcars_top_header_align", "dropdown", "Header Align:", "left", options_dict={"Left": "left", "Center": "center", "Right": "right"}),
                ConfigOption("lcars_top_header_width_mode", "dropdown", "Header Width:", "full", options_dict={"Full Width": "full", "Fit to Text": "fit"}),
                ConfigOption("lcars_top_header_shape", "dropdown", "Header Shape:", "pill", options_dict={"Pill": "pill", "Square": "square"}),
                ConfigOption("lcars_top_header_bg_color", "color", "Header BG Color:", "rgba(204,153,255,1)"),
                ConfigOption("lcars_top_header_padding", "spinner", "Header Padding (px):", 10, 0, 50, 1, 0),
            ],
            "Header Bar (Bottom)": [
                ConfigOption("lcars_bottom_header_position", "dropdown", "Header Position:", "none", options_dict={"Bottom Bar": "bottom", "None": "none"}),
                ConfigOption("lcars_bottom_header_text", "string", "Header Text:", "LCARS"),
                ConfigOption("lcars_bottom_header_font", "font", "Header Font:", "Swiss 911 Ultra Compressed 18"),
                ConfigOption("lcars_bottom_header_color", "color", "Header Color:", "rgba(0,0,0,1)"),
                ConfigOption("lcars_bottom_header_align", "dropdown", "Header Align:", "left", options_dict={"Left": "left", "Center": "center", "Right": "right"}),
                ConfigOption("lcars_bottom_header_width_mode", "dropdown", "Header Width:", "full", options_dict={"Full Width": "full", "Fit to Text": "fit"}),
                ConfigOption("lcars_bottom_header_shape", "dropdown", "Header Shape:", "pill", options_dict={"Pill": "pill", "Square": "square"}),
                ConfigOption("lcars_bottom_header_bg_color", "color", "Header BG Color:", "rgba(204,153,255,1)"),
                ConfigOption("lcars_bottom_header_padding", "spinner", "Header Padding (px):", 10, 0, 50, 1, 0),
            ],
            "Animation": [
                ConfigOption("lcars_animation_enabled", "bool", "Enable Bar Animation:", "True"),
                ConfigOption("lcars_animation_speed", "scale", "Animation Speed:", "0.1", 0.01, 0.5, 0.01, 2, 
                             tooltip="Controls how quickly the bar moves to its target. Smaller is faster."),
            ]
        }
        
        primary_model = cls._get_content_item_model("primary")
        for section, options in primary_model.items():
            model[f"Primary {section}"] = options

        for i in range(1, 17):
            sec_model = cls._get_content_item_model(f"secondary{i}")
            for section, options in sec_model.items():
                model[f"Secondary {i} {section}"] = options
        
        for i in range(1, 17):
            seg_model = cls._get_segment_model(i)
            for section, options in seg_model.items():
                model[section] = options
                
        return model

    def get_configure_callback(self):
        """Builds the comprehensive UI for the Display tab."""
        def build_display_ui(dialog, content_box, widgets, available_sources, panel_config):
            
            display_notebook = Gtk.Notebook(vexpand=True)
            content_box.append(display_notebook)

            # --- Tab 1: Frame & Side Bar ---
            frame_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            frame_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            frame_scroll.set_child(frame_box)
            display_notebook.append_page(frame_scroll, Gtk.Label(label="Frame"))
            
            full_model = self._get_full_config_model()
            frame_ui_model = {
                "Frame Style": full_model["Frame Style"],
                "Header Bar (Top)": full_model["Header Bar (Top)"],
                "Header Bar (Bottom)": full_model["Header Bar (Bottom)"],
                "Animation": full_model["Animation"]
            }
            build_ui_from_model(frame_box, panel_config, frame_ui_model, widgets)
            dialog.dynamic_models.append(frame_ui_model)
            
            # --- Dynamic UI for Headers ---
            def setup_header_dynamics(prefix):
                pos_combo = widgets.get(f"lcars_{prefix}_header_position")
                if not pos_combo: return
                
                rows_to_toggle = []
                header_section_key = f"Header Bar ({prefix.capitalize()})"
                for opt in full_model.get(header_section_key, []):
                    if opt.key != f"lcars_{prefix}_header_position":
                        widget = widgets.get(opt.key)
                        if widget and hasattr(widget, 'get_parent') and widget.get_parent():
                            parent = widget.get_parent()
                            while parent.get_parent() != frame_box and parent.get_parent() is not None:
                                parent = parent.get_parent()
                            if parent not in rows_to_toggle:
                                rows_to_toggle.append(parent)

                def on_pos_changed(combo):
                    is_none = combo.get_active_id() == "none"
                    for row in rows_to_toggle:
                        row.set_visible(not is_none)
                
                pos_combo.connect("changed", on_pos_changed)
                GLib.idle_add(on_pos_changed, pos_combo)

            setup_header_dynamics("top")
            setup_header_dynamics("bottom")

            # --- Dynamic UI for Spacing ---
            spacing_mode_combo = widgets.get("lcars_secondary_spacing_mode")
            spacing_value_spinner = widgets.get("lcars_secondary_spacing_value")

            if spacing_mode_combo and spacing_value_spinner:
                spacing_value_row = spacing_value_spinner.get_parent()
                def on_spacing_mode_changed(combo):
                    is_manual = combo.get_active_id() == "manual"
                    spacing_value_row.set_visible(is_manual)
                
                spacing_mode_combo.connect("changed", on_spacing_mode_changed)
                GLib.idle_add(on_spacing_mode_changed, spacing_mode_combo)

            frame_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            frame_box.append(Gtk.Label(label="<b>Side Bar Segments</b>", use_markup=True, xalign=0))
            
            sidebar_model = {"": [ConfigOption("lcars_segment_count", "spinner", "Number of Segments:", 3, 0, 16, 1, 0)]}
            build_ui_from_model(frame_box, panel_config, sidebar_model, widgets)
            dialog.dynamic_models.append(sidebar_model)

            segment_scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            segment_scrolled.set_min_content_height(300)
            segment_notebook = Gtk.Notebook()
            segment_notebook.set_scrollable(True)
            segment_scrolled.set_child(segment_notebook)
            frame_box.append(segment_scrolled)
            
            segment_tabs_content = []
            for i in range(1, 17):
                tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                tab_scroll.set_child(tab_box)
                segment_notebook.append_page(tab_scroll, Gtk.Label(label=f"Seg {i}"))
                segment_tabs_content.append(tab_scroll)
                
                seg_model = self._get_segment_model(i)
                build_ui_from_model(tab_box, panel_config, seg_model, widgets)
                dialog.dynamic_models.append(seg_model)

            def on_segment_count_changed(spinner):
                count = spinner.get_value_as_int()
                for i, content_widget in enumerate(segment_tabs_content):
                    content_widget.set_visible(i < count)

            seg_count_spinner = widgets["lcars_segment_count"]
            seg_count_spinner.connect("value-changed", on_segment_count_changed)
            GLib.idle_add(on_segment_count_changed, seg_count_spinner)

            # --- Tab 2: Content ---
            content_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            content_box_tab = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            content_scroll.set_child(content_box_tab)
            display_notebook.append_page(content_scroll, Gtk.Label(label="Content"))
            
            content_notebook = Gtk.Notebook()
            content_notebook.set_scrollable(True)
            content_box_tab.append(content_notebook)

            primary_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            primary_scroll.set_min_content_height(300)
            primary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            primary_scroll.set_child(primary_box)
            content_notebook.append_page(primary_scroll, Gtk.Label(label="Primary"))
            
            primary_model = self._get_content_item_model("primary")
            build_ui_from_model(primary_box, panel_config, primary_model, widgets)
            self._setup_dynamic_content_ui(dialog, primary_box, widgets, panel_config, "primary")
            dialog.dynamic_models.append(primary_model)

            secondary_tabs_content = []
            for i in range(1, 17):
                prefix = f"secondary{i}"
                tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                tab_scroll.set_min_content_height(300)
                tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                tab_scroll.set_child(tab_box)
                content_notebook.append_page(tab_scroll, Gtk.Label(label=f"Item {i}"))
                secondary_tabs_content.append(tab_scroll)
                
                sec_model = self._get_content_item_model(prefix)
                build_ui_from_model(tab_box, panel_config, sec_model, widgets)
                self._setup_dynamic_content_ui(dialog, tab_box, widgets, panel_config, prefix)
                dialog.dynamic_models.append(sec_model)

            def on_secondary_count_changed(spinner):
                count = spinner.get_value_as_int()
                for i, content_widget in enumerate(secondary_tabs_content):
                    content_widget.set_visible(i < count)

            sec_count_spinner = widgets.get("number_of_secondary_sources")
            if sec_count_spinner:
                sec_count_spinner.connect("value-changed", on_secondary_count_changed)
                GLib.idle_add(on_secondary_count_changed, sec_count_spinner)

            # --- Effects Tab ---
            effects_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            effects_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=15, margin_bottom=15, margin_start=15, margin_end=15)
            effects_scroll.set_child(effects_box)
            display_notebook.append_page(effects_scroll, Gtk.Label(label="Effects"))

            effects_box.append(Gtk.Label(label="<b>Copy Item Style</b>", xalign=0, use_markup=True))
            copy_grid = Gtk.Grid(column_spacing=10, row_spacing=10)
            effects_box.append(copy_grid)
            source_item_combo = Gtk.ComboBoxText()
            copy_grid.attach(Gtk.Label(label="Source Item:", xalign=1), 0, 0, 1, 1); copy_grid.attach(source_item_combo, 1, 0, 1, 1)
            
            copy_checkboxes = {
                "Content": Gtk.CheckButton(label="Content Style (Display As, Height)"),
                "Text": Gtk.CheckButton(label="Text Style (Fonts, Colors, Visibility)"),
                "Bar": Gtk.CheckButton(label="Bar Style (Colors, Radius, Layout)"),
            }
            for i, (key, chk) in enumerate(copy_checkboxes.items()):
                chk.set_active(True); copy_grid.attach(chk, 0, i + 1, 2, 1)
            
            apply_style_button = Gtk.Button(label="Apply Selected Style to All Other Items")
            copy_grid.attach(apply_style_button, 0, len(copy_checkboxes) + 2, 2, 1)

            property_map = {
                "Content": ["display_as", "item_height"],
                "Text": ["show_label", "label_font", "label_color", "show_value", "value_font", "value_color"],
                "Bar": ["bar_bg_color", "bar_fg_color", "bar_corner_radius", "bar_text_layout", "bar_text_split_ratio"],
            }

            def on_apply_same_style_clicked(button):
                sec_count = widgets["number_of_secondary_sources"].get_value_as_int()
                source_id_str = source_item_combo.get_active_id()
                if not source_id_str: return
                
                keys_to_copy = []
                for key, chk in copy_checkboxes.items():
                    if chk.get_active(): keys_to_copy.extend(property_map.get(key, []))

                all_prefixes = ["primary"] + [f"secondary{i}" for i in range(1, sec_count + 1)]
                for dest_prefix in all_prefixes:
                    if dest_prefix == source_id_str: continue
                    for key_suffix in keys_to_copy:
                        source_widget = widgets.get(f"{source_id_str}_{key_suffix}")
                        dest_widget = widgets.get(f"{dest_prefix}_{key_suffix}")
                        if source_widget and dest_widget:
                            if isinstance(source_widget, (Gtk.SpinButton, Gtk.Scale)): dest_widget.set_value(source_widget.get_value())
                            elif isinstance(source_widget, Gtk.ColorButton): dest_widget.set_rgba(source_widget.get_rgba())
                            elif isinstance(source_widget, Gtk.FontButton): dest_widget.set_font(source_widget.get_font())
                            elif isinstance(source_widget, Gtk.ComboBoxText): dest_widget.set_active_id(source_widget.get_active_id())
                            elif isinstance(source_widget, Gtk.Switch): dest_widget.set_active(source_widget.get_active())
                
                if hasattr(dialog, 'apply_button') and dialog.apply_button:
                    dialog.apply_button.emit("clicked")

            apply_style_button.connect("clicked", on_apply_same_style_clicked)

            def on_sec_count_changed_for_effects(spinner):
                count = spinner.get_value_as_int()
                source_item_combo.remove_all()
                source_item_combo.append(id="primary", text="Primary")
                for i in range(1, count + 1):
                    source_item_combo.append(id=f"secondary{i}", text=f"Item {i}")
                source_item_combo.set_active(0)

            if sec_count_spinner:
                sec_count_spinner.connect("value-changed", on_sec_count_changed_for_effects)
                GLib.idle_add(on_sec_count_changed_for_effects, sec_count_spinner)

        return build_display_ui
        
    def _setup_dynamic_content_ui(self, dialog, parent_box, widgets, panel_config, prefix):
        """Shows/hides config sections based on the 'Display As' dropdown for an item."""
        display_as_combo = widgets.get(f"{prefix}_display_as")
        if not display_as_combo: return

        all_children = list(parent_box)
        
        def find_section_widgets(title):
            try:
                header = next(c for c in all_children if isinstance(c, Gtk.Label) and c.get_label() and title in c.get_label())
                start_index = all_children.index(header)
                separator = all_children[start_index - 1]
                section_widgets = [separator, header]
                for child in all_children[start_index + 1:]:
                    if isinstance(child, Gtk.Separator): break
                    section_widgets.append(child)
                return section_widgets
            except (StopIteration, IndexError):
                return []

        section_map = {
            "text": find_section_widgets("Text Style"),
            "bar": find_section_widgets("Bar Style"),
            "level_bar": find_section_widgets("Level Bar Style"),
            "graph": find_section_widgets("Graph Style"),
            "graph_text_overlay": find_section_widgets("Graph Text Overlay"),
        }
        
        item_height_widget_container = None
        item_height_widget = widgets.get(f"{prefix}_item_height")
        if item_height_widget:
            item_height_widget_container = item_height_widget.get_parent()
        
        # --- NEW: Setup dynamic text overlay line configuration ---
        text_overlay_enabled_switch = widgets.get(f"{prefix}_text_overlay_enabled")
        text_line_count_spinner = widgets.get(f"{prefix}_text_line_count")
        
        if text_overlay_enabled_switch and text_line_count_spinner:
            # Find the container for text overlay lines
            text_overlay_lines_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10)
            
            # Find the Graph Text Overlay section and append the container
            for child in all_children:
                if isinstance(child, Gtk.Label) and child.get_label() and "Graph Text Overlay" in child.get_label():
                    # Insert after the main text overlay settings
                    idx = all_children.index(child)
                    # Find where to insert (after the last config option in this section)
                    insert_point = None
                    for i in range(idx + 1, len(all_children)):
                        if isinstance(all_children[i], Gtk.Separator):
                            insert_point = i
                            break
                    if insert_point:
                        parent_box.insert_child_after(text_overlay_lines_container, all_children[insert_point - 1])
                    else:
                        parent_box.append(text_overlay_lines_container)
                    break
            
            def rebuild_text_line_ui(spinner):
                # Clear existing line configs
                child = text_overlay_lines_container.get_first_child()
                while child:
                    text_overlay_lines_container.remove(child)
                    child = text_overlay_lines_container.get_first_child()
                
                # Remove old line widgets from registry
                keys_to_remove = [k for k in widgets if k.startswith(f"{prefix}_line")]
                for k in keys_to_remove:
                    widgets.pop(k, None)
                
                count = spinner.get_value_as_int()
                for i in range(1, count + 1):
                    frame = Gtk.Frame(label=f"Line {i} Settings", margin_top=6)
                    text_overlay_lines_container.append(frame)
                    
                    line_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                                      margin_top=5, margin_bottom=5, margin_start=5, margin_end=5)
                    frame.set_child(line_box)
                    
                    source_opts = {
                        "Main Display String": "display_string",
                        "Primary Label": "primary_label",
                        "Secondary Label": "secondary_label",
                        "Tooltip Text": "tooltip_string",
                        "Custom Static Text": "custom_text"
                    }
                    align_opts = {"Left": "left", "Center": "center", "Right": "right"}
                    
                    line_model = {"": [
                        ConfigOption(f"{prefix}_line{i}_source", "dropdown", "Text Source:", "display_string", options_dict=source_opts),
                        ConfigOption(f"{prefix}_line{i}_custom_text", "string", "Custom Text:", ""),
                        ConfigOption(f"{prefix}_line{i}_align", "dropdown", "Align:", "center", options_dict=align_opts),
                        ConfigOption(f"{prefix}_line{i}_font", "font", "Font:", "Sans 12"),
                        ConfigOption(f"{prefix}_line{i}_color", "color", "Color:", "rgba(220,220,220,1)"),
                        ConfigOption(f"{prefix}_line{i}_slant", "spinner", "Slant (deg):", 0, -45, 45, 1, 0),
                        ConfigOption(f"{prefix}_line{i}_rotation", "spinner", "Rotation (deg):", 0, -180, 180, 5, 0),
                    ]}
                    
                    build_ui_from_model(line_box, panel_config, line_model, widgets)
                    dialog.dynamic_models.append(line_model)
                    
                    # Setup dynamic visibility for custom text
                    source_combo = widgets[f"{prefix}_line{i}_source"]
                    custom_text_row = widgets[f"{prefix}_line{i}_custom_text"].get_parent()
                    
                    def on_source_changed(combo, row):
                        row.set_visible(combo.get_active_id() == "custom_text")
                    
                    source_combo.connect("changed", on_source_changed, custom_text_row)
                    GLib.idle_add(on_source_changed, source_combo, custom_text_row)
            
            text_line_count_spinner.connect("value-changed", rebuild_text_line_ui)
            
            def on_overlay_enabled_changed(switch, gparam):
                enabled = switch.get_active()
                text_overlay_lines_container.set_visible(enabled)
                if enabled:
                    GLib.idle_add(rebuild_text_line_ui, text_line_count_spinner)
            
            text_overlay_enabled_switch.connect("notify::active", on_overlay_enabled_changed)
            GLib.idle_add(on_overlay_enabled_changed, text_overlay_enabled_switch, None)

        def update_visibility(combo):
            active_id = combo.get_active_id()
            for key, section_widgets in section_map.items():
                if key == "graph_text_overlay":
                    is_visible = (active_id == "graph")
                else:
                    is_visible = (key == active_id) or (key == 'text' and active_id == 'bar')
                for w in section_widgets:
                    if w and w.get_parent():
                        w.set_visible(is_visible)
            
            if item_height_widget_container:
                item_height_widget_container.set_visible(True)

        display_as_combo.connect("changed", update_visibility)
        GLib.idle_add(update_visibility, display_as_combo)

    def apply_styles(self):
        super().apply_styles()
        self._static_layout_cache.clear()
        self.widget.queue_draw()

    def update_display(self, value):
        super().update_display(value) 
        
        all_prefixes = ["primary"] + [f"secondary{i}" for i in range(1, 17)]
        for prefix in all_prefixes:
            source_key = f"{prefix}_source"
            bar_anim_key = f"{prefix}_bar"
            graph_history_key = f"{prefix}_graph"
            
            if bar_anim_key not in self._bar_values:
                self._bar_values[bar_anim_key] = {'current': 0.0, 'target': 0.0, 'first_update': True}
            if graph_history_key not in self._history_buffers:
                self._history_buffers[graph_history_key] = []

            data_packet = self.data_bundle.get(source_key, {})
            num_val = data_packet.get('numerical_value')
            
            max_hist = int(self.config.get(f"{prefix}_max_history_points", 100))
            history = self._history_buffers[graph_history_key]
            if num_val is not None:
                history.append((time.time(), num_val))
                if len(history) > max_hist:
                    self._history_buffers[graph_history_key] = history[-max_hist:]

            percent_val = 0.0
            if isinstance(num_val, (int, float)):
                min_v = data_packet.get('min_value', 0.0)
                max_v = data_packet.get('max_value', 100.0)
                v_range = max_v - min_v if max_v > min_v else 1
                percent_val = (min(max(num_val, min_v), max_v) - min_v) / v_range if v_range > 0 else 0.0
            
            if self._bar_values[bar_anim_key]['first_update']:
                self._bar_values[bar_anim_key]['current'] = percent_val
                self._bar_values[bar_anim_key]['first_update'] = False
            self._bar_values[bar_anim_key]['target'] = percent_val
            
            # --- NEW: Update text overlay lines for graphs ---
            display_as = self.config.get(f"{prefix}_display_as", "bar")
            text_overlay_enabled = str(self.config.get(f"{prefix}_text_overlay_enabled", "False")).lower() == 'true'
            
            if display_as == "graph" and text_overlay_enabled:
                line_count = int(self.config.get(f"{prefix}_text_line_count", 2))
                if prefix not in self._text_overlay_lines:
                    self._text_overlay_lines[prefix] = []
                
                text_lines = []
                child_source = self.panel_ref.data_source.child_sources.get(source_key) if self.panel_ref else None
                
                for i in range(line_count):
                    line_num = i + 1
                    source_type = self.config.get(f"{prefix}_line{line_num}_source", "display_string")
                    
                    text = "N/A"
                    if child_source and data_packet:
                        if source_type == "primary_label":
                            text = child_source.get_primary_label_string(data_packet.get('raw_data'))
                        elif source_type == "secondary_label":
                            text = child_source.get_secondary_display_string(data_packet.get('raw_data'))
                        elif source_type == "tooltip_string":
                            text = child_source.get_tooltip_string(data_packet.get('raw_data'))
                        elif source_type == "custom_text":
                            text = self.config.get(f"{prefix}_line{line_num}_custom_text", "")
                        else:  # display_string
                            text = child_source.get_display_string(data_packet.get('raw_data'))
                    
                    text_lines.append(text or "")
                
                self._text_overlay_lines[prefix] = text_lines

    def _start_animation_timer(self, widget=None):
        self._stop_animation_timer()
        self._animation_timer_id = GLib.timeout_add(16, self._animation_tick)

    def _stop_animation_timer(self, widget=None):
        if self._animation_timer_id is not None:
            GLib.source_remove(self._animation_timer_id)
            self._animation_timer_id = None

    def _animation_tick(self):
        if not self.widget.get_realized():
            self._animation_timer_id = None
            return GLib.SOURCE_REMOVE

        animation_enabled = str(self.config.get("lcars_animation_enabled", "True")).lower() == 'true'
        anim_speed = float(self.config.get("lcars_animation_speed", 0.1))
        needs_redraw = False

        for key, values in self._bar_values.items():
            diff = values['target'] - values['current']
            if not animation_enabled:
                if values['current'] != values['target']: values['current'] = values['target']; needs_redraw = True
                continue
            if abs(diff) < 0.001:
                if values['current'] != values['target']: values['current'] = values['target']; needs_redraw = True
            else:
                values['current'] += diff * anim_speed; needs_redraw = True
        if needs_redraw: self.widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return
        self._draw_frame_and_sidebar(ctx, width, height)
        self._draw_content_widgets(ctx, width, height)

    def _create_pango_layout(self, ctx, text, font_str):
        cache_key = f"{text}_{font_str}"
        layout = self._static_layout_cache.get(cache_key)
        if layout is None:
            layout = PangoCairo.create_layout(ctx)
            font_str = font_str or "Sans 12"
            layout.set_font_description(Pango.FontDescription.from_string(font_str))
            layout.set_text(text, -1)
            self._static_layout_cache[cache_key] = layout
        return layout

    def _draw_frame_and_sidebar(self, ctx, width, height):
        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        radius = float(self.config.get("lcars_corner_radius", 60))
        frame_color_str = self.config.get("lcars_frame_color", "rgba(255,153,102,1)")
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        ext_style = self.config.get("lcars_extension_corner_style", "square")
        ext_radius = float(self.config.get("lcars_extension_corner_radius", 20))

        top_bar_h = float(self.config.get("lcars_top_bar_height", 40))
        bottom_ext_h = float(self.config.get("lcars_bottom_extension_height", 40))
        
        has_top_ext = mode in ["top", "both"]
        has_bottom_ext = mode in ["bottom", "both"]
        
        ctx.new_path()
        ctx.move_to(0, radius) 
        ctx.arc(radius, radius, radius, math.pi, 1.5 * math.pi)
        
        if ext_style == "round" and has_top_ext:
            ctx.line_to(width - ext_radius, 0)
            ctx.arc(width - ext_radius, ext_radius, ext_radius, 1.5 * math.pi, 2 * math.pi)
        else:
            ctx.line_to(width, 0)

        if ext_style == "round" and has_bottom_ext:
            ctx.line_to(width, height - ext_radius)
            ctx.arc(width - ext_radius, height - ext_radius, ext_radius, 0, 0.5 * math.pi)
        else:
            ctx.line_to(width, height)

        ctx.line_to(radius, height)
        ctx.arc(radius, height - radius, radius, 0.5 * math.pi, math.pi)
        ctx.close_path()

        content_y_start = top_bar_h if has_top_ext else 0
        content_y_end = height - bottom_ext_h if has_bottom_ext else height
        
        ctx.move_to(width, content_y_start)
        
        if has_top_ext:
            ctx.line_to(sidebar_w + radius, content_y_start)
            ctx.arc_negative(sidebar_w + radius, content_y_start + radius, radius, 1.5 * math.pi, math.pi)
        else:
            ctx.line_to(sidebar_w, content_y_start)

        ctx.line_to(sidebar_w, content_y_end - (radius if has_bottom_ext else 0))

        if has_bottom_ext:
            ctx.arc_negative(sidebar_w + radius, content_y_end - radius, radius, math.pi, 0.5 * math.pi)
            ctx.line_to(width, content_y_end)
        else:
            ctx.line_to(width, content_y_end)

        ctx.close_path()

        frame_color = Gdk.RGBA(); frame_color.parse(frame_color_str)
        ctx.set_source_rgba(frame_color.red, frame_color.green, frame_color.blue, frame_color.alpha)
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.fill()
        ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
        
        top_header_pos = self.config.get("lcars_top_header_position", "top")
        bottom_header_pos = self.config.get("lcars_bottom_header_position", "none")

        if top_header_pos == "top" and has_top_ext:
            self._draw_header_bar(ctx, width, height, is_top=True)
        if bottom_header_pos == "bottom" and has_bottom_ext:
            self._draw_header_bar(ctx, width, height, is_top=False)
            
        self._draw_sidebar_segments(ctx, width, height)

    def _draw_header_bar(self, ctx, width, height, is_top):
        prefix = "top" if is_top else "bottom"
        
        bar_h_config_key = "lcars_top_bar_height" if is_top else "lcars_bottom_extension_height"
        bar_h = float(self.config.get(bar_h_config_key, 40))

        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        radius = float(self.config.get("lcars_corner_radius", 60))
        padding = float(self.config.get(f"lcars_{prefix}_header_padding", 10))
        shape = self.config.get(f"lcars_{prefix}_header_shape", "pill")
        align = self.config.get(f"lcars_{prefix}_header_align", "left")
        width_mode = self.config.get(f"lcars_{prefix}_header_width_mode", "full")
        text = self.config.get(f"lcars_{prefix}_header_text", "").upper()
        font_str = self.config.get(f"lcars_{prefix}_header_font")
        color_str = self.config.get(f"lcars_{prefix}_header_color")
        bg_color_str = self.config.get(f"lcars_{prefix}_header_bg_color")
        
        bar_content_h = bar_h - (2 * padding)
        if bar_content_h <= 0: return
        
        layout = self._create_pango_layout(ctx, text, font_str)
        _, log = layout.get_pixel_extents()

        if width_mode == "fit":
            bar_w = log.width + (padding * 2) + (bar_content_h if shape == 'pill' else 0)
        else:
            bar_w = width - (sidebar_w + radius + padding) - padding

        if bar_w <= 0: return
        
        bar_y = padding if is_top else height - bar_h + padding
        if align == "right":
            bar_x = width - padding - bar_w
        elif align == "center":
            available_space = width - (sidebar_w + radius + padding) - padding
            bar_x = sidebar_w + radius + padding + (available_space - bar_w) / 2
        else:
            bar_x = sidebar_w + radius + padding
            
        bar_radius = bar_content_h / 2
        
        ctx.new_path()
        if shape == "square":
            ctx.rectangle(bar_x, bar_y, bar_w, bar_content_h)
        else:
            ctx.arc(bar_x + bar_radius, bar_y + bar_radius, bar_radius, 0.5 * math.pi, 1.5 * math.pi)
            ctx.arc(bar_x + bar_w - bar_radius, bar_y + bar_radius, bar_radius, 1.5 * math.pi, 0.5 * math.pi)
            ctx.close_path()
        
        bg_color = Gdk.RGBA(); bg_color.parse(bg_color_str)
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha); ctx.fill()
        
        text_rgba = Gdk.RGBA(); text_rgba.parse(color_str)
        ctx.set_source_rgba(text_rgba.red, text_rgba.green, text_rgba.blue, text_rgba.alpha)
        
        text_y = bar_y + (bar_content_h - log.height) / 2
        text_x = bar_x + (bar_w - log.width) / 2
        ctx.move_to(text_x, text_y); PangoCairo.show_layout(ctx, layout)
        
    def _draw_sidebar_segments(self, ctx, width, height):
        num_segments = int(self.config.get("lcars_segment_count", 3))
        if num_segments == 0: return

        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        
        has_top_ext = mode in ["top", "both"]
        has_bottom_ext = mode in ["bottom", "both"]

        top_bar_h = float(self.config.get("lcars_top_bar_height", 40)) if has_top_ext else 0
        bottom_ext_h = float(self.config.get("lcars_bottom_extension_height", 40)) if has_bottom_ext else 0
        
        start_y = top_bar_h
        available_h = height - top_bar_h - bottom_ext_h
        
        total_weight = sum(float(self.config.get(f"segment_{i}_height_weight", 1)) for i in range(1, num_segments + 1)) or 1
        current_y = start_y

        for i in range(1, num_segments + 1):
            weight = float(self.config.get(f"segment_{i}_height_weight", 1))
            seg_h = (weight / total_weight) * available_h if total_weight > 0 else 0
            color_str = self.config.get(f"segment_{i}_color", "rgba(200,100,100,1)")
            seg_color = Gdk.RGBA(); seg_color.parse(color_str)
            ctx.set_source_rgba(seg_color.red, seg_color.green, seg_color.blue, seg_color.alpha)
            ctx.rectangle(0, current_y, sidebar_w, seg_h); ctx.fill()
            
            ctx.set_source_rgba(0,0,0,1); ctx.set_line_width(2)
            if i < num_segments:
                ctx.move_to(0, current_y + seg_h); ctx.line_to(sidebar_w, current_y + seg_h); ctx.stroke()
            
            label_text = self.config.get(f"segment_{i}_label", "").upper()
            font_str = self.config.get(f"segment_{i}_font")
            color_str = self.config.get(f"segment_{i}_label_color")
            layout = self._create_pango_layout(ctx, label_text, font_str)
            _, log = layout.get_pixel_extents()
            
            text_rgba = Gdk.RGBA(); text_rgba.parse(color_str)
            ctx.set_source_rgba(text_rgba.red, text_rgba.green, text_rgba.blue, text_rgba.alpha)
            ctx.move_to(sidebar_w - log.width - 5, current_y + seg_h - log.height - 5); PangoCairo.show_layout(ctx, layout)
            current_y += seg_h

    def _draw_content_widgets(self, ctx, width, height):
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        
        has_top_ext = mode in ["top", "both"]
        has_bottom_ext = mode in ["bottom", "both"]
        
        top_bar_h = float(self.config.get("lcars_top_bar_height", 40)) if has_top_ext else 0
        bottom_ext_h = float(self.config.get("lcars_bottom_extension_height", 40)) if has_bottom_ext else 0
        
        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        padding = float(self.config.get("lcars_content_padding", 5))
        
        content_x = sidebar_w + padding
        content_y = top_bar_h + padding
        content_w = width - content_x - padding
        content_h = height - top_bar_h - bottom_ext_h - (2 * padding)

        if content_w <= 0 or content_h <= 0: return
        
        ctx.save(); ctx.rectangle(content_x, content_y, content_w, content_h); ctx.clip()
        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("lcars_content_bg_color"))
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha); ctx.paint()

        num_secondary = int(self.config.get("number_of_secondary_sources", 4))
        current_y = content_y
        
        primary_data = self.data_bundle.get("primary_source", {})
        if primary_data:
            primary_h = float(self.config.get("primary_item_height", 60))
            self._draw_content_item(ctx, content_x, current_y, content_w, primary_h, "primary", primary_data)
            current_y += primary_h
            content_h -= primary_h
            
        if num_secondary > 0 and content_h > 0:
            secondary_items = []
            total_weight = 0
            fixed_height_total = 0

            spacing_mode = self.config.get("lcars_secondary_spacing_mode", "auto")
            spacing_value = float(self.config.get("lcars_secondary_spacing_value", 5))
            
            for i in range(1, num_secondary + 1):
                prefix = f"secondary{i}"
                display_as = self.config.get(f"{prefix}_display_as")
                item = {"prefix": prefix, "data": self.data_bundle.get(f"{prefix}_source", {})}
                if display_as in ["level_bar", "graph"]:
                    item["height"] = float(self.config.get(f"{prefix}_item_height", 60))
                    fixed_height_total += item["height"]
                else:
                    item["weight"] = 1 
                    total_weight += 1
                secondary_items.append(item)
            
            auto_spacing = 5
            if spacing_mode == "manual":
                total_spacing_needed = (num_secondary - 1) * spacing_value if num_secondary > 1 else 0
                remaining_h = content_h - fixed_height_total - total_spacing_needed
            else:
                total_spacing_needed = (num_secondary - 1) * auto_spacing if num_secondary > 1 else 0
                remaining_h = content_h - fixed_height_total - total_spacing_needed
                spacing_value = auto_spacing

            for i, item in enumerate(secondary_items):
                item_h = 0
                if "height" in item:
                    item_h = item["height"]
                elif total_weight > 0 and remaining_h > 0:
                    item_h = (item["weight"] / total_weight) * remaining_h
                
                if item_h > 0:
                    self._draw_content_item(ctx, content_x, current_y, content_w, item_h, item["prefix"], item["data"])
                    if i < len(secondary_items) - 1:
                        current_y += item_h + spacing_value
        ctx.restore()

    def _draw_content_item(self, ctx, x, y, w, h, prefix, data):
        display_as = self.config.get(f"{prefix}_display_as", "bar")
        if display_as == "bar":
            radius = float(self.config.get(f"{prefix}_bar_corner_radius", 8))
            self._draw_key_value_bar(ctx, x, y, w, h, prefix, data, radius)
        elif display_as == "level_bar":
            self._draw_secondary_level_bar(ctx, x, y, w, h, prefix, data)
        elif display_as == "graph":
            self._draw_secondary_graph(ctx, x, y, w, h, prefix, data)
        else:
            self._draw_key_value_text(ctx, x, y, w, h, prefix, data, radius=0)
    
    def _draw_secondary_graph(self, ctx, x, y, w, h, prefix, data):
        padding = 10
        ctx.save(); ctx.rectangle(x+padding, y, w-2*padding, h); ctx.clip(); ctx.translate(x+padding,y)
        drawer_config = {}; populate_defaults_from_model(drawer_config, GraphDisplayer._get_graph_config_model_definition())
        
        for key, value in self.config.items():
            if key.startswith(f"{prefix}_"):
                unprefixed_key = key[len(prefix) + 1:]
                drawer_config[unprefixed_key] = value
        
        if 'min_value' in data and data['min_value'] is not None:
            drawer_config['graph_min_value'] = data['min_value']
        if 'max_value' in data and data['max_value'] is not None:
            drawer_config['graph_max_value'] = data['max_value']

        lcars_bg_color = self.config.get(f"{prefix}_graph_lcars_bg_color")
        if lcars_bg_color:
            drawer_config['graph_bg_color'] = lcars_bg_color
            drawer_config['graph_bg_type'] = 'solid'

        self._graph_drawer.config = drawer_config
        self._graph_drawer.history = self._history_buffers.get(f"{prefix}_graph", [])
        
        child_source_instance = self.panel_ref.data_source.child_sources.get(f"{prefix}_source")
        self._graph_drawer.update_display(data.get('raw_data'), source_override=child_source_instance)
        
        self._graph_drawer.on_draw(None, ctx, w-2*padding, h)
        
        # --- NEW: Draw text overlay on top of graph ---
        text_overlay_enabled = str(self.config.get(f"{prefix}_text_overlay_enabled", "False")).lower() == 'true'
        if text_overlay_enabled and prefix in self._text_overlay_lines:
            self._draw_text_overlay(ctx, 0, 0, w-2*padding, h, prefix)
        
        ctx.restore()
    
    def _draw_text_overlay(self, ctx, x, y, w, h, prefix):
        """Draws text overlay on graph using text.py style configuration."""
        line_count = int(self.config.get(f"{prefix}_text_line_count", 2))
        spacing = int(self.config.get(f"{prefix}_text_spacing", 4))
        text_lines = self._text_overlay_lines.get(prefix, [])
        
        if not text_lines:
            return
        
        layouts_to_draw = []
        total_text_height = 0
        max_text_width = 0
        
        for i in range(min(line_count, len(text_lines))):
            line_num = i + 1
            font_str = self.config.get(f"{prefix}_line{line_num}_font", "Sans 12")
            layout = self._create_pango_layout(ctx, text_lines[i], font_str)
            layouts_to_draw.append(layout)
            
            text_dims = layout.get_pixel_extents()[1]
            total_text_height += text_dims.height
            max_text_width = max(max_text_width, text_dims.width)
        
        if len(layouts_to_draw) > 1:
            total_text_height += (len(layouts_to_draw) - 1) * spacing

        v_align = self.config.get(f"{prefix}_text_vertical_align", "center")
        if v_align == "start":
            current_y = 0
        elif v_align == "end":
            current_y = h - total_text_height
        else:
            current_y = (h - total_text_height) / 2

        h_align_block = self.config.get(f"{prefix}_text_horizontal_align", "center")
        if h_align_block == "start":
            block_x = 0
        elif h_align_block == "end":
            block_x = w - max_text_width
        else:
            block_x = (w - max_text_width) / 2
        
        for i, layout in enumerate(layouts_to_draw):
            line_num = i + 1
            
            ctx.save()

            rgba = Gdk.RGBA()
            rgba.parse(self.config.get(f"{prefix}_line{line_num}_color", "rgba(220,220,220,1)"))
            ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)

            align_str_line = self.config.get(f"{prefix}_line{line_num}_align", "center")
            text_width = layout.get_pixel_extents()[1].width
            text_height = layout.get_pixel_extents()[1].height
            
            line_offset_x = 0
            if align_str_line == "right":
                line_offset_x = max_text_width - text_width
            elif align_str_line == "center":
                line_offset_x = (max_text_width - text_width) / 2
            
            current_x = block_x + line_offset_x
            
            slant_deg = float(self.config.get(f"{prefix}_line{line_num}_slant", "0"))
            rotation_deg = float(self.config.get(f"{prefix}_line{line_num}_rotation", "0"))

            ctx.translate(current_x + text_width / 2, current_y + text_height / 2)
            if rotation_deg != 0:
                ctx.rotate(math.radians(rotation_deg))
            if slant_deg != 0:
                ctx.transform(cairo.Matrix(1, 0, math.tan(math.radians(slant_deg)), 1, 0, 0))

            ctx.move_to(-text_width / 2, -text_height / 2)
            PangoCairo.show_layout(ctx, layout)
            
            ctx.restore()
            
            current_y += text_height + spacing

    def _draw_secondary_level_bar(self, ctx, x, y, w, h, prefix, data):
        padding = 10
        ctx.save(); ctx.rectangle(x+padding, y, w-2*padding, h); ctx.clip(); ctx.translate(x+padding,y)
        drawer_config = {}; populate_defaults_from_model(drawer_config, LevelBarDisplayer.get_config_model())
        
        for key, value in self.config.items():
            if key.startswith(f"{prefix}_level_bar"):
                drawer_config[key.replace(f"{prefix}_", '', 1)] = value
        
        drawer_config['level_min_value'] = data.get('min_value', 0.0)
        drawer_config['level_max_value'] = data.get('max_value', 100.0)
        
        self._level_bar_drawer.config = drawer_config
        self._level_bar_drawer._sync_state_with_config()
        
        bar_anim_key = f"{prefix}_bar"
        percent = self._bar_values.get(bar_anim_key, {}).get('current', 0.0)
        num_segments = int(drawer_config.get("level_bar_segment_count", 30))
        
        self._level_bar_drawer.current_on_level = int(round(percent * num_segments))
        self._level_bar_drawer.target_on_level = self._level_bar_drawer.current_on_level
        self._level_bar_drawer.primary_text = data.get("primary_label", "")
        self._level_bar_drawer.secondary_text = data.get("display_string", "")
        
        self._level_bar_drawer.on_draw(None, ctx, w-2*padding, h)
        ctx.restore()

    def _draw_key_value_text(self, ctx, x, y, w, h, prefix, data, radius=0):
        text_padding = 10 + radius
        show_label = str(self.config.get(f"{prefix}_show_label", "True")).lower() == 'true'
        show_value = str(self.config.get(f"{prefix}_show_value", "True")).lower() == 'true'
        if not show_label and not show_value: return
        
        final_label = data.get("primary_label", "N/A").upper()
        final_value = data.get("display_string", "-").upper()
        
        if show_label:
            font_str = self.config.get(f"{prefix}_label_font")
            color_str = self.config.get(f"{prefix}_label_color")
            label_layout = self._create_pango_layout(ctx, final_label, font_str)
            _, log_label = label_layout.get_pixel_extents()
            
            text_rgba = Gdk.RGBA(); text_rgba.parse(color_str)
            ctx.set_source_rgba(text_rgba.red, text_rgba.green, text_rgba.blue, text_rgba.alpha)
            ctx.move_to(x + text_padding, y + (h - log_label.height) / 2)
            PangoCairo.show_layout(ctx, label_layout)

        if show_value:
            font_str = self.config.get(f"{prefix}_value_font")
            color_str = self.config.get(f"{prefix}_value_color")
            value_layout = self._create_pango_layout(ctx, final_value, font_str)
            _, log_value = value_layout.get_pixel_extents()

            text_rgba = Gdk.RGBA(); text_rgba.parse(color_str)
            ctx.set_source_rgba(text_rgba.red, text_rgba.green, text_rgba.blue, text_rgba.alpha)
            ctx.move_to(x + w - log_value.width - text_padding, y + (h - log_value.height) / 2)
            PangoCairo.show_layout(ctx, value_layout)

    def _draw_key_value_bar(self, ctx, x, y, w, h, prefix, data, radius):
        layout = self.config.get(f"{prefix}_bar_text_layout", "superimposed")
        
        if layout == "superimposed":
            padding = 10
            bar_h, bar_y = h * 0.6, y + (h - h * 0.6) / 2
            bar_x, bar_w = x + padding, w - 2 * padding
            bar_anim_key = f"{prefix}_bar"
            percent = self._bar_values.get(bar_anim_key, {}).get('current', 0.0)
            bg_color_str = self.config.get(f"{prefix}_bar_bg_color", "rgba(0,0,0,0.5)")
            fg_color_str = self.config.get(f"{prefix}_bar_fg_color", "rgba(255,153,102,1)")
            
            ctx.save()
            bg_color = Gdk.RGBA(); bg_color.parse(bg_color_str)
            ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
            self._draw_rounded_rect(ctx, bar_x, bar_y, bar_w, bar_h, radius); ctx.fill()
            if percent > 0:
                fg_color = Gdk.RGBA(); fg_color.parse(fg_color_str)
                ctx.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, fg_color.alpha)
                self._draw_rounded_rect(ctx, bar_x, bar_y, bar_w * percent, bar_h, radius); ctx.fill()
            ctx.restore()
            self._draw_key_value_text(ctx, x, y, w, h, prefix, data, radius)
        else:
            ratio = float(self.config.get(f"{prefix}_bar_text_split_ratio", 0.4))
            spacing = 5
            
            text_w = (w * ratio) - (spacing / 2)
            bar_w = w * (1.0 - ratio) - (spacing / 2)

            if layout == "left":
                text_x = x
                bar_x = x + text_w + spacing
            else:
                bar_x = x
                text_x = x + bar_w + spacing

            bar_anim_key = f"{prefix}_bar"
            percent = self._bar_values.get(bar_anim_key, {}).get('current', 0.0)
            bg_color_str = self.config.get(f"{prefix}_bar_bg_color", "rgba(0,0,0,0.5)")
            fg_color_str = self.config.get(f"{prefix}_bar_fg_color", "rgba(255,153,102,1)")
            
            ctx.save()
            bg_color = Gdk.RGBA(); bg_color.parse(bg_color_str)
            ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
            self._draw_rounded_rect(ctx, bar_x, y, bar_w, h, radius); ctx.fill()
            if percent > 0:
                fg_color = Gdk.RGBA(); fg_color.parse(fg_color_str)
                ctx.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, fg_color.alpha)
                self._draw_rounded_rect(ctx, bar_x, y, bar_w * percent, h, radius); ctx.fill()
            ctx.restore()

            self._draw_key_value_text(ctx, text_x, y, text_w, h, prefix, data, radius=0)

    def _draw_rounded_rect(self, ctx, x, y, w, h, r):
        if r <= 0 or w <= 0 or h <= 0: ctx.rectangle(x, y, w, h); return
        r = min(r, h / 2, w / 2)
        ctx.new_path(); ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
        ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
        ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi); ctx.close_path()

    def close(self):
        self._stop_animation_timer()
        if self._level_bar_drawer: self._level_bar_drawer.close(); self._level_bar_drawer = None
        if self._graph_drawer: self._graph_drawer.close(); self._graph_drawer = None
        super().close()
