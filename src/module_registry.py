import os
import importlib

APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Base classes for dynamic loading
from data_source import DataSource
from data_displayer import DataDisplayer

# Dictionaries to hold the dynamically loaded classes and their metadata
ALL_SOURCE_CLASSES = {}
ALL_DISPLAYER_CLASSES = {}
AVAILABLE_DATA_SOURCES = {}
AVAILABLE_DISPLAYERS = {}

def _load_modules_from_directory(directory, base_class, target_dict):
    """Dynamically loads modules and populates a target dictionary mapping ClassName to ClassObject."""
    dir_path = os.path.join(APP_DIR, directory)
    if not os.path.isdir(dir_path):
        return
        
    for filename in os.listdir(dir_path):
        if filename.endswith(".py") and not filename.startswith("__"):
            module_name = filename[:-3]
            module_path = f"{directory}.{module_name}"
            try:
                module = importlib.import_module(module_path)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and issubclass(attr, base_class) and attr is not base_class:
                        target_dict[attr_name] = attr
            except ImportError as e:
                print(f"Error importing module {module_path}: {e}")

def discover_and_load_modules():
    """
    Discovers all source and displayer modules, loads them, and populates
    the global dictionaries with their classes and metadata.
    This should be called once at application startup.
    """
    # Step 1: Discover all raw classes
    _load_modules_from_directory('data_sources', DataSource, ALL_SOURCE_CLASSES)
    _load_modules_from_directory('data_displayers', DataDisplayer, ALL_DISPLAYER_CLASSES)

    # Step 2: Define metadata linking keys to classes and defining relationships
    SOURCE_METADATA = sorted([
        {'key': 'analog_clock', 'class_name': 'AnalogClockDataSource', 'name': 'Clock', "displayers": ["analog_clock", "text"], "default_size": (16, 16)},
        {'key': 'combo', 'class_name': 'ComboDataSource', 'name': 'Combo Panel', "displayers": ["combo", "level_bar_combo"], "default_size": (16, 16)},
        {'key': 'cpu', 'class_name': 'CPUDataSource', 'name': 'CPU Monitor', "displayers": ["text", "graph", "bar", "arc_gauge", "indicator", "level_bar", "speedometer"], "default_size": (16, 16)},
        {'key': 'disk_usage', 'class_name': 'DiskUsageDataSource', 'name': 'Disk Usage', "displayers": ["text", "bar", "arc_gauge", "indicator", "level_bar", "speedometer"], "default_size": (16, 16)},
        {'key': 'fan_speed', 'class_name': 'FanSpeedDataSource', 'name': 'Fan Speed', "displayers": ["text", "graph", "bar", "arc_gauge", "indicator", "level_bar", "speedometer"], "default_size": (16, 16)},
        {'key': 'gpu', 'class_name': 'GPUDataSource', 'name': 'GPU Monitor', "displayers": ["text", "graph", "bar", "arc_gauge", "indicator", "level_bar", "speedometer"], "default_size": (16, 16)},
        {'key': 'memory_usage', 'class_name': 'MemoryUsageDataSource', 'name': 'Memory Usage', "displayers": ["text", "graph", "bar", "arc_gauge", "indicator", "level_bar", "speedometer"], "default_size": (16, 16)},
        {'key': 'system_temp', 'class_name': 'SystemTempDataSource', 'name': 'System Temperature', "displayers": ["graph", "text", "bar", "arc_gauge", "indicator", "level_bar", "speedometer"], "default_size": (16, 16)},
    ], key=lambda x: x['name'])

    DISPLAYER_METADATA = sorted([
        {'key': 'analog_clock', 'class_name': 'AnalogClockDisplayer', 'name': 'Analog Clock'},
        {'key': 'arc_gauge', 'class_name': 'ArcGaugeDisplayer', 'name': 'Arc Gauge'},
        {'key': 'bar', 'class_name': 'BarDisplayer', 'name': 'Bar Chart'},
        {'key': 'combo', 'class_name': 'ArcComboDisplayer', 'name': 'Combo (Arcs)'},
        {'key': 'level_bar_combo', 'class_name': 'LevelBarComboDisplayer', 'name': 'Combo (Level Bars)'},
        {'key': 'graph', 'class_name': 'GraphDisplayer', 'name': 'Graph'},
        {'key': 'indicator', 'class_name': 'IndicatorDisplayer', 'name': 'Indicator'},
        {'key': 'level_bar', 'class_name': 'LevelBarDisplayer', 'name': 'Level Bar'},
        {'key': 'speedometer', 'class_name': 'SpeedometerDisplayer', 'name': 'Speedometer'},
        {'key': 'text', 'class_name': 'TextDisplayer', 'name': 'Text'},
    ], key=lambda x: x['name'])

    # Step 3: Populate the AVAILABLE dictionaries using the metadata and loaded classes
    for meta in SOURCE_METADATA:
        class_name = meta['class_name']
        if class_name in ALL_SOURCE_CLASSES:
            AVAILABLE_DATA_SOURCES[meta['key']] = meta.copy()
            AVAILABLE_DATA_SOURCES[meta['key']]['class'] = ALL_SOURCE_CLASSES[class_name]

    for meta in DISPLAYER_METADATA:
        class_name = meta['class_name']
        if class_name in ALL_DISPLAYER_CLASSES:
            AVAILABLE_DISPLAYERS[meta['key']] = meta.copy()
            AVAILABLE_DISPLAYERS[meta['key']]['class'] = ALL_DISPLAYER_CLASSES[class_name]
