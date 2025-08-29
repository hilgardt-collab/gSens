# data_displayers/lcars_combo.py
import gi
import math
import cairo
from .combo_base import ComboBase
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model
from .level_bar import LevelBarDisplayer

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

class LCARSComboDisplayer(ComboBase):
    """
    A displayer that renders multiple data sources in the iconic LCARS style,
    allowing secondary items to be displayed as text or as level bars.
    """
    def __init__(self, panel_ref, config):
        # Create a drawer instance to reuse for any level bars
        self._level_bar_drawer = LevelBarDisplayer(panel_ref, config)
        super().__init__(panel_ref, config)
        # The main config now only needs populating from the callback-built model
        
    @staticmethod
    def get_config_model():
        # The entire UI is built by the callback to prevent duplicates.
        return {}

    def get_configure_callback(self):
        """Builds the comprehensive UI for the Display tab."""
        def build_display_ui(dialog, content_box, widgets, available_sources, panel_config):
            # Define the model once, inside the callback.
            static_model = {
                "LCARS Style": [
                    ConfigOption("lcars_corner_radius_factor", "scale", "Corner Radius:", 0.4, 0.0, 1.0, 0.05, 2, 
                                 tooltip="Corner radius as a factor of the elbow bar height."),
                    ConfigOption("lcars_color_bg", "color", "Background Color:", "rgba(0,0,0,1)"),
                    ConfigOption("lcars_color_elbow", "color", "Elbow Color:", "rgba(255,153,102,1)"), # Peach
                    ConfigOption("lcars_color_bar", "color", "Bar Color:", "rgba(153,153,204,1)"),    # Periwinkle
                ],
                "LCARS Fonts & Primary Color": [
                    ConfigOption("lcars_font_primary_label", "font", "Primary Label Font:", "Swiss 911 Ultra Compressed 18"),
                    ConfigOption("lcars_font_primary_value", "font", "Primary Value Font:", "Swiss 911 Ultra Compressed 22"),
                    ConfigOption("lcars_color_text_primary", "color", "Primary Text Color:", "rgba(255,204,153,1)"), # Light Peach
                    ConfigOption("lcars_font_secondary", "font", "Default Secondary Font:", "Swiss 911 Ultra Compressed 16")
                ]
            }
            dialog.dynamic_models.append(static_model)

            display_notebook = Gtk.Notebook()
            content_box.append(display_notebook)

            # -- Tab 1: Overall Style --
            overall_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            overall_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            overall_scroll.set_child(overall_box)
            display_notebook.append_page(overall_scroll, Gtk.Label(label="Overall Style"))
            build_ui_from_model(overall_box, panel_config, static_model, widgets)
            
            # -- Tab 2: Secondary Item Styles --
            secondary_styles_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            secondary_styles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            secondary_styles_scroll.set_child(secondary_styles_box)
            display_notebook.append_page(secondary_styles_scroll, Gtk.Label(label="Secondary Styles"))
            
            style_notebook = Gtk.Notebook()
            secondary_styles_box.append(style_notebook)

            def get_secondary_style_model(i):
                base_lb_model = LevelBarDisplayer.get_config_model()
                prefixed_lb_model = {}
                for section, options in base_lb_model.items():
                    if section in ["Level Bar Range"]: continue
                    prefixed_options = [ConfigOption(f"secondary{i}_{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for opt in options]
                    prefixed_lb_model[section] = prefixed_options

                return {
                    f"Item {i} Style": [
                        ConfigOption(f"secondary{i}_display_as", "dropdown", "Display As:", "text", options_dict={"Text": "text", "Level Bar": "level_bar"}),
                        ConfigOption(f"secondary{i}_label_color", "color", "Text Label Color:", "rgba(0,0,0,1)"),
                        ConfigOption(f"secondary{i}_value_color", "color", "Text Value Color:", "rgba(204,204,255,1)")
                    ],
                    **prefixed_lb_model
                }
            
            def build_secondary_style_tabs(spinner):
                count = spinner.get_value_as_int()
                # Clear old per-item style models
                dialog.dynamic_models = [m for m in dialog.dynamic_models if not any(opt.key.startswith("secondary") for s in m.values() for opt in s)]
                
                while style_notebook.get_n_pages() > count:
                    style_notebook.remove_page(-1)
                
                for i in range(1, count + 1):
                    if i > style_notebook.get_n_pages():
                        tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                        tab_scroll.set_child(tab_box)
                        style_notebook.append_page(tab_scroll, Gtk.Label(label=f"Item {i}"))
                        
                        style_model = get_secondary_style_model(i)
                        populate_defaults_from_model(panel_config, style_model)
                        build_ui_from_model(tab_box, panel_config, style_model, widgets)
                        dialog.dynamic_models.append(style_model)

                        # Logic to show/hide sections based on dropdown
                        display_as_combo = widgets[f"secondary{i}_display_as"]
                        text_widgets = [widgets[f"secondary{i}_label_color"].get_parent(), widgets[f"secondary{i}_value_color"].get_parent()]
                        
                        lb_widget_keys = [opt.key for section in style_model.values() for opt in section if "level_bar" in opt.key]
                        
                        # Find all parent containers for the level bar settings
                        lb_widgets = []
                        for key in lb_widget_keys:
                             if key in widgets and widgets[key].get_parent() and widgets[key].get_parent() not in lb_widgets:
                                 lb_widgets.append(widgets[key].get_parent())
                        # Also find the section headers and separators
                        all_children = list(tab_box)
                        for section_title in style_model.keys():
                            if "Level Bar" in section_title:
                                try:
                                    header = next(c for c in all_children if isinstance(c, Gtk.Label) and c.get_label() == f"<b>{section_title}</b>")
                                    sep = all_children[all_children.index(header) - 1]
                                    lb_widgets.extend([header, sep])
                                except (StopIteration, IndexError):
                                    pass


                        def update_visibility(combo):
                            is_bar = combo.get_active_id() == 'level_bar'
                            for w in text_widgets: w.set_visible(not is_bar)
                            for w in lb_widgets: w.set_visible(is_bar)

                        display_as_combo.connect("changed", update_visibility)
                        GLib.idle_add(update_visibility, display_as_combo)

            # Connect to the spinner on the Data Source tab
            sec_count_spinner = widgets.get("number_of_secondary_sources")
            if sec_count_spinner:
                sec_count_spinner.connect("value-changed", build_secondary_style_tabs)
                GLib.idle_add(build_secondary_style_tabs, sec_count_spinner)

        return build_display_ui

    def on_draw(self, area, ctx, width, height):
        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("lcars_color_bg", "rgba(0,0,0,1)"))
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
        ctx.paint()

        elbow_height = height * 0.2
        bar_height = height - elbow_height
        elbow_width = width * 0.3
        radius_factor = float(self.config.get("lcars_corner_radius_factor", 0.4))
        radius = elbow_height * radius_factor

        self._draw_elbow(ctx, 0, 0, elbow_width, elbow_height, radius)
        self._draw_horizontal_bar(ctx, elbow_width, 0, width - elbow_width, elbow_height)
        self._draw_side_panel(ctx, 0, elbow_height, elbow_width, bar_height)
        
        primary_data = self.data_bundle.get('primary_source', {})
        self._draw_primary_data(ctx, elbow_width, elbow_height, width - elbow_width, bar_height, primary_data)

        num_secondary = int(self.config.get("number_of_secondary_sources", 4))
        for i in range(1, num_secondary + 1):
            secondary_data = self.data_bundle.get(f"secondary{i}_source", {})
            self._draw_secondary_data(ctx, 0, elbow_height, elbow_width, bar_height, i, num_secondary, secondary_data)

    def _draw_elbow(self, ctx, x, y, w, h, r):
        elbow_color = Gdk.RGBA(); elbow_color.parse(self.config.get("lcars_color_elbow", "rgba(255,153,102,1)"))
        ctx.set_source_rgba(elbow_color.red, elbow_color.green, elbow_color.blue, elbow_color.alpha)
        ctx.new_path(); ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        ctx.line_to(x + w, y); ctx.line_to(x + w, y + h)
        ctx.line_to(x, y + h); ctx.line_to(x, y + r); ctx.close_path(); ctx.fill()

    def _draw_horizontal_bar(self, ctx, x, y, w, h):
        bar_color = Gdk.RGBA(); bar_color.parse(self.config.get("lcars_color_bar", "rgba(153,153,204,1)"))
        ctx.set_source_rgba(bar_color.red, bar_color.green, bar_color.blue, bar_color.alpha)
        ctx.rectangle(x, y, w, h); ctx.fill()

    def _draw_side_panel(self, ctx, x, y, w, h):
        bar_color = Gdk.RGBA(); bar_color.parse(self.config.get("lcars_color_bar", "rgba(153,153,204,1)"))
        ctx.set_source_rgba(bar_color.red, bar_color.green, bar_color.blue, bar_color.alpha)
        ctx.rectangle(x, y, w, h); ctx.fill()

    def _draw_primary_data(self, ctx, x, y, w, h, data):
        padding = w * 0.1
        label_text = data.get("primary_label", "N/A").upper()
        value_text = data.get("display_string", "-").upper()

        font_label = Pango.FontDescription.from_string(self.config.get("lcars_font_primary_label"))
        color_label = Gdk.RGBA(); color_label.parse(self.config.get("lcars_color_text_primary"))
        layout_label = self._create_pango_layout(ctx, label_text, font_label, color_label)
        _, log_label = layout_label.get_pixel_extents()
        ctx.move_to(x + padding, y + (h - log_label.height) / 2)
        PangoCairo.show_layout(ctx, layout_label)

        font_value = Pango.FontDescription.from_string(self.config.get("lcars_font_primary_value"))
        layout_value = self._create_pango_layout(ctx, value_text, font_value, color_label)
        _, log_value = layout_value.get_pixel_extents()
        ctx.move_to(x + w - log_value.width - padding, y + (h - log_value.height) / 2)
        PangoCairo.show_layout(ctx, layout_value)

    def _draw_secondary_data(self, ctx, x, y, w, h, index, total, data):
        if not data: return

        item_height = h / total; item_y = y + (index - 1) * item_height
        
        display_as = self.config.get(f"secondary{index}_display_as", "text")
        
        if display_as == "level_bar":
            self._draw_secondary_level_bar(ctx, x, item_y, w, item_height, index, data)
        else:
            self._draw_secondary_text(ctx, x, item_y, w, item_height, index, data)

    def _draw_secondary_text(self, ctx, x, y, w, h, index, data):
        padding_x = w * 0.1
        label_text = (self.config.get(f"secondary{index}_caption") or data.get("primary_label", f"ITEM {index}")).upper()
        value_text = data.get("display_string", "-").upper()
        font = Pango.FontDescription.from_string(self.config.get("lcars_font_secondary"))
        
        label_color_str = self.config.get(f"secondary{index}_label_color", "rgba(0,0,0,1)")
        value_color_str = self.config.get(f"secondary{index}_value_color", "rgba(204,204,255,1)")

        color_label = Gdk.RGBA(); color_label.parse(label_color_str)
        layout_label = self._create_pango_layout(ctx, label_text, font, color_label)
        _, log_label = layout_label.get_pixel_extents()
        ctx.move_to(x + padding_x, y + (h - log_label.height) / 2)
        PangoCairo.show_layout(ctx, layout_label)
        
        color_value = Gdk.RGBA(); color_value.parse(value_color_str)
        layout_value = self._create_pango_layout(ctx, value_text, font, color_value)
        _, log_value = layout_value.get_pixel_extents()
        ctx.move_to(x + w - log_value.width - padding_x, y + (h - log_value.height) / 2)
        PangoCairo.show_layout(ctx, layout_value)

    def _draw_secondary_level_bar(self, ctx, x, y, w, h, index, data):
        padding_x = w * 0.1; padding_y = h * 0.1
        bar_w, bar_h = w - 2 * padding_x, h - 2 * padding_y
        
        drawer_config = {}; populate_defaults_from_model(drawer_config, LevelBarDisplayer.get_config_model())
        
        prefix = f"secondary{index}_"
        for key, value in self.config.items():
            if key.startswith(prefix):
                drawer_config[key.replace(prefix, '')] = value
        
        drawer_config['level_min_value'] = data.get('min_value', 0.0)
        drawer_config['level_max_value'] = data.get('max_value', 100.0)
        
        self._level_bar_drawer.config = drawer_config
        self._level_bar_drawer._sync_state_with_config()

        self._level_bar_drawer.primary_text = self.config.get(f"secondary{index}_caption") or data.get("primary_label", '')
        self._level_bar_drawer.secondary_text = data.get('display_string', '')
        self._level_bar_drawer.current_value = data.get('numerical_value', 0.0)
        
        min_v, max_v = drawer_config['level_min_value'], drawer_config['level_max_value']
        v_range = max_v - min_v if max_v > min_v else 1
        num_segments = int(drawer_config.get("level_bar_segment_count", 30))
        val = self._level_bar_drawer.current_value
        self._level_bar_drawer.target_on_level = int(round(((min(max(val, min_v), max_v) - min_v) / v_range) * num_segments))
        self._level_bar_drawer.current_on_level = self._level_bar_drawer.target_on_level

        ctx.save(); ctx.translate(x + padding_x, y + padding_y)
        self._level_bar_drawer.on_draw(None, ctx, bar_w, bar_h)
        ctx.restore()

    def _create_pango_layout(self, ctx, text, font_desc, color):
        layout = PangoCairo.create_layout(ctx)
        layout.set_font_description(font_desc)
        layout.set_text(text, -1)
        ctx.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        return layout

    def close(self):
        if self._level_bar_drawer:
            self._level_bar_drawer.close()
            self._level_bar_drawer = None
        super().close()

