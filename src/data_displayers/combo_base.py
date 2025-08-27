# data_displayers/combo_base.py
import gi
from data_displayer import DataDisplayer
from abc import abstractmethod

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk

class ComboBase(DataDisplayer):
    """
    A simplified base class for complex, custom-drawn displayers that receive
    a bundle of data from a ComboDataSource.

    This class provides the basic structure: a Gtk.DrawingArea and an update
    loop. Subclasses are responsible for implementing the actual drawing logic
    in the on_draw method.
    """
    def __init__(self, panel_ref, config):
        self.data_bundle = {}
        super().__init__(panel_ref, config)

    def _create_widget(self):
        """
        Creates the widget for this displayer, which is a DrawingArea for custom drawing.
        """
        drawing_area = Gtk.DrawingArea(hexpand=True, vexpand=True)
        drawing_area.set_draw_func(self.on_draw)
        return drawing_area

    def update_display(self, value):
        """
        Receives the data bundle from the ComboDataSource, stores it,
        and queues a redraw of the drawing area.
        """
        if not self.panel_ref:
            return
        if isinstance(value, dict):
            self.data_bundle = value
        self.widget.queue_draw()

    @abstractmethod
    def on_draw(self, area, context, width, height):
        """
        Abstract draw method. Subclasses must implement this to render the
        visual representation of the data bundle.
        """
        pass
