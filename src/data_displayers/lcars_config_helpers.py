# /data_displayers/lcars_config_helpers.py
import gi
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from .level_bar import LevelBarDisplayer
from .graph import GraphDisplayer
from .static import StaticDisplayer
from .cpu_multicore import CpuMultiCoreDisplayer
from ui_helpers import build_background_config_ui

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib

def get_segment_model(i):
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

def get_content_item_model(prefix):
    """Helper to generate a config model for a single content item (primary or secondary)."""
    
    # Define the display-as controller key first
    controller_key = f"{prefix}_display_as"
    
    # NOTE: We purposefully do NOT use dynamic_group here.
    # The visibility of these sections is handled manually by setup_dynamic_content_ui
    # to ensure compatibility with nested dynamic displayers (like Graph/MultiCore).
    
    model = {
        "Content": [
            ConfigOption(controller_key, "dropdown", "Display As:", "bar", 
                            options_dict={"Bar with Text": "bar", "Text Only": "text", 
                                        "Level Bar": "level_bar", "Graph": "graph", 
                                        "Static Content": "static", "Multi-Core Bars": "cpu_multicore"}),
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
            ConfigOption(f"{prefix}_bar_text_split_ratio", "spinner", "Text/Bar Split Ratio:", 0.4, 0.1, 0.9, 0.05, 2,
                            tooltip="The proportion of space given to the text when layout is not superimposed."),
        ]
    }
    
    # --- Level Bar Options ---
    lb_model = LevelBarDisplayer.get_config_model()
    lb_options = []
    for section_name, opts in lb_model.items():
        if section_name != "Level Bar Range": 
            for opt in opts:
                new_key = f"{prefix}_{opt.key}"
                lb_options.append(ConfigOption(new_key, opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters))
    model["Level Bar Style"] = lb_options
    
    # --- Graph Options ---
    g_model = GraphDisplayer._get_graph_config_model_definition()
    graph_style_options = []
    graph_style_options.append(ConfigOption(f"{prefix}_graph_lcars_bg_color", "color", "Background Color:", "rgba(0,0,0,1)"))
    
    for section_name, opts in g_model.items():
        for opt in opts:
            new_key = f"{prefix}_{opt.key}"
            # Preserve internal dynamic logic for Graph (e.g. line vs bar style)
            # We prefix the dynamic group to ensure uniqueness
            new_group = f"{prefix}_{opt.dynamic_group}" if opt.dynamic_group else None
            graph_style_options.append(ConfigOption(new_key, opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters, 
                                                    dynamic_group=new_group, dynamic_show_on=opt.dynamic_show_on))
    model["Graph Style"] = graph_style_options
    
    model["Graph Text Overlay"] = [
        ConfigOption(f"{prefix}_text_overlay_enabled", "bool", "Enable Text Overlay:", "False"),
        ConfigOption(f"{prefix}_text_line_count", "spinner", "Number of Lines:", 2, 1, 10, 1, 0),
        ConfigOption(f"{prefix}_text_horizontal_align", "dropdown", "Horizontal Align:", "center", 
                        options_dict={"Left": "start", "Center": "center", "Right": "end"}),
        ConfigOption(f"{prefix}_text_vertical_align", "dropdown", "Vertical Align:", "center", 
                        options_dict={"Top": "start", "Center": "center", "Bottom": "end"}),
        ConfigOption(f"{prefix}_text_spacing", "spinner", "Spacing (px):", 4, 0, 50, 1, 0),
    ]
    
    # --- Static Options ---
    static_model = StaticDisplayer._get_full_config_model_definition()
    static_options = []
    static_options.append(ConfigOption(f"{prefix}_static_content_type", "dropdown", "Content Type:", "text", 
                                            options_dict={"Text": "text", "Image": "image"}))
                                            
    for section_name, opts in static_model.items():
            for opt in opts:
                new_key = f"{prefix}_{opt.key}"
                # Preserve internal dynamic logic for Static
                new_group = f"{prefix}_{opt.dynamic_group}" if opt.dynamic_group else None
                static_options.append(ConfigOption(new_key, opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters, 
                                                   dynamic_group=new_group, dynamic_show_on=opt.dynamic_show_on))
    model["Static Content"] = static_options

    # --- Multi-Core Options ---
    mc_model = CpuMultiCoreDisplayer.get_config_model()
    mc_options = []
    for section_name, opts in mc_model.items():
        for opt in opts:
            new_key = f"{prefix}_{opt.key}"
            # Note: CpuMultiCoreDisplayer doesn't use dynamic_group anymore (manual logic), so new_group is None
            new_group = None
            mc_options.append(ConfigOption(new_key, opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters, 
                                           dynamic_group=new_group, dynamic_show_on=opt.dynamic_show_on))
    model["Multi-Core Style"] = mc_options

    return model

def get_full_config_model():
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
            ConfigOption("lcars_frame_color", "color", "Frame Color:", "rgba(255,153,102,1)"),
            ConfigOption("lcars_content_bg_color", "color", "Content BG Color:", "rgba(0,0,0,1)"),
            ConfigOption("lcars_content_padding", "spinner", "Content Padding (px):", 5, 0, 100, 1, 0),
            ConfigOption("lcars_secondary_spacing_mode", "dropdown", "Secondary Item Spacing:", "auto", options_dict={"Automatic": "auto", "Manual": "manual"}),
            ConfigOption("lcars_secondary_spacing_value", "spinner", "Manual Spacing (px):", 5, 0, 50, 1, 0),
        ],
        "Split View (Divider)": [
            ConfigOption("lcars_split_screen_enabled", "bool", "Enable Split View:", "False"),
            ConfigOption("lcars_split_screen_orientation", "dropdown", "Split Orientation:", "vertical", options_dict={"Vertical (Left/Right)": "vertical", "Horizontal (Top/Bottom)": "horizontal"}),
            ConfigOption("lcars_split_screen_ratio", "spinner", "Split Ratio:", 0.5, 0.1, 0.9, 0.05, 2, tooltip="Adjusts the relative size of the Primary vs Secondary area."),
            ConfigOption("lcars_split_screen_divider_width", "spinner", "Divider Thickness (px):", 10, 1, 50, 1, 0),
            ConfigOption("lcars_split_screen_divider_color", "color", "Divider Color:", "rgba(255,153,102,1)", 
                            tooltip="Defaults to frame color if not set."),
            ConfigOption("lcars_split_screen_spacing_before", "spinner", "Spacing Before Divider (px):", 0, 0, 100, 1, 0),
            ConfigOption("lcars_split_screen_spacing_after", "spinner", "Spacing After Divider (px):", 0, 0, 100, 1, 0),
            ConfigOption("lcars_split_screen_divider_cap_start", "dropdown", "Start Cap Style:", "square", options_dict={"Square": "square", "Round": "round"}),
            ConfigOption("lcars_split_screen_divider_cap_end", "dropdown", "End Cap Style:", "square", options_dict={"Square": "square", "Round": "round"}),
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
            ConfigOption("lcars_animation_speed", "spinner", "Animation Speed:", 0.1, 0.01, 0.5, 0.01, 2, 
                            tooltip="Controls how quickly the bar moves to its target. Smaller is faster."),
        ]
    }
    
    for i in range(1, 17):
        prim_model = get_content_item_model(f"primary{i}")
        for section, options in prim_model.items():
            model[f"Primary {i} {section}"] = options

    for i in range(1, 17):
        sec_model = get_content_item_model(f"secondary{i}")
        for section, options in sec_model.items():
            model[f"Secondary {i} {section}"] = options
    
    for i in range(1, 17):
        seg_model = get_segment_model(i)
        for section, options in seg_model.items():
            model[section] = options
            
    return model

def setup_dynamic_content_ui(dialog, parent_box, widgets, available_sources, panel_config, prefix):
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
        "static": find_section_widgets("Static Content"),
        "cpu_multicore": find_section_widgets("Multi-Core Style")
    }
    
    item_height_widget_container = None
    item_height_widget = widgets.get(f"{prefix}_item_height")
    if item_height_widget:
        item_height_widget_container = item_height_widget.get_parent()
    
    text_overlay_enabled_switch = widgets.get(f"{prefix}_text_overlay_enabled")
    text_line_count_spinner = widgets.get(f"{prefix}_text_line_count")
    
    if text_overlay_enabled_switch and text_line_count_spinner:
        text_overlay_lines_container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10)
        
        for child in all_children:
            if isinstance(child, Gtk.Label) and child.get_label() and "Graph Text Overlay" in child.get_label():
                idx = all_children.index(child)
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
            child = text_overlay_lines_container.get_first_child()
            while child:
                text_overlay_lines_container.remove(child)
                child = text_overlay_lines_container.get_first_child()
            
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
            for w in section_widgets:
                if w and w.get_parent(): w.set_visible(False)

        if active_id == "text":
            for w in section_map["text"]: w.set_visible(True)
        elif active_id == "bar":
            for w in section_map["text"]: w.set_visible(True)
            for w in section_map["bar"]: w.set_visible(True)
        elif active_id == "level_bar":
            for w in section_map["level_bar"]: w.set_visible(True)
        elif active_id == "graph":
            for w in section_map["graph"]: w.set_visible(True)
            for w in section_map["graph_text_overlay"]: w.set_visible(True)
        elif active_id == "static":
            for w in section_map["static"]: w.set_visible(True)
        elif active_id == "cpu_multicore":
            for w in section_map["cpu_multicore"]: w.set_visible(True)

        if item_height_widget_container:
            item_height_widget_container.set_visible(True)

    display_as_combo.connect("changed", update_visibility)
    GLib.idle_add(update_visibility, display_as_combo)
    
    # --- Inject Multi-Core Dynamic Logic ---
    temp_mc = CpuMultiCoreDisplayer(None, panel_config)
    mc_cb = temp_mc.get_configure_callback()
    if mc_cb:
        mc_cb(dialog, parent_box, widgets, available_sources, panel_config, prefix=prefix)
    
    # --- Inject Level Bar Dynamic Logic ---
    temp_lb = LevelBarDisplayer(None, panel_config)
    lb_cb = temp_lb.get_configure_callback()
    if lb_cb:
        lb_cb(dialog, parent_box, widgets, available_sources, panel_config, prefix=prefix)

def build_display_ui_impl(dialog, content_box, widgets, available_sources, panel_config):
    """Builds the comprehensive UI for the Display tab."""
    display_notebook = Gtk.Notebook(vexpand=True)
    content_box.append(display_notebook)

    # --- Tab 1: Frame & Side Bar ---
    frame_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
    frame_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
    frame_scroll.set_child(frame_box)
    display_notebook.append_page(frame_scroll, Gtk.Label(label="Frame"))
    
    full_model = get_full_config_model()
    frame_ui_model = {
        "Frame Style": full_model["Frame Style"],
        "Split View (Divider)": full_model["Split View (Divider)"],
        "Header Bar (Top)": full_model["Header Bar (Top)"],
        "Header Bar (Bottom)": full_model["Header Bar (Bottom)"],
        "Animation": full_model["Animation"]
    }
    frame_ui_model["Frame Style"] = [opt for opt in frame_ui_model["Frame Style"] if opt.key != "lcars_extension_corner_radius"]

    build_ui_from_model(frame_box, panel_config, frame_ui_model, widgets)
    dialog.dynamic_models.append(frame_ui_model)
    
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
        
        seg_model = get_segment_model(i)
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

    primary_tabs_content = []
    for i in range(1, 17):
        prefix = f"primary{i}"
        tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        tab_scroll.set_min_content_height(300)
        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        tab_scroll.set_child(tab_box)
        content_notebook.append_page(tab_scroll, Gtk.Label(label=f"Prim {i}"))
        primary_tabs_content.append(tab_scroll)
        model_to_use = get_content_item_model(prefix)
        build_ui_from_model(tab_box, panel_config, model_to_use, widgets)
        setup_dynamic_content_ui(dialog, tab_box, widgets, available_sources, panel_config, prefix)
        dialog.dynamic_models.append(model_to_use)

    secondary_tabs_content = []
    for i in range(1, 17):
        prefix = f"secondary{i}"
        tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        tab_scroll.set_min_content_height(300)
        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        tab_scroll.set_child(tab_box)
        content_notebook.append_page(tab_scroll, Gtk.Label(label=f"Sec {i}"))
        secondary_tabs_content.append(tab_scroll)
        sec_model = get_content_item_model(prefix)
        build_ui_from_model(tab_box, panel_config, sec_model, widgets)
        setup_dynamic_content_ui(dialog, tab_box, widgets, available_sources, panel_config, prefix)
        dialog.dynamic_models.append(sec_model)

    def on_content_counts_changed(spinner):
        prim_count = widgets.get("number_of_primary_sources").get_value_as_int()
        sec_count = widgets.get("number_of_secondary_sources").get_value_as_int()
        for i, content_widget in enumerate(primary_tabs_content):
            content_widget.set_visible(i < prim_count)
        for i, content_widget in enumerate(secondary_tabs_content):
            content_widget.set_visible(i < sec_count)
    prim_count_spinner = widgets.get("number_of_primary_sources")
    sec_count_spinner = widgets.get("number_of_secondary_sources")
    if prim_count_spinner: prim_count_spinner.connect("value-changed", on_content_counts_changed)
    if sec_count_spinner: sec_count_spinner.connect("value-changed", on_content_counts_changed)
    GLib.idle_add(on_content_counts_changed, None)

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
        prim_count = widgets["number_of_primary_sources"].get_value_as_int()
        sec_count = widgets["number_of_secondary_sources"].get_value_as_int()
        source_id_str = source_item_combo.get_active_id()
        if not source_id_str: return
        keys_to_copy = []
        for key, chk in copy_checkboxes.items():
            if chk.get_active(): keys_to_copy.extend(property_map.get(key, []))
        all_prefixes = [f"primary{i}" for i in range(1, prim_count + 1)] + [f"secondary{i}" for i in range(1, sec_count + 1)]
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
    def on_counts_changed_for_effects(spinner):
        prim_count = widgets["number_of_primary_sources"].get_value_as_int()
        sec_count = widgets.get("number_of_secondary_sources").get_value_as_int()
        source_item_combo.remove_all()
        for i in range(1, prim_count + 1):
            source_item_combo.append(id=f"primary{i}", text=f"Primary {i}")
        for i in range(1, sec_count + 1):
            source_item_combo.append(id=f"secondary{i}", text=f"Secondary {i}")
        source_item_combo.set_active(0)
    if prim_count_spinner: prim_count_spinner.connect("value-changed", on_counts_changed_for_effects)
    if sec_count_spinner: sec_count_spinner.connect("value-changed", on_counts_changed_for_effects)
    GLib.idle_add(on_counts_changed_for_effects, None)

    return build_display_ui_impl
