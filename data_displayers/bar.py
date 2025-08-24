# data_displayers/bar.py
import gi
import math
from data_displayer import DataDisplayer
from config_dialog import ConfigOption
from ui_helpers import ScrollingLabel
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Pango

class BarDisplayer(DataDisplayer):
    """
    Displays data as a custom-drawn, rounded horizontal bar with 
    configurable labels and colors.
    """
    def __init__(self, panel_ref, config):
        self.current_percent = 0.0
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self.get_config_model())

    def _create_widget(self):
        """Creates the widget structure with labels and a drawing area for the bar."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, valign=Gtk.Align.CENTER)
        
        self.primary_label = ScrollingLabel(hexpand=True)
        vbox.append(self.primary_label)
        
        self.bar_area = Gtk.DrawingArea(content_height=12, hexpand=True, margin_top=2, margin_bottom=2)
        self.bar_area.set_draw_func(self.draw_bar)
        vbox.append(self.bar_area)
        
        self.secondary_label = ScrollingLabel(hexpand=True)
        vbox.append(self.secondary_label)
        
        return vbox

    def update_display(self, data):
        """Updates the labels and bar percentage based on new data."""
        if not self.panel_ref: return # Guard against race condition on close
        
        if not data:
            self.current_percent = 0.0
            self.primary_label.set_text("")
            self.secondary_label.set_text("N/A")
            return

        num_val = self.panel_ref.data_source.get_numerical_value(data)
        self.current_percent = max(0.0, min(100.0, num_val)) if num_val is not None else 0.0
        
        self.primary_label.set_text(self.panel_ref.data_source.get_primary_label_string(data))
        
        self.secondary_label.set_text(self.panel_ref.data_source.get_display_string(data))
        
        self.panel_ref.set_tooltip_text(self.panel_ref.data_source.get_tooltip_string(data))
        self.bar_area.queue_draw()
    
    @staticmethod
    def get_config_model():
        """Returns the configuration options for the bar and its labels."""
        model = DataDisplayer.get_config_model()
        model["Bar Style"] = [
            ConfigOption("show_bar", "bool", "Show Bar:", "True"),
            ConfigOption("bar_color", "color", "Bar Color:", "rgba(0,150,255,1.0)"),
            ConfigOption("bar_background_color", "color", "Bar Background:", "rgba(204,204,204,0.7)"),
            ConfigOption("bar_padding", "scale", "Side Padding:", "3", 0, 50, 1, 0)
        ]
        model["Labels"] = [
            ConfigOption("show_primary_label", "bool", "Show Primary Label:", "True"),
            ConfigOption("primary_label_font", "font", "Primary Font:", "Sans Italic 9"),
            ConfigOption("primary_label_color", "color", "Primary Color:", "#D0D0D0"),
            ConfigOption("show_secondary_label", "bool", "Show Secondary Label:", "True"),
            ConfigOption("secondary_label_font", "font", "Secondary Font:", "Sans 10"),
            ConfigOption("secondary_label_color", "color", "Secondary Color:", "#E0E0E0")
        ]
        return model

    def apply_styles(self):
        """Applies visibility, font, color, and padding settings from config."""
        super().apply_styles()
        
        # Primary Label Styling
        show_p = str(self.config.get("show_primary_label", "True")).lower() == 'true'
        self.primary_label.set_visible(show_p)
        if show_p:
            self.primary_label.set_font_description(Pango.FontDescription.from_string(self.config.get("primary_label_font", "Sans Italic 9")))
            r = Gdk.RGBA()
            r.parse(self.config.get("primary_label_color", "#D0D0D0"))
            self.primary_label.set_color(r)
            
        # Secondary Label Styling
        show_s = str(self.config.get("show_secondary_label", "True")).lower() == 'true'
        self.secondary_label.set_visible(show_s)
        if show_s:
            self.secondary_label.set_font_description(Pango.FontDescription.from_string(self.config.get("secondary_label_font", "Sans 10")))
            r = Gdk.RGBA()
            r.parse(self.config.get("secondary_label_color", "#E0E0E0"))
            self.secondary_label.set_color(r)
            
        # Bar Area Styling
        self.bar_area.set_visible(str(self.config.get("show_bar", "True")).lower() == 'true')
        pad = int(self.config.get("bar_padding", 3))
        self.bar_area.set_margin_start(pad)
        self.bar_area.set_margin_end(pad)
        self.bar_area.queue_draw()

    def _draw_rounded_rect(self, ctx, x, y, w, h, r):
        """Helper to draw a rectangle with rounded corners."""
        r = min(r, h / 2, w / 2)
        ctx.new_path()
        ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
        ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
        ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi)
        ctx.close_path()

    def draw_bar(self, area, ctx, width, height):
        """The main drawing function for the bar."""
        if width <= 0 or height <= 0: return
        
        bg = Gdk.RGBA()
        bg.parse(self.config.get("bar_background_color"))
        fg = Gdk.RGBA()
        fg.parse(self.config.get("bar_color"))
        
        # Draw background
        r = height / 2.0
        ctx.set_source_rgba(bg.red, bg.green, bg.blue, bg.alpha)
        self._draw_rounded_rect(ctx, 0, 0, width, height, r)
        ctx.fill()
        
        # Draw foreground
        fill_w = width * (self.current_percent / 100.0)
        if fill_w > 0:
            ctx.set_source_rgba(fg.red, fg.green, fg.blue, fg.alpha)
            self._draw_rounded_rect(ctx, 0, 0, fill_w, height, r)
            ctx.fill()
