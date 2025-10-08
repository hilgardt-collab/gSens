# /data_displayers/static.py
import gi
import os
import cairo
import math
from .text import TextDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from utils import populate_defaults_from_model

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf

class StaticDisplayer(TextDisplayer):
    """
    A displayer for static content, capable of showing either a multi-line
    text block (using TextDisplayer's logic) or an image.
    """
    def __init__(self, panel_ref, config):
        # Image-related state
        self._image_pixbuf = None
        self._cached_image_path = None
        
        # Initialize the parent TextDisplayer
        super().__init__(panel_ref, config)
        
        # Populate with image-specific defaults
        populate_defaults_from_model(self.config, self._get_image_config_model())
        self.apply_styles()

    def update_display(self, data):
        """Receives data from the source, updates text lines, and triggers a redraw."""
        # The parent TextDisplayer's update_display handles everything for text mode
        super().update_display(data)

    def apply_styles(self):
        """Reloads the image if the path has changed and calls parent's apply_styles."""
        # Call parent first to handle all text-related style updates
        super().apply_styles()
        
        image_path = self.config.get("static_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            try:
                self._image_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
            except GLib.Error as e:
                print(f"Error loading static image: {e}")
                self._image_pixbuf = None
        
        # Parent already queues a draw
        # self.widget.queue_draw()

    def on_draw(self, area, ctx, width, height):
        """Draws either the image or calls the parent to draw the text."""
        content_type = self.config.get("static_content_type", "text")

        if content_type == 'image' and self._image_pixbuf:
            self._draw_image(ctx, width, height)
        elif content_type == 'text':
            # Let the parent (TextDisplayer) handle all text drawing
            super().on_draw(area, ctx, width, height)

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
        else: # Default to zoom (cover)
            scale = max(width / img_w, height / img_h)
            x_offset = (width / scale - img_w) / 2
            y_offset = (height / scale - img_h) / 2
            ctx.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(ctx, self._image_pixbuf, x_offset, y_offset)

        ctx.paint_with_alpha(float(self.config.get("static_image_alpha", 1.0)))
        ctx.restore()
        
    @staticmethod
    def get_config_model():
        """
        Returns an empty model. All UI is built in the get_configure_callback
        to prevent the DataPanel from drawing a default UI.
        """
        return {}

    @staticmethod
    def _get_image_config_model():
        """Internal helper to define just the image-specific options."""
        return {
            "Image Style": [
                ConfigOption("static_image_style", "dropdown", "Style:", "zoom", 
                             options_dict={"Zoom (Cover)": "zoom", "Stretch": "stretch", "Center (No Scale)": "center", "Tile": "tile"}),
                ConfigOption("static_image_alpha", "scale", "Image Opacity:", "1.0", 
                             min_val=0.0, max_val=1.0, step=0.05, digits=2),
            ]
        }

    def get_configure_callback(self):
        """
        Builds the dynamic configuration UI for the "Display" tab, with a
        Gtk.Stack to switch between Text and Image options.
        """
        def build_dynamic_display_config(dialog, content_box, widgets, available_sources, panel_config):
            controller_widget = widgets.get("static_content_type")
            if not controller_widget:
                print("Warning: Could not find 'static_content_type' controller for dynamic UI.")
                return

            stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_UP_DOWN)
            content_box.append(stack)

            # --- Page 1: Text Options (from parent TextDisplayer) ---
            text_page_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
            text_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=5, margin_bottom=5, margin_start=5, margin_end=5)
            text_page_scroll.set_child(text_page)
            
            text_model = TextDisplayer.get_config_model()
            text_cb = TextDisplayer(None, panel_config).get_configure_callback()
            build_ui_from_model(text_page, panel_config, text_model, widgets)
            if text_cb:
                text_cb(dialog, text_page, widgets, available_sources, panel_config)
            
            dialog.dynamic_models.append(text_model)
            stack.add_titled(text_page_scroll, "text", "Text Options")

            # --- Page 2: Image Options ---
            image_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=5, margin_bottom=5, margin_start=5, margin_end=5)
            image_model = self._get_image_config_model()
            build_ui_from_model(image_page, panel_config, image_model, widgets)
            dialog.dynamic_models.append(image_model)
            stack.add_titled(image_page, "image", "Image Options")
            
            # --- Connect the controller to the stack ---
            def on_controller_changed(combo):
                active_id = combo.get_active_id()
                if active_id and stack.get_child_by_name(active_id):
                    stack.set_visible_child_name(active_id)

            controller_widget.connect("changed", on_controller_changed)
            GLib.idle_add(on_controller_changed, controller_widget)

        return build_dynamic_display_config

