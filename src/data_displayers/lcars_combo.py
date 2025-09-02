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
        self._cached_primary_image = None
        self._cached_primary_image_path = None
        
        self._animation_timer_id = None
        self._bar_values = {}
        self._history_buffers = {}

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
        
        g_model = GraphDisplayer.get_config_model()
        graph_style_options = [ConfigOption(f"{prefix}_{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for section in g_model.values() for opt in section]
        graph_style_options.insert(0, ConfigOption(f"{prefix}_graph_lcars_bg_color", "color", "Background Color:", "rgba(0,0,0,1)"))
        model["Graph Style"] = graph_style_options
        
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
                ConfigOption("lcars_top_extension_height", "spinner", "Top Extension Height (px):", 40, 0, 500, 5, 0),
                ConfigOption("lcars_bottom_extension_height", "spinner", "Bottom Extension Height (px):", 40, 0, 500, 5, 0),
                ConfigOption("lcars_top_bar_height", "spinner", "Top Bar Height (px):", 40, 10, 200, 2, 0),
                ConfigOption("lcars_sidebar_width", "spinner", "Side Bar Width (px):", 150, 20, 500, 5, 0),
                ConfigOption("lcars_corner_radius", "spinner", "Corner Radius (px):", 60, 10, 500, 5, 0),
                ConfigOption("lcars_frame_color", "color", "Frame Color:", "rgba(255,153,102,1)"), # Peach
                ConfigOption("lcars_content_bg_color", "color", "Content BG Color:", "rgba(0,0,0,1)"),
                ConfigOption("lcars_content_padding", "spinner", "Content Padding (px):", 5, 0, 100, 1, 0),
            ],
            "Top Bar": [
                ConfigOption("lcars_header_text", "string", "Header Text:", "U.S.S. ENTERPRISE"),
                ConfigOption("lcars_header_font", "font", "Header Font:", "Swiss 911 Ultra Compressed 18"),
                ConfigOption("lcars_header_color", "color", "Header Color:", "rgba(0,0,0,1)"),
                ConfigOption("lcars_header_bg_color", "color", "Header BG Color:", "rgba(204,153,255,1)"), # Lilac
                ConfigOption("lcars_header_padding", "spinner", "Header Padding (px):", 10, 0, 50, 1, 0),
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

        for i in range(1, 13):
            sec_model = cls._get_content_item_model(f"secondary{i}")
            for section, options in sec_model.items():
                model[f"Secondary {i} {section}"] = options
        
        for i in range(1, 13):
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
            
            frame_ui_model = {
                "Frame Style": self._get_full_config_model()["Frame Style"],
                "Top Bar": self._get_full_config_model()["Top Bar"],
                "Animation": self._get_full_config_model()["Animation"]
            }
            build_ui_from_model(frame_box, panel_config, frame_ui_model, widgets)
            dialog.dynamic_models.append(frame_ui_model)

            # Dynamic visibility for extension height spinners
            ext_mode_combo = widgets.get("lcars_sidebar_extension_mode")
            top_ext_spinner = widgets.get("lcars_top_extension_height")
            bottom_ext_spinner = widgets.get("lcars_bottom_extension_height")
            if ext_mode_combo and top_ext_spinner and bottom_ext_spinner:
                top_ext_row = top_ext_spinner.get_parent()
                bottom_ext_row = bottom_ext_spinner.get_parent()
                def on_ext_mode_changed(combo):
                    mode = combo.get_active_id()
                    top_ext_row.set_visible(mode in ["top", "both"])
                    bottom_ext_row.set_visible(mode in ["bottom", "both"])
                ext_mode_combo.connect("changed", on_ext_mode_changed)
                GLib.idle_add(on_ext_mode_changed, ext_mode_combo)
            
            frame_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            frame_box.append(Gtk.Label(label="<b>Side Bar Segments</b>", use_markup=True, xalign=0))
            
            sidebar_model = {"": [ConfigOption("lcars_segment_count", "spinner", "Number of Segments:", 3, 0, 12, 1, 0)]}
            build_ui_from_model(frame_box, panel_config, sidebar_model, widgets)
            dialog.dynamic_models.append(sidebar_model)

            segment_scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            segment_scrolled.set_min_content_height(300)
            segment_notebook = Gtk.Notebook()
            segment_notebook.set_scrollable(True)
            segment_scrolled.set_child(segment_notebook)
            frame_box.append(segment_scrolled)
            
            segment_tabs_content = []
            for i in range(1, 13):
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

            # --- Primary Item Sub-Tab ---
            primary_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            primary_scroll.set_min_content_height(300)
            primary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            primary_scroll.set_child(primary_box)
            content_notebook.append_page(primary_scroll, Gtk.Label(label="Primary"))
            
            primary_model = self._get_content_item_model("primary")
            build_ui_from_model(primary_box, panel_config, primary_model, widgets)
            self._setup_dynamic_content_ui(dialog, primary_box, widgets, panel_config, "primary")
            dialog.dynamic_models.append(primary_model)

            # --- Secondary Items Sub-Tabs ---
            secondary_tabs_content = []
            for i in range(1, 13):
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
        }
        
        item_height_widget_container = None
        item_height_widget = widgets.get(f"{prefix}_item_height")
        if item_height_widget:
            item_height_widget_container = item_height_widget.get_parent()

        def update_visibility(combo):
            active_id = combo.get_active_id()
            for key, section_widgets in section_map.items():
                is_visible = (key == active_id) or (key == 'text' and active_id == 'bar')
                for w in section_widgets:
                    if w and w.get_parent(): w.set_visible(is_visible)
            
            if item_height_widget_container:
                item_height_widget_container.set_visible(True)

        display_as_combo.connect("changed", update_visibility)
        GLib.idle_add(update_visibility, display_as_combo)

    def apply_styles(self):
        super().apply_styles()
        self.widget.queue_draw()

    def update_display(self, value):
        super().update_display(value) 
        
        all_prefixes = ["primary"] + [f"secondary{i}" for i in range(1, 13)]
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

    def _create_pango_layout(self, ctx, text, font_str, color_str):
        layout = PangoCairo.create_layout(ctx)
        font_str = font_str or "Sans 12"; color_str = color_str or "rgba(255,255,255,1)"
        layout.set_font_description(Pango.FontDescription.from_string(font_str))
        layout.set_text(text, -1)
        color = Gdk.RGBA(); color.parse(color_str)
        ctx.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        return layout

    def _draw_frame_and_sidebar(self, ctx, width, height):
        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        radius = float(self.config.get("lcars_corner_radius", 60))
        frame_color_str = self.config.get("lcars_frame_color", "rgba(255,153,102,1)")
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        top_ext_h = float(self.config.get("lcars_top_extension_height", 40)) if mode in ["top", "both"] else 0
        
        # This top_bar_h is now effectively the starting Y of the main content area
        top_bar_h = top_ext_h

        ctx.new_path()
        # Top-left and top edge
        ctx.move_to(0, radius)
        ctx.arc(radius, radius, radius, math.pi, 1.5 * math.pi)
        ctx.line_to(width, 0)
        
        # Top-right down to content area
        ctx.line_to(width, top_bar_h)
        
        # Top edge of content area and inner corner
        ctx.line_to(sidebar_w + radius, top_bar_h)
        ctx.arc_negative(sidebar_w + radius, top_bar_h + radius, radius, 1.5 * math.pi, math.pi)
        
        # Left edge of content area, goes down to bottom of panel
        ctx.line_to(sidebar_w, height)
        
        # Bottom edge and bottom-left corner
        ctx.line_to(0, height)
        ctx.close_path()
        
        frame_color = Gdk.RGBA(); frame_color.parse(frame_color_str)
        ctx.set_source_rgba(frame_color.red, frame_color.green, frame_color.blue, frame_color.alpha)
        ctx.fill()
        
        self._draw_header(ctx, width, height)
        self._draw_sidebar_segments(ctx, width, height)

    def _draw_header(self, ctx, width, height):
        top_bar_h = float(self.config.get("lcars_top_bar_height", 40))
        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        radius = float(self.config.get("lcars_corner_radius", 60))
        padding = float(self.config.get("lcars_header_padding", 10))
        pill_x, pill_y, pill_w, pill_h = sidebar_w + radius + padding, padding, width - (sidebar_w + radius + padding) - padding, top_bar_h - 2 * padding
        pill_radius = pill_h / 2
        if pill_w <= 0 or pill_h <= 0: return

        ctx.new_path(); ctx.arc(pill_x + pill_radius, pill_y + pill_radius, pill_radius, 0.5 * math.pi, 1.5 * math.pi)
        ctx.arc(pill_x + pill_w - pill_radius, pill_y + pill_radius, pill_radius, 1.5 * math.pi, 0.5 * math.pi); ctx.close_path()
        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("lcars_header_bg_color"))
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha); ctx.fill()
        
        header_text = self.config.get("lcars_header_text", "").upper()
        font_str, color_str = self.config.get("lcars_header_font"), self.config.get("lcars_header_color")
        layout = self._create_pango_layout(ctx, header_text, font_str, color_str)
        _, log = layout.get_pixel_extents()
        ctx.move_to(pill_x + pill_radius, pill_y + (pill_h - log.height) / 2); PangoCairo.show_layout(ctx, layout)
        
    def _draw_sidebar_segments(self, ctx, width, height):
        num_segments = int(self.config.get("lcars_segment_count", 3))
        if num_segments == 0: return

        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        top_ext_h = float(self.config.get("lcars_top_extension_height", 40)) if mode in ["top", "both"] else 0
        bottom_ext_h = float(self.config.get("lcars_bottom_extension_height", 40)) if mode in ["bottom", "both"] else 0
        
        start_y = top_ext_h
        available_h = height - top_ext_h - bottom_ext_h
        
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
            font_str, color_str = self.config.get(f"segment_{i}_font"), self.config.get(f"segment_{i}_label_color")
            layout = self._create_pango_layout(ctx, label_text, font_str, color_str)
            _, log = layout.get_pixel_extents()
            ctx.move_to(sidebar_w - log.width - 5, current_y + seg_h - log.height - 5); PangoCairo.show_layout(ctx, layout)
            current_y += seg_h

    def _draw_content_widgets(self, ctx, width, height):
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        top_ext_h = float(self.config.get("lcars_top_extension_height", 40)) if mode in ["top", "both"] else 0
        bottom_ext_h = float(self.config.get("lcars_bottom_extension_height", 40)) if mode in ["bottom", "both"] else 0
        
        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        padding = float(self.config.get("lcars_content_padding", 5))
        
        content_x = sidebar_w + padding
        content_y = top_ext_h + padding
        content_w = width - content_x - padding
        content_h = height - top_ext_h - bottom_ext_h - (2 * padding)

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
            current_y += primary_h + 5; content_h -= primary_h + 5
            
        if num_secondary > 0 and content_h > 0:
            secondary_items = []
            total_weight = 0
            fixed_height_total = 0

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
            
            remaining_h = content_h - fixed_height_total - ( (len(secondary_items) - 1) * 5)
            
            for item in secondary_items:
                item_h = 0
                if "height" in item:
                    item_h = item["height"]
                elif total_weight > 0 and remaining_h > 0:
                    item_h = (item["weight"] / total_weight) * remaining_h
                
                if item_h > 0:
                    self._draw_content_item(ctx, content_x, current_y, content_w, item_h, item["prefix"], item["data"])
                    current_y += item_h + 5
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
        drawer_config = {}; populate_defaults_from_model(drawer_config, GraphDisplayer.get_config_model())
        
        for key, value in self.config.items():
            if key.startswith(f"{prefix}_"):
                unprefixed_key = key[len(prefix) + 1:]
                drawer_config[unprefixed_key] = value

        lcars_bg_color = self.config.get(f"{prefix}_graph_lcars_bg_color")
        if lcars_bg_color:
            drawer_config['graph_bg_color'] = lcars_bg_color
            drawer_config['graph_bg_type'] = 'solid'

        self._graph_drawer.config = drawer_config
        self._graph_drawer.history = self._history_buffers.get(f"{prefix}_graph", [])
        
        caption = data.get("primary_label", "")
        value_str = data.get("display_string", "")
        combined_text = f"{caption}: {value_str}" if caption and value_str else caption or value_str
        self._graph_drawer.secondary_text = combined_text

        self._graph_drawer.on_draw_graph(None, ctx, w-2*padding, h)
        ctx.restore()

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
            font_str, color_str = self.config.get(f"{prefix}_label_font"), self.config.get(f"{prefix}_label_color")
            label_layout = self._create_pango_layout(ctx, final_label, font_str, color_str)
            _, log_label = label_layout.get_pixel_extents()
            ctx.move_to(x + text_padding, y + (h - log_label.height) / 2)
            PangoCairo.show_layout(ctx, label_layout)
        if show_value:
            font_str, color_str = self.config.get(f"{prefix}_value_font"), self.config.get(f"{prefix}_value_color")
            value_layout = self._create_pango_layout(ctx, final_value, font_str, color_str)
            _, log_value = value_layout.get_pixel_extents()
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
        else: # Handle left/right layouts
            ratio = float(self.config.get(f"{prefix}_bar_text_split_ratio", 0.4))
            spacing = 5
            
            text_w = (w * ratio) - (spacing / 2)
            bar_w = w * (1.0 - ratio) - (spacing / 2)

            if layout == "left":
                text_x = x
                bar_x = x + text_w + spacing
            else: # right
                bar_x = x
                text_x = x + bar_w + spacing

            # Draw bar part
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

            # Draw text part
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
