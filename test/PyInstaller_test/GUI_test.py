import sys, os, qdarkstyle, logging, time, ctypes
import PyQt5
import PyQt5.QtWidgets as qt
import pyqtgraph as pg
import numpy as np

class NewPlot(pg.PlotWidget):
    """A formated plot widget"""

    def __init__(self, parent=None):
        super().__init__()
        tickstyle = {"showValues": False}

        self.showGrid(True, True)
        self.setLabel("top")
        self.getAxis("top").setStyle(**tickstyle)
        self.setLabel("right")
        self.getAxis("right").setStyle(**tickstyle)

        self.getAxis("bottom").enableAutoSIPrefix(False)

class NewBox(qt.QGroupBox):
    def __init__(self, layout_type="grid"):
        super().__init__()
        self.setStyleSheet("QGroupBox {border: 0px;}")
        if layout_type == "grid":
            self.frame = qt.QGridLayout()
        elif layout_type == "vbox":
            self.frame = qt.QVBoxLayout()
        elif layout_type == "hbox":
            self.frame = qt.QHBoxLayout()
        elif layout_type == "form":
            self.frame = qt.QFormLayout()
            self.frame.setHorizontalSpacing(0)
            self.setStyleSheet("QGroupBox {border: 0px; padding-left: 0; padding-right: 0;}")
        else:
            print("newBox: layout type not supported.")
            self.frame = qt.QGridLayout()
        self.frame.setContentsMargins(0,0,0,0)
        self.setLayout(self.frame)

# follow https://stackoverflow.com/questions/7674790/bundling-data-files-with-pyinstaller-onefile
# This is to find paths of accessories files after using PyInstaller to create a single executable file.
def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

class Worker(PyQt5.QtCore.QObject):
    """A worker class that controls DAQ. This class should be run in a separate thread."""

    finished = PyQt5.QtCore.pyqtSignal()
    update = PyQt5.QtCore.pyqtSignal(dict)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.rng = np.random.default_rng(12345)

    def run(self):
        
        while self.parent.running:
            # send signal back to the main window to update plots and log
            num = 100
            info_dict = {"reading": np.sin(np.linspace(0, 4*np.pi, num)) + self.rng.random(num)*0.3}
            self.update.emit(info_dict)

            time.sleep(0.5)

        self.finished.emit()

class mainWindow(qt.QMainWindow):
    def __init__(self, *args):
        super().__init__()
        self.app = app

        # self.icon = PyQt5.QtGui.QIcon(resource_path('icon\Dev8-Cavity-Lock-Icon.png'))
        # self.setWindowIcon(self.icon)

        logging.getLogger().setLevel("INFO")
        
        self.box = NewBox(layout_type="grid")
        self.setCentralWidget(self.box)

        self.restart_thread_pb = qt.QPushButton("Restar worker thread")
        self.restart_thread_pb.clicked.connect(self.restart_worker_thread)
        self.box.frame.addWidget(self.restart_thread_pb, 0, 0)

        self.plot = NewPlot()
        self.resize(450, 250)
        fontstyle = {"color": "#919191", "font-size": "11pt"}
        self.plot.setLabel("bottom", "time (ms)", **fontstyle)
        self.plot.setLabel("left", "Normalized signal", **fontstyle)
        self.plot.setRange(yRange=(-1.3, 1.3))
        self.curve = self.plot.plot()
        self.curve.setPen('w')
        self.box.frame.addWidget(self.plot, 1, 0, 4, 1)

        self.config = {"general": {"name": "Source Absorption"}, "setting": {"samp_rate_kS_per_s": 10}}
        self.show()

        self.popup_window_dict = {}

        self.running = False
        self.run()

    def run(self):
        """Start a worker thread and DAQ. Be called when the experiment starts"""

        self.running = True
        self.thread = PyQt5.QtCore.QThread()

        self.worker = Worker(self)
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.thread.wait)
        self.worker.finished.connect(self.worker.deleteLater)
        # self.worker.finished.connect(self.update_running_status)
        self.thread.finished.connect(self.thread.deleteLater)
        self.worker.update[dict].connect(lambda val: self.update_plot(val))

        self.thread.start()

    def update_running_status(self):
        self.running = False

    def restart_worker_thread(self):
        self.running = False
        try:
            self.thread.quit()
            self.thread.wait() # wait until the thread exits
        except RuntimeError as err:
            pass

        self.run()

    @PyQt5.QtCore.pyqtSlot(dict)
    def update_plot(self, info_dict):
        self.curve.setData(list(range(len(info_dict["reading"]))), info_dict["reading"])

    @PyQt5.QtCore.pyqtSlot(str)
    def delete_popup_window(self, name):
        self.popup_window_dict.pop(name)

    def program_close(self):
        if self.running:
            self.running = False
            try:
                self.thread.quit()
                self.thread.wait() # wait until the thread exits
            except RuntimeError as err:
                pass

    def closeEvent(self, event):
        self.program_close()
        return super().closeEvent(event)


if __name__ == '__main__':
    # apply a unique ID to the app to avoid Windows 10 from grouping multiple instances of the app into one taskbar icon
    myappid = u'Dev8-Cavity-Lock-test' # basically any arbitrary string should work
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

    app = qt.QApplication(sys.argv)
    # screen = app.screens()
    # monitor_dpi = screen[0].physicalDotsPerInch()
    monitor_dpi = 96
    palette = {"dark":qdarkstyle.dark.palette.DarkPalette, "light":qdarkstyle.light.palette.LightPalette}
    app.setStyleSheet(qdarkstyle._load_stylesheet(qt_api='pyqt5', palette=palette["dark"]))
    prog = mainWindow(app)
    
    try:
        sys.exit(app.exec_())
    except SystemExit:
        print("\nApp is closing...")