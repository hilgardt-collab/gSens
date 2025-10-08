# data_sources/disk_usage.py
from data_source import DataSource
from config_dialog import ConfigOption
from ui_helpers import CustomDialog
import psutil
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Pango, GLib, Gio

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
        if data is None or not isinstance(data, dict) or data.get("error"): 
            mount_path = self.config.get('mount_path', '/')
            error_msg = data.get('error', 'No data') if isinstance(data, dict) else 'No data'
            return f"Mount: {mount_path}\nError: {error_msg}"
        return f"Mount: {data['path']}\nUsed: {data['used_gb']:.1f} GB ({data['percent']:.1f}%)\nFree: {data['free_gb']:.1f} GB\nTotal: {data['total_gb']:.1f} GB"

    def get_primary_label_string(self, data):
        """Returns the disk mount path formatted according to user config."""
        if isinstance(data, dict):
            mount_point = data.get('path', '')
            # Use the format string from config, default if not present
            title_format = self.config.get("disk_title_format", "Disk: {mount_point}")
            return title_format.replace("{mount_point}", mount_point)
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
            opt_prefix = f"{prefix}opt_" if prefix else ""
            mount_path_key = f"{opt_prefix}mount_path"

            mount_path_entry = widgets.get(mount_path_key)
            if not mount_path_entry: return

            original_row = mount_path_entry.get_parent()
            if not original_row: return
            original_row.set_visible(False)

            custom_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_bottom=4)
            parent_box = original_row.get_parent()
            if parent_box:
                parent_box.insert_child_after(custom_row, original_row)
            else:
                content_box.append(custom_row)

            custom_row.append(Gtk.Label(label="Monitoring Path:", xalign=0))
            
            path_label = Gtk.Label(label=mount_path_entry.get_text(), xalign=0, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE)
            custom_row.append(path_label)
            
            choose_button = Gtk.Button(label="Choose…")
            choose_button.connect("clicked", self._show_mount_chooser, dialog, path_label, mount_path_entry, panel_config, mount_path_key)
            custom_row.append(choose_button)

        return add_disk_chooser

    def _show_mount_chooser(self, btn, parent_dlg, path_label, mount_path_entry, panel_config, mount_path_key):
        dlg=CustomDialog(parent=parent_dlg, title="Choose Mount Point", modal=True)
        dlg.set_default_size(400,500)
        scroll=Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER, vexpand=True)
        dlg.get_content_area().append(scroll)
        expanders_box=Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=10, margin_bottom=10, margin_start=10, margin_end=10)
        scroll.set_child(expanders_box)
        
        partitions = {"internal":[], "external":[], "user":[], "other":[]}
        seen_mounts = set()

        # 1. Get all physical and pseudo partitions from psutil
        try:
            for p in psutil.disk_partitions(all=True):
                if not p.mountpoint or p.mountpoint in seen_mounts: continue
                seen_mounts.add(p.mountpoint)
                cat = "other"; lbl = f"{p.mountpoint} ({p.device}, {p.fstype})"
                if p.mountpoint == "/" or p.mountpoint.startswith(("/home","/boot")): cat="internal"
                elif p.mountpoint.startswith(("/media/","/run/media/")): cat="external"
                partitions[cat].append({"label":lbl, "mountpoint":p.mountpoint})
        except Exception as e:
            print(f"Error getting partitions from psutil: {e}")

        # 2. Get all user-visible mounts from Gio (USB drives, network shares, etc.)
        try:
            monitor = Gio.VolumeMonitor.get()
            for volume in monitor.get_volumes():
                mount = volume.get_mount()
                if mount:
                    root = mount.get_root()
                    if root:
                        path = root.get_path()
                        if path and path not in seen_mounts:
                            seen_mounts.add(path)
                            name = mount.get_name()
                            lbl = f"{name} ({path})"
                            partitions["user"].append({"label": lbl, "mountpoint": path})
        except Exception as e:
            print(f"Error getting volumes from Gio: {e}")

        list_boxes=[]
        # Define categories and their order
        category_map = [
            ("internal", "Internal"),
            ("external", "External"),
            ("user", "Removable & Network"),
            ("other", "Other")
        ]

        for cat_key, cat_name in category_map:
            if not partitions[cat_key]: continue
            exp=Gtk.Expander(label=cat_name, expanded=(cat_key != "other"))
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
                    
                    panel_config[mount_path_key] = selected_path
                    
                    # Apply changes to save the new mount path, which will trigger
                    # a panel update and allow the new title logic to take effect.
                    if hasattr(parent_dlg, 'apply_button') and parent_dlg.apply_button:
                        parent_dlg.apply_button.emit("clicked")
                    break
        dlg.destroy()
