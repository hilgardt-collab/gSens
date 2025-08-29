# **gSens \- A Highly Customizable GTK4 System Monitor**

gSens is a desktop system monitoring application for Linux, built with Python and GTK4. Its core feature is a fully modular and customizable grid-based layout that allows you to create a personalized dashboard of system metrics. You can mix and match different data sources (like CPU usage, GPU temperature, etc.) with various visual displayers (gauges, bars, graphs, and more).  
*(Add a screenshot of your application here\!)*

## **Features**

* **Fully Customizable Grid Layout:**  
  * Drag-and-drop panels to arrange your dashboard exactly how you want it.  
  * Resize panels to give important metrics more space.  
  * Save and load different layout configurations.  
* **Modular Component System:**  
  * **Data Sources:** Monitor a wide range of system statistics.  
  * **Data Displayers:** Visualize your data in numerous ways.  
* **Extensive Styling:**  
  * Customize the background of the entire grid (solid color, gradient, or image).  
  * Style individual panels, including background, borders, and titles.  
  * Fine-tune the appearance of each displayer, from gauge colors to font sizes.  
* **Available Data Sources:**  
  * CPU (Overall/Per-core Usage, Temperature, Frequency)  
  * GPU (NVIDIA, AMD, Intel) (Utilization, Temperature, VRAM, Clock Speed, etc.)  
  * Memory (RAM) Usage  
  * Disk Usage (per mount point)  
  * System Temperatures (from sensors)  
  * Fan Speeds  
  * Analog Clock with Timezone Support  
* **Available Display Types:**  
  * **Single Value:** Arc Gauges, Level Bars, Speedometers, Text, Indicators.  
  * **Time-Series:** Graphs, Bar Charts.  
  * **Compound Panels:**  
    * **Arc Combo:** A central gauge surrounded by multiple data arcs.  
    * **Level Bar Combo:** A stack of multiple, individually configurable level bars.  
    * **LCARS Combo:** A *Star Trek*\-inspired panel with primary and secondary data readouts.

## **Installation**

This project is designed for Linux desktops.

#### **1\. Dependencies**

You will need to install Python 3, GTK4, and the Python bindings for GTK (PyGObject). You will also need the psutil and PyNVML libraries for data collection.  
**On Debian/Ubuntu:**  
sudo apt update  
sudo apt install python3 python3-pip python3-gi python3-gi-cairo gir1.2-gtk-4.0 lm-sensors  
pip3 install psutil pynvml pytz

**On Fedora/CentOS:**  
sudo dnf install python3 python3-pip gobject-introspection-devel cairo-devel pkg-config python3-cairo gtk4 lm\_sensors  
pip3 install psutil pynvml pytz

**For NVIDIA GPU Monitoring:** You need the pynvml library, which is installed via pip above, and the NVIDIA drivers must be installed on your system.

#### **2\. Clone the Repository**

git clone \<your-repository-url\>  
cd gSens

## **Usage**

To run the application, simply execute the main.py script:  
python3 main.py

### **Configuration**

* **Adding Panels:** Click the \+ button in the header bar to open the Panel Builder.  
* **Editing Panels:** Right-click on any panel and select "Configure" to change its data source, displayer, and appearance.  
* **Layout:** Right-click on the background grid to configure its appearance or to save/load the entire panel layout.  
* **Arranging:** Click and drag panels to move them. Select multiple panels by dragging a selection box on the background.

Your layouts and panel configurations are automatically saved to \~/.config/gtk-system-monitor/panel\_settings.ini.

## **For Developers**

The application is designed to be easily extensible.

* **To add a new data source:**  
  1. Create a new Python file in the data\_sources/ directory.  
  2. Create a class that inherits from DataSource.  
  3. Implement the get\_data() and get\_config\_model() methods.  
  4. Register your new source in module\_registry.py.  
* **To add a new data displayer:**  
  1. Create a new Python file in the data\_displayers/ directory.  
  2. Create a class that inherits from DataDisplayer.  
  3. Implement the drawing logic and a get\_config\_model() for styling options.  
  4. Register your new displayer in module\_registry.py and link it to compatible data sources.