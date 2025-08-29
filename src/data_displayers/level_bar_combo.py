# data_displayers/lcars_combo.py
import gi
import math
import cairo
import os
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
        self._level_bar_drawer = LevelBarDisplayer(panel_ref, config)
        self._graph_drawer = GraphDisplayer(panel_ref, config)
        self._cached_primary_image = None
        self._cached_primary_image_path = None
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self._get_static_config_model())
        
    @staticmethod
    def get_config_model():
        return {}

    @staticmethod
    def _get_static_config_model():
        """Defines all style options with defaults to prevent crashes."""
        model = {
            "Frame Style": [
                ConfigOption("lcars_frame_style", "dropdown", "Frame Style:", "top_left", 
                             options_dict={"Top Left": "top_left", "Bottom Left": "bottom_left", "Both": "both"}),
                ConfigOption("lcars_v_bar_width", "spinner", "Vertical Bar Width (px):", 120, 20, 500, 5, 0),
                ConfigOption("lcars_h_bar_height", "spinner", "Horizontal Bar Height (px):", 30, 10, 200, 2, 0),
                ConfigOption("lcars_shoulder_radius", "spinner", "Shoulder Radius (px):", 60, 10, 500, 5, 0),
                ConfigOption("lcars_color_frame", "color", "Frame Color:", "rgba(255,153,102,1)"), # Peach
                ConfigOption("lcars_color_bg", "color", "Content BG Color:", "rgba(0,0,0,1)"),
            ],
            "Frame Segments": [
                ConfigOption("lcars_segment_count", "spinner", "Vertical Segments:", 4, 1, 12, 1, 0),
                ConfigOption("lcars_segment_font", "font", "Default Segment Font:", "Swiss 911 Ultra Compressed 16"),
                ConfigOption("lcars_segment_color", "color", "Default Segment Text Color:", "rgba(0,0,0,1)"),
            ],
            "Primary Display": [
                ConfigOption("primary_display_as", "dropdown", "Display Content Area As:", "secondary_items", 
                             options_dict={"Secondary Items List": "secondary_items", "Primary Source (Text)": "text", "Primary Source (Graph)": "graph", "Primary Source (Image)": "image"}),
                ConfigOption("lcars_secondary_layout", "dropdown", "Secondary Item Layout:", "vertical", 
                             options_dict={"Vertical List": "vertical", "Horizontal Row": "horizontal"}),
                ConfigOption("lcars_font_primary_label", "font", "Primary Label Font:", "Swiss 911 Ultra Compressed 18"),
                ConfigOption("lcars_font_primary_value", "font", "Primary Value Font:", "Swiss 911 Ultra Compressed 22"),
                ConfigOption("lcars_color_text_primary", "color", "Primary Text Color:", "rgba(255,204,153,1)"), # Light Peach
            ],
            "Default Secondary Font": [
                ConfigOption("lcars_font_secondary", "font", "Default Secondary Font:", "Swiss 911 Ultra Compressed 16")
            ]
        }
        # Add default segment configurations
        for i in range(1, 13):
            default_color = "rgba(255, 153, 102, 1)" if i % 2 == 0 else "rgba(204, 153, 255, 1)"
            model[f"Segment {i} Defaults"] = [
                ConfigOption(f"lcars_segment_{i}_label", "string", f"Label {i}:", f"0{i}-00000"),
                ConfigOption(f"lcars_segment_{i}_height_weight", "spinner", "Height Weight:", 1, 1, 10, 1, 0),
                ConfigOption(f"lcars_segment_{i}_bg_color", "color", "Segment BG Color:", default_color),
                ConfigOption(f"lcars_segment_{i}_text_bg_color", "color", "Text BG Color:", "rgba(0,0,0,1)"),
                ConfigOption(f"lcars_segment_{i}_show_break", "bool", "Show Break Line:", "True"),
            ]
        return model


    def get_configure_callback(self):
        """Builds the comprehensive UI for the Display tab."""
        def build_display_ui(dialog, content_box, widgets, available_sources, panel_config):
            static_model = self._get_static_config_model()
            dialog.dynamic_models.append(static_model)

            display_notebook = Gtk.Notebook()
            content_box.append(display_notebook)

            # --- Tab 1: Frame ---
            frame_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            frame_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            frame_scroll.set_child(frame_box)
            display_notebook.append_page(frame_scroll, Gtk.Label(label="Frame"))
            build_ui_from_model(frame_box, panel_config, {"Frame Style": static_model["Frame Style"], "Frame Segments": static_model["Frame Segments"]}, widgets)
            
            frame_box.append(Gtk.Separator(margin_top=10, margin_bottom=5))
            frame_box.append(Gtk.Label(label="<b>Segment Details</b>", use_markup=True, xalign=0))

            # Create a scrolled window for the segment notebook to live in
            segment_scrolled_window = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            segment_scrolled_window.set_min_content_height(250)
            segment_notebook = Gtk.Notebook()
            segment_scrolled_window.set_child(segment_notebook)
            frame_box.append(segment_scrolled_window)

            def build_segment_tabs(spinner):
                count = spinner.get_value_as_int()
                
                while segment_notebook.get_n_pages() > count:
                    segment_notebook.remove_page(-1)
                
                for i in range(1, count + 1):
                    if i > segment_notebook.get_n_pages():
                        tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
                        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=5, margin_bottom=5, margin_start=5, margin_end=5)
                        tab_scroll.set_child(tab_box)
                        segment_notebook.append_page(tab_scroll, Gtk.Label(label=f"Seg {i}"))

                        seg_model = {f"Segment {i}": static_model[f"Segment {i} Defaults"]}
                        build_ui_from_model(tab_box, panel_config, seg_model, widgets)
                        dialog.dynamic_models.append(seg_model)

            seg_count_spinner = widgets["lcars_segment_count"]
            seg_count_spinner.connect("value-changed", build_segment_tabs)
            GLib.idle_add(build_segment_tabs, seg_count_spinner)

            # --- Tab 2: Content Area ---
            primary_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            primary_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            primary_scroll.set_child(primary_box)
            display_notebook.append_page(primary_scroll, Gtk.Label(label="Content Area"))
            
            build_ui_from_model(primary_box, panel_config, {"Primary Display": static_model["Primary Display"]}, widgets)
            
            text_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            graph_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            image_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            secondary_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            primary_box.append(text_section); primary_box.append(graph_section); primary_box.append(image_section); primary_box.append(secondary_section)
            
            text_model = { "Text Style": [static_model["Primary Display"][i] for i in [2,3,4]] } # Fonts and color
            build_ui_from_model(text_section, panel_config, text_model, widgets)
            dialog.dynamic_models.append(text_model)
            
            graph_model = GraphDisplayer.get_config_model()
            prefixed_graph_model = {f"Primary {k}": [ConfigOption(f"primary_{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for opt in v] for k, v in graph_model.items()}
            build_ui_from_model(graph_section, panel_config, prefixed_graph_model, widgets)
            dialog.dynamic_models.append(prefixed_graph_model)
            
            build_background_config_ui(image_section, panel_config, widgets, dialog, prefix="primary_image_", title="Content Area Background Image")
            build_ui_from_model(secondary_section, panel_config, {"Default Secondary Font": static_model["Default Secondary Font"]}, widgets)


            def update_primary_visibility(combo):
                active = combo.get_active_id()
                text_section.set_visible(active in ["text", "image"])
                graph_section.set_visible(active == "graph")
                image_section.set_visible(active == "image")
                secondary_section.set_visible(active == "secondary_items")
                widgets["lcars_secondary_layout"].get_parent().set_visible(active == "secondary_items")

            
            primary_display_combo = widgets["primary_display_as"]
            primary_display_combo.connect("changed", update_primary_visibility)
            GLib.idle_add(update_primary_visibility, primary_display_combo)
            
            # --- Tab 3: Secondary Item Styles ---
            secondary_styles_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            secondary_styles_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            secondary_styles_scroll.set_child(secondary_styles_box)
            display_notebook.append_page(secondary_styles_scroll, Gtk.Label(label="Secondary Styles"))
            
            # Create a scrolled window for the secondary styles notebook
            style_scrolled_window = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            style_scrolled_window.set_min_content_height(250)
            style_notebook = Gtk.Notebook()
            style_scrolled_window.set_child(style_notebook)
            secondary_styles_box.append(style_scrolled_window)

            def get_secondary_style_model(i):
                base_lb_model = LevelBarDisplayer.get_config_model()
                prefixed_lb_model = {section: [ConfigOption(f"secondary{i}_{opt.key}", opt.type, opt.label, opt.default, opt.min_val, opt.max_val, opt.step, opt.digits, opt.options_dict, opt.tooltip, opt.file_filters) for opt in options] for section, options in base_lb_model.items() if section not in ["Level Bar Range"]}
                return {
                    f"Item {i} Style": [ ConfigOption(f"secondary{i}_display_as", "dropdown", "Display As:", "text", options_dict={"Text": "text", "Level Bar": "level_bar"}),
                                        ConfigOption(f"secondary{i}_label_color", "color", "Text Label Color:", "rgba(153,153,204,1)"),
                                        ConfigOption(f"secondary{i}_value_color", "color", "Text Value Color:", "rgba(255,204,153,1)")],
                    **prefixed_lb_model
                }
            
            def build_secondary_style_tabs(spinner):
                count = spinner.get_value_as_int()
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
                        
                        temp_widgets = {}
                        build_ui_from_model(tab_box, panel_config, style_model, temp_widgets)
                        widgets.update(temp_widgets)
                        
                        dialog.dynamic_models.append(style_model)

                        unprefixed_widgets = {key.replace(f"secondary{i}_", '', 1): widget for key, widget in temp_widgets.items() if key.startswith(f"secondary{i}_")}
                        lb_instance = LevelBarDisplayer(None, panel_config)
                        lb_callback = lb_instance.get_configure_callback()
                        if lb_callback:
                            lb_callback(dialog, tab_box, unprefixed_widgets, available_sources, panel_config)

                        display_as_combo = temp_widgets[f"secondary{i}_display_as"]
                        text_widgets = [temp_widgets[f"secondary{i}_label_color"].get_parent(), temp_widgets[f"secondary{i}_value_color"].get_parent()]
                        
                        lb_widgets = [widget.get_parent() for key, widget in temp_widgets.items() if key.startswith(f"secondary{i}_level_bar")]
                        
                        def update_visibility(combo, tw, lbw):
                            is_bar = combo.get_active_id() == 'level_bar'
                            for w in tw: w.set_visible(not is_bar)
                            for w in lbw: w.set_visible(is_bar)

                        display_as_combo.connect("changed", update_visibility, text_widgets, lb_widgets)
                        GLib.idle_add(update_visibility, display_as_combo, text_widgets, lb_widgets)

            sec_count_spinner = widgets.get("number_of_secondary_sources")
            if sec_count_spinner:
                sec_count_spinner.connect("value-changed", build_secondary_style_tabs)
                GLib.idle_add(build_secondary_style_tabs, sec_count_spinner)

        return build_display_ui

    def apply_styles(self):
        super().apply_styles()
        image_path = self.config.get("primary_image_background_image_path", "")
        if self._cached_primary_image_path != image_path:
            self._cached_primary_image_path = image_path
            self._cached_primary_image = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
        self.widget.queue_draw()


    def on_draw(self, area, ctx, width, height):
        frame_style = self.config.get("lcars_frame_style", "top_left")
        v_bar_w = float(self.config.get("lcars_v_bar_width", 100))
        h_bar_h = float(self.config.get("lcars_h_bar_height", 40))
        
        content_x, content_y = 0, 0
        content_w, content_h = width, height

        if frame_style in ["top_left", "bottom_left", "both"]:
            content_x = v_bar_w
            content_w -= v_bar_w
        if frame_style in ["top_left", "both"]:
            content_y = h_bar_h
            content_h -= h_bar_h
        if frame_style in ["bottom_left", "both"]:
            content_h -= h_bar_h

        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("lcars_color_bg", "rgba(0,0,0,1)"))
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
        ctx.rectangle(0, 0, width, height)
        ctx.paint()
        
        if frame_style in ["top_left", "both"]:
            self._draw_frame(ctx, width, height, "top")
        if frame_style in ["bottom_left", "both"]:
            self._draw_frame(ctx, width, height, "bottom")
            
        self._draw_content_area(ctx, content_x, content_y, content_w, content_h)

    def _draw_frame(self, ctx, width, height, position):
        v_bar_w = float(self.config.get("lcars_v_bar_width", 120))
        h_bar_h = float(self.config.get("lcars_h_bar_height", 30))
        shoulder_r = float(self.config.get("lcars_shoulder_radius", 60))
        
        frame_color = Gdk.RGBA(); frame_color.parse(self.config.get("lcars_color_frame", "rgba(255,153,102,1)"))
        ctx.set_source_rgba(frame_color.red, frame_color.green, frame_color.blue, frame_color.alpha)
        
        if position == "top":
            ctx.new_path()
            ctx.move_to(width, h_bar_h + (shoulder_r / 2)) # Start
            ctx.arc(width - (h_bar_h/2), h_bar_h/2, h_bar_h/2, 0, math.pi/2) # End cap
            ctx.line_to(shoulder_r, 0) # Top edge
            ctx.arc(shoulder_r, shoulder_r, shoulder_r, 3*math.pi/2, math.pi, True) # outer shoulder
            ctx.line_to(0, height) # Left edge
            ctx.line_to(v_bar_w, height) # bottom edge of v_bar
            ctx.line_to(v_bar_w, h_bar_h + shoulder_r) # inner v_bar
            ctx.arc(v_bar_w - shoulder_r, h_bar_h + shoulder_r, shoulder_r, 0, 3*math.pi/2, True) # inner shoulder
            ctx.line_to(width - (h_bar_h/2), h_bar_h) # bottom edge of h_bar
            ctx.arc(width - (h_bar_h/2), h_bar_h/2, h_bar_h/2, math.pi/2, 0, True)
            ctx.close_path()
            ctx.fill()
        else: # bottom
            ctx.new_path()
            ctx.move_to(width, height - h_bar_h - (shoulder_r / 2)) # Start
            ctx.arc(width - (h_bar_h/2), height - h_bar_h/2, h_bar_h/2, math.pi, 3*math.pi/2)
            ctx.line_to(shoulder_r, height - h_bar_h)
            ctx.arc(shoulder_r, height - shoulder_r, shoulder_r, 3*math.pi/2, math.pi, False)
            ctx.line_to(0, 0)
            ctx.line_to(v_bar_w, 0)
            ctx.line_to(v_bar_w, height - h_bar_h - shoulder_r)
            ctx.arc(v_bar_w - shoulder_r, height - h_bar_h - shoulder_r, shoulder_r, 0, 3*math.pi/2, False)
            ctx.line_to(width - (h_bar_h/2), height)
            ctx.arc(width-(h_bar_h/2), height-h_bar_h/2, h_bar_h/2, math.pi/2, math.pi)
            ctx.close_path()
            ctx.fill()
        
        self._draw_segments(ctx, height, position)

    def _draw_segments(self, ctx, height, position):
        v_bar_w = float(self.config.get("lcars_v_bar_width", 120))
        h_bar_h = float(self.config.get("lcars_h_bar_height", 30))
        num_segments = int(self.config.get("lcars_segment_count", 4))
        if num_segments == 0: return

        total_weight = sum(float(self.config.get(f"lcars_segment_{i+1}_height_weight", 1)) for i in range(num_segments))
        if total_weight == 0: total_weight = 1
            
        v_bar_total_h = height
        v_bar_y_start = 0
        frame_style = self.config.get("lcars_frame_style", "top_left")

        if frame_style == "both":
             v_bar_y_start = h_bar_h
             v_bar_total_h = height - 2 * h_bar_h
        elif frame_style == "top_left":
            v_bar_y_start = h_bar_h
            v_bar_total_h = height - h_bar_h
        elif frame_style == "bottom_left":
            v_bar_total_h = height - h_bar_h

        current_y = v_bar_y_start
        
        for i in range(1, num_segments + 1):
            weight = float(self.config.get(f"lcars_segment_{i}_height_weight", 1))
            segment_height = (weight / total_weight) * v_bar_total_h
            
            # --- FIX: Do not draw the first segment over the shoulder ---
            draw_y = current_y
            draw_h = segment_height
            if position == "top" and i == 1:
                draw_y = current_y + h_bar_h
                draw_h = segment_height - h_bar_h
            elif position == "bottom" and i == num_segments:
                 draw_h = segment_height - h_bar_h
            if draw_h <= 0:
                current_y += segment_height
                continue

            bg_color = Gdk.RGBA(); bg_color.parse(self.config.get(f"lcars_segment_{i}_bg_color"))
            ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
            ctx.rectangle(0, draw_y, v_bar_w, draw_h)
            ctx.fill()

            label = self.config.get(f"lcars_segment_{i}_label")
            font = Pango.FontDescription.from_string(self.config.get("lcars_segment_font"))
            text_color = Gdk.RGBA(); text_color.parse(self.config.get("lcars_segment_color"))
            text_bg_color = Gdk.RGBA(); text_bg_color.parse(self.config.get(f"lcars_segment_{i}_text_bg_color"))

            layout = self._create_pango_layout(ctx, label, font, text_color)
            _, log = layout.get_pixel_extents()
            
            text_bg_padding = 4
            text_bg_w, text_bg_h = log.width + 2 * text_bg_padding, log.height + 2 * text_bg_padding
            text_bg_x, text_bg_y = 5, current_y + (segment_height - text_bg_h) / 2

            ctx.set_source_rgba(text_bg_color.red, text_bg_color.green, text_bg_color.blue, text_bg_color.alpha)
            ctx.rectangle(text_bg_x, text_bg_y, text_bg_w, text_bg_h)
            ctx.fill()
            
            ctx.set_source_rgba(text_color.red, text_color.green, text_color.blue, text_color.alpha)
            ctx.move_to(text_bg_x + text_bg_padding, text_bg_y + text_bg_padding)
            PangoCairo.show_layout(ctx, layout)
            
            if str(self.config.get(f"lcars_segment_{i}_show_break", "True")).lower() == 'true' and i < num_segments:
                ctx.set_source_rgba(0,0,0,1) # Black break line
                ctx.set_line_width(2)
                ctx.move_to(0, current_y + segment_height)
                ctx.line_to(v_bar_w, current_y + segment_height)
                ctx.stroke()

            current_y += segment_height
            
    def _draw_content_area(self, ctx, x, y, w, h):
        display_as = self.config.get("primary_display_as", "secondary_items")
        
        if display_as == "secondary_items":
            num_secondary = int(self.config.get("number_of_secondary_sources", 4))
            if num_secondary == 0: return

            layout = self.config.get("lcars_secondary_layout", "vertical")
            item_x, item_y = x, y
            
            item_width = w
            item_height = h / num_secondary if layout == "vertical" and num_secondary > 0 else h
            if layout == "horizontal":
                item_width = w / num_secondary if num_secondary > 0 else w
                item_height = h

            for i in range(1, num_secondary + 1):
                secondary_data = self.data_bundle.get(f"secondary{i}_source", {})
                ctx.save(); ctx.rectangle(item_x, item_y, item_width, item_height); ctx.clip()
                self._draw_secondary_item(ctx, item_x, item_y, item_width, item_height, i, secondary_data)
                ctx.restore()
                if layout == "vertical": item_y += item_height
                else: item_x += item_width
        else:
            self._draw_primary_display(ctx, x, y, w, h, self.data_bundle.get('primary_source', {}))
             
    def _draw_primary_display(self, ctx, x, y, w, h, data):
        display_as = self.config.get("primary_display_as", "text")
        if display_as == "graph": self._draw_primary_graph(ctx, x, y, w, h, data)
        elif display_as == "image": self._draw_primary_image(ctx, x, y, w, h, data)
        else: self._draw_primary_text(ctx, x, y, w, h, data)

    def _draw_primary_text(self, ctx, x, y, w, h, data):
        padding = w * 0.05
        label_text = data.get("primary_label", "N/A").upper()
        value_text = data.get("display_string", "-").upper()

        font_label = Pango.FontDescription.from_string(self.config.get("lcars_font_primary_label"))
        color = Gdk.RGBA(); color.parse(self.config.get("lcars_color_text_primary"))
        layout_label = self._create_pango_layout(ctx, label_text, font_label, color)
        _, log_label = layout_label.get_pixel_extents()
        ctx.move_to(x + padding, y + (h - log_label.height) / 2)
        PangoCairo.show_layout(ctx, layout_label)

        font_value = Pango.FontDescription.from_string(self.config.get("lcars_font_primary_value"))
        layout_value = self._create_pango_layout(ctx, value_text, font_value, color)
        _, log_value = layout_value.get_pixel_extents()
        ctx.move_to(x + w - log_value.width - padding, y + (h - log_value.height) / 2)
        PangoCairo.show_layout(ctx, layout_value)

    def _draw_primary_graph(self, ctx, x, y, w, h, data):
        ctx.save(); ctx.rectangle(x,y,w,h); ctx.clip(); ctx.translate(x,y)
        drawer_config = {}; populate_defaults_from_model(drawer_config, GraphDisplayer.get_config_model())
        for key, value in self.config.items():
            if key.startswith("primary_"):
                drawer_config[key.replace("primary_", '')] = value
        self._graph_drawer.config = drawer_config
        self._graph_drawer.update_display(data.get("raw_data"))
        self._graph_drawer.on_draw_graph(None, ctx, w, h)
        ctx.restore()

    def _draw_primary_image(self, ctx, x, y, w, h, data):
        if self._cached_primary_image:
            ctx.save(); ctx.rectangle(x,y,w,h); ctx.clip()
            img_w, img_h = self._cached_primary_image.get_width(), self._cached_primary_image.get_height()
            scale = max(w/img_w, h/img_h)
            ctx.translate(x + w/2, y + h/2); ctx.scale(scale, scale); ctx.translate(-img_w/2, -img_h/2)
            Gdk.cairo_set_source_pixbuf(ctx, self._cached_primary_image, 0, 0)
            ctx.paint_with_alpha(float(self.config.get("primary_image_background_image_alpha", 1.0)))
            ctx.restore()
        self._draw_primary_text(ctx, x, y, w, h, data)

    def _draw_secondary_item(self, ctx, x, y, w, h, index, data):
        if not data: return
        display_as = self.config.get(f"secondary{index}_display_as", "text")
        if display_as == "level_bar": self._draw_secondary_level_bar(ctx, x, y, w, h, index, data)
        else: self._draw_secondary_text(ctx, x, y, w, h, index, data)

    def _draw_secondary_text(self, ctx, x, y, w, h, index, data):
        padding_x = w * 0.1
        label_text = (self.config.get(f"secondary{index}_caption") or data.get("primary_label", f"ITEM {index}")).upper()
        value_text = data.get("display_string", "-").upper()
        font = Pango.FontDescription.from_string(self.config.get("lcars_font_secondary"))
        
        label_color_str = self.config.get(f"secondary{index}_label_color", "rgba(153,153,204,1)")
        value_color_str = self.config.get(f"secondary{index}_value_color", "rgba(255,204,153,1)")

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
        padding_x = w * 0.05; padding_y = h * 0.1
        bar_w, bar_h = w - 2 * padding_x, h - 2 * padding_y
        if bar_w <=0 or bar_h <= 0: return
        
        drawer_config = {}; populate_defaults_from_model(drawer_config, LevelBarDisplayer.get_config_model())
        
        prefix = f"secondary{index}_"
        for key, value in self.config.items():
            if key.startswith(prefix):
                drawer_config[key.replace(prefix, '', 1)] = value
        
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
        if self._level_bar_drawer: self._level_bar_drawer.close(); self._level_bar_drawer = None
        if self._graph_drawer: self._graph_drawer.close(); self._graph_drawer = None
        super().close()

