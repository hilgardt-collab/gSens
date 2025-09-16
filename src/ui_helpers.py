import gi
import os
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo
from config_dialog import ConfigOption, build_ui_from_model
import math
import cairo

def draw_cairo_background(ctx, width, height, config, prefix, pixbuf=None, shape_info=None):
    """
    A centralized helper to draw various background types (solid, gradient, image)
    onto a Cairo context. The caller is responsible for setting any clipping path.

    :param ctx: The Cairo context to draw on.
    :param width: The width of the drawing area.
    :param height: The height of the drawing area.
    :param config: The configuration dictionary containing style keys.
    :param prefix: The unique prefix for the background config keys (e.g., "gauge_").
    :param pixbuf: An optional, pre-loaded GdkPixbuf for image backgrounds.
    :param shape_info: Optional dict for gradients, e.g., {'type': 'circle', 'cx': w/2, 'cy': h/2, 'radius': r}
    """
    bg_type = config.get(f"{prefix}bg_type", "solid")

    if bg_type == "image" and pixbuf:
        img_w, img_h = pixbuf.get_width(), pixbuf.get_height()
        if img_w == 0 or img_h == 0: return

        # Default to cover/zoom style
        scale = max(width / img_w, height / img_h)
        ctx.save()
        ctx.scale(scale, scale)
        # Center the image within the scaled context
        Gdk.cairo_set_source_pixbuf(ctx, pixbuf, (width / scale - img_w) / 2, (height / scale - img_h) / 2)
        ctx.paint_with_alpha(float(config.get(f"{prefix}background_image_alpha", 1.0)))
        ctx.restore()
    
    elif bg_type == "gradient_linear":
        c1_str = config.get(f"{prefix}gradient_linear_color1")
        c2_str = config.get(f"{prefix}gradient_linear_color2")
        angle = float(config.get(f"{prefix}gradient_linear_angle_deg", 90.0))
        angle_rad = math.radians(angle)

        x1, y1 = 0.5 - 0.5 * math.cos(angle_rad), 0.5 - 0.5 * math.sin(angle_rad)
        x2, y2 = 0.5 + 0.5 * math.cos(angle_rad), 0.5 + 0.5 * math.sin(angle_rad)
        pat = cairo.LinearGradient(x1 * width, y1 * height, x2 * width, y2 * height)
        
        c1 = Gdk.RGBA(); c1.parse(c1_str)
        c2 = Gdk.RGBA(); c2.parse(c2_str)
        pat.add_color_stop_rgba(0, c1.red, c1.green, c1.blue, c1.alpha)
        pat.add_color_stop_rgba(1, c2.red, c2.green, c2.blue, c2.alpha)
        ctx.set_source(pat)
        ctx.paint()

    elif bg_type == "gradient_radial":
        c1_str = config.get(f"{prefix}gradient_radial_color1")
        c2_str = config.get(f"{prefix}gradient_radial_color2")
        
        cx = shape_info.get('cx', width/2) if shape_info else width/2
        cy = shape_info.get('cy', height/2) if shape_info else height/2
        radius = shape_info.get('radius', max(width, height)/2) if shape_info else max(width, height)/2
        
        pat = cairo.RadialGradient(cx, cy, 0, cx, cy, radius)
        c1 = Gdk.RGBA(); c1.parse(c1_str)
        c2 = Gdk.RGBA(); c2.parse(c2_str)
        pat.add_color_stop_rgba(0, c1.red, c1.green, c1.blue, c1.alpha)
        pat.add_color_stop_rgba(1, c2.red, c2.green, c2.blue, c2.alpha)
        ctx.set_source(pat)
        ctx.paint()

    else:  # solid
        bg_color_str = config.get(f"{prefix}bg_color", "rgba(40,40,40,1)")
        bg_rgba = Gdk.RGBA()
        bg_rgba.parse(bg_color_str)
        ctx.set_source_rgba(bg_rgba.red, bg_rgba.green, bg_rgba.blue, bg_rgba.alpha)
        ctx.paint()

def get_background_config_model(prefix):
    """
    Returns a dictionary defining the configuration model for background styles,
    with all keys using the provided prefix. This is a data-only function.
    """
    image_file_filters = [{"name": "Image Files", "patterns": ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.svg"]}, {"name": "All Files", "patterns": ["*"]}]
    
    return {
        "Background Style": [
            ConfigOption(f"{prefix}bg_type", "dropdown", "Style:", "solid", 
                         options_dict={"Solid Color": "solid", "Linear Gradient": "gradient_linear", 
                                       "Radial Gradient": "gradient_radial", "Image": "image"}),
            ConfigOption(f"{prefix}bg_color", "color", "Color:", "#222222"),
            ConfigOption(f"{prefix}gradient_linear_color1", "color", "Start Color:", "#444444"),
            ConfigOption(f"{prefix}gradient_linear_color2", "color", "End Color:", "#222222"),
            ConfigOption(f"{prefix}gradient_linear_angle_deg", "spinner", "Angle (°):", 90.0, 0, 359, 1, 0),
            ConfigOption(f"{prefix}gradient_radial_color1", "color", "Center Color:", "#444444"),
            ConfigOption(f"{prefix}gradient_radial_color2", "color", "Edge Color:", "#222222"),
            ConfigOption(f"{prefix}background_image_path", "file", "Image File:", "", file_filters=image_file_filters),
            ConfigOption(f"{prefix}background_image_style", "dropdown", "Style:", "zoom", 
                                       options_dict={"Zoom (Cover)": "zoom", "Tile": "tile", "Stretch": "stretch"}),
            ConfigOption(f"{prefix}background_image_alpha", "scale", "Image Opacity:", "1.0", min_val=0.0, max_val=1.0, step=0.05, digits=2),
        ]
    }

def build_background_config_ui(parent_box, config, widgets, dialog_parent, prefix, title="Background Settings"):
    """
    Builds and adds a comprehensive set of UI controls for selecting a background
    (solid, gradient, image) to a given parent container.
    """
    sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=12, margin_bottom=6)
    parent_box.append(sep)
    header_label = Gtk.Label(xalign=0)
    header_label.set_markup(f"<b>{title}</b>")
    parent_box.append(header_label)

    # Use the helper to get the model definition
    full_model = get_background_config_model(prefix)
    bg_model_list = full_model.get("Background Style", [])
    
    bg_model = {
        "bg_type": next(o for o in bg_model_list if o.key == f"{prefix}bg_type"),
        "bg_color": next(o for o in bg_model_list if o.key == f"{prefix}bg_color"),
        "gradient_linear_color1": next(o for o in bg_model_list if o.key == f"{prefix}gradient_linear_color1"),
        "gradient_linear_color2": next(o for o in bg_model_list if o.key == f"{prefix}gradient_linear_color2"),
        "gradient_linear_angle": next(o for o in bg_model_list if o.key == f"{prefix}gradient_linear_angle_deg"),
        "gradient_radial_color1": next(o for o in bg_model_list if o.key == f"{prefix}gradient_radial_color1"),
        "gradient_radial_color2": next(o for o in bg_model_list if o.key == f"{prefix}gradient_radial_color2"),
        "background_image_path": next(o for o in bg_model_list if o.key == f"{prefix}background_image_path"),
        "background_image_style": next(o for o in bg_model_list if o.key == f"{prefix}background_image_style"),
        "background_image_alpha": next(o for o in bg_model_list if o.key == f"{prefix}background_image_alpha"),
    }
    
    if dialog_parent and not hasattr(dialog_parent, 'ui_models'):
        dialog_parent.ui_models = {}
    if dialog_parent:
        dialog_parent.ui_models[f'background_{prefix}'] = {title: bg_model_list}

    build_ui_from_model(parent_box, config, {"": [bg_model["bg_type"]]}, widgets)
    
    bg_type_combo = widgets[f"{prefix}bg_type"]

    solid_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=5)
    parent_box.append(solid_box)
    build_ui_from_model(solid_box, config, {"": [bg_model["bg_color"]]}, widgets)

    grad_linear_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=5)
    parent_box.append(grad_linear_box)
    build_ui_from_model(grad_linear_box, config, {"": [bg_model["gradient_linear_color1"], bg_model["gradient_linear_color2"], bg_model["gradient_linear_angle"]]}, widgets)

    grad_radial_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=5)
    parent_box.append(grad_radial_box)
    build_ui_from_model(grad_radial_box, config, {"": [bg_model["gradient_radial_color1"], bg_model["gradient_radial_color2"]]}, widgets)

    image_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=5)
    parent_box.append(image_box)
    build_ui_from_model(image_box, config, {"": [bg_model["background_image_path"], bg_model["background_image_style"], bg_model["background_image_alpha"]]}, widgets)

    def on_bg_type_changed(combo):
        active_id = combo.get_active_id()
        solid_box.set_visible(active_id == "solid")
        grad_linear_box.set_visible(active_id == "gradient_linear")
        grad_radial_box.set_visible(active_id == "gradient_radial")
        image_box.set_visible(active_id == "image")

    bg_type_combo.connect("changed", on_bg_type_changed)
    on_bg_type_changed(bg_type_combo)


class ScrollingLabel(Gtk.DrawingArea):
    SCROLL_PIXELS_PER_TICK = 1
    SCROLL_TICK_INTERVAL_MS = 50

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._text = ""
        self._pango_layout = self.create_pango_layout(self._text)
        self._font_desc = Pango.FontDescription.from_string("Sans 10")
        self._rgba = Gdk.RGBA()
        self._rgba.parse("#FFFFFF") 

        self.scroll_offset_x = 0
        self.text_natural_width = 0
        self.is_scrolling = False
        self._scroll_timer_id = None
        self._last_width = -1

        self.set_draw_func(self.on_draw)
        self.connect("unrealize", self._on_unrealize)

    def do_size_allocate(self, width, height, baseline):
        Gtk.Widget.do_size_allocate(self, width, height, baseline)
        if self._last_width != width:
            self._last_width = width
            self._setup_scrolling()

    def _on_unrealize(self, widget):
        if self._scroll_timer_id is not None:
            GLib.source_remove(self._scroll_timer_id)
            self._scroll_timer_id = None

    def set_text(self, text):
        text = text if text is not None else ""
        if self._text == text:
            return
        self._text = text
        self._pango_layout = self.create_pango_layout(self._text)
        if self._pango_layout:
            self._pango_layout.set_font_description(self._font_desc)
            self._update_layout_height()
        self._setup_scrolling()
        self.queue_draw()
        self.queue_resize()

    def get_text(self):
        return self._text

    def set_font_description(self, font_desc):
        self._font_desc = font_desc
        if self._pango_layout:
            self._pango_layout.set_font_description(self._font_desc)
        self._update_layout_height()
        self._setup_scrolling()
        self.queue_draw()
        self.queue_resize()

    def set_color(self, rgba):
        self._rgba = rgba
        self.queue_draw()

    def _update_layout_height(self):
        dummy_layout = self.create_pango_layout("Mg")
        if dummy_layout:
            dummy_layout.set_font_description(self._font_desc)
            _ink_rect, logical_rect = dummy_layout.get_pixel_extents()
            self.set_content_height(logical_rect.height + 2)
        else:
            self.set_content_height(20)

    def _setup_scrolling(self):
        if not self._pango_layout or not self.get_realized():
            return

        _ink, logical = self._pango_layout.get_pixel_extents()
        self.text_natural_width = logical.width
        
        allocated_width = self.get_allocated_width()
        
        should_be_scrolling = self.text_natural_width > allocated_width and allocated_width > 0

        if should_be_scrolling and not self.is_scrolling:
            self.is_scrolling = True
            if self._scroll_timer_id is None:
                self.scroll_offset_x = 0
                self._scroll_timer_id = GLib.timeout_add(self.SCROLL_TICK_INTERVAL_MS, self._scroll_tick)
        elif not should_be_scrolling and self.is_scrolling:
            self.is_scrolling = False
            if self._scroll_timer_id is not None:
                GLib.source_remove(self._scroll_timer_id)
                self._scroll_timer_id = None
            self.scroll_offset_x = 0
            self.queue_draw()

    def _scroll_tick(self):
        if not self.is_scrolling:
            self._scroll_timer_id = None
            return GLib.SOURCE_REMOVE
        
        self.scroll_offset_x += self.SCROLL_PIXELS_PER_TICK
        space = 50 
        if self.scroll_offset_x > self.text_natural_width + space:
            self.scroll_offset_x = 0
            
        self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def on_draw(self, area, ctx, width, height):
        if self._pango_layout:
            _ink, logical = self._pango_layout.get_pixel_extents()

        ctx.set_source_rgba(self._rgba.red, self._rgba.green, self._rgba.blue, self._rgba.alpha)
        
        text_height = self._pango_layout.get_pixel_extents()[1].height
        y_centered = max(0, (height - text_height) / 2)

        if self.is_scrolling:
            ctx.save()
            ctx.rectangle(0, 0, width, height)
            ctx.clip()
            
            x_start = -self.scroll_offset_x
            ctx.move_to(x_start, y_centered)
            PangoCairo.show_layout(ctx, self._pango_layout)
            
            space = 50
            x_second_copy = x_start + self.text_natural_width + space
            if x_second_copy < width:
                ctx.move_to(x_second_copy, y_centered)
                PangoCairo.show_layout(ctx, self._pango_layout)
            
            ctx.restore()
        else:
            x_centered = max(0, (width - self.text_natural_width) / 2)
            ctx.move_to(x_centered, y_centered)
            PangoCairo.show_layout(ctx, self._pango_layout)

class CustomDialog(Gtk.Window):
    def __init__(self, parent=None, title="", primary_text=None, secondary_text=None, icon_name=None, modal=True, **kwargs):
        super().__init__(**kwargs)

        self._response = Gtk.ResponseType.NONE
        self._loop = None
        self.is_modal = modal

        if parent:
            self.set_transient_for(parent)
        self.set_title(title)
        self.set_modal(modal)
        self.set_resizable(True) 
        self.set_deletable(True)
        self.set_hide_on_close(not modal) 

        main_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_vbox)
        
        self._content_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self._content_area.set_vexpand(True)
        main_vbox.append(self._content_area)

        if primary_text:
            content_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15, 
                                  margin_top=15, margin_bottom=15, margin_start=15, margin_end=15)
            self._content_area.append(content_box)
            
            if icon_name:
                icon = Gtk.Image.new_from_icon_name(icon_name)
                icon.set_pixel_size(48)
                content_box.append(icon)

            label_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5, hexpand=True)
            content_box.append(label_box)
            primary_label = Gtk.Label(xalign=0)
            primary_label.set_markup(f"<b>{GLib.markup_escape_text(primary_text)}</b>")
            label_box.append(primary_label)

            if secondary_text:
                secondary_label = Gtk.Label(label=secondary_text, xalign=0, wrap=True, 
                                            wrap_mode=Pango.WrapMode.WORD_CHAR)
                label_box.append(secondary_label)

        main_vbox.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        self.action_area = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, 
                                   halign=Gtk.Align.END,
                                   margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        main_vbox.append(self.action_area)
        
        self.connect("close-request", self._on_close_request)

    def get_content_area(self):
        return self._content_area

    def respond(self, response_id):
        if not self.is_modal:
            print("Warning: respond() called on a non-modal dialog.")
            return
        self._response = response_id
        if self._loop and self._loop.is_running():
            self._loop.quit()
		
    def run(self):
        if not self.is_modal:
            print("Warning: run() called on a non-modal dialog. This is not supported.")
            return Gtk.ResponseType.NONE
        self.present()
        self._loop = GLib.MainLoop()
        self._loop.run()
        response = self._response
        self.destroy()
        return response

    def _on_close_request(self, window):
        self.respond(Gtk.ResponseType.CANCEL)
        return True

    def _on_button_clicked(self, button, response_id):
        self.respond(response_id)

    def add_button(self, label, response_id):
        button = Gtk.Button.new_with_mnemonic(label)
        button.connect("clicked", self._on_button_clicked, response_id)
        self.action_area.append(button)
        return button

    def add_styled_button(self, label, response_id, style_class=None, is_default=False):
        button = self.add_button(label, response_id)
        if style_class:
            button.add_css_class(style_class)
        if is_default:
            self.set_default_widget(button)
        return button

    def add_non_modal_button(self, label, style_class=None, is_default=False):
        button = Gtk.Button.new_with_mnemonic(label)
        if style_class:
            button.add_css_class(style_class)
        if is_default:
            self.set_default_widget(button)
        self.action_area.append(button)
        return button
