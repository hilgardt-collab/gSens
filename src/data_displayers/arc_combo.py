# data_displayers/arc_combo.py
import gi
import math
import cairo
import re
import os
from .combo_base import ComboBase
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from utils import populate_defaults_from_model
from ui_helpers import build_background_config_ui

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class ArcComboDisplayer(ComboBase):
    """
    A complex, 3D-effect displayer with a central radial gauge and multiple
    concentric arcs, each representing a different data source. Arcs can share
    the same ring if their angles do not overlap.
    """
    def __init__(self, panel_ref, config):
        self._cached_center_pixbuf = None
        self._cached_image_path = None
        self._animation_timer_id = None
        self._arc_values = {}
        
        # Caching state
        self._static_surface = None
        self._last_draw_width, self._last_draw_height = -1, -1

        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self._get_static_config_model())

        self.widget.connect("realize", self._start_animation_timer)
        self.widget.connect("unrealize", self._stop_animation_timer)

    def update_display(self, value):
        super().update_display(value)

        num_arcs = int(self.config.get("combo_arc_count", 5))
        for i in range(1, num_arcs + 1):
            arc_key = f"arc{i}"; source_key = f"{arc_key}_source"
            if arc_key not in self._arc_values:
                self._arc_values[arc_key] = {'current': 0.0, 'target': 0.0, 'first_update': True}
            new_value = 0.0
            data_packet = self.data_bundle.get(source_key, {})
            num_val = data_packet.get('numerical_value')
            if isinstance(num_val, (int, float)): new_value = num_val
            if self._arc_values[arc_key]['first_update']:
                self._arc_values[arc_key]['current'] = new_value; self._arc_values[arc_key]['first_update'] = False
            self._arc_values[arc_key]['target'] = new_value

    def reset_state(self):
        self._arc_values.clear()
        super().reset_state()

    @staticmethod
    def get_config_model():
        return {}
    
    @staticmethod
    def _get_static_config_model():
        return {
            "Overall Layout": [ ConfigOption("combo_vertical_offset", "spinner", "Vertical Offset (px):", 0, -200, 200, 1, 0), ConfigOption("combo_scale_factor", "scale", "Manual Scale:", 1.0, 0.5, 2.0, 0.05, 2) ],
            "Center Circle Text": [ ConfigOption("center_text_vertical_offset", "spinner", "V. Offset:", 0, -100, 100, 1, 0), ConfigOption("center_text_spacing", "spinner", "Text Spacing:", 2, 0, 50, 1, 0) ],
            "Center Primary Text": [ ConfigOption("center_show_primary_text", "bool", "Show Primary Text:", "True"), ConfigOption("center_primary_text_font", "font", "Primary Font:", "Sans 10"), ConfigOption("center_primary_text_color", "color", "Primary Color:", "rgba(200,200,200,1)") ],
            "Center Secondary Text": [ ConfigOption("center_show_secondary_text", "bool", "Show Secondary Text:", "True"), ConfigOption("center_secondary_text_font", "font", "Secondary Font:", "Sans Bold 18"), ConfigOption("center_secondary_text_color", "color", "Secondary Color:", "rgba(255,255,255,1)") ],
            "Center Caption": [ ConfigOption("center_caption_text", "string", "Caption Text:", ""), ConfigOption("center_caption_position", "dropdown", "Position:", "top", options_dict={"None": "none", "Top": "top", "Bottom": "bottom", "Left": "left", "Right": "right"}), ConfigOption("center_caption_font", "font", "Font:", "Sans 9"), ConfigOption("center_caption_color", "color", "Color:", "rgba(220,220,220,1)") ],
            "Animation": [ ConfigOption("combo_animation_enabled", "bool", "Enable Arc Animation:", "True") ]
        }

    def get_configure_callback(self):
        def build_style_tabs(dialog, content_box, widgets, available_sources, panel_config):
            full_model = self._get_static_config_model(); dialog.dynamic_models.append(full_model)
            display_notebook = Gtk.Notebook(margin_top=10); content_box.append(Gtk.Label(label="<b>Display Appearance</b>", use_markup=True, xalign=0, margin_top=5)); content_box.append(display_notebook)
            layout_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True); layout_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); layout_scroll.set_child(layout_box); display_notebook.append_page(layout_scroll, Gtk.Label(label="Layout"))
            build_ui_from_model(layout_box, panel_config, {"Overall Layout": full_model["Overall Layout"], "Animation": full_model["Animation"]}, widgets)
            center_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True); center_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); center_scroll.set_child(center_box); display_notebook.append_page(center_scroll, Gtk.Label(label="Center"))
            build_background_config_ui(center_box, panel_config, widgets, dialog, prefix="center_", title="Center Circle Background"); center_model = {k: v for k, v in full_model.items() if k.startswith("Center")}; build_ui_from_model(center_box, panel_config, center_model, widgets)
            arcs_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True); arcs_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); arcs_scroll.set_child(arcs_box); display_notebook.append_page(arcs_scroll, Gtk.Label(label="Arcs"))
            style_notebook = Gtk.Notebook(); arcs_box.append(style_notebook)
            def get_arc_style_model(i): return { f"Arc {i} Style": [ ConfigOption(f"arc{i}_start_angle", "spinner", "Start Angle (deg):", -225, -360, 360, 5, 0), ConfigOption(f"arc{i}_end_angle", "spinner", "End Angle (deg):", 45, -360, 360, 5, 0), ConfigOption(f"arc{i}_fill_direction", "dropdown", "Fill Direction:", "start", options_dict={"From Start": "start", "From End": "end"}), ConfigOption(f"arc{i}_bg_color", "color", "Background Color:", "rgba(40,40,40,0.5)"), ConfigOption(f"arc{i}_fg_color", "color", "Foreground Color:", f"rgba({min(255, 50*i)}, {max(0, 255-i*20)}, 255, 1.0)"), ConfigOption(f"arc{i}_width_factor", "scale", "Width (% of radius):", "0.1", 0.02, 0.2, 0.01, 2), ConfigOption(f"arc{i}_label_position", "dropdown", "Label Position:", "start", options_dict={"None": "none", "Start": "start", "Middle": "middle", "End": "end"}), ConfigOption(f"arc{i}_label_content", "dropdown", "Label Content:", "caption", options_dict={"Caption Only": "caption", "Value Only": "value", "Caption and Value": "both"}), ConfigOption(f"arc{i}_label_font", "font", "Font:", "Sans 8"), ConfigOption(f"arc{i}_label_color", "color", "Label Color:", "rgba(200,200,200,1)") ] }
            def build_arc_tabs(spinner):
                arc_count = spinner.get_value_as_int(); 
                while style_notebook.get_n_pages() > arc_count: style_notebook.remove_page(-1)
                for i in range(1, arc_count + 1):
                    if i > style_notebook.get_n_pages():
                        tab_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True); tab_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10); tab_scroll.set_child(tab_box); style_notebook.append_page(tab_scroll, Gtk.Label(label=f"Style {i}"))
                        arc_model = get_arc_style_model(i); populate_defaults_from_model(panel_config, arc_model); build_ui_from_model(tab_box, panel_config, arc_model, widgets); dialog.dynamic_models.append(arc_model)
            arc_count_spinner = widgets.get("combo_arc_count")
            if arc_count_spinner: arc_count_spinner.connect("value-changed", build_arc_tabs); GLib.idle_add(build_arc_tabs, arc_count_spinner)
        return build_style_tabs

    def apply_styles(self):
        super().apply_styles()
        image_path = self.config.get("center_background_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            self._cached_center_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
        self._static_surface = None
        self.widget.queue_draw()

    def _start_animation_timer(self, widget=None):
        self._stop_animation_timer()
        self._animation_timer_id = GLib.timeout_add(16, self._animation_tick)

    def _stop_animation_timer(self, widget=None):
        if self._animation_timer_id is not None:
            GLib.source_remove(self._animation_timer_id)
            self._animation_timer_id = None

    def _animation_tick(self):
        if not self.widget.get_realized(): self._animation_timer_id = None; return GLib.SOURCE_REMOVE
        animation_enabled = str(self.config.get("combo_animation_enabled", "True")).lower() == 'true'
        needs_redraw = False
        if not animation_enabled:
            for arc_key, values in self._arc_values.items():
                if values['current'] != values['target']: values['current'] = values['target']; needs_redraw = True
        else:
            for arc_key, values in self._arc_values.items():
                diff = values['target'] - values['current']
                if abs(diff) < 0.01:
                    if values['current'] != values['target']: values['current'] = values['target']; needs_redraw = True
                    continue
                values['current'] += diff * 0.1; needs_redraw = True
        if needs_redraw: self.widget.queue_draw()
        return GLib.SOURCE_CONTINUE

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return

        v_offset = float(self.config.get("combo_vertical_offset", 0))
        scale_factor = float(self.config.get("combo_scale_factor", 1.0))
        cx, cy = width / 2, (height / 2) + v_offset
        max_radius = ((min(width, height) / 2) * 0.90) * scale_factor
        if max_radius <= 0: return

        rings = []; all_arc_data = []
        num_arcs = int(self.config.get("combo_arc_count", 5))
        for i in range(1, num_arcs + 1):
            all_arc_data.append({ "index": i, "start": float(self.config.get(f"arc{i}_start_angle", -225)), "end": float(self.config.get(f"arc{i}_end_angle", 45)) })
        for arc_data in all_arc_data:
            placed = False
            for ring in rings:
                is_overlapping = False
                for existing_arc in ring:
                    s1, e1 = (existing_arc["start"] % 360), (existing_arc["end"] % 360)
                    s2, e2 = (arc_data["start"] % 360), (arc_data["end"] % 360)
                    if s1 > e1: e1 += 360
                    if s2 > e2: e2 += 360
                    if max(s1, s2) < min(e1, e2): is_overlapping = True; break
                if not is_overlapping: ring.append(arc_data); placed = True; break
            if not placed: rings.append([arc_data])

        if not self._static_surface or self._last_draw_width != width or self._last_draw_height != height:
            self._static_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            static_ctx = cairo.Context(self._static_surface)
            self._draw_center_gauge(static_ctx, cx, cy, max_radius, static_only=True)
            current_radius = max_radius * 0.45
            for ring in rings:
                max_width_factor_in_ring = max(float(self.config.get(f"arc{arc_info['index']}_width_factor", 0.1)) for arc_info in ring) if ring else 0
                max_arc_width_in_ring = max_radius * max_width_factor_in_ring
                draw_radius = current_radius + max_arc_width_in_ring / 2
                for arc_info in ring:
                    i = arc_info["index"]
                    arc_width = max_radius * float(self.config.get(f"arc{i}_width_factor", 0.1))
                    self._draw_arc(static_ctx, cx, cy, draw_radius, arc_width, 0, i, "", static_only=True)
                current_radius += max_arc_width_in_ring + (max_radius * 0.02)
            self._last_draw_width, self._last_draw_height = width, height

        ctx.set_source_surface(self._static_surface, 0, 0); ctx.paint()
        self._draw_center_gauge(ctx, cx, cy, max_radius, dynamic_only=True)
        
        current_radius = max_radius * 0.45
        for ring in rings:
            max_width_factor_in_ring = max(float(self.config.get(f"arc{arc_info['index']}_width_factor", 0.1)) for arc_info in ring) if ring else 0
            max_arc_width_in_ring = max_radius * max_width_factor_in_ring
            draw_radius = current_radius + max_arc_width_in_ring / 2
            for arc_info in ring:
                i = arc_info["index"]
                arc_width = max_radius * float(self.config.get(f"arc{i}_width_factor", 0.1))
                source_key = f"arc{i}_source"; data_packet = self.data_bundle.get(source_key, {})
                value = self._arc_values.get(f"arc{i}", {}).get('current', 0.0)
                min_v, max_v = data_packet.get('min_value', 0.0), data_packet.get('max_value', 100.0)
                v_range = max_v - min_v if max_v > min_v else 1
                percent = (value - min_v) / v_range if v_range > 0 else 0
                self._draw_arc(ctx, cx, cy, draw_radius, arc_width, percent, i, "", dynamic_only=True)
            current_radius += max_arc_width_in_ring + (max_radius * 0.02)

        # --- BUG FIX: Draw all text labels last, on top of everything else ---
        current_radius = max_radius * 0.45
        for ring in rings:
            max_width_factor_in_ring = max(float(self.config.get(f"arc{arc_info['index']}_width_factor", 0.1)) for arc_info in ring) if ring else 0
            max_arc_width_in_ring = max_radius * max_width_factor_in_ring
            draw_radius = current_radius + max_arc_width_in_ring / 2
            for arc_info in ring:
                i = arc_info["index"]
                arc_width = max_radius * float(self.config.get(f"arc{i}_width_factor", 0.1))
                source_key = f"arc{i}_source"; data_packet = self.data_bundle.get(source_key, {})
                label_content_type = self.config.get(f"arc{i}_label_content", "caption")
                caption = self.config.get(f"arc{i}_caption") or data_packet.get('primary_label', '')
                value_str = data_packet.get('display_string', '')
                label_text = f"{caption}: {value_str}" if label_content_type == "both" else value_str if label_content_type == "value" else caption
                self._draw_arc(ctx, cx, cy, draw_radius, arc_width, 0, i, label_text, text_only=True)
            current_radius += max_arc_width_in_ring + (max_radius * 0.02)


    def _draw_center_gauge(self, ctx, cx, cy, available_radius, static_only=False, dynamic_only=False):
        radius = available_radius * 0.4
        if radius <= 0: return

        if not dynamic_only:
            ctx.save(); ctx.arc(cx, cy, radius, 0, 2 * math.pi); ctx.clip()
            bg_type = self.config.get("center_bg_type", "solid")
            if bg_type == "image" and self._cached_center_pixbuf:
                img_w, img_h = self._cached_center_pixbuf.get_width(), self._cached_center_pixbuf.get_height()
                scale = max((2*radius)/img_w, (2*radius)/img_h); ctx.save()
                ctx.translate(cx, cy); ctx.scale(scale, scale); ctx.translate(-img_w/2, -img_h/2)
                Gdk.cairo_set_source_pixbuf(ctx, self._cached_center_pixbuf, 0, 0)
                ctx.paint_with_alpha(float(self.config.get("center_background_image_alpha", 1.0))); ctx.restore()
            elif bg_type == "gradient_linear":
                c1=Gdk.RGBA(); c1.parse(self.config.get("center_gradient_linear_color1")); c2=Gdk.RGBA(); c2.parse(self.config.get("center_gradient_linear_color2"))
                angle = float(self.config.get("center_gradient_linear_angle_deg", 90.0)); angle_rad = angle * math.pi / 180
                x1, y1, x2, y2 = cx - radius * math.cos(angle_rad), cy - radius * math.sin(angle_rad), cx + radius * math.cos(angle_rad), cy + radius * math.sin(angle_rad)
                pat = cairo.LinearGradient(x1, y1, x2, y2); pat.add_color_stop_rgba(0, c1.red,c1.green,c1.blue,c1.alpha); pat.add_color_stop_rgba(1, c2.red,c2.green,c2.blue,c2.alpha)
                ctx.set_source(pat); ctx.paint()
            elif bg_type == "gradient_radial":
                c1=Gdk.RGBA(); c1.parse(self.config.get("center_gradient_radial_color1")); c2=Gdk.RGBA(); c2.parse(self.config.get("center_gradient_radial_color2"))
                pat = cairo.RadialGradient(cx, cy, 0, cx, cy, radius); pat.add_color_stop_rgba(0, c1.red,c1.green,c1.blue,c1.alpha); pat.add_color_stop_rgba(1, c2.red,c2.green,c2.blue,c2.alpha)
                ctx.set_source(pat); ctx.paint()
            else:
                bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("center_bg_color", "rgba(40,40,40,1)")); ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha); ctx.paint()
            ctx.restore()
            self._draw_center_caption(ctx, cx, cy, radius)

        if not static_only:
            center_data_packet = self.data_bundle.get('center_source', {}); primary_text = center_data_packet.get('primary_label', ''); display_string = center_data_packet.get('display_string', 'N/A')
            value_text, unit_text = ("N/A", "")
            if ":" in display_string: value_text = display_string
            else:
                if display_string and display_string != "N/A":
                    match = re.match(r'\s*([+-]?\d+\.?\d*)\s*(.*)', display_string)
                    if match: value_text, unit_text = match.group(1), match.group(2).strip()
                    else: value_text = display_string
            show_primary = str(self.config.get("center_show_primary_text", "True")).lower() == 'true'
            show_secondary = str(self.config.get("center_show_secondary_text", "True")).lower() == 'true'
            layout_p, log_p = (PangoCairo.create_layout(ctx), None) if show_primary and primary_text else (None, None)
            if layout_p: layout_p.set_font_description(Pango.FontDescription.from_string(self.config.get("center_primary_text_font"))); layout_p.set_text(primary_text, -1); _, log_p = layout_p.get_pixel_extents()
            layout_s, log_s = (PangoCairo.create_layout(ctx), None) if show_secondary else (None, None)
            if layout_s: layout_s.set_font_description(Pango.FontDescription.from_string(self.config.get("center_secondary_text_font"))); layout_s.set_text(value_text, -1); _, log_s = layout_s.get_pixel_extents()
            layout_u, log_u = (PangoCairo.create_layout(ctx), None) if show_secondary and unit_text else (None, None)
            if layout_u: layout_u.set_font_description(Pango.FontDescription.from_string(self.config.get("center_primary_text_font"))); layout_u.set_text(unit_text, -1); _, log_u = layout_u.get_pixel_extents()
            spacing, v_offset = float(self.config.get("center_text_spacing", 2)), float(self.config.get("center_text_vertical_offset", 0))
            total_h = sum(filter(None, [log_p.height if log_p else 0, log_s.height if log_s else 0, log_u.height if log_u else 0])); 
            if log_p and (log_s or log_u): total_h += spacing
            if log_s and log_u: total_h += spacing
            current_y = (cy - total_h / 2) + v_offset
            if layout_p: color_p = Gdk.RGBA(); color_p.parse(self.config.get("center_primary_text_color")); ctx.set_source_rgba(color_p.red, color_p.green, color_p.blue, color_p.alpha); ctx.move_to(cx - log_p.width / 2, current_y); PangoCairo.show_layout(ctx, layout_p); current_y += log_p.height + spacing
            if layout_s: color_s = Gdk.RGBA(); color_s.parse(self.config.get("center_secondary_text_color")); ctx.set_source_rgba(color_s.red, color_s.green, color_s.blue, color_s.alpha); ctx.move_to(cx - log_s.width / 2, current_y); PangoCairo.show_layout(ctx, layout_s); current_y += log_s.height + spacing
            if layout_u: color_u = Gdk.RGBA(); color_u.parse(self.config.get("center_primary_text_color")); ctx.set_source_rgba(color_u.red, color_u.green, color_u.blue, color_u.alpha); ctx.move_to(cx - log_u.width / 2, current_y); PangoCairo.show_layout(ctx, layout_u)

    def _draw_center_caption(self, ctx, cx, cy, radius):
        text, pos = self.config.get("center_caption_text"), self.config.get("center_caption_position")
        if not text or pos == "none": return
        rgba = Gdk.RGBA(); rgba.parse(self.config.get("center_caption_color")); ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        layout = PangoCairo.create_layout(ctx); layout.set_font_description(Pango.FontDescription.from_string(self.config.get("center_caption_font")))
        char_widths = [layout.set_text(char, -1) or layout.get_pixel_extents()[1].width for char in text]
        total_text_angular_width = sum(char_widths) / (radius * 0.85) if radius > 0 else 0
        text_angle = {"top": -math.pi/2, "bottom": math.pi/2, "left": math.pi, "right": 0}.get(pos, -math.pi/2) - (total_text_angular_width / 2.0)
        ctx.save(); ctx.translate(cx, cy)
        for i, char in enumerate(text):
            layout.set_text(char, -1); _, log = layout.get_pixel_extents()
            char_angle = char_widths[i] / (radius * 0.85) if radius > 0 else 0
            rotation_angle = text_angle + (char_angle / 2.0)
            ctx.save(); ctx.rotate(rotation_angle); ctx.translate(radius * 0.85, 0); ctx.rotate(math.pi / 2)
            ctx.move_to(-log.width / 2.0, -log.height / 2.0); PangoCairo.show_layout(ctx, layout); ctx.restore()
            text_angle += char_angle
        ctx.restore()

    def _draw_arc(self, ctx, cx, cy, radius, width, percent, index, label_text, static_only=False, dynamic_only=False, text_only=False):
        start_angle, end_angle = math.radians(float(self.config.get(f"arc{index}_start_angle"))), math.radians(float(self.config.get(f"arc{index}_end_angle")))
        total_angle = end_angle - start_angle
        if total_angle <= 0: total_angle += 2 * math.pi
        
        if text_only:
            if self.config.get(f"arc{index}_label_position", "start") != "none" and label_text:
                self._draw_text_on_arc(ctx, cx, cy, radius, width, label_text, index, start_angle, total_angle)
            return

        if not dynamic_only:
            ctx.new_path(); bg_color = Gdk.RGBA(); bg_color.parse(self.config.get(f"arc{index}_bg_color")); ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
            ctx.set_line_width(width); ctx.set_line_cap(cairo.LINE_CAP_ROUND); ctx.arc(cx, cy, radius, start_angle, end_angle); ctx.stroke()
        
        if not static_only and percent > 0:
            ctx.new_path(); fg_color = Gdk.RGBA(); fg_color.parse(self.config.get(f"arc{index}_fg_color")); ctx.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, fg_color.alpha); ctx.set_line_width(width); ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            fill_direction = self.config.get(f"arc{index}_fill_direction", "start")
            if fill_direction == "end": ctx.arc_negative(cx, cy, radius, end_angle, end_angle - total_angle * min(1.0, percent))
            else: ctx.arc(cx, cy, radius, start_angle, start_angle + total_angle * min(1.0, percent))
            ctx.stroke()

    def _draw_text_on_arc(self, ctx, cx, cy, radius, arc_width, text, index, start_angle, total_angle):
        rgba = Gdk.RGBA(); rgba.parse(self.config.get(f"arc{index}_label_color")); ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        layout = PangoCairo.create_layout(ctx); layout.set_font_description(Pango.FontDescription.from_string(self.config.get(f"arc{index}_label_font")))
        char_widths = [layout.set_text(char, -1) or layout.get_pixel_extents()[1].width for char in text]
        total_text_angular_width = sum(char_widths) / radius if radius > 0 else 0
        pos = self.config.get(f"arc{index}_label_position")
        if pos == 'middle': text_angle = start_angle + (total_angle - total_text_angular_width) / 2.0
        elif pos == 'end': text_angle = start_angle + total_angle - total_text_angular_width
        else: text_angle = start_angle
        ctx.save(); ctx.translate(cx, cy)
        for i, char in enumerate(text):
            layout.set_text(char, -1); _, log = layout.get_pixel_extents()
            char_angle = char_widths[i] / radius if radius > 0 else 0
            rotation_angle = text_angle + (char_angle / 2.0)
            ctx.save(); ctx.rotate(rotation_angle); ctx.translate(radius, 0); ctx.rotate(math.pi / 2)
            ctx.move_to(-log.width / 2.0, -log.height / 2.0); PangoCairo.show_layout(ctx, layout); ctx.restore()
            text_angle += char_angle
        ctx.restore()

    def close(self):
        self._stop_animation_timer()
        super().close()

