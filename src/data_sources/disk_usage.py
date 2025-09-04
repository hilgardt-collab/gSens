# data_sources/disk_usage.py
from data_source import DataSource
from config_dialog import ConfigOption
from ui_helpers import CustomDialog
import psutil
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, GLib

class DiskUsageDataSource(DataSource):
    """Data source for fetching disk usage statistics for a mountpoint."""
    def __init__(self, config):
        super().__init__(config)
        self.config.setdefault("mount_path", "/")

    def get_data(self):
        path = self.config.get("mount_path", "/")
        try:
            usage = psutil.disk_usage(path)
            return {"path": path, "percent": usage.percent, "used_gb": usage.used/(1024**3), "total_gb": usage.total/(1024**3), "free_gb": usage.free/(1024**3)}
        except Exception as e: return {"path": path, "error": str(e)}

    def get_display_string(self, data):
        if not isinstance(data, dict):
            if isinstance(data, (int, float)):
                return f"{data:.1f}%"
            return "N/A"

        if data.get("error"): return "N/A"
        mode = self.config.get("display_mode", "percent")
        if mode == "percent": return f"{data['percent']:.1f}%"
        if mode == "used": return f"Used: {data['used_gb']:.1f} GB"
        if mode == "total": return f"Total: {data['total_gb']:.1f} GB"
        if mode == "free": return f"Free: {data['free_gb']:.1f} GB"
        if mode == "used_total": return f"{data['used_gb']:.1f}/{data['total_gb']:.1f} GB"
        return f"{data['percent']:.1f}%"
    
    def get_tooltip_string(self, data):
        if not isinstance(data, dict) or data.get("error"): return f"Mount: {self.config.get('mount_path', '/')}\\nError: {data.get('error', 'N/A')}"
        return f"Mount: {data['path']}\\nUsed: {data['used_gb']:.1f} GB ({data['percent']:.1f}%)\\nFree: {data['free_gb']:.1f} GB\\nTotal: {data['total_gb']:.1f} GB"

    def get_primary_label_string(self, data):
        """Returns the disk mount path for the primary label."""
        if isinstance(data, dict):
            return data.get('path', '')
        return ""

    @staticmethod
    def get_config_model():
        model = DataSource.get_config_model()
        model["Data Source & Update"].extend([
            ConfigOption("mount_path", "string", "Monitoring Path:", "/"),
            ConfigOption("display_mode", "dropdown", "Text Display Mode:", "percent", options_dict={"Percentage Only": "percent", "Used GB": "used", "Total GB": "total", "Free GB": "free", "Used/Total GB": "used_total"}),
            ConfigOption("disk_title_format", "string", "Title Format:", "Disk: {mount_point}", tooltip="Use {mount_point} as a placeholder for the selected path.")
        ])
        model["Alarm"][1] = ConfigOption(f"data_alarm_high_value", "scale", "Alarm High Value (%):", "90.0", 0.0, 100.0, 1.0, 1)
        model["Graph Range"] = [
            ConfigOption("graph_min_value", "spinner", "Graph Min Value (%):", "0.0", 0.0, 100.0, 1.0, 0),
            ConfigOption("graph_max_value", "spinner", "Graph Max Value (%):", "100.0", 0.0, 100.0, 1.0, 0)
        ]
        return model
    
    @staticmethod
    def get_alarm_unit(): return "%"

    def get_configure_callback(self):
        """Callback to replace the standard mount_path entry with a custom chooser."""
        def add_disk_chooser(dialog, content_box, widgets, available_sources, panel_config, prefix=None):
            is_combo_child = prefix is not None
            opt_prefix = f"{prefix}opt_" if is_combo_child else ""
            mount_path_key = f"{opt_prefix}mount_path" if is_combo_child else "mount_path"

            mount_path_entry = widgets.get(mount_path_key)
            if not mount_path_entry: return

            original_row = mount_path_entry.get_parent()
            original_row.set_visible(False)

            custom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_bottom=4)
            parent_box = original_row.get_parent()
            # Insert the custom row right after the hidden original one for proper layout
            parent_box.insert_child_after(custom_row, original_row)

            custom_row.append(Gtk.Label(label="Monitoring Path:", xalign=0))
            
            path_label = Gtk.Label(label=mount_path_entry.get_text(), xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
            custom_row.append(path_label)
            
            choose_button = Gtk.Button(label="Choose…")
            # --- FIX: Pass the panel_config and the key to the chooser callback ---
            choose_button.connect("clicked", self._show_mount_chooser, dialog, path_label, mount_path_entry, panel_config, mount_path_key)
            custom_row.append(choose_button)
            
            title_format_key = "disk_title_format"
            if is_combo_child:
                 title_format_key = f"{opt_prefix}disk_title_format"

            if title_format_key in widgets:
                widgets[title_format_key].connect("changed", lambda w: self._update_caption(widgets, mount_path_entry, prefix))
            
            GLib.idle_add(self._update_caption, widgets, mount_path_entry, prefix)

        return add_disk_chooser

    def _update_caption(self, widgets, mount_path_entry, prefix):
        is_combo_child = prefix is not None
        
        title_format_key = "disk_title_format" 
        if is_combo_child:
            key_prefix = f"{prefix}opt_"
            title_format_key = f"{key_prefix}disk_title_format"

        caption_key = f"{prefix}caption" if is_combo_child else "title_text"

        try:
            title_format_entry = widgets[title_format_key]
            caption_entry = widgets[caption_key]
            
            format_str = title_format_entry.get_text()
            current_path = mount_path_entry.get_text()
            
            new_caption = format_str.replace("{mount_point}", current_path)
            caption_entry.set_text(new_caption)
        except KeyError:
            pass

    # --- FIX: Update signature to accept panel_config and the key ---
    def _show_mount_chooser(self, btn, parent_dlg, path_label, mount_path_entry, panel_config, mount_path_key):
        dlg=CustomDialog(parent=parent_dlg, title="Choose Mount Point", modal=True)
        dlg.set_default_size(400,500)
        scroll=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        dlg.get_content_area().append(scroll)
        expanders_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        scroll.set_child(expanders_box)
        
        partitions = {"internal":[],"external":[],"other":[]}
        for p in psutil.disk_partitions():
            if not p.mountpoint: continue
            cat = "other"; lbl = f"{p.mountpoint} ({p.device}, {p.fstype})"
            if p.mountpoint == "/" or p.mountpoint.startswith(("/home","/boot")): cat="internal"
            elif p.mountpoint.startswith(("/media/","/run/media/")): cat="external"
            partitions[cat].append({"label":lbl, "mountpoint":p.mountpoint})
        
        list_boxes=[]
        for cat_key, cat_name in [("internal","Internal"),("external","External"),("other","Other")]:
            if not partitions[cat_key]: continue
            exp=Gtk.Expander(label=cat_name, expanded=True)
            list_box=Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
            list_boxes.append(list_box)

            def on_row_selected(current_list_box, row):
                for other_lb in list_boxes:
                    if other_lb is not current_list_box:
                        other_lb.unselect_all()
            list_box.connect("row-selected", on_row_selected)

            for item in sorted(partitions[cat_key], key=lambda x:x["mountpoint"]):
                row=Gtk.ListBoxRow(); row.set_child(Gtk.Label(label=item["label"], xalign=0, margin_start=5, margin_end=5)); row.mountpoint_data=item["mountpoint"]; list_box.append(row)
                if item["mountpoint"] == mount_path_entry.get_text(): list_box.select_row(row)
            exp.set_child(list_box); expanders_box.append(exp)

        dlg.add_styled_button("_Cancel", Gtk.ResponseType.CANCEL)
        choose=dlg.add_styled_button("_Choose", Gtk.ResponseType.OK, "suggested-action", True)
        def update_sensitivity(): choose.set_sensitive(any(lb.get_selected_row() is not None for lb in list_boxes))
        for lb in list_boxes: lb.connect("row-selected", lambda l,r: update_sensitivity())
        update_sensitivity()
        if dlg.run() == Gtk.ResponseType.OK:
            for lb in list_boxes:
                if lb.get_selected_row():
                    selected_path = lb.get_selected_row().mountpoint_data
                    mount_path_entry.set_text(selected_path)
                    path_label.set_text(selected_path)
                    
                    # --- FIX: Immediately update the main config dictionary ---
                    panel_config[mount_path_key] = selected_path
                    
                    # We can't access `widgets` directly here, but the title update can be deferred
                    # until the next full UI build, which is acceptable.
                    break
        dlg.destroy()

