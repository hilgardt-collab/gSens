# /data_displayers/static.py
import gi
import os
import cairo
import math
from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class StaticDisplayer(DataDisplayer):
    """
    A self-contained displayer for static content, capable of showing either a 
    multi-line text block or an image with various scaling options.
    """
    def __init__(self, panel_ref, config):
        self._image_pixbuf = None
        self._cached_image_path = None
        self._text_to_draw = ""
        self._layout_cache = None
        
        super().__init__(panel_ref, config)
        # Populate defaults using the internal method, not the empty one
        populate_defaults_from_model(self.config, self._get_full_config_model_definition())
        self.apply_styles()

    def _create_widget(self):
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def update_display(self, data):
        """Receives data from the source, updates internal state, and triggers a redraw."""
        if isinstance(data, dict) and data.get("content_type") == 'text':
            self._text_to_draw = data.get("text", "")
        self.widget.queue_draw()

    def apply_styles(self):
        """Reloads the image if the path has changed and invalidates text layout cache."""
        super().apply_styles()
        image_path = self.config.get("static_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            try:
                self._image_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
            except GLib.Error as e:
                print(f"Error loading static image: {e}")
                self._image_pixbuf = None
        
        self._layout_cache = None
        self.widget.queue_draw()
        
    def on_draw(self, area, ctx, width, height):
        """Draws either the image or the text based on configuration."""
        content_type = self.config.get("static_content_type", "text")

        if content_type == 'image' and self._image_pixbuf:
            self._draw_image(ctx, width, height)
        elif content_type == 'text':
            self._draw_text(ctx, width, height)

    def _draw_image(self, ctx, width, height):
        """Handles the logic for drawing the configured image."""
        img_w, img_h = self._image_pixbuf.get_width(), self._image_pixbuf.get_height()
        if img_w == 0 or img_h == 0: return

        style = self.config.get("static_image_style", "zoom")
        
        ctx.save()
        if style == "stretch":
            scale_x, scale_y = width / img_w, height / img_h
            ctx.scale(scale_x, scale_y)
            Gdk.cairo_set_source_pixbuf(ctx, self._image_pixbuf, 0, 0)
        elif style == "center":
            x_offset = (width - img_w) / 2
            y_offset = (height - img_h) / 2
            Gdk.cairo_set_source_pixbuf(ctx, self._image_pixbuf, x_offset, y_offset)
        elif style == "tile":
            img_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, img_w, img_h)
            img_ctx = cairo.Context(img_surface)
            Gdk.cairo_set_source_pixbuf(img_ctx, self._image_pixbuf, 0, 0)
            pattern = cairo.SurfacePattern(img_surface)
            pattern.set_extend(cairo.EXTEND_REPEAT)
            ctx.set_source(pattern)
        else: # zoom (cover)
            scale = max(width / img_w, height / img_h)
            x_offset = (width / scale - img_w) / 2
            y_offset = (height / scale - img_h) / 2
            ctx.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(ctx, self._image_pixbuf, x_offset, y_offset)

        ctx.paint_with_alpha(float(self.config.get("static_image_alpha", 1.0)))
        ctx.restore()

    def _draw_text(self, ctx, width, height):
        """Handles the logic for drawing styled, multi-line text."""
        if not self._text_to_draw:
            return

        if self._layout_cache is None:
            self._layout_cache = self.widget.create_pango_layout("")
        
        layout = self._layout_cache
        font_str = self.config.get("static_text_font", "Sans 12")
        layout.set_font_description(Pango.FontDescription.from_string(font_str))
        layout.set_text(self._text_to_draw, -1)
        layout.set_width(width * Pango.SCALE) # Enable wrapping

        align_str = self.config.get("static_text_align_horiz", "center")
        pango_align_map = {"left": Pango.Alignment.LEFT, "center": Pango.Alignment.CENTER, "right": Pango.Alignment.RIGHT}
        layout.set_alignment(pango_align_map.get(align_str, Pango.Alignment.CENTER))

        text_width, text_height = layout.get_pixel_extents()[1].width, layout.get_pixel_extents()[1].height
        
        # Calculate position
        v_align = self.config.get("static_text_align_vert", "center")
        if v_align == "top": y = 0
        elif v_align == "bottom": y = height - text_height
        else: y = (height - text_height) / 2

        # Horizontal alignment is handled by Pango, so we just start at x=0
        x = 0
        
        ctx.save()
        color_str = self.config.get("static_text_color", "rgba(220,220,220,1)")
        rgba = Gdk.RGBA(); rgba.parse(color_str)
        ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        
        ctx.move_to(x, y)
        PangoCairo.show_layout(ctx, layout)
        ctx.restore()

    @staticmethod
    def get_config_model():
        """
        Returns an empty model. All UI is now built in the get_configure_callback
        to ensure it runs after the controller widget is created.
        """
        return {}

    @staticmethod
    def _get_full_config_model_definition():
        """Internal helper to define the complete model for this displayer."""
        controller_key = "static_content_type"
        
        text_align_horiz_opts = {"Left": "left", "Center": "center", "Right": "right"}
        text_align_vert_opts = {"Top": "top", "Center": "center", "Bottom": "bottom"}

        return {
            "Text Style": [
                ConfigOption("static_text_font", "font", "Font:", "Sans 12",
                             dynamic_group=controller_key, dynamic_show_on="text"),
                ConfigOption("static_text_color", "color", "Color:", "rgba(220,220,220,1)",
                             dynamic_group=controller_key, dynamic_show_on="text"),
                ConfigOption("static_text_align_horiz", "dropdown", "Horizontal Align:", "center", options_dict=text_align_horiz_opts,
                             dynamic_group=controller_key, dynamic_show_on="text"),
                ConfigOption("static_text_align_vert", "dropdown", "Vertical Align:", "center", options_dict=text_align_vert_opts,
                             dynamic_group=controller_key, dynamic_show_on="text"),
            ],
            "Image Style": [
                ConfigOption("static_image_style", "dropdown", "Style:", "zoom", 
                             options_dict={"Zoom (Cover)": "zoom", "Stretch": "stretch", "Center (No Scale)": "center", "Tile": "tile"},
                             dynamic_group=controller_key, dynamic_show_on="image"),
                ConfigOption("static_image_alpha", "spinner", "Image Opacity:", "1.0", 
                             min_val=0.0, max_val=1.0, step=0.05, digits=2,
                             dynamic_group=controller_key, dynamic_show_on="image"),
            ]
        }

    def get_configure_callback(self):
        """
        Builds the dynamic configuration UI for the "Display" tab.
        """
        def build_dynamic_display_config(dialog, content_box, widgets, available_sources, panel_config):
            # Find the controller widget, which was built in the "Data Source" tab
            controller_widget = widgets.get("static_content_type")
            if not controller_widget:
                print("Warning (StaticDisplayer): Could not find 'static_content_type' controller for dynamic UI.")
                return

            # Build the UI using the full model, which will create the dynamic Gtk.Stack
            model = self._get_full_config_model_definition()
            build_ui_from_model(content_box, panel_config, model, widgets)
            dialog.dynamic_models.append(model)

        return build_dynamic_display_config

