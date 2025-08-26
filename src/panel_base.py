# panel_base.py
from abc import ABC, abstractmethod
import gi
import re
import os
gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango
from config_manager import config_manager
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from ui_helpers import ScrollingLabel, CustomDialog

class BasePanelMeta(type(Gtk.Frame), type(ABC)):
    pass

class BasePanelABC(ABC):
    @abstractmethod
    def update(self):
        pass

    @abstractmethod
    def get_config_model(self):
        pass
    
    @abstractmethod
    def configure(self, *args):
        pass

class BasePanel(Gtk.Frame, BasePanelABC, metaclass=BasePanelMeta):
    SELECTED_BORDER_WIDTH_ADDITION = 1 
    ALARM_FLASH_INTERVAL_MS = 500

    def __init__(self, title="", config=None):
        super().__init__()
        self.set_margin_top(2)
        self.set_margin_bottom(2)
        self.set_margin_start(2)
        self.set_margin_end(2)

        self.original_title = title
        self.config = config or {} 
        self._timeout_id = None
        self._config_dialog = None 
        
        self._frame_css_provider = Gtk.CssProvider()
        self.get_style_context().add_provider(self._frame_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        self._title_label_css_provider = None 

        self.is_selected = False 

        self.is_in_alarm_state = False
        self._alarm_flash_on = False
        self._alarm_flash_timer_id = None
        self._current_alarm_flash_color = None
        
        # --- REFACTOR: Remove old, unprefixed background defaults ---
        # These are now handled by the unified build_background_config_ui helper.

        self.config["id"] = self.config.get("id", "panel_" + title.lower().replace(" ", "_") + "_" + str(id(self))[:5])
        self.config["name"] = self.config.get("name", self.config["id"]) 
        self.config["width"] = int(self.config.get("width", "2"))
        self.config["height"] = int(self.config.get("height", "2"))
        self.config["grid_x"] = int(self.config.get("grid_x", "0"))
        self.config["grid_y"] = int(self.config.get("grid_y", "0"))
        self.config["title_text"] = str(self.config.get("title_text", self.original_title))
        
        show_title_val = self.config.get("show_title", True)
        self.config["show_title"] = str(show_title_val).lower() == 'true' if isinstance(show_title_val, str) else bool(show_title_val)
        
        self.config["title_color"] = str(self.config.get("title_color", "#FFFFFF"))
        self.config["title_font"] = str(self.config.get("title_font", "Sans Bold 10"))
        self.config.setdefault("text_color", "#E0E0E0") 
        self.config.setdefault("font", "Sans 10")      
        self.config.setdefault("cell_size", 64) 

        self.set_name(self.config["name"]) 

        self.init_ui() 
        self.setup_context_menu() 

    def _alarm_flash_callback(self):
        if not self.is_in_alarm_state: 
            return GLib.SOURCE_REMOVE 
        
        self._alarm_flash_on = not self._alarm_flash_on
        GLib.idle_add(self.apply_panel_frame_style) 
        if hasattr(self, 'data_displayer') and hasattr(self.data_displayer, 'graph_area') and \
           self.data_displayer.graph_area and self.data_displayer.graph_area.get_visible():
            GLib.idle_add(self.data_displayer.graph_area.queue_draw)
        return GLib.SOURCE_CONTINUE

    def enter_alarm_state(self, flash_color=None):
        if self.is_in_alarm_state:
            return
        self.is_in_alarm_state = True
        self._alarm_flash_on = True 
        
        if flash_color:
            self._current_alarm_flash_color = flash_color
        else:
            alarm_color_key = next((k for k in self.config if k.endswith("alarm_color")), None)
            self._current_alarm_flash_color = self.config.get(alarm_color_key, 'rgba(255,0,0,0.6)')

        if self._alarm_flash_timer_id is None:
            self._alarm_flash_timer_id = GLib.timeout_add(self.ALARM_FLASH_INTERVAL_MS, self._alarm_flash_callback)
        self.apply_panel_frame_style()
        if hasattr(self, 'data_displayer') and hasattr(self.data_displayer, 'graph_area') and \
           self.data_displayer.graph_area and self.data_displayer.graph_area.get_visible():
             GLib.idle_add(self.data_displayer.graph_area.queue_draw)

    def exit_alarm_state(self):
        if not self.is_in_alarm_state:
            return
        self.is_in_alarm_state = False
        self._alarm_flash_on = False 
        self._current_alarm_flash_color = None
        if self._alarm_flash_timer_id is not None:
            GLib.source_remove(self._alarm_flash_timer_id)
            self._alarm_flash_timer_id = None
        
        self.apply_panel_frame_style()
        
        if hasattr(self, 'data_displayer') and hasattr(self.data_displayer, 'graph_area') and \
           self.data_displayer.graph_area and self.data_displayer.graph_area.get_visible():
             GLib.idle_add(self.data_displayer.graph_area.queue_draw)

    def check_and_update_alarm_state(self, current_value, alarm_config_prefix=""):
        enable_alarm_key = f"{alarm_config_prefix}enable_alarm"
        alarm_high_value_key = f"{alarm_config_prefix}alarm_high_value"
        
        alarm_enabled = str(self.config.get(enable_alarm_key, "False")).lower() == 'true'
        try:
            alarm_high_value = float(self.config.get(alarm_high_value_key, "80.0"))
        except (ValueError, TypeError):
            alarm_high_value = 80.0 
            print(f"Warning: Invalid alarm_high_value for {self.config['id']}. Using default.")

        if alarm_enabled and current_value is not None and current_value > alarm_high_value:
            self.enter_alarm_state()
        else: 
            self.exit_alarm_state()

    def apply_all_configurations(self):
        self.apply_panel_frame_style() 

        if hasattr(self, 'title_label'): 
            show_title_val = self.config.get("show_title", True)
            is_title_visible = str(show_title_val).lower() == 'true' if isinstance(show_title_val, str) else bool(show_title_val)

            self.title_label.set_visible(is_title_visible)
            if is_title_visible:
                self.title_label.set_text(self.config.get("title_text", self.original_title))
                font_desc = Pango.FontDescription.from_string(self.config.get("title_font", "Sans Bold 10"))
                self.title_label.set_font_description(font_desc)
                rgba = Gdk.RGBA()
                rgba.parse(self.config.get('title_color', '#FFFFFF'))
                self.title_label.set_color(rgba)
        
        self.set_standard_size_and_notify_grid()

    def _notify_grid_parent_of_dimension_change(self):
        parent_grid = self.get_parent()
        try:
            if parent_grid and parent_grid.__class__.__name__ == "GridLayoutManager":
                panel_id = self.config["id"]
                width_units = int(self.config["width"])
                height_units = int(self.config["height"])
                parent_grid.handle_panel_dimension_update(panel_id, width_units, height_units)
        except Exception as e:
            print(f"Warning: Could not notify grid parent of dimension change: {e}")

    def set_standard_size_and_notify_grid(self):
        try:
            width_units = int(self.config.get("width", 2))
            height_units = int(self.config.get("height", 2))
            cell_size = int(self.config.get("cell_size", 64))
            self.set_size_request(width_units * cell_size, height_units * cell_size)
        except (ValueError, TypeError) as e:
            print(f"Error setting size request for panel {self.config.get('id')}: {e}. Using default size.")
            self.set_size_request(2 * 64, 2 * 64)
        
        self._notify_grid_parent_of_dimension_change() 

    def apply_panel_frame_style(self):
        css_parts = []
        
        is_in_alarm = self.is_in_alarm_state and self._alarm_flash_on
        if is_in_alarm:
            css_parts.append(f"background: {self._current_alarm_flash_color};")
        else:
            # --- REFACTOR: Use the new, prefixed config keys ---
            bg_type = self.config.get("panel_bg_type", "solid")
            if bg_type == "image":
                image_path = self.config.get("panel_background_image_path")
                if image_path and os.path.exists(image_path):
                    image_uri = GLib.filename_to_uri(image_path, None)
                    image_alpha = float(self.config.get("panel_background_image_alpha", 1.0))
                    overlay_alpha = 1.0 - image_alpha
                    overlay_color = f"rgba(0, 0, 0, {overlay_alpha:.2f})"
                    css_parts.append(f"background-image: linear-gradient({overlay_color}, {overlay_color}), url('{image_uri}');")
                    css_parts.append(f"background-color: {self.config.get('panel_bg_color', '#222222')};")
                    image_style = self.config.get("panel_background_image_style", "zoom")
                    if image_style == "tile":
                        css_parts.extend(["background-size: auto, auto;", "background-repeat: repeat, no-repeat;"])
                    elif image_style == "stretch":
                        css_parts.extend(["background-size: 100% 100%, 100% 100%;", "background-repeat: no-repeat, no-repeat;"])
                    else: # zoom (cover)
                        css_parts.extend(["background-size: cover, cover;", "background-repeat: no-repeat, no-repeat;"])
                else:
                    css_parts.append(f"background-color: {self.config.get('panel_bg_color', '#222222')};")
            elif bg_type == "gradient_linear":
                angle = self.config.get("panel_gradient_linear_angle_deg", "90")
                color1, color2 = self.config.get("panel_gradient_linear_color1"), self.config.get("panel_gradient_linear_color2")
                css_parts.append(f"background-image: linear-gradient({angle}deg, {color1}, {color2});")
            elif bg_type == "gradient_radial":
                color1, color2 = self.config.get("panel_gradient_radial_color1"), self.config.get("panel_gradient_radial_color2")
                css_parts.append(f"background-image: radial-gradient(circle, {color1}, {color2});")
            else: # solid
                css_parts.append(f"background-color: {self.config.get('panel_bg_color', '#222222')};")
        
        grid_layout_config = config_manager.config["GridLayout"]
        global_show_borders = grid_layout_config.get("show_panel_borders", "True").lower() == 'true'
        radius_val = int(grid_layout_config.get("panel_border_radius", 4))
        width_val = int(grid_layout_config.get("panel_border_width", 1))
        
        css_parts.append(f"border-radius: {radius_val}px;")
        
        final_border_color = grid_layout_config.get("panel_border_color")
        final_border_width = width_val
        apply_border = global_show_borders
        
        if self.is_selected:
            final_border_color = grid_layout_config.get("selected_panel_border_color")
            final_border_width = max(1, width_val + self.SELECTED_BORDER_WIDTH_ADDITION) if global_show_borders and width_val > 0 else self.SELECTED_BORDER_WIDTH_ADDITION
            apply_border = True

        if apply_border:
            css_parts.append(f"border: {final_border_width}px solid {final_border_color};")
        else:
            css_parts.append("border-style: none; border-width: 0px;")

        selector = f"frame#{self.get_name()}"
        css_data = f"{selector} {{ {' '.join(css_parts)} }}"
        try:
            self._frame_css_provider.load_from_data(css_data.encode())
        except GLib.Error as e:
            print(f"!!! CSS FRAME PARSE ERROR: {e}\nCSS: {css_data}")

    def set_selected_visual_indicator(self, is_selected):
        if self.is_selected != is_selected:
            self.is_selected = is_selected
            self.apply_panel_frame_style() 

    def init_ui(self):
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.set_child(self.box) 
        
        self.title_label = ScrollingLabel(margin_top=2)
        self.box.append(self.title_label)
              
        self.content_area = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.content_area.set_vexpand(True); self.content_area.set_hexpand(True) 
        self.box.append(self.content_area) 

    def setup_context_menu(self):
        select_gesture = Gtk.GestureClick.new(); select_gesture.set_button(Gdk.BUTTON_PRIMARY) 
        select_gesture.connect("pressed", self.on_gesture_pressed); self.add_controller(select_gesture)

        context_gesture = Gtk.GestureClick.new(); context_gesture.set_button(Gdk.BUTTON_SECONDARY)
        context_gesture.connect("pressed", self.on_gesture_pressed); self.add_controller(context_gesture)

        self.popover = Gtk.Popover()
        menu_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        for m_prop in ["top", "bottom", "start", "end"]: getattr(menu_box, f"set_margin_{m_prop}")(6)
        self.popover.set_child(menu_box)
        config_btn = Gtk.Button(label="Configure"); config_btn.connect("clicked", self.on_configure_clicked)
        menu_box.append(config_btn)
        close_btn = Gtk.Button(label="Close"); close_btn.connect("clicked", self.on_close_clicked)
        menu_box.append(close_btn)
        self.popover.set_parent(self) 

    def on_gesture_pressed(self, gesture, n_press, x, y):
        parent_grid = self.get_parent()
        is_multi_selecting_or_dragging = False
        if hasattr(parent_grid, 'rubberband_active') and parent_grid.rubberband_active:
            is_multi_selecting_or_dragging = True
        if hasattr(parent_grid, 'drag_active') and parent_grid.drag_active:
            is_multi_selecting_or_dragging = True

        event = gesture.get_current_event()
        if not event: return

        is_ctrl = bool(event.get_modifier_state() & Gdk.ModifierType.CONTROL_MASK)
        is_shift = bool(event.get_modifier_state() & Gdk.ModifierType.SHIFT_MASK)
        button = gesture.get_current_button()
        
        # Highest priority: Copy config on Ctrl+Shift+PrimaryClick
        if button == Gdk.BUTTON_PRIMARY and is_ctrl and is_shift:
            print(f"DEBUG: Ctrl+Shift+Click detected on panel {self.config.get('id')}")
            if hasattr(parent_grid, 'handle_copy_config_request'):
                parent_grid.handle_copy_config_request(self.config.get("id"))
            return # Stop further processing for this gesture
        
        # Second priority: Context menu on Right-Click
        if button == Gdk.BUTTON_SECONDARY and not is_multi_selecting_or_dragging:
             self.popover.popup()
             return

        # Third priority: Selection on Primary Click (if not dragging)
        if button == Gdk.BUTTON_PRIMARY and not is_multi_selecting_or_dragging:
            if hasattr(parent_grid, 'selected_panel_ids') and hasattr(parent_grid, '_update_selected_panels_visuals'):
                panel_id = self.config.get("id")
                if is_ctrl: # Toggle selection
                    if panel_id in parent_grid.selected_panel_ids:
                        parent_grid.selected_panel_ids.remove(panel_id)
                    else:
                        parent_grid.selected_panel_ids.add(panel_id)
                else: # Simple select
                    parent_grid.selected_panel_ids.clear()
                    parent_grid.selected_panel_ids.add(panel_id)
                parent_grid._update_selected_panels_visuals()

    def on_configure_clicked(self, button):
        self.popover.popdown(); self.configure()

    def on_close_clicked(self, button):
        self.popover.popdown()
        parent_grid = self.get_parent()
        panel_id = self.config.get("id")
        if panel_id and parent_grid and hasattr(parent_grid, 'remove_panel_widget_by_id'):
            parent_grid.remove_panel_widget_by_id(panel_id)
        else:
            print(f"Error: Could not request removal for panel {panel_id}. Parent or method not found.")

    def close_panel(self, widget=None):
        """
        Thoroughly cleans up the panel to prevent memory and thread leaks.
        """
        if self._config_dialog:
            self._config_dialog.destroy()
            self._config_dialog = None
        if self._timeout_id: 
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None
        if self._alarm_flash_timer_id is not None:
            GLib.source_remove(self._alarm_flash_timer_id)
            self._alarm_flash_timer_id = None
        
        if self._frame_css_provider:
            self.get_style_context().remove_provider(self._frame_css_provider)
            self._frame_css_provider = None
        if self._title_label_css_provider and hasattr(self, 'title_label') and self.title_label:
            self.title_label.get_style_context().remove_provider(self._title_label_css_provider)
            self._title_label_css_provider = None
            
        panel_id = self.config["id"]
        config_manager.remove_panel_config(panel_id)
        
    def set_update_interval(self, seconds):
        if self._timeout_id: 
            GLib.source_remove(self._timeout_id)
            self._timeout_id = None
        try:
            update_seconds = int(seconds)
            if update_seconds <= 0: update_seconds = 1 
        except ValueError: update_seconds = 1 
        
        should_continue = self.update()
        if not should_continue:
             return 
        self._timeout_id = GLib.timeout_add_seconds(update_seconds, self.update)
  
    def on_config_dialog_destroy(self, dialog):
        self._config_dialog = None

    @abstractmethod
    def update(self):
        return True 

    def get_config_model(self):
        return {}

    def get_configure_callback(self):
        return None

    def configure(self, *args):
        pass
