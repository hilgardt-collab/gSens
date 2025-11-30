# /data_displayers/lcars_draw.py
import gi
import math
import cairo
from utils import populate_defaults_from_model
from .level_bar import LevelBarDisplayer
from .graph import GraphDisplayer
from .static import StaticDisplayer
from .cpu_multicore import CpuMultiCoreDisplayer

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, Pango, PangoCairo

class LcarsDrawMixin:
    """
    Mixin for LCARSComboDisplayer that handles all Cairo drawing logic.
    Assumes access to self.config, self.data_bundle, self._drawer_instances, 
    and other state variables initialized in the main class.
    """

    def _create_pango_layout(self, ctx, text, font_str):
        cache_key = f"{text}_{font_str}"
        layout = self._static_layout_cache.get(cache_key)
        if layout is None:
            layout = PangoCairo.create_layout(ctx)
            font_str = font_str or "Sans 12"
            layout.set_font_description(Pango.FontDescription.from_string(font_str))
            layout.set_text(text, -1)
            self._static_layout_cache[cache_key] = layout
        return layout

    def _draw_frame_and_sidebar(self, ctx, width, height):
        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        radius = float(self.config.get("lcars_corner_radius", 60))
        frame_color_str = self.config.get("lcars_frame_color", "rgba(255,153,102,1)")
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        ext_style = self.config.get("lcars_extension_corner_style", "square")
        
        top_bar_h = float(self.config.get("lcars_top_bar_height", 40))
        bottom_ext_h = float(self.config.get("lcars_bottom_extension_height", 40))
        
        has_top_ext = mode in ["top", "both"]
        has_bottom_ext = mode in ["bottom", "both"]
        
        r_top = top_bar_h / 2
        r_bot = bottom_ext_h / 2

        ctx.new_path()
        ctx.move_to(0, radius) 
        ctx.arc(radius, radius, radius, math.pi, 1.5 * math.pi)

        if has_top_ext:
            ctx.line_to(width - r_top, 0)
            if ext_style == "round" and r_top > 0:
                ctx.arc(width - r_top, r_top, r_top, 1.5 * math.pi, 0.5 * math.pi)
            else:
                ctx.line_to(width, 0); ctx.line_to(width, top_bar_h)
            ctx.line_to(sidebar_w + radius, top_bar_h)
            ctx.arc_negative(sidebar_w + radius, top_bar_h + radius, radius, 1.5 * math.pi, math.pi)
        else:
            ctx.line_to(sidebar_w, 0)
            
        end_y_inner = height - bottom_ext_h - radius if has_bottom_ext else height
        ctx.line_to(sidebar_w, end_y_inner)

        if has_bottom_ext:
            ctx.arc_negative(sidebar_w + radius, height - bottom_ext_h - radius, radius, math.pi, 0.5 * math.pi)
            if ext_style == "round" and r_bot > 0:
                ctx.line_to(width - r_bot, height - bottom_ext_h)
                ctx.arc(width - r_bot, height - r_bot, r_bot, 1.5 * math.pi, 0.5 * math.pi)
            else:
                ctx.line_to(width, height - bottom_ext_h); ctx.line_to(width, height)
            ctx.line_to(radius, height)
        else:
            ctx.line_to(sidebar_w, height); ctx.line_to(radius, height)

        ctx.arc(radius, height - radius, radius, 0.5 * math.pi, math.pi) 
        ctx.close_path()

        frame_color = Gdk.RGBA(); frame_color.parse(frame_color_str)
        ctx.set_source_rgba(frame_color.red, frame_color.green, frame_color.blue, frame_color.alpha)
        ctx.fill()
        
        top_header_pos = self.config.get("lcars_top_header_position", "top")
        bottom_header_pos = self.config.get("lcars_bottom_header_position", "none")

        if top_header_pos == "top" and has_top_ext: self._draw_header_bar(ctx, width, height, is_top=True)
        if bottom_header_pos == "bottom" and has_bottom_ext: self._draw_header_bar(ctx, width, height, is_top=False)
            
        self._draw_sidebar_segments(ctx, width, height)

    def _draw_header_bar(self, ctx, width, height, is_top):
        prefix = "top" if is_top else "bottom"
        bar_h = float(self.config.get("lcars_top_bar_height" if is_top else "lcars_bottom_extension_height", 40))
        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        radius = float(self.config.get("lcars_corner_radius", 60))
        padding = float(self.config.get(f"lcars_{prefix}_header_padding", 10))
        shape = self.config.get(f"lcars_{prefix}_header_shape", "pill")
        align = self.config.get(f"lcars_{prefix}_header_align", "left")
        width_mode = self.config.get(f"lcars_{prefix}_header_width_mode", "full")
        text = self.config.get(f"lcars_{prefix}_header_text", "").upper()
        
        bar_content_h = bar_h - (2 * padding)
        if bar_content_h <= 0: return
        
        layout = self._create_pango_layout(ctx, text, self.config.get(f"lcars_{prefix}_header_font"))
        _, log = layout.get_pixel_extents()

        if width_mode == "fit": bar_w = log.width + (padding * 2) + (bar_content_h if shape == 'pill' else 0)
        else: bar_w = width - (sidebar_w + radius + padding) - padding

        if bar_w <= 0: return
        
        bar_y = padding if is_top else height - bar_h + padding
        if align == "right": bar_x = width - padding - bar_w
        elif align == "center":
            available_space = width - (sidebar_w + radius + padding) - padding
            bar_x = sidebar_w + radius + padding + (available_space - bar_w) / 2
        else: bar_x = sidebar_w + radius + padding
            
        bar_radius = bar_content_h / 2
        ctx.new_path()
        if shape == "square": ctx.rectangle(bar_x, bar_y, bar_w, bar_content_h)
        else:
            ctx.arc(bar_x + bar_radius, bar_y + bar_radius, bar_radius, 0.5 * math.pi, 1.5 * math.pi)
            ctx.arc(bar_x + bar_w - bar_radius, bar_y + bar_radius, bar_radius, 1.5 * math.pi, 0.5 * math.pi)
            ctx.close_path()
        
        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get(f"lcars_{prefix}_header_bg_color"))
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha); ctx.fill()
        
        text_rgba = Gdk.RGBA(); text_rgba.parse(self.config.get(f"lcars_{prefix}_header_color"))
        ctx.set_source_rgba(text_rgba.red, text_rgba.green, text_rgba.blue, text_rgba.alpha)
        
        ctx.move_to(bar_x + (bar_w - log.width) / 2, bar_y + (bar_content_h - log.height) / 2)
        PangoCairo.show_layout(ctx, layout)
        
    def _draw_sidebar_segments(self, ctx, width, height):
        num_segments = int(self.config.get("lcars_segment_count", 3))
        if num_segments == 0: return

        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        
        top_bar_h = float(self.config.get("lcars_top_bar_height", 40)) if mode in ["top", "both"] else 0
        bottom_ext_h = float(self.config.get("lcars_bottom_extension_height", 40)) if mode in ["bottom", "both"] else 0
        
        available_h = height - top_bar_h - bottom_ext_h
        total_weight = sum(float(self.config.get(f"segment_{i}_height_weight", 1)) for i in range(1, num_segments + 1)) or 1
        current_y = top_bar_h

        for i in range(1, num_segments + 1):
            weight = float(self.config.get(f"segment_{i}_height_weight", 1))
            seg_h = (weight / total_weight) * available_h if total_weight > 0 else 0
            seg_color = Gdk.RGBA(); seg_color.parse(self.config.get(f"segment_{i}_color", "rgba(200,100,100,1)"))
            ctx.set_source_rgba(seg_color.red, seg_color.green, seg_color.blue, seg_color.alpha)
            ctx.rectangle(0, current_y, sidebar_w, seg_h); ctx.fill()
            
            ctx.set_source_rgba(0,0,0,1); ctx.set_line_width(2)
            if i < num_segments: ctx.move_to(0, current_y + seg_h); ctx.line_to(sidebar_w, current_y + seg_h); ctx.stroke()
            
            label_text = self.config.get(f"segment_{i}_label", "").upper()
            layout = self._create_pango_layout(ctx, label_text, self.config.get(f"segment_{i}_font"))
            _, log = layout.get_pixel_extents()
            
            text_rgba = Gdk.RGBA(); text_rgba.parse(self.config.get(f"segment_{i}_label_color"))
            ctx.set_source_rgba(text_rgba.red, text_rgba.green, text_rgba.blue, text_rgba.alpha)
            ctx.move_to(sidebar_w - log.width - 5, current_y + seg_h - log.height - 5); PangoCairo.show_layout(ctx, layout)
            current_y += seg_h

    def _draw_content_widgets(self, ctx, width, height):
        mode = self.config.get("lcars_sidebar_extension_mode", "top")
        top_bar_h = float(self.config.get("lcars_top_bar_height", 40)) if mode in ["top", "both"] else 0
        bottom_ext_h = float(self.config.get("lcars_bottom_extension_height", 40)) if mode in ["bottom", "both"] else 0
        
        sidebar_w = float(self.config.get("lcars_sidebar_width", 150))
        padding = float(self.config.get("lcars_content_padding", 5))
        
        content_x = sidebar_w + padding
        content_y = top_bar_h + padding
        content_w = width - content_x - padding
        content_h = height - top_bar_h - bottom_ext_h - (2 * padding)

        if content_w <= 0 or content_h <= 0: return
        
        ctx.save(); ctx.rectangle(content_x, content_y, content_w, content_h); ctx.clip()
        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get("lcars_content_bg_color"))
        ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha); ctx.paint()

        num_primary = int(self.config.get("number_of_primary_sources", 1))
        num_secondary = int(self.config.get("number_of_secondary_sources", 4))
        
        show_split_view = str(self.config.get("lcars_split_screen_enabled", "False")).lower() == 'true'
        
        if show_split_view:
            divider_orientation = self.config.get("lcars_split_screen_orientation", "vertical")
            sb_width = float(self.config.get("lcars_split_screen_divider_width", 10))
            split_ratio = float(self.config.get("lcars_split_screen_ratio", 0.5))
            cap_style_start = self.config.get("lcars_split_screen_divider_cap_start", "square")
            cap_style_end = self.config.get("lcars_split_screen_divider_cap_end", "square")
            spacing_before = float(self.config.get("lcars_split_screen_spacing_before", 0))
            spacing_after = float(self.config.get("lcars_split_screen_spacing_after", 0))

            sb_color_str = self.config.get("lcars_split_screen_divider_color") or self.config.get("lcars_frame_color", "rgba(255,153,102,1)")
            sb_color = Gdk.RGBA(); sb_color.parse(sb_color_str)
            ctx.set_source_rgba(sb_color.red, sb_color.green, sb_color.blue, sb_color.alpha)

            if divider_orientation == "horizontal":
                total_divider_height = sb_width + spacing_before + spacing_after
                available_h = content_h - total_divider_height
                top_h = available_h * split_ratio
                bottom_h = available_h - top_h
                
                top_y = content_y
                divider_y = top_y + top_h + spacing_before
                bottom_y = divider_y + sb_width + spacing_after
                
                self._draw_divider_rect(ctx, content_x, divider_y, content_w, sb_width, cap_style_start, cap_style_end, "horizontal")
                ctx.fill()
                
                self._draw_list_of_items(ctx, content_x, top_y, content_w, top_h, "primary", num_primary)
                self._draw_list_of_items(ctx, content_x, bottom_y, content_w, bottom_h, "secondary", num_secondary)
            else:
                total_divider_width = sb_width + spacing_before + spacing_after
                available_w = content_w - total_divider_width
                left_w = available_w * split_ratio
                right_w = available_w - left_w
                
                left_x = content_x
                divider_x = left_x + left_w + spacing_before
                right_x = divider_x + sb_width + spacing_after
                
                self._draw_divider_rect(ctx, divider_x, content_y, sb_width, content_h, cap_style_start, cap_style_end, "vertical")
                ctx.fill()

                self._draw_list_of_items(ctx, left_x, content_y, left_w, content_h, "primary", num_primary)
                self._draw_list_of_items(ctx, right_x, content_y, right_w, content_h, "secondary", num_secondary)
        else:
            current_y = content_y
            used_height = self._draw_list_of_items(ctx, content_x, current_y, content_w, content_h, "primary", num_primary)
            current_y += used_height
            remaining_h = content_h - used_height
            if remaining_h > 0:
                self._draw_list_of_items(ctx, content_x, current_y, content_w, remaining_h, "secondary", num_secondary)

        ctx.restore()

    def _draw_divider_rect(self, ctx, x, y, w, h, cap_start, cap_end, orientation):
        radius = min(w, h) / 2
        ctx.new_path()
        if orientation == "horizontal":
            if cap_start == "round": ctx.arc(x + radius, y + radius, radius, 0.5 * math.pi, 1.5 * math.pi)
            else: ctx.move_to(x, y + h); ctx.line_to(x, y)
            ctx.line_to(x + w - (radius if cap_end == "round" else 0), y)
            if cap_end == "round": ctx.arc(x + w - radius, y + radius, radius, 1.5 * math.pi, 0.5 * math.pi)
            else: ctx.line_to(x + w, y + h)
            ctx.line_to(x + (radius if cap_start == "round" else 0), y + h)
        else: 
            if cap_start == "round": ctx.arc(x + radius, y + radius, radius, math.pi, 0)
            else: ctx.move_to(x, y); ctx.line_to(x + w, y)
            ctx.line_to(x + w, y + h - (radius if cap_end == "round" else 0))
            if cap_end == "round": ctx.arc(x + radius, y + h - radius, radius, 0, math.pi)
            else: ctx.line_to(x, y + h)
            ctx.line_to(x, y + (radius if cap_start == "round" else 0))
        ctx.close_path()

    def _draw_list_of_items(self, ctx, x, y, w, h, base_prefix, count):
        if count <= 0: return 0
        items, total_weight, fixed_height_total = [], 0, 0
        for i in range(1, count + 1):
            prefix = f"{base_prefix}{i}"
            display_as = self.config.get(f"{prefix}_display_as", "bar")
            source_key = f"{prefix}_source"
            if base_prefix == "primary" and i == 1 and source_key not in self.data_bundle and "primary_source" in self.data_bundle:
                 source_key = "primary_source"
            item_data = self.data_bundle.get(source_key, {})
            item = {"prefix": prefix, "data": item_data}
            
            if display_as in ["level_bar", "graph", "static", "cpu_multicore"]:
                item["height"] = float(self.config.get(f"{prefix}_item_height", 60))
                fixed_height_total += item["height"]
            else:
                item["weight"] = 1; total_weight += 1
            items.append(item)

        spacing_mode = self.config.get("lcars_secondary_spacing_mode", "auto")
        spacing_value = float(self.config.get("lcars_secondary_spacing_value", 5))
        auto_spacing = 5
        total_spacing = (count - 1) * (spacing_value if spacing_mode == "manual" else auto_spacing)
        available_flex_h = h - fixed_height_total - total_spacing
        
        current_y = y
        drawn_height = 0
        for item in items:
            item_h = item.get("height", max(0, (item.get("weight", 0) / total_weight) * available_flex_h) if total_weight > 0 else 0)
            if item_h > 0:
                if current_y + item_h > y + h: item_h = y + h - current_y
                self._draw_content_item(ctx, x, current_y, w, item_h, item["prefix"], item["data"])
                step = item_h + (spacing_value if spacing_mode == "manual" else auto_spacing)
                current_y += step; drawn_height += step
        return drawn_height

    def _draw_content_item(self, ctx, x, y, w, h, prefix, data):
        display_as = self.config.get(f"{prefix}_display_as", "bar")
        if display_as == "bar":
            radius = float(self.config.get(f"{prefix}_bar_corner_radius", 8))
            self._draw_key_value_bar(ctx, x, y, w, h, prefix, data, radius)
        elif display_as == "level_bar":
            self._draw_secondary_level_bar(ctx, x, y, w, h, prefix, data)
        elif display_as == "graph":
            self._draw_secondary_graph(ctx, x, y, w, h, prefix, data)
        elif display_as == "static":
            self._draw_secondary_static(ctx, x, y, w, h, prefix, data)
        elif display_as == "cpu_multicore":
            self._draw_secondary_multicore(ctx, x, y, w, h, prefix, data)
        else:
            self._draw_key_value_text(ctx, x, y, w, h, prefix, data, radius=0)

    def _draw_secondary_static(self, ctx, x, y, w, h, prefix, data):
        drawer = self._drawer_instances.get(prefix)
        if not drawer: return
        padding = 10
        ctx.save(); ctx.rectangle(x + padding, y, w - 2 * padding, h); ctx.clip(); ctx.translate(x + padding, y)
        drawer.on_draw(None, ctx, w - 2 * padding, h)
        ctx.restore()

    def _draw_secondary_multicore(self, ctx, x, y, w, h, prefix, data):
        drawer = self._drawer_instances.get(prefix)
        if not drawer: return
        padding = 10
        ctx.save(); ctx.rectangle(x + padding, y, w - 2 * padding, h); ctx.clip(); ctx.translate(x + padding, y)
        drawer.on_draw(None, ctx, w - 2 * padding, h)
        ctx.restore()

    def _draw_secondary_graph(self, ctx, x, y, w, h, prefix, data):
        drawer = self._drawer_instances.get(prefix)
        if not drawer: return
        padding = 10
        ctx.save(); ctx.rectangle(x+padding, y, w-2*padding, h); ctx.clip(); ctx.translate(x+padding,y)
        drawer.on_draw(None, ctx, w-2*padding, h)
        
        text_overlay_enabled = str(self.config.get(f"{prefix}_text_overlay_enabled", "False")).lower() == 'true'
        if text_overlay_enabled and prefix in self._text_overlay_lines:
            self._draw_text_overlay(ctx, 0, 0, w-2*padding, h, prefix)
        ctx.restore()
    
    def _draw_text_overlay(self, ctx, x, y, w, h, prefix):
        text_lines = self._text_overlay_lines.get(prefix, [])
        if not text_lines: return
        
        line_count = int(self.config.get(f"{prefix}_text_line_count", 2))
        spacing = int(self.config.get(f"{prefix}_text_spacing", 4))
        layouts_to_draw, total_text_height, max_text_width = [], 0, 0
        
        for i in range(min(line_count, len(text_lines))):
            font_str = self.config.get(f"{prefix}_line{i+1}_font", "Sans 12")
            layout = self._create_pango_layout(ctx, text_lines[i], font_str)
            layouts_to_draw.append(layout)
            dims = layout.get_pixel_extents()[1]
            total_text_height += dims.height
            max_text_width = max(max_text_width, dims.width)
        
        if len(layouts_to_draw) > 1: total_text_height += (len(layouts_to_draw) - 1) * spacing

        v_align = self.config.get(f"{prefix}_text_vertical_align", "center")
        current_y = 0 if v_align == "start" else (h - total_text_height) if v_align == "end" else (h - total_text_height) / 2
        
        h_align_block = self.config.get(f"{prefix}_text_horizontal_align", "center")
        block_x = 0 if h_align_block == "start" else (w - max_text_width) if h_align_block == "end" else (w - max_text_width) / 2
        
        for i, layout in enumerate(layouts_to_draw):
            line_num = i + 1
            ctx.save()
            rgba = Gdk.RGBA(); rgba.parse(self.config.get(f"{prefix}_line{line_num}_color", "rgba(220,220,220,1)"))
            ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            
            w_layout, h_layout = layout.get_pixel_extents()[1].width, layout.get_pixel_extents()[1].height
            align_str = self.config.get(f"{prefix}_line{line_num}_align", "center")
            off_x = max_text_width - w_layout if align_str == "right" else (max_text_width - w_layout) / 2 if align_str == "center" else 0
            
            slant = float(self.config.get(f"{prefix}_line{line_num}_slant", "0"))
            rot = float(self.config.get(f"{prefix}_line{line_num}_rotation", "0"))
            
            ctx.translate(block_x + off_x + w_layout/2, current_y + h_layout/2)
            if rot != 0: ctx.rotate(math.radians(rot))
            if slant != 0: ctx.transform(cairo.Matrix(1, 0, math.tan(math.radians(slant)), 1, 0, 0))
            ctx.move_to(-w_layout/2, -h_layout/2); PangoCairo.show_layout(ctx, layout)
            ctx.restore(); current_y += h_layout + spacing

    def _draw_secondary_level_bar(self, ctx, x, y, w, h, prefix, data):
        drawer = self._drawer_instances.get(prefix)
        if not drawer: return
        padding = 10
        ctx.save(); ctx.rectangle(x+padding, y, w-2*padding, h); ctx.clip(); ctx.translate(x+padding,y)
        
        # Sync LevelBar manual animation state from _bar_values
        bar_anim_key = f"{prefix}_bar"
        percent = self._bar_values.get(bar_anim_key, {}).get('current', 0.0)
        num_segments = int(drawer.config.get("level_bar_segment_count", 30))
        
        drawer.current_on_level = int(round(percent * num_segments))
        drawer.target_on_level = drawer.current_on_level
        drawer.primary_text = data.get("primary_label", "")
        drawer.secondary_text = data.get("display_string", "")
        
        drawer.on_draw(None, ctx, w-2*padding, h)
        ctx.restore()

    def _draw_key_value_text(self, ctx, x, y, w, h, prefix, data, radius=0):
        text_padding = 10 + radius
        show_label = str(self.config.get(f"{prefix}_show_label", "True")).lower() == 'true'
        show_value = str(self.config.get(f"{prefix}_show_value", "True")).lower() == 'true'
        if not show_label and not show_value: return
        
        if show_label:
            layout = self._create_pango_layout(ctx, data.get("primary_label", "N/A").upper(), self.config.get(f"{prefix}_label_font"))
            _, log = layout.get_pixel_extents()
            rgba = Gdk.RGBA(); rgba.parse(self.config.get(f"{prefix}_label_color"))
            ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            ctx.move_to(x + text_padding, y + (h - log.height) / 2); PangoCairo.show_layout(ctx, layout)

        if show_value:
            layout = self._create_pango_layout(ctx, data.get("display_string", "-").upper(), self.config.get(f"{prefix}_value_font"))
            _, log = layout.get_pixel_extents()
            rgba = Gdk.RGBA(); rgba.parse(self.config.get(f"{prefix}_value_color"))
            ctx.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
            ctx.move_to(x + w - log.width - text_padding, y + (h - log.height) / 2); PangoCairo.show_layout(ctx, layout)

    def _draw_key_value_bar(self, ctx, x, y, w, h, prefix, data, radius):
        layout = self.config.get(f"{prefix}_bar_text_layout", "superimposed")
        bar_anim_key = f"{prefix}_bar"
        percent = self._bar_values.get(bar_anim_key, {}).get('current', 0.0)
        bg_color = Gdk.RGBA(); bg_color.parse(self.config.get(f"{prefix}_bar_bg_color", "rgba(0,0,0,0.5)"))
        fg_color = Gdk.RGBA(); fg_color.parse(self.config.get(f"{prefix}_bar_fg_color", "rgba(255,153,102,1)"))

        if layout == "superimposed":
            padding = 10; bar_h = h * 0.6; bar_y = y + (h - bar_h) / 2; bar_x, bar_w = x + padding, w - 2 * padding
            ctx.save()
            ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
            self._draw_rounded_rect(ctx, bar_x, bar_y, bar_w, bar_h, radius); ctx.fill()
            if percent > 0:
                ctx.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, fg_color.alpha)
                self._draw_rounded_rect(ctx, bar_x, bar_y, bar_w * percent, bar_h, radius); ctx.fill()
            ctx.restore()
            self._draw_key_value_text(ctx, x, y, w, h, prefix, data, radius)
        else:
            ratio = float(self.config.get(f"{prefix}_bar_text_split_ratio", 0.4)); spacing = 5
            text_w = (w * ratio) - (spacing / 2); bar_w = w * (1.0 - ratio) - (spacing / 2)
            if layout == "left": text_x, bar_x = x, x + text_w + spacing
            else: bar_x, text_x = x, x + bar_w + spacing
            
            ctx.save()
            ctx.set_source_rgba(bg_color.red, bg_color.green, bg_color.blue, bg_color.alpha)
            self._draw_rounded_rect(ctx, bar_x, y, bar_w, h, radius); ctx.fill()
            if percent > 0:
                ctx.set_source_rgba(fg_color.red, fg_color.green, fg_color.blue, fg_color.alpha)
                self._draw_rounded_rect(ctx, bar_x, y, bar_w * percent, h, radius); ctx.fill()
            ctx.restore()
            self._draw_key_value_text(ctx, text_x, y, text_w, h, prefix, data, radius=0)

    def _draw_rounded_rect(self, ctx, x, y, w, h, r):
        if r <= 0 or w <= 0 or h <= 0: ctx.rectangle(x, y, w, h); return
        r = min(r, h / 2, w / 2)
        ctx.new_path(); ctx.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        ctx.arc(x + w - r, y + r, r, 1.5 * math.pi, 2 * math.pi)
        ctx.arc(x + w - r, y + h - r, r, 0, 0.5 * math.pi)
        ctx.arc(x + r, y + h - r, r, 0.5 * math.pi, math.pi); ctx.close_path()

    def close(self):
        self._stop_animation_timer()
        for drawer in self._drawer_instances.values():
            drawer.close()
        self._drawer_instances.clear()
        super().close()
