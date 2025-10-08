# grid_layout_manager.py
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Gio, GLib, Pango
from config_manager import config_manager
from utils import show_confirmation_dialog
import os
import uuid
import configparser
from config_dialog import ConfigOption, build_ui_from_model, get_config_from_widgets
from ui_helpers import build_background_config_ui, CustomDialog
from data_panel import DataPanel
import math

CELL_SIZE = 16

class GridLayoutManager(Gtk.Fixed):
    """
    Manages the layout of all panels in a grid. Handles panel creation,
    deletion, drag-and-drop, multi-selection with a rubberband,
    and the overall background appearance.
    """
    def __init__(self, available_sources, available_displayers, all_source_classes):
        super().__init__()
        self.AVAILABLE_DATA_SOURCES = available_sources
        self.AVAILABLE_DISPLAYERS = available_displayers
        self.ALL_SOURCE_CLASSES = all_source_classes
        
        self.panel_positions = {}
        self.panel_sizes = {}
        self.panel_widgets = {}

        # Drag state variables
        self.drag_active = False
        self.drag_primary_panel_id = None
        self.drag_panel_offsets = {}
        self.drag_original_positions = {}
        self.drag_group_min_orig_x = 0
        self.drag_group_min_orig_y = 0
        self.drag_start_coords_abs = None
        self.drag_offset_from_group_origin = None

        self.current_preview_grid_pos = (0,0)
        self.is_copy_drag = False
        self.current_drop_is_valid = True

        # Selection state variables
        self.selected_panel_ids = set()
        self.rubberband_active = False
        self.rubberband_start_coords = None
        self.last_rubberband_x = 0
        self.last_rubberband_y = 0
        self.last_rubberband_width = 0
        self.last_rubberband_height = 0

        # UI Widgets
        self.drag_preview_overlay_area = Gtk.DrawingArea()
        self.drag_preview_overlay_area.set_draw_func(self._on_draw_drag_preview)
        self.drag_preview_overlay_area.set_visible(False)
        self.rubberband_selector_widget = self._create_rubberband_selector()
        
        self.add_css_class("grid-layout-manager")
        
        self._grid_background_css_provider = None
        self._rubberband_css_provider = None
        self._layout_config_dialog = None

        self._h_adjustment = None
        self._v_adjustment = None

        # Auto-scroll state
        self._scroll_timer_id = None
        self._scroll_animation_id = None
        self._current_scroll_page = 0

        if not config_manager.config.has_section("GridLayout"):
            config_manager.config.add_section("GridLayout")
        
        grid_layout_config = config_manager.config["GridLayout"]
        grid_layout_config.setdefault("rubberband_bg_color", "rgba(70, 130, 180, 0.2)")
        grid_layout_config.setdefault("rubberband_border_color", "rgba(70, 130, 180, 0.6)")
        grid_layout_config.setdefault("rubberband_border_style", "dashed")
        grid_layout_config.setdefault("drag_preview_valid_color", "rgba(0, 200, 0, 0.7)")
        grid_layout_config.setdefault("drag_preview_invalid_color", "rgba(200, 0, 0, 0.7)")
        grid_layout_config.setdefault("drag_preview_line_style", "dashed")
        grid_layout_config.setdefault("selected_panel_border_color", "rgba(0, 120, 212, 0.9)")
        grid_layout_config.setdefault("launch_fullscreen", "False")
        grid_layout_config.setdefault("fullscreen_display_index", "-1") 
        grid_layout_config.setdefault("auto_scroll_on_overflow", "False")
        grid_layout_config.setdefault("auto_scroll_interval_seconds", "5.0")
        grid_layout_config.setdefault("grid_bg_type", "solid")
        grid_layout_config.setdefault("grid_bg_color", "#333333")
        grid_layout_config.setdefault("grid_gradient_linear_color1", "#444444")
        grid_layout_config.setdefault("grid_gradient_linear_color2", "#222222")
        grid_layout_config.setdefault("grid_gradient_linear_angle_deg", "90")
        grid_layout_config.setdefault("grid_gradient_radial_color1", "#444444")
        grid_layout_config.setdefault("grid_gradient_radial_color2", "#222222")
        grid_layout_config.setdefault("grid_background_image_path", "")
        grid_layout_config.setdefault("grid_background_image_style", "zoom")
        grid_layout_config.setdefault("grid_background_image_alpha", "1.0")
        grid_layout_config.setdefault("show_panel_borders", "True")
        grid_layout_config.setdefault("panel_border_width", "1")
        grid_layout_config.setdefault("panel_border_color", "rgba(100,100,100,0.8)")
        grid_layout_config.setdefault("panel_border_radius", "4")

        self._load_and_apply_grid_config()
        self._setup_context_menu_and_actions()
        self._setup_selection_gestures()
        
        self.fullscreen_menu_item_label = "Enter Fullscreen"

    def _sort_and_reorder_panels(self):
        """
        Sorts all panels by their z_order config and re-adds them to the
        Gtk.Fixed layout to enforce drawing order (higher z_order on top).
        """
        panel_items = []
        for panel_id, widget in self.panel_widgets.items():
            try:
                z_order = int(config_manager.config.get(panel_id, "z_order", fallback="0"))
                panel_items.append((z_order, panel_id, widget))
            except (configparser.NoSectionError, configparser.NoOptionError):
                panel_items.append((0, panel_id, widget))
        
        panel_items.sort(key=lambda x: x[0])

        for _, panel_id, widget in panel_items:
            if widget.get_parent() == self:
                x_pos, y_pos = self.panel_positions.get(panel_id, (0, 0))
                # Removing and re-adding to Gtk.Fixed updates the drawing order
                self.remove(widget)
                self.put(widget, x_pos * CELL_SIZE, y_pos * CELL_SIZE)

    def set_scroll_adjustments(self, hadjustment, vadjustment):
        self._h_adjustment = hadjustment
        self._v_adjustment = vadjustment
        if hadjustment:
            hadjustment.connect("changed", self.check_and_update_scrolling_state)
            hadjustment.connect("value-changed", self.check_and_update_scrolling_state)

    def create_panel_widget(self, config_dict):
        type_id = config_dict.get('type')
        
        if type_id in self.AVAILABLE_DATA_SOURCES:
            source_info = self.AVAILABLE_DATA_SOURCES[type_id]
            disp_key = config_dict.get('displayer_type')
            
            if disp_key == 'combo':
                disp_key = 'arc_combo'
                config_dict['displayer_type'] = 'arc_combo'
            
            if not disp_key or disp_key not in source_info['displayers']:
                disp_key = source_info['displayers'][0] if source_info['displayers'] else None
            
            if disp_key and disp_key in self.AVAILABLE_DISPLAYERS:
                SourceClass = source_info['class']
                DisplayerClass = self.AVAILABLE_DISPLAYERS[disp_key]['class']
                
                source = SourceClass(config=config_dict)
                displayer = DisplayerClass(panel_ref=None, config=config_dict)
                
                return DataPanel(
                    config=config_dict, 
                    data_source=source, 
                    data_displayer=displayer,
                    available_sources=self.AVAILABLE_DATA_SOURCES
                )
        
        print(f"Warning: Could not create panel. Unknown type_id: {type_id}")
        return None

    def create_and_add_panel_from_config(self, config_dict):
        panel_id = config_manager.add_panel_config(config_dict['type'], config_dict)
        full_config = dict(config_manager.config.items(panel_id))
        
        w, h = int(full_config.get('width', 2)), int(full_config.get('height', 2))
        x, y = self._find_first_available_spot(w, h)
        full_config['grid_x'], full_config['grid_y'] = str(x), str(y)
        config_manager.update_panel_config(panel_id, full_config)

        new_widget = self.create_panel_widget(full_config)
        if new_widget:
            self.add_panel(new_widget, full_config)
            config_manager.save()

    def load_panels_from_config(self):
        for type_id, cfg in config_manager.get_all_panel_configs():
            panel = self.create_panel_widget(cfg)
            if panel: 
                self.add_panel(panel, cfg)
        GLib.idle_add(self.check_and_update_scrolling_state)

    def clear_all_panels(self):
        for panel_id in list(self.panel_widgets.keys()):
            self.remove_panel_widget_by_id(panel_id)
        config_manager.remove_all_panel_configs()

    def handle_copy_config_request(self, destination_id):
        if len(self.selected_panel_ids) != 1:
            print("Copy Config: Select exactly one source panel first.")
            return

        source_id = list(self.selected_panel_ids)[0]
        if source_id == destination_id: return
        
        source_widget = self.panel_widgets.get(source_id)
        dest_widget = self.panel_widgets.get(destination_id)
        if not source_widget or not dest_widget: return

        source_config = dict(config_manager.config.items(source_id))
        dest_config = dict(config_manager.config.items(destination_id))

        keys_to_copy = [
            'width', 'height', 'panel_bg_type', 'panel_bg_color', 
            'panel_gradient_linear_color1', 'panel_gradient_linear_color2', 'panel_gradient_linear_angle_deg',
            'panel_gradient_radial_color1', 'panel_gradient_radial_color2',
            'panel_background_image_path', 'panel_background_image_style', 'panel_background_image_alpha'
        ]

        if source_config.get('displayer_type') == dest_config.get('displayer_type'):
            if hasattr(source_widget, 'data_displayer'):
                displayer_model = source_widget.data_displayer.get_config_model()
                displayer_keys = [opt.key for section in displayer_model.values() for opt in section]
                keys_to_copy.extend(displayer_keys)

        new_dest_config = dest_config.copy()
        for key in set(keys_to_copy):
            if key in source_config:
                new_dest_config[key] = source_config[key]
        
        config_manager.update_panel_config(destination_id, new_dest_config)
        dest_widget.config = new_dest_config
        dest_widget.apply_all_configurations()
        print(f"Copied style from '{source_id}' to '{destination_id}'.")


    def recreate_panel(self, panel_id):
        if panel_id not in self.panel_widgets:
            return

        full_config = dict(config_manager.config.items(panel_id))
        full_config["id"] = panel_id
        
        self.remove_panel_widget_by_id(panel_id)

        new_panel_widget = self.create_panel_widget(full_config)
        if new_panel_widget:
            self.add_panel(new_panel_widget, full_config)
            self.selected_panel_ids.add(panel_id)
            self._update_selected_panels_visuals()

    def delete_selected_panels(self):
        if self.selected_panel_ids:
            self._confirm_and_delete_selected_panels()

    def _confirm_and_delete_selected_panels(self):
        num_selected = len(self.selected_panel_ids)
        if num_selected == 0: return
        response = show_confirmation_dialog(
            parent=self.get_ancestor(Gtk.Window),
            title="Confirm Deletion",
            primary_text=f"Delete {num_selected} selected panel{'s' if num_selected > 1 else ''}?",
            secondary_text="This action cannot be undone.",
            ok_text="_Delete", ok_style="destructive-action"
        )
        if response == Gtk.ResponseType.OK:
            for panel_id in list(self.selected_panel_ids):
                if panel_id in self.panel_widgets:
                    self.remove_panel_widget_by_id(panel_id)
    
    def _on_draw_drag_preview(self, drawing_area, cr, width, height):
        if not self.drag_active or not self.selected_panel_ids: return False
        
        scroll_x_offset = self._h_adjustment.get_value() if self._h_adjustment else 0
        scroll_y_offset = self._v_adjustment.get_value() if self._v_adjustment else 0

        grid_layout_config = config_manager.config["GridLayout"]
        color_str = grid_layout_config.get("drag_preview_valid_color") if self.current_drop_is_valid else grid_layout_config.get("drag_preview_invalid_color")
        preview_rgba = Gdk.RGBA()
        preview_rgba.parse(color_str)
        cr.set_source_rgba(preview_rgba.red, preview_rgba.green, preview_rgba.blue, preview_rgba.alpha)
        cr.set_line_width(2.0)
        
        line_style = grid_layout_config.get("drag_preview_line_style", "dashed")
        if line_style == "dashed": cr.set_dash([4.0, 4.0])
        elif line_style == "dotted": cr.set_dash([1.0, 3.0])
        else: cr.set_dash([])

        for panel_id in self.selected_panel_ids:
            if panel_id not in self.drag_panel_offsets or panel_id not in self.panel_sizes: continue
            
            offset_x_grid, offset_y_grid = self.drag_panel_offsets[panel_id]
            panel_w_units, panel_h_units = self.panel_sizes[panel_id]
            snapped_group_grid_x, snapped_group_grid_y = self.current_preview_grid_pos

            px_in_grid_manager = (snapped_group_grid_x + offset_x_grid) * CELL_SIZE
            py_in_grid_manager = (snapped_group_grid_y + offset_y_grid) * CELL_SIZE

            px_on_overlay = px_in_grid_manager - scroll_x_offset
            py_on_overlay = py_in_grid_manager - scroll_y_offset
            pw, ph = panel_w_units * CELL_SIZE, panel_h_units * CELL_SIZE
            
            cr.rectangle(px_on_overlay, py_on_overlay, pw, ph)
            cr.stroke()
        return True

    def _apply_rubberband_style(self):
        if not hasattr(self, 'rubberband_selector_widget'): return
        grid_layout_config = config_manager.config["GridLayout"]
        css_data = f"""
            #rubberband-selector {{
                background-color: {grid_layout_config.get("rubberband_bg_color")};
                border: 1px {grid_layout_config.get("rubberband_border_style")} {grid_layout_config.get("rubberband_border_color")};
                opacity: 0.7;
            }}
        """.encode()
        if self._rubberband_css_provider:
            self.rubberband_selector_widget.get_style_context().remove_provider(self._rubberband_css_provider)
        self._rubberband_css_provider = Gtk.CssProvider()
        try:
            self._rubberband_css_provider.load_from_data(css_data)
            self.rubberband_selector_widget.get_style_context().add_provider(self._rubberband_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        except GLib.Error as e: print(f"Error loading rubberband CSS: {e}")

    def _create_rubberband_selector(self):
        selector = Gtk.Box(name="rubberband-selector", visible=False)
        self.put(selector, 0, 0)
        return selector

    def _setup_selection_gestures(self):
        self.rubberband_gesture = Gtk.GestureDrag.new()
        self.rubberband_gesture.set_button(Gdk.BUTTON_PRIMARY)
        self.rubberband_gesture.connect("drag-begin", self._on_rubberband_drag_begin)
        self.rubberband_gesture.connect("drag-update", self._on_rubberband_drag_update)
        self.rubberband_gesture.connect("drag-end", self._on_rubberband_drag_end)
        self.add_controller(self.rubberband_gesture)

        self.background_click_gesture = Gtk.GestureClick.new()
        self.background_click_gesture.set_button(Gdk.BUTTON_PRIMARY)
        self.background_click_gesture.connect("pressed", self._on_background_pressed)
        self.add_controller(self.background_click_gesture)

    def _on_background_pressed(self, gesture, n_press, x, y):
        if self.pick(x, y, Gtk.PickFlags.DEFAULT) != self:
            return

        self.grab_focus()
        
        if n_press == 2:
            main_window = self.get_ancestor(Gtk.ApplicationWindow)
            if main_window and hasattr(main_window, 'toggle_fullscreen_mode'):
                main_window.toggle_fullscreen_mode()
        
        elif n_press == 1:
            event = gesture.get_current_event()
            if event and not (event.get_modifier_state() & (Gdk.ModifierType.SHIFT_MASK | Gdk.ModifierType.CONTROL_MASK)):
                if self.selected_panel_ids:
                    self.selected_panel_ids.clear()
                    self._update_selected_panels_visuals()

    def _on_rubberband_drag_begin(self, gesture, start_x, start_y):
        self.grab_focus()
        event = gesture.get_current_event()
        if self.pick(start_x, start_y, Gtk.PickFlags.DEFAULT) != self: 
            gesture.set_state(Gtk.EventSequenceState.DENIED)
            return

        self.rubberband_active = True
        self.rubberband_start_coords = (start_x, start_y)
        if not (event and (event.get_modifier_state() & Gdk.ModifierType.CONTROL_MASK)):
            if self.selected_panel_ids:
                self.selected_panel_ids.clear()
                self._update_selected_panels_visuals()
        
        self.move(self.rubberband_selector_widget, int(start_x), int(start_y))
        
        self.rubberband_selector_widget.set_size_request(1, 1)
        self.rubberband_selector_widget.set_visible(True)
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def _on_rubberband_drag_update(self, gesture, offset_x, offset_y):
        if not self.rubberband_active or self.rubberband_start_coords is None: return
        cur_x, cur_y = self.rubberband_start_coords[0] + offset_x, self.rubberband_start_coords[1] + offset_y
        self.last_rubberband_x = int(min(self.rubberband_start_coords[0], cur_x))
        self.last_rubberband_y = int(min(self.rubberband_start_coords[1], cur_y))
        self.last_rubberband_width = int(abs(cur_x - self.rubberband_start_coords[0]))
        self.last_rubberband_height = int(abs(cur_y - self.rubberband_start_coords[1]))
        
        self.move(self.rubberband_selector_widget, self.last_rubberband_x, self.last_rubberband_y)
        self.rubberband_selector_widget.set_size_request(self.last_rubberband_width, self.last_rubberband_height)

    def _on_rubberband_drag_end(self, gesture, offset_x, offset_y):
        if not self.rubberband_active: return
        self.rubberband_active = False
        self.rubberband_selector_widget.set_visible(False)
        rb_rect = Gdk.Rectangle()
        rb_rect.x, rb_rect.y = self.last_rubberband_x, self.last_rubberband_y
        rb_rect.width, rb_rect.height = self.last_rubberband_width, self.last_rubberband_height
        
        event = gesture.get_current_event()
        add_to_selection = bool(event and (event.get_modifier_state() & Gdk.ModifierType.CONTROL_MASK))
        
        newly_selected_by_drag = set()
        for panel_id, panel_widget in self.panel_widgets.items():
            intersects, _ = panel_widget.get_allocation().intersect(rb_rect)
            if intersects: newly_selected_by_drag.add(panel_id)
        
        if add_to_selection: self.selected_panel_ids.update(newly_selected_by_drag)
        else: self.selected_panel_ids = newly_selected_by_drag
        
        self._update_selected_panels_visuals()

    def _update_selected_panels_visuals(self):
        for panel_id, panel_widget in self.panel_widgets.items():
            if hasattr(panel_widget, 'set_selected_visual_indicator'):
                panel_widget.set_selected_visual_indicator(panel_id in self.selected_panel_ids)

    def _load_and_apply_grid_config(self, config_data=None):
        style_context = self.get_style_context()
        if self._grid_background_css_provider:
            style_context.remove_provider(self._grid_background_css_provider)
        
        css_rules = []
        
        grid_config = config_data if config_data is not None else config_manager.config["GridLayout"]
        
        bg_type = grid_config.get("grid_bg_type", "solid")
        
        if bg_type == "image":
            image_path = grid_config.get("grid_background_image_path")
            if image_path and os.path.exists(image_path):
                image_uri = GLib.filename_to_uri(image_path, None)
                css_rules.append(f"background-image: url('{image_uri}');")
                style = grid_config.get("grid_background_image_style", "zoom")
                if style == "tile": css_rules.extend(["background-size: auto;", "background-repeat: repeat;"])
                elif style == "stretch": css_rules.extend(["background-size: 100% 100%;", "background-repeat: no-repeat;"])
                else: css_rules.extend(["background-size: cover;", "background-repeat: no-repeat;"])
            else: css_rules.append(f"background-color: {grid_config.get('grid_bg_color', '#333333')};")
        elif bg_type == "gradient_linear":
            angle = grid_config.get("grid_gradient_linear_angle_deg", "90")
            color1, color2 = grid_config.get("grid_gradient_linear_color1"), grid_config.get("grid_gradient_linear_color2")
            css_rules.append(f"background-image: linear-gradient({angle}deg, {color1}, {color2});")
        elif bg_type == "gradient_radial":
            color1, color2 = grid_config.get("grid_gradient_radial_color1"), grid_config.get("grid_gradient_radial_color2")
            css_rules.append(f"background-image: radial-gradient(circle, {color1}, {color2});")
        else: # solid
            css_rules.append(f"background-color: {grid_config.get('grid_bg_color', '#333333')};")
        
        if css_rules:
            self._grid_background_css_provider = Gtk.CssProvider()
            css_data_str = f".grid-layout-manager {{ {' '.join(css_rules)} }}"
            try:
                self._grid_background_css_provider.load_from_data(css_data_str.encode())
                style_context.add_provider(self._grid_background_css_provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)
            except GLib.Error as e: print(f"Error loading grid background CSS: {e}")

        self._apply_rubberband_style()
        self._update_selected_panels_visuals()

        for panel_widget in self.panel_widgets.values():
            if hasattr(panel_widget, 'apply_panel_frame_style'):
                panel_widget.apply_panel_frame_style()

    def _setup_context_menu_and_actions(self):
        self.context_menu = Gio.Menu()
        self.context_menu.append("Add Panel...", "win.add_panel")
        self.context_menu.append_section(None, Gio.Menu.new()) 
        self.context_menu.append("Configure Layout & Appearance...", "grid.configure_layout_and_appearance")
        
        self.fullscreen_menu_item = Gio.MenuItem.new("Enter Fullscreen", "win.toggle_fullscreen")
        self.context_menu.append_item(self.fullscreen_menu_item)

        self.context_menu.append("Save Layout Now", "win.save_layout_now")
        self.context_menu.append_section(None, Gio.Menu.new()) 
        self.context_menu.append("Quit", "app.quit")

        action_group = Gio.SimpleActionGroup.new()
        configure_action = Gio.SimpleAction.new("configure_layout_and_appearance", None)
        configure_action.connect("activate", self._on_configure_layout_activate)
        action_group.add_action(configure_action)
        self.insert_action_group("grid", action_group)

        self.context_menu_gesture = Gtk.GestureClick.new()
        self.context_menu_gesture.set_button(Gdk.BUTTON_SECONDARY)
        self.context_menu_gesture.connect("pressed", self._on_background_right_click_for_menu)
        self.add_controller(self.context_menu_gesture)
        
        self.popover_context_menu = Gtk.PopoverMenu.new_from_model(self.context_menu)
        self.popover_context_menu.set_parent(self)
        self.popover_context_menu.connect("closed", self.check_and_update_scrolling_state)


    def _on_background_right_click_for_menu(self, gesture, n_press, x, y):
        if self.pick(x, y, Gtk.PickFlags.DEFAULT) == self:
            self.grab_focus()
            
            if self._scroll_timer_id is not None:
                self.stop_auto_scrolling(reset_position=False)

            main_window = self.get_ancestor(Gtk.ApplicationWindow)
            if main_window:
                label = "Exit Fullscreen" if main_window.is_fullscreen() else "Enter Fullscreen"
                self.fullscreen_menu_item.set_label(label)
            
            rect = Gdk.Rectangle()
            rect.x = x
            rect.y = y
            rect.width = 1
            rect.height = 1
            self.popover_context_menu.set_pointing_to(rect)
            
            self.popover_context_menu.popup()

    def _on_configure_layout_activate(self, action, param):
        if self._layout_config_dialog and self._layout_config_dialog.get_visible():
            self._layout_config_dialog.present()
            return

        if self._scroll_timer_id is not None:
            self.stop_auto_scrolling(reset_position=False)
        
        dialog = CustomDialog(parent=self.get_ancestor(Gtk.Window), title="Configure Layout & Appearance", modal=False)
        self._layout_config_dialog = dialog
        dialog.ui_models = {}
        dialog.set_default_size(480, 850)
        
        dialog_scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vscrollbar_policy=Gtk.PolicyType.AUTOMATIC, vexpand=True)
        dialog.get_content_area().append(dialog_scroll)
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        dialog_scroll.set_child(main_box)
        
        all_widgets = {}

        monitor_options = {"Current Display": "-1"}
        try:
            display = self.get_display()
            monitors = display.get_monitors()
            for i in range(monitors.get_n_items()):
                monitor = monitors.get_item(i)
                manufacturer = monitor.get_manufacturer() or ""
                model = monitor.get_model() or ""
                monitor_name = f"Monitor {i}: {manufacturer} {model}".strip()
                monitor_options[monitor_name] = str(i)
        except Exception as e:
            print(f"Could not enumerate monitors: {e}")

        layout_config_model = {
            "Panel Borders & Roundness": [
                ConfigOption("show_panel_borders", "bool", "Show Panel Borders:", "True"),
                ConfigOption("panel_border_width", "scale", "Border Width (px):", "1", 0, 10, 1),
                ConfigOption("panel_border_color", "color", "Border Color:", "rgba(100,100,100,0.8)"),
                ConfigOption("panel_border_radius", "scale", "Corner Roundness (px):", "4", 0, 20, 1),
                ConfigOption("selected_panel_border_color", "color", "Selected Border Color:", "rgba(0, 120, 212, 0.9)"),
            ],
            "Fullscreen & Scrolling": [
                ConfigOption("launch_fullscreen", "bool", "Launch in Fullscreen:", "False"),
                ConfigOption("fullscreen_display_index", "dropdown", "Fullscreen on Display:", "-1", 
                             options_dict=monitor_options, 
                             tooltip="Select which monitor to use for fullscreen mode."),
                ConfigOption("auto_scroll_on_overflow", "bool", "Enable Auto-Scroll on Overflow:", "False",
                             tooltip="Automatically scroll horizontally if content is wider than the window."),
                ConfigOption("auto_scroll_interval_seconds", "scale", "Auto-Scroll Interval (sec):", "5.0", 1.0, 30.0, 1.0, 1),
            ]
        }
        
        build_ui_from_model(main_box, dict(config_manager.config["GridLayout"]), layout_config_model, all_widgets)
        
        build_background_config_ui(main_box, dict(config_manager.config["GridLayout"]), all_widgets, dialog, prefix="grid_", title="Layout Background")

        dialog.ui_models['layout'] = layout_config_model

        def apply_changes(widget=None):
            background_model = dialog.ui_models.get('background_grid_', {})
            
            new_background_conf = get_config_from_widgets(all_widgets, [background_model])
            new_layout_conf = get_config_from_widgets(all_widgets, [dialog.ui_models['layout']])
            
            final_conf = {**new_background_conf, **new_layout_conf}
            
            grid_config_section = config_manager.config["GridLayout"]
            for key, value in final_conf.items():
                grid_config_section[key] = str(value)
            
            self._load_and_apply_grid_config(final_conf)
            self.check_and_update_scrolling_state()

        cancel = dialog.add_non_modal_button("_Cancel", style_class="destructive-action")
        cancel.connect("clicked", lambda w: dialog.destroy())
        apply = dialog.add_non_modal_button("_Apply")
        apply.connect("clicked", apply_changes)
        accept = dialog.add_non_modal_button("_Accept", style_class="suggested-action", is_default=True)
        accept.connect("clicked", lambda w: (apply_changes(), dialog.destroy()))
        
        dialog.connect("destroy", self._on_layout_dialog_destroy)
        dialog.present()

    def _on_layout_dialog_destroy(self, dialog):
        """Called when the layout config dialog is closed."""
        self._layout_config_dialog = None
        self.check_and_update_scrolling_state()

    def add_panel(self, widget, config):
        panel_id = config["id"]
        width_units, height_units = int(config.get("width", 2)), int(config.get("height", 2))
        grid_x, grid_y = int(config.get("grid_x", 0)), int(config.get("grid_y", 0))

        if panel_id not in self.panel_widgets and grid_x == 0 and grid_y == 0 and self.is_occupied(0,0, width_units, height_units):
            grid_x, grid_y = self._find_first_available_spot(width_units, height_units)
            widget.config["grid_x"], widget.config["grid_y"] = grid_x, grid_y
            config_manager.update_panel_config(panel_id, widget.config)
        
        widget.set_size_request(width_units * CELL_SIZE, height_units * CELL_SIZE)
        self.put(widget, grid_x * CELL_SIZE, grid_y * CELL_SIZE)
        self.panel_widgets[panel_id] = widget
        self.panel_sizes[panel_id] = (width_units, height_units)
        self.panel_positions[panel_id] = (grid_x, grid_y)
        
        panel_drag_controller = Gtk.GestureDrag.new()
        panel_drag_controller.set_button(Gdk.BUTTON_PRIMARY)
        panel_drag_controller.connect("drag-begin", self.on_drag_begin, widget, panel_id)
        panel_drag_controller.connect("drag-update", self.on_drag_update, widget, panel_id)
        panel_drag_controller.connect("drag-end", self.on_drag_end, widget, panel_id)
        widget.add_controller(panel_drag_controller)
        
        self._recalculate_container_size()
        widget.apply_panel_frame_style()
        self._sort_and_reorder_panels()

    def handle_panel_dimension_update(self, panel_id, new_width_units, new_height_units):
        if panel_id not in self.panel_widgets: return
        self.panel_sizes[panel_id] = (new_width_units, new_height_units)
        widget = self.panel_widgets[panel_id]
        widget.set_size_request(new_width_units * CELL_SIZE, new_height_units * CELL_SIZE)
        self._recalculate_container_size()
        
    def _find_first_available_spot(self, w_units, h_units, exclude_id=None):
        max_x, max_y = 20, 20
        if self.panel_positions:
            for panel_id, (px, py) in self.panel_positions.items():
                pw, ph = self.panel_sizes.get(panel_id, (1,1))
                max_x = max(max_x, px + pw)
                max_y = max(max_y, py + ph)
        
        search_limit_x, search_limit_y = max_x + w_units, max_y + h_units

        for y_coord in range(search_limit_y):
            for x_coord in range(search_limit_x):
                if not self.is_occupied(x_coord, y_coord, w_units, h_units, exclude_id):
                    return x_coord, y_coord
        return 0, 0

    def _get_content_bounding_box(self):
        max_x = 0
        max_y = 0
        if not self.panel_positions:
            return {'width': 0, 'height': 0}

        for panel_id, (grid_x, grid_y) in self.panel_positions.items():
            if panel_id in self.panel_sizes:
                width_units, height_units = self.panel_sizes[panel_id]
                max_x = max(max_x, (grid_x + width_units) * CELL_SIZE)
                max_y = max(max_y, (grid_y + height_units) * CELL_SIZE)
        
        return {'width': max_x, 'height': max_y}

    def _recalculate_container_size(self):
        bbox = self._get_content_bounding_box()
        required_width = bbox['width'] + CELL_SIZE
        required_height = bbox['height'] + CELL_SIZE
        self.set_size_request(required_width, required_height)
        GLib.idle_add(self.check_and_update_scrolling_state)
    
    def remove_panel_widget_by_id(self, panel_id_to_remove):
        widget = self.panel_widgets.pop(panel_id_to_remove, None)
        if not widget:
            if panel_id_to_remove in self.selected_panel_ids:
                self.selected_panel_ids.remove(panel_id_to_remove)
            return

        self.panel_positions.pop(panel_id_to_remove, None)
        self.panel_sizes.pop(panel_id_to_remove, None)
        if panel_id_to_remove in self.selected_panel_ids:
            self.selected_panel_ids.remove(panel_id_to_remove)

        if hasattr(widget, 'close_panel'):
            widget.close_panel()

        if widget.get_parent() == self:
            self.remove(widget)
        
        self._recalculate_container_size()

    def on_drag_begin(self, gesture, start_x, start_y, widget, panel_id):
        event = gesture.get_current_event()
        target = widget.pick(start_x, start_y, Gtk.PickFlags.DEFAULT)
        if target and target != widget:
            current = target
            while current and current != widget:
                if isinstance(current, (Gtk.Button, Gtk.Switch, Gtk.Scale, Gtk.Entry, Gtk.ComboBox, Gtk.SpinButton, Gtk.GestureClick)):
                    gesture.set_state(Gtk.EventSequenceState.DENIED)
                    return
                current = current.get_parent()
        
        self.drag_active = True
        self.drag_primary_panel_id = panel_id
        self.is_copy_drag = bool(event and (event.get_modifier_state() & Gdk.ModifierType.CONTROL_MASK))
        
        if panel_id not in self.selected_panel_ids:
            self.selected_panel_ids = {panel_id}
            self._update_selected_panels_visuals()
        
        drag_ids = self.selected_panel_ids
        all_x = [self.panel_positions[pid][0] for pid in drag_ids if pid in self.panel_positions]
        all_y = [self.panel_positions[pid][1] for pid in drag_ids if pid in self.panel_positions]
        self.drag_group_min_orig_x = min(all_x) if all_x else 0
        self.drag_group_min_orig_y = min(all_y) if all_y else 0
        
        self.drag_panel_offsets.clear(); self.drag_original_positions.clear()
        for pid in drag_ids:
            if pid not in self.panel_widgets or pid not in self.panel_positions: continue
            self.panel_widgets[pid].set_opacity(0.6 if not self.is_copy_drag else 1.0)
            orig_x, orig_y = self.panel_positions[pid]
            self.drag_original_positions[pid] = (orig_x, orig_y)
            self.drag_panel_offsets[pid] = (orig_x - self.drag_group_min_orig_x, orig_y - self.drag_group_min_orig_y)
        
        self.drag_start_coords_abs = widget.translate_coordinates(self, start_x, start_y)
        group_start_px_x = self.drag_group_min_orig_x * CELL_SIZE
        group_start_px_y = self.drag_group_min_orig_y * CELL_SIZE
        self.drag_offset_from_group_origin = (self.drag_start_coords_abs[0] - group_start_px_x, self.drag_start_coords_abs[1] - group_start_px_y)

        self.drag_preview_overlay_area.set_visible(True)
        self.current_preview_grid_pos = (self.drag_group_min_orig_x, self.drag_group_min_orig_y)
        self.drag_preview_overlay_area.queue_draw()
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)

    def on_drag_update(self, gesture, offset_x, offset_y, widget, panel_id):
        if not self.drag_active: return
        
        current_mouse_abs_x = self.drag_start_coords_abs[0] + offset_x
        current_mouse_abs_y = self.drag_start_coords_abs[1] + offset_y
        
        target_group_px_x = current_mouse_abs_x - self.drag_offset_from_group_origin[0]
        target_group_px_y = current_mouse_abs_y - self.drag_offset_from_group_origin[1]
        
        snapped_group_grid_x = round(target_group_px_x / CELL_SIZE)
        snapped_group_grid_y = round(target_group_px_y / CELL_SIZE)
        self.current_preview_grid_pos = (snapped_group_grid_x, snapped_group_grid_y)
        
        is_valid = not (snapped_group_grid_x < 0 or snapped_group_grid_y < 0)
        if is_valid:
            dragged_panel_config = dict(config_manager.config.items(self.drag_primary_panel_id))
            dragged_collision_enabled = str(dragged_panel_config.get("enable_collision", "True")).lower() == 'true'

            # Only check for collisions if the primary dragged panel has it enabled.
            if dragged_collision_enabled:
                exclude = self.selected_panel_ids if not self.is_copy_drag else None
                for pid_check in self.selected_panel_ids:
                    if pid_check not in self.drag_panel_offsets: continue
                    offset_x_grid, offset_y_grid = self.drag_panel_offsets[pid_check]
                    w_units, h_units = self.panel_sizes[pid_check]
                    target_x = snapped_group_grid_x + offset_x_grid
                    target_y = snapped_group_grid_y + offset_y_grid
                    if self.is_occupied(target_x, target_y, w_units, h_units, exclude):
                        is_valid = False; break
        
        self.current_drop_is_valid = is_valid
        self.drag_preview_overlay_area.queue_draw()

    def on_drag_end(self, gesture, offset_x, offset_y, widget, panel_id):
        if not self.drag_active: return
        self.drag_preview_overlay_area.set_visible(False)
        for pid_restore in self.selected_panel_ids:
            if pid_restore in self.panel_widgets: self.panel_widgets[pid_restore].set_opacity(1.0)
        
        snapped_group_grid_x, snapped_group_grid_y = self.current_preview_grid_pos
        
        if self.current_drop_is_valid:
            if self.is_copy_drag:
                main_window = self.get_ancestor(Gtk.Window)
                if not main_window: return

                newly_created_ids = set()
                for original_pid in self.selected_panel_ids:
                    original_config = dict(config_manager.config.items(original_pid))
                    new_config = original_config.copy()
                    new_id = f"panel_{uuid.uuid4().hex[:12]}"
                    new_config["id"] = new_id
                    new_config["name"] = new_id
                    
                    panel_offset_x, panel_offset_y = self.drag_panel_offsets[original_pid]
                    new_config["grid_x"] = str(snapped_group_grid_x + panel_offset_x)
                    new_config["grid_y"] = str(snapped_group_grid_y + panel_offset_y)

                    config_manager.add_panel_config(new_config['type'], new_config)
                    new_panel = self.create_panel_widget(new_config)
                    if new_panel:
                        self.add_panel(new_panel, new_config)
                        newly_created_ids.add(new_id)
                
                self.selected_panel_ids = newly_created_ids
            else: # Move logic
                for pid_move in self.selected_panel_ids:
                    if pid_move not in self.drag_panel_offsets: continue
                    offset_x_grid, offset_y_grid = self.drag_panel_offsets[pid_move]
                    final_x, final_y = snapped_group_grid_x + offset_x_grid, snapped_group_grid_y + offset_y_grid
                    
                    self.panel_positions[pid_move] = (final_x, final_y)
                    self.move(self.panel_widgets[pid_move], final_x * CELL_SIZE, final_y * CELL_SIZE)
                    
                    self.panel_widgets[pid_move].config["grid_x"] = str(final_x)
                    self.panel_widgets[pid_move].config["grid_y"] = str(final_y)
                    config_manager.update_panel_config(pid_move, self.panel_widgets[pid_move].config)
                
                self._recalculate_container_size()
                self._sort_and_reorder_panels()

        self.drag_active = False
        self._update_selected_panels_visuals()
        
    def is_occupied(self, x, y, w, h, exclude_id=None):
        if x < 0 or y < 0: return True
        rect_to_check_x2, rect_to_check_y2 = x + w, y + h
        for panel_id, (current_x, current_y) in self.panel_positions.items():
            if exclude_id:
                if isinstance(exclude_id, set) and panel_id in exclude_id: continue
                elif panel_id == exclude_id: continue
            
            # Check if the panel being checked has collision enabled
            try:
                panel_config = dict(config_manager.config.items(panel_id))
                collision_enabled = str(panel_config.get("enable_collision", "True")).lower() == 'true'
                if not collision_enabled:
                    continue # This panel doesn't collide, so skip it.
            except Exception:
                pass # Failsafe
            
            current_w, current_h = self.panel_sizes.get(panel_id, (1,1))
            current_x2, current_y2 = current_x + current_w, current_y + current_h
            if (x < current_x2 and rect_to_check_x2 > current_x and
                y < current_y2 and rect_to_check_y2 > current_y):
                return True
        return False
        
    def check_and_update_scrolling_state(self, *args):
        grid_config = config_manager.config["GridLayout"]
        is_enabled = grid_config.get("auto_scroll_on_overflow", "False").lower() == 'true'

        if not self._h_adjustment:
            self.stop_auto_scrolling(reset_position=False)
            return

        content_width = self._get_content_bounding_box()['width']
        viewport_width = self._h_adjustment.get_page_size()
        
        is_overflowing = content_width > viewport_width

        if not is_enabled:
            self.stop_auto_scrolling(reset_position=False)
            return

        if is_overflowing and self._scroll_timer_id is None:
            self._start_auto_scrolling()
        elif not is_overflowing and self._scroll_timer_id is not None:
            self.stop_auto_scrolling(reset_position=True)

    def _start_auto_scrolling(self):
        self.stop_auto_scrolling(reset_position=False) 
        
        grid_config = config_manager.config["GridLayout"]
        interval_sec = float(grid_config.get("auto_scroll_interval_seconds", "5.0"))
        self._current_scroll_page = 0
        self._scroll_timer_id = GLib.timeout_add_seconds(int(interval_sec), self._auto_scroll_callback)

    def stop_auto_scrolling(self, reset_position=False):
        if self._scroll_timer_id is not None:
            GLib.source_remove(self._scroll_timer_id)
            self._scroll_timer_id = None
        
        if self._scroll_animation_id is not None:
            GLib.source_remove(self._scroll_animation_id)
            self._scroll_animation_id = None
        
        if reset_position and self._h_adjustment and self._h_adjustment.get_value() != 0:
            self._animate_scroll_to(0)

    def _auto_scroll_callback(self):
        if not self._h_adjustment:
            self._scroll_timer_id = None
            return GLib.SOURCE_REMOVE

        total_width = self._get_content_bounding_box()['width']
        page_width = self._h_adjustment.get_page_size()
        
        if total_width <= page_width:
            self.stop_auto_scrolling(reset_position=True)
            return GLib.SOURCE_REMOVE

        num_pages = math.ceil(total_width / page_width)
        self._current_scroll_page = (self._current_scroll_page + 1) % num_pages
        
        target_x = self._current_scroll_page * page_width
        target_x = min(target_x, self._h_adjustment.get_upper() - page_width)
        
        self._animate_scroll_to(target_x)
        
        return GLib.SOURCE_CONTINUE

    def _animate_scroll_to(self, target_x):
        if self._scroll_animation_id is not None:
            GLib.source_remove(self._scroll_animation_id)
        
        start_x = self._h_adjustment.get_value()
        distance = target_x - start_x
        if abs(distance) < 1: return

        duration = 500 # ms
        start_time = GLib.get_monotonic_time()

        def animation_step(_user_data):
            elapsed = GLib.get_monotonic_time() - start_time
            progress = min(elapsed / (duration * 1000.0), 1.0)
            
            eased_progress = 1 - pow(1 - progress, 3)
            
            current_pos = start_x + distance * eased_progress
            self._h_adjustment.set_value(current_pos)
            
            if progress >= 1.0:
                self._h_adjustment.set_value(target_x)
                self._scroll_animation_id = None
                return GLib.SOURCE_REMOVE
            return GLib.SOURCE_CONTINUE
        
        self._scroll_animation_id = GLib.timeout_add(16, animation_step, None)

