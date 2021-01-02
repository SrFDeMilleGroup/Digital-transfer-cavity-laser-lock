import sys
import h5py
import time
import logging
import traceback
import configparser
import numpy as np
import scipy
import PyQt5
import pyqtgraph as pg
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as qt
import os
import nidaqmx
import qdarkstyle # see https://github.com/ColinDuquesnoy/QDarkStyleSheet


def pt_to_px(pt):
    return round(pt*monitor_dpi/72)

class newBox(qt.QGroupBox):
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

class hLine(qt.QLabel):
    def __init__(self):
        super().__init__()
        self.setText("-"*50)
        self.setMaximumHeight(pt_to_px(7))

class scrollArea(qt.QGroupBox):
    def __init__(self, layout_type, scroll_type="both"):
        super().__init__()
        self.setStyleSheet("QGroupBox{margin-top: 0;}")
        # self.setSizePolicy(qt.QSizePolicy.MinimumExpanding, qt.QSizePolicy.Preferred)
        outer_layout = qt.QGridLayout()
        outer_layout.setContentsMargins(0,0,0,0)
        self.setLayout(outer_layout)

        self.scroll = qt.QScrollArea()
        self.scroll.setWidgetResizable(True)
        if scroll_type == "vertical":
            self.scroll.horizontalScrollBar().setEnabled(False)
            self.scroll.setHorizontalScrollBarPolicy(PyQt5.QtCore.Qt.ScrollBarAlwaysOff)
        elif scroll_type == "horizontal":
            self.scroll.verticalScrollBar().setEnabled(False)
            self.scroll.setVerticalScrollBarPolicy(PyQt5.QtCore.Qt.ScrollBarAlwaysOff)
        elif scroll_type == "both":
            pass
        else:
            print("scrollArea: scroll type not supported.")
            return

        # scroll.setFrameStyle(0x10) # see https://doc.qt.io/qt-5/qframe.html for different frame styles
        self.scroll.setStyleSheet("QFrame{border: 0px;}")
        outer_layout.addWidget(self.scroll)

        box = qt.QWidget()
        self.scroll.setWidget(box)
        if layout_type == "hbox":
            self.frame = qt.QHBoxLayout()
        elif layout_type == "vbox":
            self.frame = qt.QVBoxLayout()
        elif layout_type == "grid":
            self.frame = qt.QGridLayout()
        else:
            print("scrollArea: layout type not supported.")
            return
        self.frame.setContentsMargins(0,0,0,0)
        box.setLayout(self.frame)

class newDoubleSpinBox(qt.QDoubleSpinBox):
    def __init__(self, range=None, decimal=None, stepsize=None, suffix=None):
        super().__init__()
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)
        # 0 != None
        if range != None:
            self.setRange(range[0], range[1])
        if decimal != None:
            self.setDecimals(decimal)
        if stepsize != None:
            self.setSingleStep(stepsize)
        if suffix != None:
            self.setSuffix(suffix)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

class newComboBox(qt.QComboBox):
    def __init__(self):
        super().__init__()
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

class newPlot(pg.PlotWidget):
    def __init__(self, parent):
        super().__init__()
        tickstyle = {"showValues": False}
        fontstyle = {"color": "#919191", "font-size": "11pt"}

        self.showGrid(True, True)
        self.setLabel("top")
        self.getAxis("top").setStyle(**tickstyle)
        self.setLabel("right")
        self.getAxis("right").setStyle(**tickstyle)

        self.setLabel("bottom", "time", **fontstyle)
        self.getAxis("bottom").enableAutoSIPrefix(False)
        data = np.linspace(1, 100, 100)
        self.cavity_curve = self.plot(data*4)
        self.cavity_curve.setPen('w')  ## white pen
        self.laser_curves = []
        for i in range(3):
            curve = self.plot(data*i)
            curve.setPen(parent.color_list[i%3])
            self.laser_curves.append(curve)

class abstractLaserColumn(qt.QGroupBox):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.setMaximumWidth(pt_to_px(125))
        self.setStyleSheet("QGroupBox {border: 1px solid #304249;}")

        self.frame = qt.QVBoxLayout()
        self.frame.setContentsMargins(0,0,0,0)
        self.frame.setSpacing(0)
        self.setLayout(self.frame)

    def place_peak_box(self):
        peak_box = newBox(layout_type="form")
        self.frame.addWidget(peak_box)

        self.peak_height_dsb = newDoubleSpinBox(range=(0, 10), decimal=3, stepsize=0.01, suffix=" V")
        peak_box.frame.addRow("Peak height:", self.peak_height_dsb)

        self.peak_width_sb = qt.QSpinBox()
        self.peak_width_sb.setRange(0, 1000)
        self.peak_width_sb.setSuffix(" pts")
        peak_box.frame.addRow("Peak width:", self.peak_width_sb)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    def place_freq_box(self):
        self.freq_box = newBox(layout_type="form")
        self.frame.addWidget(self.freq_box)

        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_pid_box(self):
        pid_box = newBox(layout_type="form")
        self.frame.addWidget(pid_box)

        self.kp_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=1, suffix=None)

        self.kp_chb = qt.QCheckBox()
        self.kp_chb.setTristate(False)

        kp_box = newBox(layout_type="hbox")
        kp_box.frame.addWidget(self.kp_dsb)
        kp_box.frame.addWidget(self.kp_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KP:", kp_box)

        self.ki_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=1, suffix=None)

        self.ki_chb = qt.QCheckBox()
        self.ki_chb.setTristate(False)

        ki_box = newBox(layout_type="hbox")
        ki_box.frame.addWidget(self.ki_dsb)
        ki_box.frame.addWidget(self.ki_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KI:", ki_box)

        self.kd_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=1, suffix=None)

        self.kd_chb = qt.QCheckBox()
        self.kd_chb.setTristate(False)

        kd_box = newBox(layout_type="hbox")
        kd_box.frame.addWidget(self.kd_dsb)
        kd_box.frame.addWidget(self.kd_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KD:", kd_box)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    def place_voltage_box(self):
        voltage_box = newBox(layout_type="form")
        self.frame.addWidget(voltage_box)

        self.offset_dsb = newDoubleSpinBox(range=(-10, 10), decimal=2, stepsize=0.1, suffix=" V")
        voltage_box.frame.addRow("Offset:", self.offset_dsb)

        self.limit_dsb = newDoubleSpinBox(range=(-10, 10), decimal=3, stepsize=0.01, suffix=" V")
        voltage_box.frame.addRow("Limit:", self.limit_dsb)

        self.daq_output_la = qt.QLabel("0 V")
        voltage_box.frame.addRow("DAQ ao:", self.daq_output_la)

        self.rms_width_la = qt.QLabel("0 MHz")
        voltage_box.frame.addRow("RMS width:", self.rms_width_la)

        self.locked_la = qt.QLabel()
        voltage_box.frame.addRow("Locked:", self.locked_la)

        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_daq_box(self):
        daq_box = newBox(layout_type="form")
        self.frame.addWidget(daq_box)

        self.daq_in_cb = newComboBox()
        self.daq_in_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.daq_in_cb.setMaximumWidth(pt_to_px(74))
        daq_box.frame.addRow("DAQ ai:", self.daq_in_cb)

        self.daq_out_cb = newComboBox()
        self.daq_out_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.daq_out_cb.setMaximumWidth(pt_to_px(74))
        daq_box.frame.addRow("DAQ ao:", self.daq_out_cb)

        self.wavenum_dsb = newDoubleSpinBox(range=(0, 20000), decimal=1, stepsize=1, suffix="  1/cm")
        self.wavenum_dsb.setMaximumWidth(pt_to_px(74))
        daq_box.frame.addRow("Wave #:", self.wavenum_dsb)

    def update_daq_channel(self):
        dev_collect = nidaqmx.system._collections.device_collection.DeviceCollection()
        for i in dev_collect.device_names:
            ch_collect = nidaqmx.system._collections.physical_channel_collection.AIPhysicalChannelCollection(i)
            for j in ch_collect.channel_names:
                self.daq_in_cb.addItem(j)
        for i in dev_collect.device_names:
            ch_collect = nidaqmx.system._collections.physical_channel_collection.AOPhysicalChannelCollection(i)
            for j in ch_collect.channel_names:
                self.daq_out_cb.addItem(j)

    def update_config(self, config):
        self.config = {}
        self.config["peak height"] = config.getfloat("peak height/V")
        self.config["peak width"] = config.getint("peak width/pts")
        self.config["kp multiplier"] = config.getfloat("kp multiplier")
        self.config["kp"] = config.getfloat("kp")
        self.config["kp on"] = config.getboolean("kp on")
        self.config["ki multiplier"] = config.getfloat("ki multiplier")
        self.config["ki"] = config.getfloat("ki")
        self.config["ki on"] = config.getboolean("ki on")
        self.config["kd multiplier"] = config.getfloat("kd multiplier")
        self.config["kd"] = config.getfloat("kd")
        self.config["kd on"] = config.getboolean("kd on")
        self.config["offset"] = config.getfloat("offset/V")
        self.config["limit"] = config.getfloat("limit/V")
        self.config["daq ai"] = config.get("daq ai")
        self.config["daq ao"] = config.get("daq ao")
        self.config["wavenumber"] = config.getfloat("wavenumber/cm-1")

    def update_widgets(self):
        self.peak_height_dsb.setValue(self.config["peak height"])
        self.peak_width_sb.setValue(self.config["peak width"])
        self.kp_dsb.setSuffix(" x"+np.format_float_scientific(self.config["kp multiplier"], exp_digits=1))
        self.kp_dsb.setValue(self.config["kp"])
        self.kp_chb.setChecked(self.config["kp on"])
        self.ki_dsb.setSuffix(" x"+np.format_float_scientific(self.config["ki multiplier"], exp_digits=1))
        self.ki_dsb.setValue(self.config["ki"])
        self.ki_chb.setChecked(self.config["ki on"])
        self.kd_dsb.setSuffix(" x"+np.format_float_scientific(self.config["kd multiplier"], exp_digits=1))
        self.kd_dsb.setValue(self.config["kd"])
        self.kd_chb.setChecked(self.config["kd on"])
        self.offset_dsb.setValue(self.config["offset"])
        self.limit_dsb.setValue(self.config["limit"])
        self.daq_in_cb.setCurrentText(self.config["daq ai"])
        self.daq_out_cb.setCurrentText(self.config["daq ao"])
        self.wavenum_dsb.setValue(self.config["wavenumber"])


class cavityColumn(abstractLaserColumn):
    def __init__(self, parent):
        super().__init__(parent)

        self.place_label()
        self.place_peak_box()
        self.place_freq_box()
        self.place_freq_widget()
        self.place_pid_box()
        self.place_voltage_box()
        self.place_daq_box()
        # self.update_daq_channel()

    def place_label(self):
        la = qt.QLabel("Cavity/HeNe")
        la.setStyleSheet("QLabel{font: 16pt;}")
        self.frame.addWidget(la, alignment=PyQt5.QtCore.Qt.AlignHCenter)
        # self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_freq_widget(self):
        self.first_peak_la = qt.QLabel("0")
        self.freq_box.frame.addRow("First peak:", self.first_peak_la)

        self.peak_sep_la = qt.QLabel("0")
        self.freq_box.frame.addRow("Pk-pk sep.:", self.peak_sep_la)

        self.setpoint_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=0.1, suffix=" ms")
        self.freq_box.frame.addRow("Set point:", self.setpoint_dsb)

    def update_config(self, config):
        super().update_config(config)
        self.config["set point"] = config.getfloat("set point/ms")

    def update_widgets(self):
        super().update_widgets()
        self.setpoint_dsb.setValue(self.config["set point"])


class laserColumn(abstractLaserColumn):
    def __init__(self, parent):
        super().__init__(parent)

        self.place_label()
        self.place_peak_box()
        self.place_freq_box()
        self.place_freq_widget()
        self.place_pid_box()
        self.place_voltage_box()
        self.place_daq_box()
        # self.update_daq_channel()

    def place_label(self):
        self.label_box = newBox(layout_type="hbox")
        la = qt.QLabel("  Laser:")
        la.setStyleSheet("QLabel{font: 16pt; background: transparent;}")
        self.label_box.frame.addWidget(la, alignment=PyQt5.QtCore.Qt.AlignRight)

        self.label_le = qt.QLineEdit()
        self.label_le.setStyleSheet("QLineEdit{font: 16pt; background: transparent;}")
        self.label_le.setMaximumWidth(pt_to_px(30))
        self.label_box.frame.addWidget(self.label_le, alignment=PyQt5.QtCore.Qt.AlignLeft)
        self.frame.addWidget(self.label_box)

        # self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_freq_widget(self):
        self.global_freq_la = qt.QLabel("0 MHz")
        self.global_freq_la.setToolTip("Global Frequency")

        self.global_rb = qt.QRadioButton()
        rbgroup = qt.QButtonGroup(self.parent)
        rbgroup.addButton(self.global_rb)

        global_box = newBox(layout_type="hbox")
        global_box.frame.addWidget(self.global_freq_la)
        global_box.frame.addWidget(self.global_rb, alignment=PyQt5.QtCore.Qt.AlignRight)
        self.freq_box.frame.addRow("G. F.:", global_box)

        self.local_freq_dsb = newDoubleSpinBox(range=(0, 1500), decimal=1, stepsize=1, suffix=" MHz")
        self.local_freq_dsb.setToolTip("Local Frequency")

        self.local_rb = qt.QRadioButton()
        self.local_rb.setChecked(True)
        rbgroup.addButton(self.local_rb)

        local_box = newBox(layout_type="hbox")
        local_box.frame.addWidget(self.local_freq_dsb)
        local_box.frame.addWidget(self.local_rb, alignment=PyQt5.QtCore.Qt.AlignRight)
        self.freq_box.frame.addRow("L. F.:", local_box)

        self.actual_freq_la = qt.QLabel("0 MHz")
        self.actual_freq_la.setToolTip("Actual Frequency")
        self.freq_box.frame.addRow("A. F.:", self.actual_freq_la)

    def update_config(self, config):
        super().update_config(config)
        self.config["label"] = config.get("label")
        self.config["local freq"] = config.getfloat("local freq/MHz")
        self.config["freq source"] = config.get("freq source")

    def update_widgets(self):
        super().update_widgets()
        self.label_le.setText(self.config["label"])
        self.local_freq_dsb.setValue(self.config["local freq"])
        if self.config["freq source"] != "global":
            self.local_rb.setChecked(True)
        else:
            self.global_rb.setChecked(True)


class mainWindow(qt.QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Transfer Cavity Laser Lock")
        self.color_list = ["#800000", "#008080", "#000080"]

        cf = configparser.ConfigParser()
        cf.optionxform = str # make config key name case sensitive
        cf.read("defaults.ini")

        self.box = newBox(layout_type="grid")
        self.box.frame.setRowStretch(0, 3)
        self.box.frame.setRowStretch(1, 8)
        self.box.frame.setRowStretch(2, 3)

        self.scan_plot = newPlot(self)
        self.box.frame.addWidget(self.scan_plot, 0, 0)

        ctrl_box = self.place_controls(cf["Setting"].getint("num of lasers"))
        self.box.frame.addWidget(ctrl_box, 1, 0)

        self.err_plot = newPlot(self)
        self.box.frame.addWidget(self.err_plot, 2, 0)

        self.setCentralWidget(self.box)
        self.resize(pt_to_px(500), pt_to_px(500))
        self.show()

        self.update_config(cf)
        self.update_widgets()

    def place_controls(self, num_lasers):
        control_box = scrollArea(layout_type="vbox", scroll_type="both")

        start_box = newBox(layout_type="hbox")
        control_box.frame.addWidget(start_box)

        self.start_pb = qt.QPushButton("Start Lock")
        start_box.frame.addWidget(self.start_pb)
        self.toggle_pb = qt.QPushButton("Toggle more control")
        self.toggle_pb.clicked[bool].connect(lambda val: self.toggle_more_ctrl())
        start_box.frame.addWidget(self.toggle_pb)

        self.scan_box = newBox(layout_type="grid")
        self.scan_box.setStyleSheet("QGroupBox {border: 1px solid #304249;}")
        control_box.frame.addWidget(self.scan_box)

        self.scan_box.frame.addWidget(qt.QLabel("Scan amp:"), 0, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_amp_dsb = newDoubleSpinBox(range=(0, 10), decimal=2, stepsize=0.1, suffix=" V")
        self.scan_box.frame.addWidget(self.scan_amp_dsb, 0, 1)

        self.scan_box.frame.addWidget(qt.QLabel("Scan time:"), 0, 2, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_time_dsb = newDoubleSpinBox(range=(0, 100), decimal=1, stepsize=0.1, suffix=" ms")
        self.scan_box.frame.addWidget(self.scan_time_dsb, 0, 3)

        self.scan_box.frame.addWidget(qt.QLabel("Scan ignore:"), 0, 4, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_ignore_dsb = newDoubleSpinBox(range=(0, 100), decimal=2, stepsize=0.1, suffix=" ms")
        self.scan_box.frame.addWidget(self.scan_ignore_dsb, 0, 5)

        self.scan_box.frame.addWidget(qt.QLabel("Cavity FSR:"), 1, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.cavity_fsr_dsb = newDoubleSpinBox(range=(0, 10000), decimal=1, stepsize=1, suffix=" MHz")
        self.scan_box.frame.addWidget(self.cavity_fsr_dsb, 1, 1)

        self.scan_box.frame.addWidget(qt.QLabel("Lock Criteria:"), 1, 2, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.lock_criteria_dsb = newDoubleSpinBox(range=(0, 100), decimal=1, stepsize=1, suffix=" MHz")
        self.scan_box.frame.addWidget(self.lock_criteria_dsb, 1, 3)

        self.scan_box.frame.addWidget(qt.QLabel("RMS Length:"), 1, 4, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.rms_length_sb = qt.QSpinBox()
        self.rms_length_sb.setRange(0, 10000)
        self.scan_box.frame.addWidget(self.rms_length_sb, 1, 5)

        self.file_box = newBox(layout_type="hbox")
        self.file_box.setStyleSheet("QGroupBox {border: 1px solid #304249;}")
        control_box.frame.addWidget(self.file_box)

        self.file_name_le = qt.QLineEdit("saved_settings/")
        self.file_name_le.setMaximumWidth(pt_to_px(150))
        self.file_box.frame.addWidget(self.file_name_le)

        self.date_time_chb = qt.QCheckBox("Auto append date/time")
        self.date_time_chb.setTristate(False)
        self.file_box.frame.addWidget(self.date_time_chb, alignment = PyQt5.QtCore.Qt.AlignHCenter)

        self.save_setting_pb = qt.QPushButton("Save setting")
        self.file_box.frame.addWidget(self.save_setting_pb)

        self.load_setting_pb = qt.QPushButton("Load setting")
        self.file_box.frame.addWidget(self.load_setting_pb)

        self.refresh_daq_pb = qt.QPushButton("Refresh DAQ channel")
        self.file_box.frame.addWidget(self.refresh_daq_pb)

        laser_box = newBox(layout_type="hbox")
        control_box.frame.addWidget(laser_box)

        self.cavity = cavityColumn(self)
        laser_box.frame.addWidget(self.cavity)
        self.laser_list = []
        for i in range(num_lasers):
            laser = laserColumn(self)
            laser.label_box.setStyleSheet("QGroupBox{background: "+self.color_list[i%3]+"}")
            self.laser_list.append(laser)
            laser_box.frame.addWidget(laser)

        return control_box

    def update_config(config):
        pass

    def update_widgets():
        pass

    def toggle_more_ctrl(self):
        if self.scan_box.isVisible():
            self.scan_box.hide()
        else:
            self.scan_box.show()

        if self.file_box.isVisible():
            self.file_box.hide()
        else:
            self.file_box.show()


if __name__ == '__main__':
    app = qt.QApplication(sys.argv)
    # screen = app.screens()
    # monitor_dpi = screen[0].physicalDotsPerInch()
    monitor_dpi = 183
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    prog = mainWindow(app)
    sys.exit(app.exec_())
