# data_displayers/bar.py
import gi
import math
import cairo
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo

class BarDisplayer(DataDisplayer):
    """
    Displays data as a highly configurable, custom-drawn bar with advanced
    styling for gradients, orientation, and text labels.
    """
    def __init__(self, panel_ref, config):
        self.current_percent = 0.0
        self.primary_text = ""
        self.secondary_text = ""
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        """Creates a single drawing area for the entire displayer."""
        drawing_area = Gtk.DrawingArea(vexpand=True, hexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def update_display(self, data):
        """Updates the labels and bar percentage based on new data."""
        if not self.panel_ref: return

        if data is None:
            self.current_percent = 0.0
            self.primary_text = ""
            self.secondary_text = "N/A"
        else:
            # --- FIX: Calculate percentage based on graph range from config ---
            num_val = self.panel_ref.data_source.get_numerical_value(data)
            
            try:
                min_v = float(self.config.get("graph_min_value", 0.0))
                max_v = float(self.config.get("graph_max_value", 100.0))
            except (ValueError, TypeError):
                min_v, max_v = 0.0, 100.0

            v_range = max_v - min_v if max_v > min_v else 1.0

            if num_val is not None:
                clamped_val = max(min_v, min(num_val, max_v))
                self.current_percent = ((clamped_val - min_v) / v_range) * 100.0
            else:
                self.current_percent = 0.0

            self.primary_text = self.panel_ref.data_source.get_primary_label_string(data)
            self.secondary_text = self.panel_ref.data_source.get_display_string(data)
        
        self.panel_ref.set_tooltip_text(self.panel_ref.data_source.get_tooltip_string(data))
        self.widget.queue_draw()
    
    @staticmethod
    def get_config_model():
        """Returns the configuration options for the bar and its labels."""
        align_opts = {"Left": "left", "Center": "center", "Right": "right"}
        super_align_opts = {
            "Top Left": "top_left", "Top Center": "top_center", "Top Right": "top_right",
            "Middle Left": "middle_left", "Middle Center": "middle_center", "Middle Right": "middle_right",
            "Bottom Left": "bottom_left", "Bottom Center": "bottom_center", "Bottom Right": "bottom_right"
        }
        
        model = DataDisplayer.get_config_model()
        model["Bar Style"] = [
            ConfigOption("bar_orientation", "dropdown", "Orientation:", "horizontal", 
                         options_dict={"Horizontal": "horizontal", "Vertical": "vertical"}),
            ConfigOption("bar_thickness", "spinner", "Thickness (px):", 12, 4, 200, 1, 0),
            ConfigOption("bar_end_style", "dropdown", "End Style:", "round", 
                         options_dict={"Round": "round", "Square": "square"}),
        ]
        model["Bar Colors"] = [
            ConfigOption("bar_bg_gradient", "bool", "Gradient Background:", "False"),
            ConfigOption("bar_background_color", "color", "BG Color 1:", "rgba(204,204,204,0.7)"),
            ConfigOption("bar_background_color2", "color", "BG Color 2:", "rgba(100,100,100,0.7)"),
            ConfigOption("bar_bg_angle", "spinner", "BG Angle (°):", 90, 0, 359, 1, 0),
            ConfigOption("bar_fg_gradient", "bool", "Gradient Foreground:", "False"),
            ConfigOption("bar_color", "color", "FG Color 1:", "rgba(0,150,255,1.0)"),
            ConfigOption("bar_color2", "color", "FG Color 2:", "rgba(0,100,200,1.0)"),
            ConfigOption("bar_fg_angle", "spinner", "FG Angle (°):", 90, 0, 359, 1, 0),
        ]
        model["Labels & Layout"] = [
            ConfigOption("bar_text_layout", "dropdown", "Text Layout:", "top", 
                         options_dict={"Superimposed": "superimposed", "Top": "top", 
                                       "Bottom": "bottom", "Left": "left", "Right": "right"}),
            ConfigOption("bar_split_ratio", "scale", "Text/Bar Split Ratio:", "0.4", 0.1, 0.9, 0.05, 2),
            ConfigOption("bar_superimposed_align", "dropdown", "Superimposed Align:", "middle_center", 
                         options_dict=super_align_opts),
            ConfigOption("bar_label_orientation", "dropdown", "Label Orientation:", "vertical", 
                         options_dict={"Vertical": "vertical", "Horizontal": "horizontal"}),
            ConfigOption("bar_show_primary_label", "bool", "Show Primary Label:", "True"),
            ConfigOption("bar_primary_align", "dropdown", "Primary Text Align:", "center", options_dict=align_opts),
            ConfigOption("bar_primary_font", "font", "Primary Font:", "Sans Italic 9"),
            ConfigOption("bar_primary_color", "color", "Primary Color:", "#D0D0D0"),
            ConfigOption("bar_show_secondary_label", "bool", "Show Secondary Label:", "True"),
            ConfigOption("bar_secondary_align", "dropdown", "Secondary Text Align:", "center", options_dict=align_opts),
            ConfigOption("bar_secondary_font", "font", "Secondary Font:", "Sans 10"),
            ConfigOption("bar_secondary_color", "color", "Secondary Color:", "#E0E0E0")
        ]
        return model

    def get_configure_callback(self):
        """Dynamically show/hide options based on other settings."""
        def setup_dynamic_options(dialog, content_box, widgets, available_sources, panel_config):
            bg_grad_switch = widgets.get("bar_bg_gradient")
            fg_grad_switch = widgets.get("bar_fg_gradient")
            layout_combo = widgets.get("bar_text_layout")

            def update_visibility(*args):
                if bg_grad_switch:
                    is_bg_grad = bg_grad_switch.get_active()
                    widgets["bar_background_color2"].get_parent().set_visible(is_bg_grad)
                    widgets["bar_bg_angle"].get_parent().set_visible(is_bg_grad)
                if fg_grad_switch:
                    is_fg_grad = fg_grad_switch.get_active()
                    widgets["bar_color2"].get_parent().set_visible(is_fg_grad)
                    widgets["bar_fg_angle"].get_parent().set_visible(is_fg_grad)
                if layout_combo:
                    is_super = layout_combo.get_active_id() == "superimposed"
                    widgets["bar_split_ratio"].get_parent().set_visible(not is_super)
            
            if bg_grad_switch: bg_grad_switch.connect("notify::active", update_visibility)
            if fg_grad_switch: fg_grad_switch.connect("notify::active", update_visibility)
            if layout_combo: layout_combo.connect("changed", update_visibility)
            GLib.idle_add(update_visibility)
        return setup_dynamic_options

    def on_draw(self, area, ctx, width, height):
        if width <= 0 or height <= 0: return
        
        show_primary = str(self.config.get("bar_show_primary_label", "True")).lower() == 'true'
        show_secondary = str(self.config.get("bar_show_secondary_label", "True")).lower() == 'true'

        layout_p = None
        if show_primary and self.primary_text:
            layout_p = PangoCairo.create_layout(ctx)
            layout_p.set_font_description(Pango.FontDescription.from_string(self.config.get("bar_primary_font")))
            layout_p.set_text(self.primary_text, -1)

        layout_s = None
        if show_secondary and self.secondary_text:
            layout_s = PangoCairo.create_layout(ctx)
            layout_s.set_font_description(Pango.FontDescription.from_string(self.config.get("bar_secondary_font")))
            layout_s.set_text(self.secondary_text, -1)

        layout = self.config.get("bar_text_layout", "top")

        if layout == "superimposed":
            self._draw_bar_graphic(ctx, 0, 0, width, height)
            self._draw_superimposed_text(ctx, 0, 0, width, height, layout_p, layout_s)
        else:
            ratio = float(self.config.get("bar_split_ratio", 0.4))
            spacing = 4
            
            if layout in ["top", "bottom"]:
                text_h, bar_h = (height * ratio) - (spacing/2), height * (1-ratio) - (spacing/2)
                text_w, bar_w = width, width
                bar_x, text_x = 0, 0
                text_y, bar_y = (0, text_h + spacing) if layout == "top" else (bar_h + spacing, 0)
            else: # left, right
                text_w, bar_w = (width * ratio) - (spacing/2), width * (1-ratio) - (spacing/2)
                text_h, bar_h = height, height
                bar_y, text_y = 0, 0
                text_x, bar_x = (0, text_w + spacing) if layout == "left" else (bar_w + spacing, 0)

            if bar_w > 0 and bar_h > 0: self._draw_bar_graphic(ctx, bar_x, bar_y, bar_w, bar_h)
            if text_w > 0 and text_h > 0: self._draw_label_set(ctx, text_x, text_y, text_w, text_h, layout_p, layout_s)

    def _draw_bar_graphic(self, ctx, x, y, w, h):
        orientation = self.config.get("bar_orientation", "horizontal")
        thickness = float(self.config.get("bar_thickness", 12))
        
        if orientation == "horizontal":
            bar_w, bar_h = w, min(h, thickness)
            bar_x, bar_y = x, y + (h - bar_h) / 2
        else: # vertical
            bar_w, bar_h = min(w, thickness), h
            bar_x, bar_y = x + (w - bar_w) / 2, y

        # Draw background
        self._draw_rect(ctx, bar_x, bar_y, bar_w, bar_h, "bg", 1.0)
        # Draw foreground
        self._draw_rect(ctx, bar_x, bar_y, bar_w, bar_h, "fg", self.current_percent / 100.0)

    def _draw_rect(self, ctx, x, y, w, h, prefix, fill_percent):
        if w <= 0 or h <= 0 or fill_percent <= 0: return

        orientation = self.config.get("bar_orientation", "horizontal")
        is_gradient = str(self.config.get(f"bar_{prefix}_gradient", "False")).lower() == 'true'
        color1_str = self.config.get(f"bar_{'background_' if prefix == 'bg' else ''}color")
        
        if is_gradient:
            color2_str = self.config.get(f"bar_{'background_' if prefix == 'bg' else ''}color2")
            angle = float(self.config.get(f"bar_{prefix}_angle", 90))
            angle_rad = math.radians(angle)
            c1, c2 = Gdk.RGBA(), Gdk.RGBA(); c1.parse(color1_str); c2.parse(color2_str)
            
            p1_x, p1_y = 0.5 - 0.5 * math.cos(angle_rad), 0.5 - 0.5 * math.sin(angle_rad)
            p2_x, p2_y = 0.5 + 0.5 * math.cos(angle_rad), 0.5 + 0.5 * math.sin(angle_rad)
            
            pat = cairo.LinearGradient(x + w*p1_x, y + h*p1_y, x + w*p2_x, y + h*p2_y)
            pat.add_color_stop_rgba(0, c1.red, c1.green, c1.blue, c1.alpha)
            pat.add_color_stop_rgba(1, c2.red, c2.green, c2.blue, c2.alpha)
            ctx.set_source(pat)
        else:
            color = Gdk.RGBA(); color.parse(color1_str)
            ctx.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        
        if orientation == "horizontal":
            fill_w = w * fill_percent
            fill_h = h
            fill_x = x
            fill_y = y
        else: # vertical
            fill_w = w
            fill_h = h * fill_percent
            fill_x = x
            fill_y = y + (h - fill_h)

        end_style = self.config.get("bar_end_style", "round")
        if end_style == "round":
            r = min(fill_w, fill_h) / 2
            self._draw_rounded_rect_path(ctx, fill_x, fill_y, fill_w, fill_h, r)
            ctx.fill()
        else:
            ctx.rectangle(fill_x, fill_y, fill_w, fill_h)
            ctx.fill()

    def _draw_rounded_rect_path(self, ctx, x, y, w, h, r):
        if r <= 0 or w <= 0 or h <= 0:
            if w > 0 and h > 0: ctx.rectangle(x, y, w, h)
            return
        r = min(r, h / 2, w / 2)
        ctx.new_path(); ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
        ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
        ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi); ctx.close_path()

    def _draw_superimposed_text(self, ctx, bar_x, bar_y, bar_width, bar_height, layout_p=None, layout_s=None):
        align = self.config.get("bar_superimposed_align", "middle_center")
        self._draw_label_set(ctx, bar_x, bar_y, bar_width, bar_height, layout_p, layout_s, align)

    def _draw_label_set(self, ctx, area_x, area_y, area_width, area_height, layout_p=None, layout_s=None, superimposed_align=None):
        show_primary = layout_p is not None and str(self.config.get("bar_show_primary_label", "True")).lower() == 'true'
        show_secondary = layout_s is not None and str(self.config.get("bar_show_secondary_label", "True")).lower() == 'true'
        if not show_primary and not show_secondary: return
        
        orientation = self.config.get("bar_label_orientation", "vertical")
        spacing = 4

        p_width = layout_p.get_pixel_extents()[1].width if show_primary else 0
        p_height = layout_p.get_pixel_extents()[1].height if show_primary else 0
        s_width = layout_s.get_pixel_extents()[1].width if show_secondary else 0
        s_height = layout_s.get_pixel_extents()[1].height if show_secondary else 0
        
        if superimposed_align:
            v_align, h_align = superimposed_align.split('_')
            
            if orientation == "vertical":
                total_text_height = p_height + s_height + (spacing if show_primary and show_secondary else 0)
                total_text_width = max(p_width, s_width)
            else: # Horizontal
                total_text_height = max(p_height, s_height)
                total_text_width = p_width + s_width + (spacing if show_primary and show_secondary else 0)

            if v_align == "top": y_start = area_y
            elif v_align == "bottom": y_start = area_y + area_height - total_text_height
            else: y_start = area_y + (area_height - total_text_height) / 2 # middle

            if h_align == "left": x_start = area_x
            elif h_align == "right": x_start = area_x + area_width - total_text_width
            else: x_start = area_x + (area_width - total_text_width) / 2 # center
        else:
             total_text_height = p_height + s_height + (spacing if show_primary and show_secondary else 0) if orientation == "vertical" else max(p_height, s_height)
             x_start = area_x
             y_start = area_y + (area_height - total_text_height) / 2

        if orientation == "vertical":
            current_y = y_start
            if show_primary:
                self._draw_pango_layout(ctx, layout_p, self.config.get("bar_primary_color"), self.config.get("bar_primary_align"), x_start, current_y, area_width, p_height)
                current_y += p_height + spacing
            if show_secondary:
                self._draw_pango_layout(ctx, layout_s, self.config.get("bar_secondary_color"), self.config.get("bar_secondary_align"), x_start, current_y, area_width, s_height)
        else: # Horizontal
            total_text_width = p_width + s_width + (spacing if show_primary and show_secondary else 0)
            current_x = area_x + (area_width - total_text_width) / 2 # Center the horizontal block
            if show_primary:
                y_pos = y_start + (total_text_height - p_height) / 2
                self._draw_pango_layout(ctx, layout_p, self.config.get("bar_primary_color"), "left", current_x, y_pos, p_width, p_height)
                current_x += p_width + spacing
            if show_secondary:
                y_pos = y_start + (total_text_height - s_height) / 2
                self._draw_pango_layout(ctx, layout_s, self.config.get("bar_secondary_color"), "left", current_x, y_pos, s_width, s_height)

    def _draw_pango_layout(self, ctx, layout, color_str, align_str, x, y, w, h):
        if not layout: return
        color = Gdk.RGBA(); color.parse(color_str)
        ctx.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        
        log_w = layout.get_pixel_extents()[1].width
        
        if align_str == "left": draw_x = x
        elif align_str == "right": draw_x = x + w - log_w
        else: draw_x = x + (w - log_w) / 2
        
        ctx.move_to(draw_x, y)
        PangoCairo.show_layout(ctx, layout)

