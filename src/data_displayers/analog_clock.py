# data_displayers/analog_clock.py
import gi
import time
import datetime
import pytz
import cairo
import math
import os
import re

from data_displayer import DataDisplayer
from config_dialog import ConfigOption, build_ui_from_model
from ui_helpers import ScrollingLabel, CustomDialog
from utils import populate_defaults_from_model
from config_manager import config_manager

gi.require_version("Gtk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("Gst", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango, PangoCairo, GdkPixbuf, Gio, Gst

Gst.init(None)

def _draw_clock_hand(context, center_x, center_y, angle, length, width, color_str, shape):
    """Helper function to draw a single clock hand using Cairo."""
    rgba = Gdk.RGBA(); rgba.parse(color_str)
    context.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
    context.set_line_cap(cairo.LINE_CAP_ROUND)
    context.set_line_width(width)
    
    context.save()
    context.translate(center_x, center_y)
    context.rotate(angle)

    if shape == "rectangle":
        context.rectangle(-length * 0.1, -width / 2, length * 1.1, width)
        context.fill()
    elif shape == "pointer":
        context.move_to(-length * 0.1, 0)
        context.line_to(length * 0.9, -width / 2.0)
        context.line_to(length, 0)
        context.line_to(length * 0.9, width / 2.0)
        context.close_path()
        context.fill()
    else: # "line" shape is the default
        context.move_to(-length * 0.15, 0) 
        context.line_to(length, 0)
        context.stroke()
    context.restore()

def _draw_hands(context, center_x, center_y, radius, config, now):
    """Draws the hour, minute, and second hands on the clock face."""
    if not now or radius <= 0: return

    sec_fraction = now.second / 60.0
    min_fraction = (now.minute + sec_fraction) / 60.0
    hour_fraction = ((now.hour % 12) + min_fraction) / 12.0
    sec_angle = sec_fraction * 2 * math.pi - math.pi / 2
    min_angle = min_fraction * 2 * math.pi - math.pi / 2
    hour_angle = hour_fraction * 2 * math.pi - math.pi / 2

    _draw_clock_hand(context, center_x, center_y, hour_angle, radius * 0.5, 6.0, config.get("hour_hand_color"), config.get("hour_hand_shape"))
    _draw_clock_hand(context, center_x, center_y, min_angle, radius * 0.75, 4.0, config.get("minute_hand_color"), config.get("hour_hand_shape"))
    if str(config.get("show_second_hand")).lower() == 'true':
        _draw_clock_hand(context, center_x, center_y, sec_angle, radius * 0.85, 2.0, config.get("second_hand_color"), "line") 
    if str(config.get("show_center_dot")).lower() == 'true':
        rgba = Gdk.RGBA(); rgba.parse(config.get("center_dot_color"))
        context.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        context.arc(center_x, center_y, max(3.0, radius * 0.05), 0, 2 * math.pi); context.fill()

def _draw_markings_and_numbers(context, center_x, center_y, radius, config):
    """Draws the hour marks and numbers on the clock face."""
    roman_numerals = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
    layout = PangoCairo.create_layout(context)
    if not layout: return
    font_desc = Pango.FontDescription.from_string(config.get("clock_number_font"))
    layout.set_font_description(font_desc)
    for i in range(1, 13): 
        angle = (i / 12.0) * (2 * math.pi) - (math.pi / 2) 
        is_cardinal = i in [3, 6, 9, 12] 
        if config.get("clock_marking_position") != 'none' and (config.get("clock_marking_position") == "all_12" or is_cardinal):
            rgba = Gdk.RGBA(); rgba.parse(config.get("clock_marking_color"))
            context.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            len_factor, width_val = (0.08, 3.0) if is_cardinal else (0.04, 2.0)
            outer_r, inner_r = radius * 0.98, radius * 0.98 - (radius * len_factor)
            context.set_line_width(width_val)
            context.move_to(center_x + math.cos(angle) * inner_r, center_y + math.sin(angle) * inner_r)
            context.line_to(center_x + math.cos(angle) * outer_r, center_y + math.sin(angle) * outer_r); context.stroke()
        if config.get("clock_number_position") != 'none' and (config.get("clock_number_position") == "all_12" or is_cardinal):
            num_style = config.get("clock_number_style", "decimal")
            if num_style == "none": continue
            num_str = roman_numerals[i] if num_style == "roman" else str(i)
            layout.set_text(num_str, -1)
            ink, logical = layout.get_pixel_extents()
            num_radius = radius * 0.82 
            num_x, num_y = center_x + math.cos(angle) * num_radius - (logical.width / 2), center_y + math.sin(angle) * num_radius - (logical.height / 2)
            rgba = Gdk.RGBA(); rgba.parse(config.get("clock_number_color"))
            context.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha); context.move_to(num_x, num_y); PangoCairo.show_layout(context, layout)

def _get_label_area_height(context, config):
    """Calculates the total vertical space required for the date and timezone labels."""
    total_height, padding = 0, 4 
    if str(config.get("show_date", "True")).lower() == 'true':
        layout = PangoCairo.create_layout(context)
        font_desc = Pango.FontDescription.from_string(config.get("date_font"))
        layout.set_font_description(font_desc)
        total_height += layout.get_pixel_extents()[1].height
        
    if str(config.get("show_timezone", "True")).lower() == 'true':
        layout = PangoCairo.create_layout(context)
        font_desc = Pango.FontDescription.from_string(config.get("tz_font"))
        layout.set_font_description(font_desc)
        total_height += layout.get_pixel_extents()[1].height
        
    return total_height + padding if total_height > 0 else 0

def _draw_clock_face(context, width, height, config, pixbuf, bottom_margin):
    """Draws the main circular clock face with background (solid, image, or gradient)."""
    center_x, drawable_height = width / 2, height - bottom_margin 
    radius, face_center_y = min(width/2, drawable_height/2), drawable_height / 2
    if radius <= 0: return 
    context.save()
    context.arc(center_x, face_center_y, radius, 0, 2 * math.pi)
    context.clip()
    face_style = config.get("clock_face_style", "solid")
    
    if face_style == "image" and pixbuf:
        img_w, img_h = pixbuf.get_width(), pixbuf.get_height()
        scale = max((2*radius)/img_w, (2*radius)/img_h); context.save()
        context.translate(center_x, face_center_y)
        context.scale(scale, scale)
        context.translate(-img_w/2, -img_h/2)
        Gdk.cairo_set_source_pixbuf(context, pixbuf, 0, 0)
        context.paint_with_alpha(float(config.get("clock_face_image_alpha", 1.0)))
        context.restore()
        
    elif face_style == "gradient_linear":
        c1_str, c2_str, angle = config.get("clock_face_gradient_linear_color1"), config.get("clock_face_gradient_linear_color2"), float(config.get("clock_face_gradient_linear_angle_deg"))
        angle_rad = angle*math.pi/180
        x1, y1 = center_x-radius*math.cos(angle_rad), face_center_y-radius*math.sin(angle_rad)
        x2, y2 = center_x+radius*math.cos(angle_rad), face_center_y+radius*math.sin(angle_rad)
        pat = cairo.LinearGradient(x1, y1, x2, y2)
        c1=Gdk.RGBA(); c1.parse(c1_str)
        c2=Gdk.RGBA(); c2.parse(c2_str)
        pat.add_color_stop_rgba(0, c1.red,c1.green,c1.blue,c1.alpha)
        pat.add_color_stop_rgba(1, c2.red,c2.green,c2.blue,c2.alpha)
        context.set_source(pat)
        context.paint()
        
    elif face_style == "gradient_radial":
        c1_str, c2_str = config.get("clock_face_gradient_radial_color1"), config.get("clock_face_gradient_radial_color2")
        pat = cairo.RadialGradient(center_x, face_center_y, 0, center_x, face_center_y, radius)
        c1=Gdk.RGBA(); c1.parse(c1_str)
        c2=Gdk.RGBA(); c2.parse(c2_str)
        pat.add_color_stop_rgba(0, c1.red,c1.green,c1.blue,c1.alpha)
        pat.add_color_stop_rgba(1, c2.red,c2.green,c2.blue,c2.alpha)
        context.set_source(pat)
        context.paint()
        
    else: # solid color
        rgba = Gdk.RGBA()
        rgba.parse(config.get("clock_face_bg_color"))
        context.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        context.paint()
        
    context.restore() 
    
    if str(config.get("show_clock_border")).lower() == 'true':
        border_width = float(config.get("clock_border_width"))
        rgba = Gdk.RGBA()
        rgba.parse(config.get("clock_border_color"))
        context.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
        context.set_line_width(border_width)
        context.arc(center_x, face_center_y, radius - border_width/2.0, 0, 2*math.pi)
        context.stroke()

def _draw_info_labels(context, width, height, config, date_str, tz_str, bottom_margin):
    """Draws the date and timezone text labels below the clock face."""
    if bottom_margin == 0: return 
    y_pos = height - bottom_margin + 2 
    if str(config.get("show_date", "True")).lower() == 'true':
        
        layout = PangoCairo.create_layout(context)
        font_desc = Pango.FontDescription.from_string(config.get("date_font"))
        layout.set_font_description(font_desc)
        layout.set_text(date_str, -1)
        
        rgba=Gdk.RGBA(); rgba.parse(config.get("date_color"))
        context.set_source_rgba(rgba.red,rgba.green,rgba.blue,rgba.alpha)
        
        x_pos = (width - layout.get_pixel_extents()[1].width) / 2
        context.move_to(x_pos, y_pos)
        PangoCairo.show_layout(context, layout)
        y_pos += layout.get_pixel_extents()[1].height 
        
    if str(config.get("show_timezone", "True")).lower() == 'true':
		
        layout = PangoCairo.create_layout(context)
        font_desc = Pango.FontDescription.from_string(config.get("tz_font"))
        layout.set_font_description(font_desc); layout.set_text(tz_str, -1)
        rgba=Gdk.RGBA(); rgba.parse(config.get("tz_color"))
        context.set_source_rgba(rgba.red,rgba.green,rgba.blue,rgba.alpha)
        x_pos = (width - layout.get_pixel_extents()[1].width) / 2
        context.move_to(x_pos, y_pos)
        PangoCairo.show_layout(context, layout)

class AnalogClockDisplayer(DataDisplayer):

    def __init__(self, panel_ref, config):
        self._cached_face_pixbuf = None
        self._cached_image_path = None
        self._static_surface = None 
        self._last_draw_width, self._last_draw_height = -1, -1
        self._current_time_data = {}
        self._sound_player = None
        self._alarm_sound_bus_id = None
        self._alarm_current_repeat_count = 0
        self._alarm_repeat_count = 0
        self._visual_update_timer_id = None
        self._date_str, self._tz_str = "", ""
        
        super().__init__(panel_ref, config)
        populate_defaults_from_model(self.config, self._get_static_config_model())
        self.widget.connect("realize", self._start_visual_update_timer)
        self.widget.connect("unrealize", self._stop_visual_update_timer)

    def _start_visual_update_timer(self, widget=None):
        self._stop_visual_update_timer() # Ensure no old timer is running
        # Start the self-perpetuating timer loop
        self._reschedule_update()

    def _stop_visual_update_timer(self, widget=None):
        if self._visual_update_timer_id:
            GLib.source_remove(self._visual_update_timer_id)
            self._visual_update_timer_id = None

    def _reschedule_update(self):
        """
        Self-perpetuating timer that redraws the clock and schedules its
        next update precisely at the start of the next second or minute,
        preventing timer drift and ensuring a consistent tick.
        """
        if not self.widget.get_realized():
            self._visual_update_timer_id = None
            return GLib.SOURCE_REMOVE # Stop the loop if widget is gone

        # 1. Redraw the UI immediately.
        self.widget.queue_draw()

        # 2. Determine the delay until the next required update.
        now = datetime.datetime.now()
        show_seconds = str(self.config.get("show_second_hand", "True")).lower() == 'true'

        if show_seconds:
            # Align to the start of the next second.
            delay = 1000 - (now.microsecond // 1000)
        else:
            # Align to the start of the next minute.
            delay = (60 - now.second) * 1000 - (now.microsecond // 1000)

        # 3. Schedule the next call. This timer is a one-shot.
        self._visual_update_timer_id = GLib.timeout_add(delay, self._reschedule_update)
        
        # 4. Tell GLib not to repeat this specific timer event.
        return GLib.SOURCE_REMOVE

    def _create_widget(self):
        self.drawing_area = Gtk.DrawingArea(name="analog-clock-drawing-area", hexpand=True, vexpand=True)
        self.drawing_area.set_draw_func(self.on_draw_clock) 
        click = Gtk.GestureClick.new()
        click.connect("pressed", self._on_drawing_area_clicked)
        self.drawing_area.add_controller(click)
        return self.drawing_area
        
    def _on_drawing_area_clicked(self, gesture, n_press, x, y):
        width, height = self.drawing_area.get_allocated_width(), self.drawing_area.get_allocated_height()
        padding = 5
        
        alarm_icon_size = float(self.config.get("alarm_icon_size"))
        alarm_icon_x, alarm_icon_y = padding, height - alarm_icon_size - padding
        
        timer_icon_size = 24
        timer_icon_x, timer_icon_y = width - timer_icon_size - padding, height - timer_icon_size - padding
        
        if alarm_icon_x <= x <= (alarm_icon_x + alarm_icon_size) and alarm_icon_y <= y <= (alarm_icon_y + alarm_icon_size):
            if self._current_time_data.get("is_alarm_ringing"): 
                self._disable_ringing_alarm()
            else:
                self._show_alarm_management_dialog()
        elif timer_icon_x <= x <= (timer_icon_x + timer_icon_size) and timer_icon_y <= y <= (timer_icon_y + timer_icon_size):
            if self._current_time_data.get("is_timer_ringing"):
                self.panel_ref.data_source.stop_ringing_timer()
                self.panel_ref.exit_alarm_state()
                if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
                self.drawing_area.queue_draw()
            else:
                self._show_timer_management_dialog()
            
    def _disable_ringing_alarm(self):
        """Disables the currently ringing alarm in the config and stops it."""
        if not self._current_time_data.get("datetime"):
            return

        if self._sound_player:
            self._sound_player.set_state(Gst.State.NULL)
        if hasattr(self.panel_ref.data_source, 'stop_ringing_alarms'):
            self.panel_ref.data_source.stop_ringing_alarms()
        self.panel_ref.exit_alarm_state()

        now = self._current_time_data["datetime"]
        current_time_hm = now.strftime("%H:%M")
        
        all_alarms = self.panel_ref.data_source._parse_alarms_from_config()
        
        config_changed = False
        for alarm in all_alarms:
            if alarm['time'] == current_time_hm and alarm['enabled']:
                alarm['enabled'] = False
                config_changed = True

        if config_changed:
            new_alarms_str = ";".join(
                f"{a['time']},{str(a['enabled']).lower()}" for a in all_alarms
            )
            self.config["alarms"] = new_alarms_str
            config_manager.update_panel_config(self.config["id"], self.config)
            config_manager.save()
            
            self.panel_ref.data_source.force_update()
            self.drawing_area.queue_draw()
        
    @staticmethod
    def get_config_model():
        return {}

    @staticmethod
    def _get_static_config_model():
        face_styles = {"Solid Color": "solid", "Image Background": "image", "Linear Gradient": "gradient_linear", "Radial Gradient": "gradient_radial"}
        marking_styles = {"All 12": "all_12", "Cardinal (3,6,9,12)": "cardinal_4", "None": "none"}
        number_styles = {"Decimal (1,2,3)": "decimal", "Roman (I,II,III)": "roman", "None": "none"}
        hand_shapes = {"Line": "line", "Rectangle": "rectangle", "Pointer": "pointer"}
        sound_file_filters = [{"name": "Audio Files", "patterns": ["*.mp3", "*.wav", "*.ogg", "*.flac"]}, {"name": "All Files", "patterns": ["*"]}]
        image_file_filters = [{"name": "Image Files", "patterns": ["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.svg"]}, {"name": "All Files", "patterns": ["*"]}]

        return {
            "Clock Face": [ ConfigOption("clock_face_style", "dropdown", "Style:", "solid", options_dict=face_styles) ],
            "Face Options (Solid)": [ ConfigOption("clock_face_bg_color", "color", "Color:", "rgba(40,40,40,1)") ],
            "Face Options (Image)": [
                ConfigOption("clock_face_image_path", "file", "Image File:", "", file_filters=image_file_filters),
                ConfigOption("clock_face_image_alpha", "scale", "Image Opacity:", 1.0, 0.0, 1.0, 0.05, 2)
            ],
            "Face Options (Linear Gradient)": [
                ConfigOption("clock_face_gradient_linear_color1", "color", "Start Color:", "rgba(220,220,240,1)"),
                ConfigOption("clock_face_gradient_linear_color2", "color", "End Color:", "rgba(200,200,220,1)"),
                ConfigOption("clock_face_gradient_linear_angle_deg", "spinner", "Angle (°):", 90.0, 0, 359, 1, 0),
            ],
            "Face Options (Radial Gradient)": [
                ConfigOption("clock_face_gradient_radial_color1", "color", "Center Color:", "rgba(250,250,250,1)"),
                ConfigOption("clock_face_gradient_radial_color2", "color", "Edge Color:", "rgba(200,200,200,1)"),
            ],
            "Labels": [
                ConfigOption("show_date", "bool", "Show Date Label", "True"),
                ConfigOption("date_font", "font", "Date Font:", "Sans 8"),
                ConfigOption("date_color", "color", "Date Color:", "rgba(200,200,200,1)"),
                ConfigOption("show_timezone", "bool", "Show Timezone Label", "True"),
                ConfigOption("tz_font", "font", "Timezone Font:", "Sans Italic 8"),
                ConfigOption("tz_color", "color", "Timezone Color:", "rgba(180,180,180,1)"), 
            ],
            "Border, Marks & Numbers": [
                ConfigOption("show_clock_border", "bool", "Show Border", "True"),
                ConfigOption("clock_border_color", "color", "Border Color:", "rgba(200,200,200,0.8)"),
                ConfigOption("clock_border_width", "scale", "Border Width (px):", 2.0, 0.5, 10, 0.5, 1),
                ConfigOption("clock_marking_position", "dropdown", "Show Marks:", "all_12", options_dict=marking_styles),
                ConfigOption("clock_marking_color", "color", "Marks Color:", "rgba(220,220,220,1.0)"),
                ConfigOption("clock_number_position", "dropdown", "Show Numbers:", "all_12", options_dict=marking_styles),
                ConfigOption("clock_number_style", "dropdown", "Number Style:", "decimal", options_dict=number_styles),
                ConfigOption("clock_number_color", "color", "Number Color:", "rgba(220,220,220,1.0)"),
                ConfigOption("clock_number_font", "font", "Number Font:", "Sans 10"),
            ],
            "Hands & Center Dot": [
                ConfigOption("hour_hand_shape", "dropdown", "Hour Hand Shape:", "rectangle", options_dict=hand_shapes),
                ConfigOption("hour_hand_color", "color", "Hour Hand Color:", "rgba(220,220,220,1.0)"),
                ConfigOption("minute_hand_color", "color", "Minute Hand Color:", "rgba(220,220,220,1.0)"),
                ConfigOption("show_second_hand", "bool", "Show Second Hand", "True"),
                ConfigOption("second_hand_color", "color", "Second Hand Color:", "rgba(255,0,0,0.9)"),
                ConfigOption("show_center_dot", "bool", "Show Center Dot", "True"),
                ConfigOption("center_dot_color", "color", "Center Dot Color:", "rgba(220,220,220,1.0)"),
            ],
            "Alarm Settings": [
                ConfigOption("alarm_color", "color", "Panel Flash Color:", "rgba(255, 215, 0, 0.7)"), 
                ConfigOption("alarm_sound_file", "file", "Alarm Sound File:", "", tooltip="Select a sound file (WAV, MP3, OGG)", file_filters=sound_file_filters),
                ConfigOption("alarm_repeat_count", "spinner", "Repeat Sound (times):", 1, 0, 10, 1, 0),
                ConfigOption("alarm_icon_size", "spinner", "Icon Size (px):", 20, 12, 48, 1, 0),
                ConfigOption("alarm_icon_base_color", "color", "Icon Base Color:", "rgba(128,128,128,0.7)"),
                ConfigOption("alarm_icon_set_color", "color", "Icon Alarm Set Color:", "rgba(255,255,255,0.9)"),
                ConfigOption("alarm_icon_ringing_color", "color", "Icon Ringing Color:", "rgba(255,0,0,1.0)"),
            ],
            "Timer Settings": [
                ConfigOption("timer_sound_file", "file", "Timer Sound File:", "", tooltip="Select a sound file (WAV, MP3, OGG)", file_filters=sound_file_filters),
                ConfigOption("timer_flash_color", "color", "Timer Panel Flash Color:", "rgba(0, 200, 255, 0.7)"),
                ConfigOption("timer_icon_color", "color", "Timer Icon Color:", "rgba(200, 200, 200, 0.8)"),
                ConfigOption("timer_countdown_font", "font", "Countdown Font:", "Sans Bold 10"),
                ConfigOption("timer_countdown_color", "color", "Countdown Color:", "rgba(255, 255, 255, 1.0)"),
            ]
        }

    def get_configure_callback(self):
        """A custom callback to build the specialized config UI for the clock."""
        def build_clock_config_tab(dialog, content_box, widgets, available_sources, panel_config):
            full_model = self._get_static_config_model()
            dialog.dynamic_models.append(full_model)

            section_to_id_map = {
                "Face Options (Solid)": "solid", "Face Options (Image)": "image",
                "Face Options (Linear Gradient)": "gradient_linear", "Face Options (Radial Gradient)": "gradient_radial",
            }

            dynamic_face_sections = {k: v for k, v in full_model.items() if k.startswith("Face Options")}
            static_sections = {k: v for k, v in full_model.items() if not k.startswith("Face Options") and k != "Clock Face"}
            
            build_ui_from_model(content_box, self.config, static_sections, widgets)
            
            face_section_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10)
            build_ui_from_model(face_section_box, self.config, {"Clock Face": full_model["Clock Face"]}, widgets)
            
            stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.SLIDE_LEFT_RIGHT, margin_top=4)
            face_section_box.append(stack)

            for section_title, options in dynamic_face_sections.items():
                page_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
                style_key = section_to_id_map.get(section_title)
                if style_key:
                    build_ui_from_model(page_box, self.config, {section_title: options}, widgets)
                    stack.add_titled(page_box, style_key, section_title)
            
            content_box.append(face_section_box)
            
            def on_face_style_changed(combo):
                active_id = combo.get_active_id()
                if active_id: stack.set_visible_child_name(active_id)
            
            face_style_combo = widgets.get("clock_face_style")
            if face_style_combo:
                face_style_combo.connect("changed", on_face_style_changed)
                GLib.idle_add(on_face_style_changed, face_style_combo)

            alarm_file_widget = widgets.get("alarm_sound_file")
            if alarm_file_widget:
                alarm_section_box = alarm_file_widget.get_parent().get_parent()
                if alarm_section_box and isinstance(alarm_section_box, Gtk.Box):
                    preview_sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL, margin_top=8, margin_bottom=4)
                    preview_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                    preview_vbox.append(Gtk.Label(label="Sound Preview:", xalign=0))
                    controls_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
                    btn = Gtk.Button(icon_name="media-playback-start-symbolic")
                    bar = Gtk.ProgressBar(show_text=True, hexpand=True)
                    controls_row.append(btn); controls_row.append(bar); preview_vbox.append(controls_row)
                    alarm_section_box.append(preview_sep); alarm_section_box.append(preview_vbox)

                    player_data = {'player': None, 'is_playing': False, 'progress_timer_id': None}
                    def _update_progress_bar():
                        if not player_data.get('is_playing') or not player_data.get('player'): return GLib.SOURCE_REMOVE
                        ret, duration = player_data['player'].query_duration(Gst.Format.TIME)
                        if not ret: return GLib.SOURCE_CONTINUE
                        ret, position = player_data['player'].query_position(Gst.Format.TIME)
                        if ret and duration > 0:
                            fraction, pos_sec, dur_sec = position / duration, position // Gst.SECOND, duration // Gst.SECOND
                            bar.set_fraction(fraction); bar.set_text(f"{pos_sec//60:02d}:{pos_sec%60:02d} / {dur_sec//60:02d}:{dur_sec%60:02d}")
                        return GLib.SOURCE_CONTINUE

                    def stop_playback(clear_text=True):
                        if player_data.get('player'): player_data['player'].set_state(Gst.State.NULL)
                        if player_data.get('progress_timer_id'): GLib.source_remove(player_data['progress_timer_id']); player_data['progress_timer_id'] = None
                        btn.set_icon_name("media-playback-start-symbolic"); player_data['is_playing'] = False
                        bar.set_fraction(0); 
                        if clear_text: bar.set_text("N/A")

                    def on_msg(bus, msg):
                        if msg.type in (Gst.MessageType.EOS, Gst.MessageType.ERROR): GLib.idle_add(stop_playback, False)
                        return True

                    def on_play_clicked(_):
                        if player_data['is_playing']: stop_playback()
                        else:
                            path = widgets.get("alarm_sound_file").get_text() if "alarm_sound_file" in widgets else ""
                            if not path or not os.path.exists(path): bar.set_text("Select a file"); return
                            if not player_data.get('player'):
                                player_data['player'] = Gst.ElementFactory.make("playbin", "preview")
                                player_data['player'].get_bus().add_watch(GLib.PRIORITY_DEFAULT, on_msg)
                            
                            player_data['player'].set_property("uri", GLib.filename_to_uri(path, None))
                            player_data['player'].set_state(Gst.State.PLAYING); btn.set_icon_name("media-playback-stop-symbolic")
                            player_data['is_playing'] = True
                            player_data['progress_timer_id'] = GLib.timeout_add(200, _update_progress_bar)
                    
                    btn.connect("clicked", on_play_clicked)
                    dialog.connect("destroy", lambda d: stop_playback())

        return build_clock_config_tab

    def apply_styles(self):
        super().apply_styles()
        image_path = self.config.get("clock_face_image_path", "")
        if self._cached_image_path != image_path:
            self._cached_image_path = image_path
            self._cached_face_pixbuf = GdkPixbuf.Pixbuf.new_from_file(image_path) if image_path and os.path.exists(image_path) else None
        
        # Invalidate cache and restart timer to apply new settings (e.g. show/hide second hand)
        self._static_surface = None
        if self.widget.get_realized():
            self._start_visual_update_timer()
        self.drawing_area.queue_draw()
    
    def update_display(self, data):
        if not self.panel_ref: return
        if not data: return 
        self._current_time_data = data 
        if self.panel_ref and self.panel_ref.data_source:
            self._date_str = self.panel_ref.data_source.get_primary_label_string(data)
            self._tz_str = self.panel_ref.data_source.get_secondary_display_string(data)
        
        is_alarm_ringing = data.get("is_alarm_ringing", False)
        is_timer_ringing = data.get("is_timer_ringing", False)
        
        if (is_alarm_ringing or is_timer_ringing) and not self.panel_ref.is_in_alarm_state:
            flash_color = self.config.get("timer_flash_color") if is_timer_ringing else self.config.get("alarm_color")
            self.panel_ref.enter_alarm_state(flash_color)
            if is_alarm_ringing: self._play_alarm_sound()
            if is_timer_ringing: self._play_timer_sound()
        elif not is_alarm_ringing and not is_timer_ringing and self.panel_ref.is_in_alarm_state:
            self.panel_ref.exit_alarm_state()
            if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
    
    def on_draw_clock(self, area, context, width, height):
        if width <= 0 or height <= 0: return 
        bottom_margin = _get_label_area_height(context, self.config)
        if not self._static_surface or self._last_draw_width != width or self._last_draw_height != height:
            self._static_surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            static_ctx = cairo.Context(self._static_surface)
            static_ctx.set_operator(cairo.OPERATOR_SOURCE)
            static_ctx.set_source_rgba(0,0,0,0)
            static_ctx.paint()
            static_ctx.set_operator(cairo.OPERATOR_OVER)
            _draw_clock_face(static_ctx, width, height, self.config, self._cached_face_pixbuf, bottom_margin)
            _draw_markings_and_numbers(static_ctx, width/2, (height-bottom_margin)/2, min(width/2,(height-bottom_margin)/2), self.config)
            self._last_draw_width, self._last_draw_height = width, height
            
        context.set_source_surface(self._static_surface, 0, 0)
        context.paint()
        
        now = self._current_time_data.get("datetime")
        
        _draw_hands(context, width/2, (height-bottom_margin)/2, min(width/2,(height-bottom_margin)/2), self.config, now)
        _draw_info_labels(context, width, height, self.config, self._date_str, self._tz_str, bottom_margin)
        
        alarm_icon_size=float(self.config.get("alarm_icon_size"))
        padding=5
        alarm_icon_x, alarm_icon_y = padding, height-alarm_icon_size-padding
        context.save()
        context.translate(alarm_icon_x, alarm_icon_y)
        self._draw_alarm_icon(area, context, alarm_icon_size, alarm_icon_size)
        context.restore()

        self._draw_timer_indicator(context, width, height)
        
    def close(self):
        super().close(); self._stop_visual_update_timer() 
        if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
        if self._alarm_sound_bus_id: GLib.source_remove(self._alarm_sound_bus_id); self._alarm_sound_bus_id = None
        
    def _show_alarm_management_dialog(self):
        dialog = CustomDialog(parent=self.panel_ref.get_ancestor(Gtk.Window), title="Manage Alarms", modal=True)
        dialog.set_default_size(350, 400)
        content_area = dialog.get_content_area()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        content_area.append(vbox)
        scrolled = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        list_box = Gtk.ListBox()
        scrolled.set_child(list_box)
        vbox.append(scrolled)
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, halign=Gtk.Align.CENTER)
        vbox.append(add_box)
        now = datetime.datetime.now()
        
        hour_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=now.hour, lower=0, upper=23, step_increment=1))
        minute_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=now.minute, lower=0, upper=59, step_increment=1))
        add_box.append(Gtk.Label(label="New:"))
        add_box.append(hour_spin)
        add_box.append(Gtk.Label(label=":"))
        add_box.append(minute_spin)
        add_btn = Gtk.Button(icon_name="list-add-symbolic")
        add_box.append(add_btn)
        
        def build_row(data):
            row=Gtk.ListBoxRow()
            hbox=Gtk.Box(spacing=10,margin_top=5,margin_bottom=5,margin_start=5,margin_end=5)
            row.set_child(hbox)
            label=Gtk.Label(label=data['time'],hexpand=True,xalign=0)
            switch=Gtk.Switch(active=data['enabled'], valign=Gtk.Align.CENTER)
            del_btn=Gtk.Button(icon_name="edit-delete-symbolic")
            hbox.append(label)
            hbox.append(switch)
            hbox.append(del_btn)
            switch.connect("notify::active", lambda s, _: setattr(row, 'alarm_enabled', s.get_active())); del_btn.connect("clicked", lambda b: list_box.remove(row))
            row.alarm_time=data['time']; row.alarm_enabled=data['enabled']; return row
        
        for alarm in self.panel_ref.data_source._parse_alarms_from_config(): list_box.append(build_row(alarm))
        
        def on_add(_):
            time_str=f"{hour_spin.get_value_as_int():02d}:{minute_spin.get_value_as_int():02d}"
            if not any(r.alarm_time == time_str for r in list(list_box)):
                list_box.append(build_row({"time":time_str, "enabled":True}))
        
        add_btn.connect("clicked", on_add)
        dialog.add_styled_button("_Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_styled_button("_Accept", Gtk.ResponseType.ACCEPT, "suggested-action", True)
        
        if dialog.run() == Gtk.ResponseType.ACCEPT:
            new_alarms_str = ";".join(f"{r.alarm_time},{str(r.alarm_enabled).lower()}" for r in sorted(list(list_box), key=lambda r:r.alarm_time))
            if self.config.get("alarms") != new_alarms_str:
                self.config["alarms"] = new_alarms_str
                config_manager.update_panel_config(self.config["id"], self.config)
                self.panel_ref.data_source.force_update()
                if not self.panel_ref.data_source.get_data().get('is_alarm_ringing'):
                    self.panel_ref.exit_alarm_state()
                    if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
                self.drawing_area.queue_draw()
        dialog.destroy()
        
    def _play_alarm_sound(self):
        sound_file = self.config.get("alarm_sound_file"); repeat = int(self.config.get("alarm_repeat_count",1))
        self._play_sound(sound_file, repeat)

    def _play_timer_sound(self):
        sound_file = self.config.get("timer_sound_file")
        self._play_sound(sound_file, 999)

    def _play_sound(self, sound_file, repeat):
        if not sound_file or not os.path.exists(sound_file) or repeat < 1: return
        if self._sound_player and self._sound_player.get_state(0).state == Gst.State.PLAYING: self._sound_player.set_state(Gst.State.NULL)
        self._alarm_current_repeat_count = 0; self._alarm_repeat_count = repeat
        
        def start_playback():
            if not self.panel_ref.is_in_alarm_state:
                 if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
                 return False
            if self._alarm_current_repeat_count >= self._alarm_repeat_count:
                if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
                if self._alarm_sound_bus_id: GLib.source_remove(self._alarm_sound_bus_id); self._alarm_sound_bus_id=None
                return False
            if not self._sound_player:
                self._sound_player = Gst.ElementFactory.make("playbin", "alarm_player"); bus = self._sound_player.get_bus()
                self._alarm_sound_bus_id = bus.add_watch(GLib.PRIORITY_DEFAULT, self._on_alarm_bus_message)
            
            self._sound_player.set_property("uri", GLib.filename_to_uri(sound_file, None))
            self._sound_player.set_state(Gst.State.PLAYING)
            self._alarm_current_repeat_count += 1
            return False
        GLib.idle_add(start_playback)
        
    def _on_alarm_bus_message(self, bus, msg):
        if msg.type == Gst.MessageType.EOS:
            if self._alarm_current_repeat_count < self._alarm_repeat_count:
                self._sound_player.seek_simple(Gst.Format.TIME, Gst.SeekFlags.FLUSH | Gst.SeekFlags.KEY_UNIT, 0)
                self._sound_player.set_state(Gst.State.PLAYING)
            else:
                if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
        elif msg.type == Gst.MessageType.ERROR:
            err, debug = msg.parse_error(); print(f"GStreamer Error: {err}, {debug}")
            if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
        return True

    def _draw_timer_indicator(self, ctx, width, height):
        padding = 5
        icon_size = 24
        x = width - icon_size - padding
        y = height - icon_size - padding
        
        ctx.save()
        ctx.translate(x, y)
        
        data = self._current_time_data
        if data.get("is_timer_running") or data.get("is_timer_ringing"):
            remaining = data.get("timer_remaining_seconds")
            if remaining is None: remaining = 0
            
            mins, secs = divmod(int(remaining), 60)
            text = f"{mins:02d}:{secs:02d}"
            
            layout = PangoCairo.create_layout(ctx)
            font_desc = Pango.FontDescription.from_string(self.config.get("timer_countdown_font"))
            layout.set_font_description(font_desc)
            layout.set_text(text, -1)
            _, log = layout.get_pixel_extents()
            
            rgba = Gdk.RGBA(); rgba.parse(self.config.get("timer_countdown_color"))
            ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            ctx.move_to((icon_size - log.width)/2, (icon_size - log.height)/2)
            PangoCairo.show_layout(ctx, layout)
            
        else: # Draw bell icon
            rgba = Gdk.RGBA(); rgba.parse(self.config.get("timer_icon_color"))
            ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            ctx.set_line_width(1.5)
            
            ctx.move_to(icon_size * 0.2, icon_size * 0.8)
            ctx.curve_to(icon_size * 0.2, icon_size * 0.4, icon_size * 0.8, icon_size * 0.4, icon_size * 0.8, icon_size * 0.8)
            ctx.close_path()
            ctx.stroke()
            ctx.arc(icon_size * 0.5, icon_size * 0.8, icon_size * 0.05, 0, 2 * math.pi)
            ctx.fill()
            ctx.move_to(icon_size * 0.4, icon_size * 0.3)
            ctx.curve_to(icon_size * 0.4, icon_size * 0.2, icon_size * 0.6, icon_size * 0.2, icon_size * 0.6, icon_size * 0.3)
            ctx.stroke()

        ctx.restore()

    def _show_timer_management_dialog(self):
        data_source = self.panel_ref.data_source
        dialog = CustomDialog(parent=self.panel_ref.get_ancestor(Gtk.Window), title="Set Timer", modal=True)
        content_area = dialog.get_content_area()
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, margin_top=15, margin_bottom=15, margin_start=15, margin_end=15)
        content_area.append(vbox)

        # FIX 1: Read from the safe, cached data instead of the live data_source.
        if self._current_time_data.get("is_timer_running") or self._current_time_data.get("is_timer_ringing"):
            vbox.append(Gtk.Label(label="A timer is currently active."))
            # FIX 2: Use a valid Gtk.ResponseType member, like REJECT.
            stop_btn = dialog.add_styled_button("_Stop Timer", Gtk.ResponseType.REJECT, "destructive-action")
        else:
            grid = Gtk.Grid(column_spacing=10, row_spacing=5)
            vbox.append(grid)
            
            h_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=0, lower=0, upper=23, step_increment=1))
            m_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=5, lower=0, upper=59, step_increment=1))
            s_spin = Gtk.SpinButton(adjustment=Gtk.Adjustment(value=0, lower=0, upper=59, step_increment=1))
            
            grid.attach(Gtk.Label(label="Hours:", xalign=1), 0, 0, 1, 1)
            grid.attach(h_spin, 1, 0, 1, 1)
            grid.attach(Gtk.Label(label="Minutes:", xalign=1), 0, 1, 1, 1)
            grid.attach(m_spin, 1, 1, 1, 1)
            grid.attach(Gtk.Label(label="Seconds:", xalign=1), 0, 2, 1, 1)
            grid.attach(s_spin, 1, 2, 1, 1)
            
            start_btn = dialog.add_styled_button("_Start Timer", Gtk.ResponseType.ACCEPT, "suggested-action", True)
            
            def on_spin_changed(spin):
                h = h_spin.get_value_as_int()
                m = m_spin.get_value_as_int()
                s = s_spin.get_value_as_int()
                start_btn.set_sensitive((h + m + s) > 0)
            
            h_spin.connect("value-changed", on_spin_changed)
            m_spin.connect("value-changed", on_spin_changed)
            s_spin.connect("value-changed", on_spin_changed)

        dialog.add_styled_button("_Cancel", Gtk.ResponseType.CANCEL)
        
        response = dialog.run()
        
        if response == Gtk.ResponseType.ACCEPT:
            h = h_spin.get_value_as_int()
            m = m_spin.get_value_as_int()
            s = s_spin.get_value_as_int()
            total_seconds = h * 3600 + m * 60 + s
            data_source.start_timer(total_seconds)
        # FIX 3: Check for the corrected ResponseType here as well.
        elif response == Gtk.ResponseType.REJECT:
            data_source.cancel_timer()
            self.panel_ref.exit_alarm_state()
            if self._sound_player: self._sound_player.set_state(Gst.State.NULL)
        
        dialog.destroy()
        self.drawing_area.queue_draw()

