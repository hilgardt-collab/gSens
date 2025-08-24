# data_displayers/combo.py
import gi
import math
import cairo
import re
import os
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class ComboDisplayer(DataDisplayer):
    """
    A complex, 3D-effect displayer with a central radial gauge and multiple
    concentric arcs, each representing a different data source. Arcs can share
    the same ring if their angles do not overlap.
    """
    def __init__(self, panel_ref, config):
        self.data_bundle = {}
        self._cached_center_pixbuf = None
        self._cached_image_path = None
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def update_display(self, value):
        if not self.panel_ref: return
        if isinstance(value, dict):
            self.data_bundle = value
        self.widget.queue_draw()

    @staticmethod
    def get_config_model():
        model = DataDisplayer.get_config_model()
        image_file_filters = [{"name": "Image Files", "patterns": ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.svg"]}, {"name": "All Files", "patterns": ["*"]}]
        
        model["Center Circle Style"] = [
            ConfigOption("center_bg_type", "dropdown", "Style:", "solid", 
                         options_dict={"Solid Color": "solid", "Linear Gradient": "gradient_linear", "Radial Gradient": "gradient_radial", "Image": "image"}),
            ConfigOption("center_bg_color", "color", "Solid Color:", "rgba(10,10,10,1)"),
            ConfigOption("center_gradient_linear_color1", "color", "Gradient Start Color:", "rgba(40,40,40,1)"),
            ConfigOption("center_gradient_linear_color2", "color", "Gradient End Color:", "rgba(10,10,10,1)"),
            ConfigOption("center_gradient_radial_color1", "color", "Gradient Center Color:", "rgba(40,40,40,1)"),
            ConfigOption("center_gradient_radial_color2", "color", "Gradient Edge Color:", "rgba(10,10,10,1)"),
            ConfigOption("center_bg_image_path", "file", "Image File:", "", file_filters=image_file_filters),
            ConfigOption("center_bg_image_alpha", "scale", "Image Opacity:", 1.0, 0.0, 1.0, 0.05, 2),
            ConfigOption("center_text_vertical_offset", "spinner", "V. Offset:", 0, -100, 100, 1, 0),
            ConfigOption("center_text_spacing", "spinner", "Text Spacing:", 2, 0, 50, 1, 0)
        ]
        model["Center Primary Text"] = [
            ConfigOption("center_show_primary_text", "bool", "Show Primary Text:", "True"),
            ConfigOption("center_primary_text_font", "font", "Primary Font:", "Sans 10"),
            ConfigOption("center_primary_text_color", "color", "Primary Color:", "rgba(200,200,200,1)")
        ]
        model["Center Secondary Text"] = [
            ConfigOption("center_show_secondary_text", "bool", "Show Secondary Text:", "True"),
            ConfigOption("center_secondary_text_font", "font", "Secondary Font:", "Sans Bold 18"),
            ConfigOption("center_secondary_text_color", "color", "Secondary Color:", "rgba(255,255,255,1)")
        ]
        model["Center Caption"] = [
            ConfigOption("center_caption_text", "string", "Caption Text:", ""),
            ConfigOption("center_caption_position", "dropdown", "Position:", "top", 
                         options_dict={"None": "none", "Top": "top", "Bottom": "bottom", "Left": "left", "Right": "right"}),
            ConfigOption("center_caption_font", "font", "Font:", "Sans 9"),
            ConfigOption("center_caption_color", "color", "Color:", "rgba(220,220,220,1)")
        ]
        return model

    def get_configure_callback(self):
        """
        Builds the UI for configuring the *appearance* of the arcs and center display.
        """
        def build_style_tabs(dialog, content_box, widgets, available_sources, panel_config):
            arc_count = int(panel_config.get("combo_arc_count", 5))

            display_notebook = Gtk.Notebook(margin_top=10)
            content_box.append(Gtk.Separator(margin_top=15, margin_bottom=5))
            content_box.append(Gtk.Label(label="<b>Display Appearance</b>", use_markup=True, xalign=0))
            content_box.append(display_notebook)

            # --- Center Appearance Tab ---
            center_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            center_scroll.set_child(center_box)
            display_notebook.append_page(center_scroll, Gtk.Label(label="Center"))
            
            center_model = {k: v for k, v in self.get_config_model().items() if k.startswith("Center")}
            build_ui_from_model(center_box, panel_config, center_model, widgets)
            
            bg_type_combo = widgets.get("center_bg_type")
            if bg_type_combo:
                solid_widgets = [widgets.get("center_bg_color").get_parent()]
                grad_lin_widgets = [widgets.get("center_gradient_linear_color1").get_parent(), widgets.get("center_gradient_linear_color2").get_parent()]
                grad_rad_widgets = [widgets.get("center_gradient_radial_color1").get_parent(), widgets.get("center_gradient_radial_color2").get_parent()]
                image_widgets = [widgets.get("center_bg_image_path").get_parent(), widgets.get("center_bg_image_alpha").get_parent()]
                
                def on_bg_type_changed(combo):
                    active_id = combo.get_active_id()
                    for w_list, visible in [(solid_widgets, active_id == "solid"), (grad_lin_widgets, active_id == "gradient_linear"), 
                                            (grad_rad_widgets, active_id == "gradient_radial"), (image_widgets, active_id == "image")]:
                        for w in w_list:
                            if w: w.set_visible(visible)
                
                bg_type_combo.connect("changed", on_bg_type_changed)
                on_bg_type_changed(bg_type_combo)

            # --- Arcs Appearance Tab ---
            arcs_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            arcs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
            arcs_scroll.set_child(arcs_box)
            display_notebook.append_page(arcs_scroll, Gtk.Label(label="Arcs"))
            
            style_notebook = Gtk.Notebook()
            arcs_box.append(style_notebook)

            def get_arc_style_model(i):
                return {
                    f"Arc {i} Style": [
                        ConfigOption(f"arc{i}_start_angle", "spinner", "Start Angle (deg):", -225, -360, 360, 5, 0),
                        ConfigOption(f"arc{i}_end_angle", "spinner", "End Angle (deg):", 45, -360, 360, 5, 0),
                        ConfigOption(f"arc{i}_bg_color", "color", "Background Color:", "rgba(40,40,40,0.5)"),
                        ConfigOption(f"arc{i}_fg_color", "color", "Foreground Color:", f"rgba({min(255, 50*i)}, {max(0, 255-i*20)}, 255, 1.0)"),
                        ConfigOption(f"arc{i}_width_factor", "scale", "Width (% of radius):", "0.1", 0.02, 0.2, 0.01, 2),
                        ConfigOption(f"arc{i}_label_position", "dropdown", "Label Position:", "start", 
                                     options_dict={"None": "none", "Start": "start", "Middle": "middle", "End": "end"}),
                        ConfigOption(f"arc{i}_label_content", "dropdown", "Label Content:", "caption",
                                     options_dict={"Caption Only": "caption", "Value Only": "value", "Caption and Value": "both"}),
                        ConfigOption(f"arc{i}_label_font", "font", "Label Font:", "Sans 8"),
                        ConfigOption(f"arc{i}_label_color", "color", "Label Color:", "rgba(200,200,200,1)")
                    ]
                }

            def build_arc_tabs(arc_count):
                while style_notebook.get_n_pages() > arc_count:
                    style_notebook.remove_page(-1)
                
                for i in range(1, arc_count + 1):
                    if i > style_notebook.get_n_pages():
                        tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
                        tab_scroll.set_min_content_height(300)
                        tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
                        tab_scroll.set_child(tab_box)
                        style_notebook.append_page(tab_scroll, Gtk.Label(label=f"Style {i}"))
                        
                        arc_model = get_arc_style_model(i)
                        populate_defaults_from_model(panel_config, arc_model)
                        build_ui_from_model(tab_box, panel_config, arc_model, widgets)
                        dialog.dynamic_models.append(arc_model)

            build_arc_tabs(arc_count)

            arc_count_spinner = widgets.get("combo_arc_count")
            if arc_count_spinner:
                arc_count_spinner.connect("value-changed", lambda spinner: build_arc_tabs(spinner.get_value_as_int()))

        return build_style_tabs

    def apply_styles(self):
        super().apply_styles()
        image_path = self.config.get("center_bg_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            self._cached_center_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
        self.widget.queue_draw()

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        cx, cy = width / 2, height / 2
        
        self._draw_center_gauge(ctx, cx, cy, width, height)

        rings = []
        all_arc_data = []
        
        num_arcs = int(self.config.get("combo_arc_count", 5))

        for i in range(1, num_arcs + 1):
            start_angle = float(self.config.get(f"arc{i}_start_angle", -225))
            end_angle = float(self.config.get(f"arc{i}_end_angle", 45))
            all_arc_data.append({ "index": i, "start": start_angle, "end": end_angle })

        for arc_data in all_arc_data:
            placed = False
            for ring in rings:
                is_overlapping = False
                for existing_arc in ring:
                    s1, e1 = (existing_arc["start"] % 360), (existing_arc["end"] % 360)
                    s2, e2 = (arc_data["start"] % 360), (arc_data["end"] % 360)
                    if s1 > e1: e1 += 360
                    if s2 > e2: e2 += 360
                    if max(s1, s2) < min(e1, e2):
                        is_overlapping = True; break
                if not is_overlapping:
                    ring.append(arc_data); placed = True; break
            if not placed:
                rings.append([arc_data])

        max_radius = min(width, height) / 2
        current_radius = max_radius * 0.45

        for ring in rings:
            max_width_factor_in_ring = max(float(self.config.get(f"arc{arc_info['index']}_width_factor", 0.1)) for arc_info in ring) if ring else 0
            max_arc_width_in_ring = max_radius * max_width_factor_in_ring
            draw_radius = current_radius + max_arc_width_in_ring / 2

            for arc_info in ring:
                i = arc_info["index"]
                arc_width = max_radius * float(self.config.get(f"arc{i}_width_factor", 0.1))
                prefix = f"arc{i}"
                source_key = f"{prefix}_source"
                data_bundle = self.data_bundle.get(source_key, {})
                data = data_bundle.get('data')
                
                label_content_type = self.config.get(f"arc{i}_label_content", "caption")
                caption = self.config.get(f"arc{i}_caption") or data_bundle.get('name', '')
                value_str = data_bundle.get('display_string', '')
                
                label_text = ""
                if label_content_type == "caption":
                    label_text = caption
                elif label_content_type == "value":
                    label_text = value_str
                elif label_content_type == "both":
                    label_text = f"{caption}: {value_str}"

                value = 0.0
                if self.panel_ref and hasattr(self.panel_ref.data_source, 'child_sources'):
                    child_source = self.panel_ref.data_source.child_sources.get(source_key)
                    if child_source:
                        value = child_source.get_numerical_value(data) if data is not None else 0.0
                value = value if isinstance(value, (int, float)) else 0.0
                min_v = float(self.config.get(f"{prefix}_graph_min_value", 0.0))
                max_v = float(self.config.get(f"{prefix}_graph_max_value", 100.0))
                v_range = max_v - min_v if max_v > min_v else 1
                percent = (value - min_v) / v_range if v_range > 0 else 0
                self._draw_arc(ctx, cx, cy, draw_radius, arc_width, percent, i, label_text)

            current_radius += max_arc_width_in_ring + (max_radius * 0.02)

    def _draw_center_gauge(self, ctx, cx, cy, width, height):
        radius = min(width, height) / 2 * 0.4
        if radius <= 0: return

        ctx.save()
        ctx.arc(cx, cy, radius, 0, 2 * math.pi); ctx.clip()
        bg_type = self.config.get("center_bg_type", "solid")
        
        if bg_type == "image" and self._cached_center_pixbuf:
            img_w, img_h = self._cached_center_pixbuf.get_width(), self._cached_center_pixbuf.get_height()
            scale = max((2*radius)/img_w, (2*radius)/img_h); ctx.save()
            ctx.translate(cx, cy); ctx.scale(scale, scale); ctx.translate(-img_w/2, -img_h/2)
            Gdk.cairo_set_source_pixbuf(ctx, self._cached_center_pixbuf, 0, 0)
            ctx.paint_with_alpha(float(self.config.get("center_bg_image_alpha", 1.0))); ctx.restore()
        elif bg_type == "gradient_linear":
            c1=Gdk.RGBA(); c1.parse(self.config.get("center_gradient_linear_color1")); c2=Gdk.RGBA(); c2.parse(self.config.get("center_gradient_linear_color2"))
            pat = cairo.LinearGradient(cx - radius, cy, cx + radius, cy)
            pat.add_color_stop_rgba(0, c1.red,c1.green,c1.blue,c1.alpha); pat.add_color_stop_rgba(1, c2.red,c2.green,c2.blue,c2.alpha)
            ctx.set_source(pat); ctx.paint()
        elif bg_type == "gradient_radial":
            c1=Gdk.RGBA(); c1.parse(self.config.get("center_gradient_radial_color1")); c2=Gdk.RGBA(); c2.parse(self.config.get("center_gradient_radial_color2"))
            pat = cairo.RadialGradient(cx, cy, 0, cx, cy, radius)
            pat.add_color_stop_rgba(0, c1.red,c1.green,c1.blue,c1.alpha); pat.add_color_stop_rgba(1, c2.red,c2.green,c2.blue,c2.alpha)
            ctx.set_source(pat); ctx.paint()
        else:
            bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("center_bg_color")); ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha); ctx.paint()
        ctx.restore()

        self._draw_center_caption(ctx, cx, cy, radius)

        center_data_bundle = self.data_bundle.get('center_source', {})
        center_data = center_data_bundle.get('data')
        primary_text, display_string = "", "N/A"
        center_source_type = self.config.get("center_source")

        if center_data is not None and self.panel_ref and hasattr(self.panel_ref.data_source, 'child_sources'):
            center_source = self.panel_ref.data_source.child_sources.get('center_source')
            if center_source:
                if center_source_type == 'analog_clock':
                    primary_text = center_source.get_display_string(center_data)
                    display_string = center_source.get_secondary_display_string(center_data)
                else:
                    primary_text = center_source.get_primary_label_string(center_data)
                    display_string = center_source.get_display_string(center_data)

        value_text, unit_text = "N/A", ""
        if display_string and display_string != "N/A":
            match = re.match(r'\s*([+-]?\d+\.?\d*)\s*(.*)', display_string)
            if match:
                value_text, unit_text = match.group(1), match.group(2).strip()
            else:
                value_text = display_string

        show_primary = str(self.config.get("center_show_primary_text", "True")).lower() == 'true'
        show_secondary = str(self.config.get("center_show_secondary_text", "True")).lower() == 'true'
        
        layout_p, log_p = (PangoCairo.create_layout(ctx), None) if show_primary else (None, None)
        if layout_p:
            layout_p.set_font_description(Pango.FontDescription.from_string(self.config.get("center_primary_text_font")))
            layout_p.set_text(primary_text, -1); _, log_p = layout_p.get_pixel_extents()

        layout_s, log_s = (PangoCairo.create_layout(ctx), None) if show_secondary else (None, None)
        if layout_s:
            layout_s.set_font_description(Pango.FontDescription.from_string(self.config.get("center_secondary_text_font")))
            layout_s.set_text(value_text, -1); _, log_s = layout_s.get_pixel_extents()
        
        layout_u, log_u = (PangoCairo.create_layout(ctx), None) if show_secondary and unit_text else (None, None)
        if layout_u:
            layout_u.set_font_description(Pango.FontDescription.from_string(self.config.get("center_primary_text_font")))
            layout_u.set_text(unit_text, -1); _, log_u = layout_u.get_pixel_extents()

        spacing = float(self.config.get("center_text_spacing", 2))
        v_offset = float(self.config.get("center_text_vertical_offset", 0))
        
        total_h = 0
        if show_primary and log_p: total_h += log_p.height
        if show_secondary and log_s: total_h += log_s.height
        if show_secondary and unit_text and log_u: total_h += log_u.height
        if show_primary and show_secondary: total_h += spacing
        if show_secondary and unit_text: total_h += spacing

        current_y = (cy - total_h / 2) + v_offset

        if show_primary and layout_p and log_p:
            color_p = Gdk.RGBA(); color_p.parse(self.config.get("center_primary_text_color"))
            ctx.set_source_rgba(color_p.red, color_p.green, color_p.blue, color_p.alpha)
            ctx.move_to(cx - log_p.width / 2, current_y); PangoCairo.show_layout(ctx, layout_p)
            current_y += log_p.height + spacing
        
        if show_secondary and layout_s and log_s:
            color_s = Gdk.RGBA(); color_s.parse(self.config.get("center_secondary_text_color"))
            ctx.set_source_rgba(color_s.red, color_s.green, color_s.blue, color_s.alpha)
            ctx.move_to(cx - log_s.width / 2, current_y); PangoCairo.show_layout(ctx, layout_s)
            current_y += log_s.height + spacing

        if show_secondary and layout_u and log_u:
            color_u = Gdk.RGBA(); color_u.parse(self.config.get("center_primary_text_color"))
            ctx.set_source_rgba(color_u.red, color_u.green, color_u.blue, color_u.alpha)
            ctx.move_to(cx - log_u.width / 2, current_y); PangoCairo.show_layout(ctx, layout_u)

    def _draw_center_caption(self, ctx, cx, cy, radius):
        text = self.config.get("center_caption_text")
        pos = self.config.get("center_caption_position")
        if not text or pos == "none":
            return
        
        font_desc = Pango.FontDescription.from_string(self.config.get("center_caption_font"))
        rgba = Gdk.RGBA(); rgba.parse(self.config.get("center_caption_color"))
        ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        
        layout = PangoCairo.create_layout(ctx); layout.set_font_description(font_desc)
        
        char_widths = []
        for char in text:
            layout.set_text(char, -1); _, log = layout.get_pixel_extents()
            char_widths.append(log.width)
        
        text_radius = radius * 0.85
        total_width_pixels = sum(char_widths)
        total_text_angular_width = total_width_pixels / text_radius if text_radius > 0 else 0
        
        angle_map = {"top": -math.pi/2, "bottom": math.pi/2, "left": math.pi, "right": 0}
        start_angle = angle_map.get(pos, -math.pi/2) - (total_text_angular_width / 2.0)
        
        ctx.save(); ctx.translate(cx, cy)
        text_angle = start_angle
        for i, char in enumerate(text):
            layout.set_text(char, -1); _, log = layout.get_pixel_extents()
            char_width = char_widths[i]
            char_angle = char_width / radius if radius > 0 else 0
            rotation_angle = text_angle + (char_angle / 2.0)
            ctx.save()
            ctx.rotate(rotation_angle); ctx.translate(text_radius, 0); ctx.rotate(math.pi / 2)
            ctx.move_to(-log.width / 2.0, -log.height / 2.0)
            PangoCairo.show_layout(ctx, layout)
            ctx.restore()
            text_angle += char_angle
        ctx.restore()

    def _draw_arc(self, ctx, cx, cy, radius, width, percent, index, label_text):
        start_angle = math.radians(float(self.config.get(f"arc{index}_start_angle", -225)))
        end_angle = math.radians(float(self.config.get(f"arc{index}_end_angle", 45)))
        total_angle = end_angle - start_angle
        if total_angle <= 0: total_angle += 2 * math.pi
        
        ctx.new_path()
        bg_color_str = self.config.get(f"arc{index}_bg_color", "rgba(40,40,40,0.5)")
        bg_color = Gdk.RGBA(); bg_color.parse(bg_color_str)
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
        ctx.set_line_width(width); ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.arc(cx, cy, radius, start_angle, end_angle); ctx.stroke()
        
        if percent > 0:
            ctx.new_path()
            fg_color_str = self.config.get(f"arc{index}_fg_color", f"rgba({min(255, 50*index)}, {max(0, 255-index*20)}, 255, 1.0)")
            fg_color = Gdk.RGBA(); fg_color.parse(fg_color_str)
            ctx.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, fg_color.alpha)
            
            fill_direction = self.config.get(f"arc{index}_fill_direction", "start")
            if fill_direction == "end":
                ctx.arc_negative(cx, cy, radius, end_angle, end_angle - total_angle * min(1.0, percent))
            else:
                ctx.arc(cx, cy, radius, start_angle, start_angle + total_angle * min(1.0, percent))
            ctx.stroke()

        label_pos = self.config.get(f"arc{index}_label_position", "start")
        if label_pos != "none" and label_text:
            self._draw_text_on_arc(ctx, cx, cy, radius, width, label_text, index, start_angle, total_angle)

    def _draw_text_on_arc(self, ctx, cx, cy, radius, arc_width, text, index, start_angle, total_angle):
        font_desc = Pango.FontDescription.from_string(self.config.get(f"arc{index}_label_font", "Sans 8"))
        rgba = Gdk.RGBA(); rgba.parse(self.config.get(f"arc{index}_label_color", "rgba(200,200,200,1)"))
        ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        
        pos = self.config.get(f"arc{index}_label_position")
        layout = PangoCairo.create_layout(ctx); layout.set_font_description(font_desc)
        
        char_widths = []
        for char in text:
            layout.set_text(char, -1)
            _, log = layout.get_pixel_extents()
            char_widths.append(log.width)
        
        total_width_pixels = sum(char_widths)
        total_text_angular_width = total_width_pixels / radius if radius > 0 else 0
        
        if pos == 'middle': text_angle = start_angle + (total_angle - total_text_angular_width) / 2.0
        elif pos == 'end': text_angle = start_angle + total_angle - total_text_angular_width
        else: text_angle = start_angle

        ctx.save(); ctx.translate(cx, cy)
        for i, char in enumerate(text):
            layout.set_text(char, -1); _, log = layout.get_pixel_extents()
            char_width = char_widths[i]
            char_angle = char_width / radius if radius > 0 else 0
            rotation_angle = text_angle + (char_angle / 2.0)
            ctx.save()
            ctx.rotate(rotation_angle); ctx.translate(radius, 0); ctx.rotate(math.pi / 2)
            ctx.move_to(-log.width / 2.0, -log.height / 2.0)
            PangoCairo.show_layout(ctx, layout)
            ctx.restore()
            text_angle += char_angle
        ctx.restore()
