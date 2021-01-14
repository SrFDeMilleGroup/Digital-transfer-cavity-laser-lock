import sys
import time
import logging
import traceback
import configparser
import numpy as np
from scipy import signal
import PyQt5
import pyqtgraph as pg
import PyQt5.QtGui as QtGui
import PyQt5.QtWidgets as qt
import os
import nidaqmx
import qdarkstyle # see https://github.com/ColinDuquesnoy/QDarkStyleSheet
from collections import deque
import socket
import selectors
import struct

# convert GUI widget size in unit pt to unit px using monitor dpi
def pt_to_px(pt):
    return round(pt*monitor_dpi/72)

# a formated QGroupBox with a layout attached
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

# a QLabel with many "-" as content, used as a delimiter for GUI widgets
class hLine(qt.QLabel):
    def __init__(self):
        super().__init__()
        self.setText("-"*50)
        self.setMaximumHeight(pt_to_px(7))

# a formated QGroupBox with scrollable area in it
# Adapted https://github.com/js216/CeNTREX/blob/master/main.py
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

# a doublespinbox that won't respond if the mouse just hovers over it and scrolls the wheel,
# it will respond if it's clicked and get focus
# the purpose is to avoid accidental value change
class newDoubleSpinBox(qt.QDoubleSpinBox):
    def __init__(self, range=None, decimal=None, stepsize=None, suffix=None):
        super().__init__()
        # mouse hovering over this widget and scrolling the wheel won't bring focus into it
        # mouse can bring focus to this widget by clicking it
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)
        # 0 != None
        # don't use "if not range:" statement, in case range is set to zero
        if range != None:
            self.setRange(range[0], range[1])
        if decimal != None:
            self.setDecimals(decimal)
        if stepsize != None:
            self.setSingleStep(stepsize)
        if suffix != None:
            self.setSuffix(suffix)

    # modify wheelEvent so this widget only responds when it has focus
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            # if the event is ignored, it will be passed to and handled by parent widget
            event.ignore()

# modify SpinBox for the same reason as modifying DoubleSpinBox, see comments for newDoubleSpinBox class
class newSpinBox(qt.QSpinBox):
    def __init__(self, range=None, stepsize=None, suffix=None):
        super().__init__()
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)

        if range != None:
            self.setRange(range[0], range[1])
        if stepsize != None:
            self.setSingleStep(stepsize)
        if suffix != None:
            self.setSuffix(suffix)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

# modify ComboBox for the same reason as modifying DoubleSpinBox, see comments for newDoubleSpinBox class
class newComboBox(qt.QComboBox):
    def __init__(self):
        super().__init__()
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()

# a formated plot widget
class newPlot(pg.PlotWidget):
    def __init__(self, parent):
        super().__init__()
        tickstyle = {"showValues": False}

        self.showGrid(True, True)
        self.setLabel("top")
        self.getAxis("top").setStyle(**tickstyle)
        self.setLabel("right")
        self.getAxis("right").setStyle(**tickstyle)

        self.getAxis("bottom").enableAutoSIPrefix(False)

# the base class for cavityColumn class and laserColumn class
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

        self.config = {}
        self.scan_curve = None
        self.err_curve = None

    # place peak height and width doubleSpinBoxes
    def place_peak_box(self):
        peak_box = newBox(layout_type="form")
        self.frame.addWidget(peak_box)

        self.peak_height_dsb = newDoubleSpinBox(range=(0, 10), decimal=3, stepsize=0.01, suffix=" V")
        self.peak_height_dsb.valueChanged[float].connect(lambda val, text="peak height": self.update_config_elem(text, val))
        peak_box.frame.addRow("Peak height:", self.peak_height_dsb)

        self.peak_width_sb = newSpinBox(range=(0, 1000), stepsize=1, suffix=" pt")
        self.peak_width_sb.valueChanged[int].connect(lambda val, text="peak width": self.update_config_elem(text, val))
        peak_box.frame.addRow("Peak width:", self.peak_width_sb)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    # place a box and layout for frequency widgets, which will be added later in cavityColumn and laserColumn class
    def place_freq_box(self):
        self.freq_box = newBox(layout_type="form")
        self.frame.addWidget(self.freq_box)

        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    # place PID parameter widgets
    def place_pid_box(self):
        pid_box = newBox(layout_type="form")
        self.frame.addWidget(pid_box)

        # proportional feedback
        self.kp_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=1, suffix=None)
        self.kp_dsb.valueChanged[float].connect(lambda val, text="kp": self.update_config_elem(text, val))

        self.kp_chb = qt.QCheckBox()
        self.kp_chb.toggled[bool].connect(lambda val, text="kp on": self.update_config_elem(text, val))
        self.kp_chb.setTristate(False)

        kp_box = newBox(layout_type="hbox")
        kp_box.frame.addWidget(self.kp_dsb)
        kp_box.frame.addWidget(self.kp_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KP:", kp_box)

        # integral feedback
        self.ki_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=1, suffix=None)
        self.ki_dsb.valueChanged[float].connect(lambda val, text="ki": self.update_config_elem(text, val))

        self.ki_chb = qt.QCheckBox()
        self.ki_chb.toggled[bool].connect(lambda val, text="ki on": self.update_config_elem(text, val))
        self.ki_chb.setTristate(False)

        ki_box = newBox(layout_type="hbox")
        ki_box.frame.addWidget(self.ki_dsb)
        ki_box.frame.addWidget(self.ki_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KI:", ki_box)

        # derivative feedback
        self.kd_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=1, suffix=None)
        self.kd_dsb.valueChanged[float].connect(lambda val, text="kd": self.update_config_elem(text, val))

        self.kd_chb = qt.QCheckBox()
        self.kd_chb.toggled[bool].connect(lambda val, text="kd on": self.update_config_elem(text, val))
        self.kd_chb.setTristate(False)

        kd_box = newBox(layout_type="hbox")
        kd_box.frame.addWidget(self.kd_dsb)
        kd_box.frame.addWidget(self.kd_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KD:", kd_box)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    # place widgets related to DAQ analog output voltage and laser frequency noise
    def place_voltage_box(self):
        voltage_box = newBox(layout_type="form")
        self.frame.addWidget(voltage_box)

        self.offset_dsb = newDoubleSpinBox(range=(-10, 10), decimal=2, stepsize=0.01, suffix=" V")
        self.offset_dsb.valueChanged[float].connect(lambda val, text="offset": self.update_config_elem(text, val))
        voltage_box.frame.addRow("Offset:", self.offset_dsb)

        self.limit_dsb = newDoubleSpinBox(range=(-10, 10), decimal=3, stepsize=0.01, suffix=" V")
        self.limit_dsb.valueChanged[float].connect(lambda val, text="limit": self.update_config_elem(text, val))
        voltage_box.frame.addRow("Limit:", self.limit_dsb)

        self.daq_output_la = qt.QLabel("0 V")
        voltage_box.frame.addRow("DAQ ao:", self.daq_output_la)

        self.rms_width_la = qt.QLabel("0 MHz")
        voltage_box.frame.addRow("RMS width:", self.rms_width_la)

        self.locked_la = qt.QLabel(" "*6)
        self.locked_la.setStyleSheet("QLabel{background: #304249}")
        voltage_box.frame.addRow("Locked:", self.locked_la)

        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    # place DAQ channel and wavenumber widgets
    def place_daq_box(self):
        daq_box = newBox(layout_type="form")
        self.frame.addWidget(daq_box)

        self.daq_in_cb = newComboBox()
        self.daq_in_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.daq_in_cb.setMaximumWidth(pt_to_px(74))
        self.daq_in_cb.currentTextChanged[str].connect(lambda val, text="daq ai": self.update_config_elem(text, val))
        daq_box.frame.addRow("DAQ ai:", self.daq_in_cb)

        self.daq_out_cb = newComboBox()
        self.daq_out_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.daq_out_cb.setMaximumWidth(pt_to_px(74))
        self.daq_out_cb.currentTextChanged[str].connect(lambda val, text="daq ao": self.update_config_elem(text, val))
        daq_box.frame.addRow("DAQ ao:", self.daq_out_cb)

        self.wavenum_dsb = newDoubleSpinBox(range=(0, 20000), decimal=1, stepsize=1, suffix="  1/cm")
        self.wavenum_dsb.setMaximumWidth(pt_to_px(74))
        self.wavenum_dsb.valueChanged[float].connect(lambda val, text="wavenumber": self.update_config_elem(text, val))
        daq_box.frame.addRow("Wave #:", self.wavenum_dsb)

    # collect available DAQ devices and their channels and update the content of DAQ channel comboBoxes
    def update_daq_channel(self):
        in_ch = self.daq_in_cb.currentText()
        self.daq_in_cb.clear()
        # get available DAQ devices
        dev_collect = nidaqmx.system._collections.device_collection.DeviceCollection()
        for i in dev_collect.device_names:
            # get available AI channels for each DAQ device
            ch_collect = nidaqmx.system._collections.physical_channel_collection.AIPhysicalChannelCollection(i)
            for j in ch_collect.channel_names:
                # add available AI channels to comboBox option list
                self.daq_in_cb.addItem(j)
        self.daq_in_cb.setCurrentText(in_ch)

        out_ch = self.daq_out_cb.currentText()
        self.daq_out_cb.clear()
        for i in dev_collect.device_names:
            # get available AO channels for each DAQ device
            ch_collect = nidaqmx.system._collections.physical_channel_collection.AOPhysicalChannelCollection(i)
            for j in ch_collect.channel_names:
                # add available AO channels to comboBox option list
                self.daq_out_cb.addItem(j)
        self.daq_out_cb.setCurrentText(out_ch)

    # update the value of self.config dictionary
    def update_config_elem(self, text, val):
        self.config[text] = val

    # update self.config from config
    def update_config(self, config):
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

    # update widget value/text from self.config
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

        # in case the channel in self.config is unavailable, comboBox will pick the first term from its option list for its currentText
        # update self.config according to that
        self.daq_in_cb.setCurrentText(self.config["daq ai"])
        self.config["daq ai"] = self.daq_in_cb.currentText()
        self.daq_out_cb.setCurrentText(self.config["daq ao"])
        self.config["daq ao"] = self.daq_out_cb.currentText()

        self.wavenum_dsb.setValue(self.config["wavenumber"])

    # prepare self.config data entry into str, in order to save them into a local .ini file
    def save_config(self):
        config = {}
        config["peak height/V"] = str(self.config["peak height"])
        config["peak width/pts"] = str(self.config["peak width"])
        config["kp multiplier"] = str(self.config["kp multiplier"])
        config["kp"] = str(self.config["kp"])
        config["kp on"] = str(self.config["kp on"])
        config["ki multiplier"] = str(self.config["ki multiplier"])
        config["ki"] = str(self.config["ki"])
        config["ki on"] = str(self.config["ki on"])
        config["kd multiplier"] = str(self.config["kd multiplier"])
        config["kd"] = str(self.config["kd"])
        config["kd on"] = str(self.config["kd on"])
        config["offset/V"] = str(self.config["offset"])
        config["limit/V"] = str(self.config["limit"])
        config["daq ai"] = self.config["daq ai"]
        config["daq ao"] = self.config["daq ao"]
        config["wavenumber/cm-1"] = str(self.config["wavenumber"])

        return config

# this class handles the cavity
class cavityColumn(abstractLaserColumn):
    def __init__(self, parent):
        super().__init__(parent)

        # place GUI widgets
        self.place_label()
        self.place_peak_box()
        self.place_freq_box()
        self.place_freq_widget()
        self.place_pid_box()
        self.place_voltage_box()
        self.place_daq_box()

        # update DAQ channel combboxes
        self.update_daq_channel()

    # place "Cavity/HeNe" label
    def place_label(self):
        la = qt.QLabel("Cavity/HeNe")
        la.setStyleSheet("QLabel{font: 16pt;}")
        self.frame.addWidget(la, alignment=PyQt5.QtCore.Qt.AlignHCenter)
        # self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_freq_widget(self):
        # position of the first peak
        self.first_peak_la = qt.QLabel("0 ms")
        self.freq_box.frame.addRow("First peak:", self.first_peak_la)

        # separation of two HeNe peaks
        self.peak_sep_la = qt.QLabel("0 ms")
        self.freq_box.frame.addRow("Pk-pk sep.:", self.peak_sep_la)

        # setpoint of the first HeNe peak
        self.setpoint_dsb = newDoubleSpinBox(range=(0, 100), decimal=2, stepsize=0.1, suffix=" ms")
        self.setpoint_dsb.valueChanged[float].connect(lambda val, text="setpoint": self.update_config_elem(text, val))
        self.freq_box.frame.addRow("Set point:", self.setpoint_dsb)

    def update_config(self, config):
        super().update_config(config)
        self.config["set point"] = config.getfloat("set point/ms")

    def update_widgets(self):
        super().update_widgets()
        self.setpoint_dsb.setValue(self.config["set point"])

    def save_config(self):
        config = super().save_config()
        config["set point/ms"] = str(self.config["set point"])

        return config

# this class handles the laser
class laserColumn(abstractLaserColumn):
    def __init__(self, parent):
        super().__init__(parent)
        self.config["global freq"] = 0

        # place GUI widgets
        self.place_label()
        self.place_peak_box()
        self.place_freq_box()
        self.place_freq_widget()
        self.place_pid_box()
        self.place_voltage_box()
        self.place_daq_box()

        # update DAQ channel combboxes
        self.update_daq_channel()

    # place laser label
    def place_label(self):
        self.label_box = newBox(layout_type="hbox")
        la = qt.QLabel("  Laser:")
        la.setStyleSheet("QLabel{font: 16pt; background: transparent;}")
        self.label_box.frame.addWidget(la, alignment=PyQt5.QtCore.Qt.AlignRight)

        self.label_le = qt.QLineEdit()
        self.label_le.setStyleSheet("QLineEdit{font: 16pt; background: transparent;}")
        self.label_le.setFixedWidth(pt_to_px(30))
        self.label_le.textChanged[str].connect(lambda val, text="label": self.update_config_elem(text, val))
        self.label_box.frame.addWidget(self.label_le, alignment=PyQt5.QtCore.Qt.AlignLeft)
        self.frame.addWidget(self.label_box)

    def place_freq_widget(self):
        self.global_freq_la = qt.QLabel("0 MHz")
        self.global_freq_la.setToolTip("Global Frequency")

        self.global_rb = qt.QRadioButton()
        self.global_rb.toggled[bool].connect(lambda val, source="global": self.set_freq_source(source, val))
        rbgroup = qt.QButtonGroup(self.parent)
        rbgroup.addButton(self.global_rb)

        global_box = newBox(layout_type="hbox")
        global_box.frame.addWidget(self.global_freq_la)
        global_box.frame.addWidget(self.global_rb, alignment=PyQt5.QtCore.Qt.AlignRight)
        self.freq_box.frame.addRow("G. F.:", global_box)

        self.local_freq_dsb = newDoubleSpinBox(range=(0, 1500), decimal=1, stepsize=1, suffix=" MHz")
        self.local_freq_dsb.setToolTip("Local Frequency")
        self.local_freq_dsb.valueChanged[float].connect(lambda val, text="local freq": self.update_config_elem(text, val))
        self.local_rb = qt.QRadioButton()
        self.local_rb.toggled[bool].connect(lambda val, source="local": self.set_freq_source(source, val))
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
        if self.config["freq source"] == "local":
            self.local_rb.setChecked(True)
        elif self.config["freq source"] == "global":
            self.global_rb.setChecked(True)
        else:
            print("LaserColumn: invalid frequency setpoint source")

    def save_config(self):
        config = super().save_config()
        config["label"] = self.config["label"]
        config["local freq/MHz"] = str(self.config["local freq"])
        config["freq source"] = self.config["freq source"]

        return config

    # set frequency setpoint source, local or global
    def set_freq_source(self, source, val):
        if val:
            self.update_config_elem("freq source", source)

# the worker thread that interfaces with DAQ and calculate PID feedback voltage
class daqThread(PyQt5.QtCore.QThread):
    signal = PyQt5.QtCore.pyqtSignal(dict)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.counter = 0
        self.err_counter = 1
        self.samp_rate = self.parent.config["sampling rate"]
        self.dt = 1.0/self.samp_rate
        # number of samples to write/read
        self.samp_num = round(self.parent.config["scan time"]/1000.0*self.samp_rate)

        # initialize all DAQ tasks
        self.ai_task_init() # read data for cavity and all lasers
        self.cavity_ao_task_init() # cavity sanning voltage, synchronized with ai_task
        self.laser_ao_task_init() # control laser piezo voltage, running in "on demand" mode
        self.counter_task_init() # configure a counter to use as the clock for ai_task and cavity_ao_task, for synchronization and retriggerability
        self.do_task_init() # trigger the counter to generate a pulse train, running in "on demand" mode

    def run(self):
        self.laser_output = []
        self.laser_last_err = []
        self.laser_last_feedback = []
        for laser in self.parent.laser_list:
            self.laser_output.append(laser.config["offset"]) # initial output voltage is the "offset"
            self.laser_last_err.append(deque([0, 0], maxlen=2)) # save frequency errors in laset two cycles, used for PID calculation
            self.laser_last_feedback.append(0) # initial feedback voltage is zero

        self.cavity_scan = np.linspace(self.parent.config["scan amp"], 0, self.samp_num) # cavity scanning voltage, reversed sawtooth wave
        self.cavity_output = self.parent.cavity.config["offset"] # initial output voltage is the "offset"
        self.cavity_last_err = deque([0, 0], maxlen=2) # save frequency errors in laset two cycles, used for PID calculation
        self.cavity_last_feedback = 0 # initial feedback voltage is zero

        self.laser_ao_task.write(self.laser_output)
        self.cavity_ao_task.write(self.cavity_scan + self.cavity_output)

        # start all tasks
        self.ai_task.start()
        self.cavity_ao_task.start()
        self.laser_ao_task.start()
        self.counter_task.start()
        self.do_task.start()

        # trigger counter, to start AI/AO for the first cycle
        self.do_task.write([False, True, False])

        while self.parent.active:
            pd_data = self.ai_task.read(number_of_samples_per_channel=self.samp_num, timeout=10.0)
            # force pd_data to be a 2D array (in case there's only one channel in ai_task so ai_task.read() returns a 1D array)
            pd_data = np.reshape(pd_data, (len(pd_data), -1))

            # chop array, because the beginning part of the data array usually have undesired peaks
            start_length = round(self.parent.config["scan ignore"]/1000*self.samp_rate)
            pd_data = pd_data[:, start_length:]

            # find cavity peaks using "peak height/width" criteria
            cavity_peaks, _ = signal.find_peaks(pd_data[0], height=self.parent.cavity.config["peak height"], width=self.parent.cavity.config["peak width"])

            # normally this frequency lock method requires two cavity scanning peaks
            if len(cavity_peaks) == 2:
                # convert the position of the first peak into unit ms
                cavity_first_peak = cavity_peaks[0]*self.dt*1000
                # convert the separation of peaks into unit ms
                cavity_pk_sep = (cavity_peaks[1] - cavity_peaks[0])*self.dt*1000
                # calculate cavity error signal in unit MHz
                cavity_err = (self.parent.cavity.config["set point"] - self.parent.config["scan ignore"] - cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"]
                # calculate cavity PID feedback voltage, use "scan time" for an approximate loop time
                cavity_feedback = self.cavity_last_feedback + \
                                  (cavity_err-self.cavity_last_err[1])*self.parent.cavity.config["kp"]*self.parent.cavity.config["kp multiplier"]*self.parent.cavity.config["kp on"] + \
                                  cavity_err*self.parent.cavity.config["ki"]*self.parent.cavity.config["ki multiplier"]*self.parent.cavity.config["ki on"]*self.parent.config["scan time"]/1000 + \
                                  (cavity_err+self.cavity_last_err[0]-2*self.cavity_last_err[1])*self.parent.cavity.config["kd"]*self.parent.cavity.config["kd multiplier"]*self.parent.cavity.config["kd on"]/(self.parent.config["scan time"]/1000)
                # coerce cavity feedbak voltage to avoid big jump
                cavity_feedback = np.clip(cavity_feedback, self.cavity_last_feedback-self.parent.cavity.config["limit"], self.cavity_last_feedback+self.parent.cavity.config["limit"])
                # check if cavity feedback voltage is NaN, use feedback voltage from last cycle if it is
                if not np.isnan(cavity_feedback):
                    self.cavity_last_feedback = cavity_feedback
                    self.cavity_output = self.parent.cavity.config["offset"] + cavity_feedback
                else:
                    print("cavity feedback voltage is NaN.")
                    self.cavity_output = self.parent.cavity.config["offset"] + self.cavity_last_feedback
                self.cavity_last_err.append(cavity_err)

                for i, laser in enumerate(self.parent.laser_list):
                    # find laser peak using "peak height/width" criteria
                    laser_peak, _ = signal.find_peaks(pd_data[i+1], height=laser.config["peak height"], width=laser.config["peak width"])
                    if len(laser_peak) > 0:
                        # choose a frequency setpoint source
                        freq_setpoint = laser.config["global freq"] if laser.config["freq source"] == "global" else laser.config["local freq"]
                        # calculate laser frequency error signal, use the position of the first peak
                        laser_err = freq_setpoint - (laser_peak[0]*self.dt*1000-cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"]*(laser.config["wavenumber"]/self.parent.cavity.config["wavenumber"])
                        # calculate laser PID feedback volatge, use "scan time" for an approximate loop time
                        laser_feedback = self.laser_last_feedback[i] + \
                                         (laser_err-self.laser_last_err[i][1])*laser.config["kp"]*laser.config["kp multiplier"]*laser.config["kp on"] + \
                                         laser_err*laser.config["ki"]*laser.config["ki multiplier"]*laser.config["ki on"]*self.parent.config["scan time"]/1000 + \
                                         (laser_err+self.laser_last_err[i][0]-2*self.laser_last_err[i][1])*laser.config["kd"]*laser.config["kd multiplier"]*laser.config["kd on"]/(self.parent.config["scan time"]/1000)
                        # coerce laser feedbak voltage to avoid big jump
                        laser_feedback = np.clip(laser_feedback, self.laser_last_feedback[i]-self.parent.cavity.config["limit"], self.laser_last_feedback[i]+self.parent.cavity.config["limit"])
                        # check if laser feedback voltage is NaN, use feedback voltage from last cycle if it is
                        if not np.isnan(laser_feedback):
                            self.laser_last_feedback[i] = laser_feedback
                            self.laser_output[i] = laser.config["offset"] + laser_feedback
                        else:
                            print(f"laser {i} feedback voltage is NaN.")
                            self.laser_output[i] = laser.config["offset"] + self.laser_last_feedback[i]
                        self.laser_last_err[i].append(laser_err)

                    else:
                        self.laser_output[i] = laser.config["offset"] + self.laser_last_feedback[i]

            else:
                # otherwise use feedback voltage from last cycle
                cavity_first_peak = cavity_peaks[0]*self.dt*1000 if len(cavity_peaks)>0 else np.nan # in ms
                cavity_pk_sep = np.nan
                self.cavity_output = self.parent.cavity.config["offset"] + self.cavity_last_feedback
                for i, laser in enumerate(self.parent.laser_list):
                    self.laser_output[i] = laser.config["offset"] + self.laser_last_feedback[i]

            # generate laser piezo feedback voltage from ao channels
            self.laser_ao_task.write(self.laser_output)

            try:
                # update cavity scanning voltage
                self.cavity_ao_task.write(self.cavity_scan + self.cavity_output)
            except nidaqmx.errors.DaqError as err:
                # This is to handle error -50410, which occurs randomly.
                # "There was no space in buffer when new data was written.
                # The oldest unread data in the buffer was lost as a result"

                # The only way I know now to avoid this error is to release buffer in EVERY cycle,
                # by calling "self.cavity_ao_task.control(nidaqmx.constants.TaskMode.TASK_UNRESERVE)"
                # and then write to buffer "self.cavity_ao_task.write(self.cavity_scan + self.cavity_output, auto_start=True)".
                # But this way reduces performance.

                # This error may only occur in PCIe-6259 or similar DAQs
                print(f"This is the {self.err_counter}-th time error occurs. \n{err}")
                # Abort task, see https://zone.ni.com/reference/en-XX/help/370466AH-01/mxcncpts/taskstatemodel/
                self.cavity_ao_task.control(nidaqmx.constants.TaskMode.TASK_ABORT)
                # write to and and restart task
                self.cavity_ao_task.write(self.cavity_scan + self.cavity_output, auto_start=True)
                self.err_counter += 1

            # trigger counter again, so AI/AO will work
            self.do_task.write([True, False])

            # update GUI widgets every certain number of cycles
            if self.counter%self.parent.config["display per"] == 0:
                data_dict = {}
                data_dict["cavity pd_data"] = pd_data[0]
                data_dict["cavity first peak"] = cavity_first_peak
                data_dict["cavity pk sep"] = cavity_pk_sep
                data_dict["cavity error"] = self.cavity_last_err[1]
                data_dict["cavity output"] = self.cavity_output
                data_dict["laser pd_data"] = pd_data[1:, :]
                data_dict["laser error"] = np.array(self.laser_last_err)[:, 1]
                data_dict["laser output"] = self.laser_output
                self.signal.emit(data_dict)

            self.counter += 1

        # close all tasks and release resources when this loop finishes
        self.ai_task.close()
        self.cavity_ao_task.close()
        self.laser_ao_task.close()
        self.counter_task.close()
        self.do_task.close()
        self.counter = 0

    # initialize ai_task, which will handle analog read for all ai channels
    def ai_task_init(self):
        self.ai_task = nidaqmx.Task("ai task")
        # add cavity ai channel to this task
        self.ai_task.ai_channels.add_ai_voltage_chan(self.parent.cavity.config["daq ai"], min_val=-0.5, max_val=1.2, units=nidaqmx.constants.VoltageUnits.VOLTS)
        # add laser ai channels to this task
        for laser in self.parent.laser_list:
            self.ai_task.ai_channels.add_ai_voltage_chan(laser.config["daq ai"], min_val=-0.5, max_val=1.2, units=nidaqmx.constants.VoltageUnits.VOLTS)
        # use the configured counter as clock and make acquisition type to be CONTINUOUS
        self.ai_task.timing.cfg_samp_clk_timing(
                                                rate = self.samp_rate,
                                                source = self.parent.config["counter PFI line"],
                                                active_edge = nidaqmx.constants.Edge.RISING,
                                                sample_mode = nidaqmx.constants.AcquisitionType.CONTINUOUS,
                                                samps_per_chan = self.samp_num
                                            )

    # initialize cavity_ao_task
    def cavity_ao_task_init(self):
        self.cavity_ao_task = nidaqmx.Task("cavity ao task")
        # add cavity ao channel to this task
        cavity_ao_ch = self.cavity_ao_task.ao_channels.add_ao_voltage_chan(self.parent.cavity.config["daq ao"], min_val=-5.0, max_val=10.0, units=nidaqmx.constants.VoltageUnits.VOLTS)
        # to avoid error200018
        # https://forums.ni.com/t5/Multifunction-DAQ/poor-analog-output-performance-error-200018/td-p/1525156?profile.language=en
        cavity_ao_ch.ao_data_xfer_mech = nidaqmx.constants.DataTransferActiveTransferMode.DMA
        cavity_ao_ch.ao_data_xfer_req_cond = nidaqmx.constants.OutputDataTransferCondition.ON_BOARD_MEMORY_LESS_THAN_FULL
        # use the configured counter as clock and make acquisition type to be CONTINUOUS
        self.cavity_ao_task.timing.cfg_samp_clk_timing(
                                            rate = self.samp_rate,
                                            # rate = 1000,
                                            source = self.parent.config["counter PFI line"],
                                            active_edge = nidaqmx.constants.Edge.RISING,
                                            sample_mode = nidaqmx.constants.AcquisitionType.CONTINUOUS,
                                            samps_per_chan = self.samp_num
                                        )
        # disable sample regeneration
        self.cavity_ao_task.out_stream.regen_mode = nidaqmx.constants.RegenerationMode.DONT_ALLOW_REGENERATION
        # self.cavity_ao_task.out_stream.regen_mode = nidaqmx.constants.RegenerationMode.ALLOW_REGENERATION

    # initialize laser_ao_task, this task handles ao channel of all lasers
    def laser_ao_task_init(self):
        self.laser_ao_task = nidaqmx.Task("laser ao task")
        # add laser ao channel to this task
        for laser in self.parent.laser_list:
            self.laser_ao_task.ao_channels.add_ao_voltage_chan(laser.config["daq ao"], min_val=-5.0, max_val=9.0, units=nidaqmx.constants.VoltageUnits.VOLTS)
        # no sample clock timing or trigger is specified, this task is running in "on demand" mode.

    # initialize a do task, it will be used to trigger the counter
    def do_task_init(self):
        self.do_task = nidaqmx.Task("do task")
        self.do_task.do_channels.add_do_chan(self.parent.config["trigger channel"])
        # no sample clock timing or trigger is specified, this task is running in "on demand" mode.

    # initialize a counter task, it will be used as the clock for ai_task and cavity_ao_task
    def counter_task_init(self):
        self.counter_task = nidaqmx.Task("counter task")
        self.counter_task.co_channels.add_co_pulse_chan_freq(
                                                            counter=self.parent.config["counter channel"],
                                                            units=nidaqmx.constants.FrequencyUnits.HZ,
                                                            freq=self.samp_rate,
                                                            duty_cycle=0.5)
        self.counter_task.timing.cfg_implicit_timing(sample_mode=nidaqmx.constants.AcquisitionType.FINITE, samps_per_chan=self.samp_num)
        # it will be triggered by the do channel in do_task
        self.counter_task.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source=self.parent.config["trigger channel"], trigger_edge=nidaqmx.constants.Edge.RISING)
        # make this task retriggerable
        self.counter_task.triggers.start_trigger.retriggerable = True

# There is a great tutorial about socket programming: https://realpython.com/python-sockets/
# part of my code is adapted from here.
class tcpThread(PyQt5.QtCore.QThread):
    signal = PyQt5.QtCore.pyqtSignal(dict)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.data = bytes()
        self.host = self.parent.config["host address"]
        self.port = self.parent.config["port"]
        self.sel = selectors.DefaultSelector()

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Avoid bind() exception: OSError: [Errno 48] Address already in use
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen()
        print("listening on", (self.host, self.port))
        self.server_sock.setblocking(False)
        self.sel.register(self.server_sock, selectors.EVENT_READ, data=None)

        # only used for network delay calibration
        # self.do_task = nidaqmx.Task()
        # self.do_task.do_channels.add_do_chan("Dev2/port0/line0")
        # self.do_task.start()

    def run(self):
        while self.parent.tcp_active:
            events = self.sel.select(timeout=0.1)
            for key, mask in events:
                if key.data is None:
                    # this event is from self.server_sock listening
                    self.accept_wrapper(key.fileobj)
                else:
                    s = key.fileobj
                    try:
                        data = s.recv(1024) # 1024 bytes should be enough for our data
                    except Exception as err:
                        print(f"TCP connection error: \n{err}")
                        continue
                    if data:
                        self.data += data
                        while len(self.data) >= 10:
                            try:
                                # data protocol is as following: (10 bytes in total)
                                # the first 2 bytes are index of the laser whose frequency setpoint need to change
                                # theh rest 8 bytes are laser frequency
                                laser_num = struct.unpack('>H', self.data[0:2])[0]
                                laser_freq = struct.unpack('>d', self.data[2:10])[0]
                                self.parent.laser_list[laser_num].config["global freq"] = laser_freq
                                print(f"laser {laser_num}: freq = {laser_freq}")
                                self.signal.emit({"type": "data", "laser": laser_num, "freq": laser_freq})
                                s.sendall(self.data[:10])
                                # self.do_task.write([True, False]*20)
                            except Exception as err:
                                print(f"TCP Thread error: \n{err}")
                            finally:
                                self.data = self.data[10:]
                    else:
                        # empty data will be interpreted as the signal of client shutting down
                        print("client shutting down...")
                        self.sel.unregister(s)
                        s.close()
                        self.signal.emit({"type": "close connection"})

        self.sel.unregister(self.server_sock)
        self.server_sock.close()
        self.sel.close()
        # self.do_task.close()

    def accept_wrapper(self, sock):
        conn, addr = sock.accept()  # Should be ready to read
        print("accepted connection from", addr)
        conn.setblocking(False)
        self.sel.register(conn, selectors.EVENT_READ, data=123) # In this application, 'data' keyword can be anything but None
        return_dict = {}
        return_dict["type"] = "open connection"
        return_dict["client addr"] = addr
        self.signal.emit(return_dict)

class mainWindow(qt.QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Transfer Cavity Laser Lock")
        self.color_list = ["#800000", "#008080", "#000080"]
        self.config = {}
        self.active = False

        self.box = newBox(layout_type="grid")
        self.box.frame.setRowStretch(0, 3)
        self.box.frame.setRowStretch(1, 8)
        self.box.frame.setRowStretch(2, 3)

        # top part of this GUI, a plot
        self.scan_plot = newPlot(self)
        fontstyle = {"color": "#919191", "font-size": "11pt"}
        self.scan_plot.setLabel("bottom", "time (ms)", **fontstyle)
        self.box.frame.addWidget(self.scan_plot, 0, 0)

        # bottom part of this GUI, another plot
        self.err_plot = newPlot(self)
        self.err_plot.setLabel("left", "freq. error (MHz)", **fontstyle)
        self.box.frame.addWidget(self.err_plot, 2, 0)

        # middle part of this GUI, a box for control widgets
        ctrl_box = self.place_controls()
        self.box.frame.addWidget(ctrl_box, 1, 0)

        self.setCentralWidget(self.box)
        self.resize(pt_to_px(500), pt_to_px(700))
        self.show()

        cf = configparser.ConfigParser()
        cf.optionxform = str # make config key name case sensitive
        cf.read("saved_settings\Rb_cavity_lock_setting.ini")

        self.update_daq_channel()
        self.update_config(cf)
        self.update_widgets()

        self.scan_plot.setRange(yRange=(0, self.cavity.config["peak height"]*2.6))

    # place controls in the middle part of this GUI
    def place_controls(self):
        control_box = scrollArea(layout_type="vbox", scroll_type="both")

        # first sub-box in this part
        start_box = newBox(layout_type="grid")
        control_box.frame.addWidget(start_box)
        start_box.frame.setColumnStretch(0, 5)
        start_box.frame.setColumnStretch(1, 5)
        start_box.frame.setColumnStretch(2, 3)

        # button to start/stop lock
        self.start_pb = qt.QPushButton("Start Lock")
        self.start_pb.clicked[bool].connect(lambda val:self.start())
        start_box.frame.addWidget(self.start_pb, 0, 0)

        # button to toggle more control widgets
        self.toggle_pb = qt.QPushButton("Toggle more control")
        self.toggle_pb.clicked[bool].connect(lambda val: self.toggle_more_ctrl())
        start_box.frame.addWidget(self.toggle_pb, 0, 1)

        # a label indicates if a client PC is connected through network
        self.tcp_la = qt.QLabel("Client PC NOT connected")
        self.tcp_la.setAlignment(PyQt5.QtCore.Qt.AlignHCenter | PyQt5.QtCore.Qt.AlignVCenter)
        self.tcp_la.setFixedWidth(pt_to_px(100))
        self.tcp_la.setStyleSheet("QLabel{background: #304249;}")
        start_box.frame.addWidget(self.tcp_la, 0, 2, alignment = PyQt5.QtCore.Qt.AlignHCenter)

        # second sub-box in this part, used for widgets controling cavity scanning parameters
        self.scan_box = newBox(layout_type="grid")
        self.scan_box.setMaximumWidth(pt_to_px(520))
        self.scan_box.setStyleSheet("QGroupBox {border: 1px solid #304249;}")
        control_box.frame.addWidget(self.scan_box)

        self.scan_box.frame.addWidget(qt.QLabel("Scan amp:"), 0, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_amp_dsb = newDoubleSpinBox(range=(0, 10), decimal=2, stepsize=0.1, suffix=" V")
        self.scan_amp_dsb.valueChanged[float].connect(lambda val, text="scan amp": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.scan_amp_dsb, 0, 1)

        self.scan_box.frame.addWidget(qt.QLabel("Scan time:"), 0, 2, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_time_dsb = newDoubleSpinBox(range=(0, 100), decimal=1, stepsize=0.1, suffix=" ms")
        self.scan_time_dsb.valueChanged[float].connect(lambda val, text="scan time": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.scan_time_dsb, 0, 3)

        self.scan_box.frame.addWidget(qt.QLabel("Scan ignore:"), 0, 4, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_ignore_dsb = newDoubleSpinBox(range=(0, 100), decimal=2, stepsize=0.1, suffix=" ms")
        self.scan_ignore_dsb.valueChanged[float].connect(lambda val, text="scan ignore": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.scan_ignore_dsb, 0, 5)

        self.scan_box.frame.addWidget(qt.QLabel("Sample rate:"), 0, 6, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.samp_rate_sb = newSpinBox(range=(0, 1000000), stepsize=1000, suffix=" S/s")
        self.samp_rate_sb.valueChanged[int].connect(lambda val, text="sampling rate": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.samp_rate_sb, 0, 7)

        self.scan_box.frame.addWidget(qt.QLabel("Cavity FSR:"), 1, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.cavity_fsr_dsb = newDoubleSpinBox(range=(0, 10000), decimal=1, stepsize=1, suffix=" MHz")
        self.cavity_fsr_dsb.valueChanged[float].connect(lambda val, text="cavity FSR": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.cavity_fsr_dsb, 1, 1)

        self.scan_box.frame.addWidget(qt.QLabel("Lock Criteria:"), 1, 2, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.lock_criteria_dsb = newDoubleSpinBox(range=(0, 100), decimal=1, stepsize=1, suffix=" MHz")
        self.lock_criteria_dsb.valueChanged[float].connect(lambda val, text="lock criteria": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.lock_criteria_dsb, 1, 3)

        self.scan_box.frame.addWidget(qt.QLabel("RMS Length:"), 1, 4, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.rms_length_sb = newSpinBox(range=(0, 10000), stepsize=1, suffix=None)
        self.rms_length_sb.valueChanged[int].connect(lambda val, text="RMS length": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.rms_length_sb, 1, 5)

        self.scan_box.frame.addWidget(qt.QLabel("Display per:"), 1, 6, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.disp_rate_sb = newSpinBox(range=(5, 10000), stepsize=1, suffix=" Cycles")
        self.disp_rate_sb.valueChanged[int].connect(lambda val, text="display per": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.disp_rate_sb, 1, 7)

        self.scan_box.frame.addWidget(qt.QLabel("Counter ch:"), 2, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.counter_cb = newComboBox()
        self.counter_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.counter_cb.currentTextChanged[str].connect(lambda val, text="counter channel": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.counter_cb, 2, 1, 1, 2)

        self.scan_box.frame.addWidget(qt.QLabel("Counter PFI:"), 2, 4, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.counter_pfi_cb = newComboBox()
        self.counter_pfi_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.counter_pfi_cb.currentTextChanged[str].connect(lambda val, text="counter PFI line": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.counter_pfi_cb, 2, 5, 1, 2)

        self.scan_box.frame.addWidget(qt.QLabel("Trigger ch:"), 3, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.trigger_cb = newComboBox()
        self.trigger_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.trigger_cb.currentTextChanged[str].connect(lambda val, text="trigger channel": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.trigger_cb, 3, 1, 1, 2)

        self.refresh_daq_pb = qt.QPushButton("Refresh DAQ channels")
        self.refresh_daq_pb.clicked[bool].connect(lambda val: self.refresh_all_daq_ch())
        self.scan_box.frame.addWidget(self.refresh_daq_pb, 3, 4, 1, 3)

        # third sub-box in this part, used for setting saving/loading control
        self.file_box = newBox(layout_type="hbox")
        self.file_box.setStyleSheet("QGroupBox {border: 1px solid #304249;}")
        control_box.frame.addWidget(self.file_box)

        self.file_name_le = qt.QLineEdit("cavity_lock_setting")
        self.file_name_le.setMaximumWidth(pt_to_px(150))
        self.file_box.frame.addWidget(self.file_name_le)

        self.date_time_chb = qt.QCheckBox("Auto append date/time")
        self.date_time_chb.setTristate(False)
        self.date_time_chb.setChecked(True)
        self.file_box.frame.addWidget(self.date_time_chb, alignment = PyQt5.QtCore.Qt.AlignHCenter)

        self.save_setting_pb = qt.QPushButton("Save setting")
        self.save_setting_pb.clicked[bool].connect(lambda val: self.save_setting())
        self.file_box.frame.addWidget(self.save_setting_pb)

        self.load_setting_pb = qt.QPushButton("Load setting")
        self.load_setting_pb.clicked[bool].connect(lambda val: self.load_setting())
        self.file_box.frame.addWidget(self.load_setting_pb)

        # fourth sub-box in this part, used for tcp connection
        self.tcp_box = newBox(layout_type="hbox")
        self.tcp_box.setStyleSheet("QGroupBox {border: 1px solid #304249;}")
        control_box.frame.addWidget(self.tcp_box)

        self.tcp_box.frame.addWidget(qt.QLabel("Server (this PC) address:"), alignment = PyQt5.QtCore.Qt.AlignRight)
        self.server_addr_la = qt.QLabel("")
        self.tcp_box.frame.addWidget(self.server_addr_la, alignment = PyQt5.QtCore.Qt.AlignLeft)

        self.tcp_box.frame.addWidget(qt.QLabel("Client address:"), alignment = PyQt5.QtCore.Qt.AlignRight)
        self.client_addr_la = qt.QLabel("No connection")
        self.tcp_box.frame.addWidget(self.client_addr_la, alignment = PyQt5.QtCore.Qt.AlignLeft)

        self.tcp_restart_pb = qt.QPushButton("Restart connection")
        self.tcp_restart_pb.clicked[bool].connect(lambda val: self.tcp_restart())
        self.tcp_box.frame.addWidget(self.tcp_restart_pb)

        self.laser_box = newBox(layout_type="hbox")
        control_box.frame.addWidget(self.laser_box)

        # place the cavity column
        self.cavity = cavityColumn(self)
        self.cavity.scan_curve = self.scan_plot.plot()
        self.cavity.scan_curve.setPen('w')
        self.cavity.err_curve = self.err_plot.plot()
        self.cavity.err_curve.setPen('w')
        self.laser_box.frame.addWidget(self.cavity)
        self.laser_list = []

        return control_box

    def update_lasers(self, num_lasers):
        # add laser columns
        while num_lasers > len(self.laser_list):
            laser = laserColumn(self)
            laser.scan_curve = self.scan_plot.plot()
            laser.scan_curve.setPen(self.color_list[len(self.laser_list)%3])
            laser.err_curve = self.err_plot.plot()
            laser.err_curve.setPen(self.color_list[len(self.laser_list)%3])
            laser.label_box.setStyleSheet("QGroupBox{background: "+self.color_list[len(self.laser_list)%3]+"}")
            self.laser_list.append(laser)
            self.laser_box.frame.addWidget(laser)

        # delete laser columns
        while num_lasers < len(self.laser_list):
            self.laser_list[-1].scan_curve.clear()
            self.laser_list[-1].err_curve.clear()
            self.laser_list[-1].setParent(None)
            del self.laser_list[-1]

    # update self.config from config
    def update_config(self, config):
        self.tcp_stop()

        self.config["scan amp"] = config["Setting"].getfloat("scan amp/V")
        self.config["scan time"] = config["Setting"].getfloat("scan time/ms")
        self.config["scan ignore"] = config["Setting"].getfloat("scan ignore/ms")
        self.config["sampling rate"] = config["Setting"].getint("sampling rate")
        self.config["cavity FSR"] = config["Setting"].getfloat("cavity FSR/MHz")
        self.config["lock criteria"] = config["Setting"].getfloat("lock criteria/MHz")
        self.config["RMS length"] = config["Setting"].getint("RMS length")
        self.config["display per"] = config["Setting"].getint("display per")
        self.config["counter channel"] = config["Setting"].get("counter channel")
        self.config["counter PFI line"] = config["Setting"].get("counter PFI line")
        self.config["trigger channel"] = config["Setting"].get("trigger channel")
        self.config["host address"] = config["Setting"].get("host address")
        self.config["port"] = config["Setting"].getint("port")
        self.config["num of lasers"] = config["Setting"].getint("num of lasers")

        # update number of lasers, add or delete current laserColumn instances
        self.update_lasers(self.config["num of lasers"])
        # update cavity config
        self.cavity.update_config(config["Cavity"])
        # update laser config
        for i, laser in enumerate(self.laser_list):
            laser.update_config(config[f"Laser{i}"])

        self.tcp_start()

    # update widget value/text from self.config
    def update_widgets(self):
        self.scan_amp_dsb.setValue(self.config["scan amp"])
        self.scan_time_dsb.setValue(self.config["scan time"])
        self.scan_ignore_dsb.setValue(self.config["scan ignore"])
        self.samp_rate_sb.setValue(self.config["sampling rate"])
        self.cavity_fsr_dsb.setValue(self.config["cavity FSR"])
        self.lock_criteria_dsb.setValue(self.config["lock criteria"])
        self.rms_length_sb.setValue(self.config["RMS length"])
        self.disp_rate_sb.setValue(self.config["display per"])

        self.counter_cb.setCurrentText(self.config["counter channel"])
        self.config["counter channel"] = self.counter_cb.currentText()
        self.counter_pfi_cb.setCurrentText(self.config["counter PFI line"])
        self.config["counter PFI line"] = self.counter_pfi_cb.currentText()
        self.trigger_cb.setCurrentText(self.config["trigger channel"])
        self.config["trigger channel"] = self.trigger_cb.currentText()

        self.server_addr_la.setText(self.config["host address"]+" ("+str(self.config["port"])+")")

        self.cavity.update_widgets()
        for laser in self.laser_list:
            laser.update_widgets()

    # update self.config elements
    def update_config_elem(self, text, val):
        self.config[text] = val

        if text == "scan time":
            self.scan_ignore_dsb.setMaximum(val)

        if text == "scan ignore":
            self.cavity.setpoint_dsb.setMinimum(val)

    # load settings from a local .ini file
    def load_setting(self):
        # open a file dialog to choose a configuration file to load
        file_name, _ = qt.QFileDialog.getOpenFileName(self,"Load settigns", "saved_settings/", "All Files (*);;INI File (*.ini)")
        if not file_name:
            return

        config = configparser.ConfigParser()
        config.optionxform = str
        config.read(file_name)

        self.update_config(config)
        self.update_widgets()

    # save settings to a local .ini file
    def save_setting(self):
        # compile file name
        file_name = ""
        if self.file_name_le.text():
            file_name += self.file_name_le.text()
        if self.date_time_chb.isChecked():
            if file_name != "":
                file_name += "_"
            file_name += time.strftime("%Y%m%d_%H%M%S")
        file_name += ".ini"
        file_name = r"saved_settings/"+file_name

        # check if the file name already exists
        if os.path.exists(file_name):
            overwrite = qt.QMessageBox.warning(self, 'File name exists',
                                            'File name already exists. Continue to overwrite it?',
                                            qt.QMessageBox.Yes | qt.QMessageBox.No,
                                            qt.QMessageBox.No)
            if overwrite == qt.QMessageBox.No:
                return

        config = configparser.ConfigParser()
        config.optionxform = str

        config["Setting"] = {}
        config["Setting"]["scan amp/V"] = str(self.config["scan amp"])
        config["Setting"]["scan time/ms"] = str(self.config["scan time"])
        config["Setting"]["scan ignore/ms"] = str(self.config["scan ignore"])
        config["Setting"]["sampling rate"] = str(self.config["sampling rate"])
        config["Setting"]["cavity FSR/MHz"] = str(self.config["cavity FSR"])
        config["Setting"]["lock criteria/MHz"] = str(self.config["lock criteria"])
        config["Setting"]["RMS length"] = str(self.config["RMS length"])
        config["Setting"]["display per"] = str(self.config["display per"])
        config["Setting"]["counter channel"] = self.config["counter channel"]
        config["Setting"]["counter PFI line"] = self.config["counter PFI line"]
        config["Setting"]["trigger channel"] = self.config["trigger channel"]
        config["Setting"]["host address"] = self.config["host address"]
        config["Setting"]["port"] = str(self.config["port"])
        config["Setting"]["num of lasers"] = str(len(self.laser_list))

        # export cavity/laser config
        config["Cavity"] = self.cavity.save_config()
        for i, laser in enumerate(self.laser_list):
            config[f"Laser{i}"] = laser.save_config()

        configfile = open(file_name, "w")
        config.write(configfile)
        configfile.close()

    def toggle_more_ctrl(self):
        for i in [self.scan_box, self.file_box, self.tcp_box]:
            if i.isVisible():
                i.hide()
            else:
                i.show()

    def refresh_all_daq_ch(self):
        self.update_daq_channel()
        self.cavity.update_daq_channel()
        for laser in self.laser_list:
            laser.update_daq_channel()

    # start frequency lock
    def start(self):
        self.daq_start()

        self.start_pb.setText("Stop Lock")
        self.start_pb.disconnect()
        self.start_pb.clicked[bool].connect(self.stop)

        self.enable_widgets(False)

        self.cavity_err_queue = deque([], maxlen=self.config["RMS length"])
        self.laser_err_list = []
        self.cavity.locked = False
        for laser in self.laser_list:
            laser.locked = False
            self.laser_err_list.append(deque([], maxlen=self.config["RMS length"]))

    # update GUI indicators to show feedback loop status
    @PyQt5.QtCore.pyqtSlot(dict)
    def feedback(self, dict):
        data_len = len(dict["cavity pd_data"])
        self.cavity.scan_curve.setData(np.linspace(self.config["scan ignore"], self.config["scan time"], data_len), dict["cavity pd_data"])
        self.cavity.first_peak_la.setText("{:.2f} ms".format(self.config["scan ignore"]+dict["cavity first peak"]))
        self.cavity.peak_sep_la.setText("{:.2f} ms".format(dict["cavity pk sep"]))
        self.cavity.daq_output_la.setText("{:.3f} V".format(dict["cavity output"]))
        self.cavity_err_queue.append(dict["cavity error"])
        rms = np.std(self.cavity_err_queue)
        self.cavity.rms_width_la.setText("{:.2f} MHz".format(rms))
        if rms < self.config["lock criteria"] and np.abs(dict["cavity error"]) < self.config["lock criteria"]:
            if not self.cavity.locked:
                self.cavity.locked = True
                self.cavity.locked_la.setStyleSheet("QLabel{background: green}")
        else:
            if self.cavity.locked:
                self.cavity.locked = False
                self.cavity.locked_la.setStyleSheet("QLabel{background: #304249}")
        self.cavity.err_curve.setData(np.array(self.cavity_err_queue))

        for i, laser in enumerate(self.laser_list):
            laser.scan_curve.setData(np.linspace(self.config["scan ignore"], self.config["scan time"], data_len), dict["laser pd_data"][i])
            laser.daq_output_la.setText("{:.3f} V".format(dict["laser output"][i]))
            self.laser_err_list[i].append(dict["laser error"][i])
            freq_setpoint = laser.config["local freq"] if laser.config["freq source"] == "local" else laser.config["global freq"]
            laser.actual_freq_la.setText("{:.1f} MHz".format(freq_setpoint+dict["laser error"][i]))
            rms = np.std(self.laser_err_list[i])
            laser.rms_width_la.setText("{:.2f} MHz".format(rms))
            if rms < self.config["lock criteria"] and dict["laser error"][i] < self.config["lock criteria"]:
                if not laser.locked:
                    laser.locked = True
                    laser.locked_la.setStyleSheet("QLabel{background: green}")
            else:
                if laser.locked:
                    laser.locked = False
                    laser.locked_la.setStyleSheet("QLabel{background: #304249}")
            laser.err_curve.setData(np.array(self.laser_err_list[i]))

    # stop frequency lock
    def stop(self):
        self.daq_stop()

        self.start_pb.setText("Start Lock")
        self.start_pb.disconnect()
        self.start_pb.clicked[bool].connect(self.start)

        self.enable_widgets(True)

    # stop DAQ thread
    def daq_stop(self):
        self.active = False
        try:
            self.daq_thread.wait() # wait until closed
        except AttributeError as err:
            pass

    # start DAQ thread
    def daq_start(self):
        self.active = True
        self.daq_thread = daqThread(self)
        self.daq_thread.signal.connect(self.feedback)
        self.daq_thread.start()

    # enable or disable/gray out some control widgets
    def enable_widgets(self, enabled):
        self.scan_amp_dsb.setEnabled(enabled)
        self.scan_time_dsb.setEnabled(enabled)
        self.samp_rate_sb.setEnabled(enabled)

        self.rms_length_sb.setEnabled(enabled) # deque max length can't be changed

        self.counter_cb.setEnabled(enabled)
        self.counter_pfi_cb.setEnabled(enabled)
        self.trigger_cb.setEnabled(enabled)

        self.refresh_daq_pb.setEnabled(enabled)

        self.load_setting_pb.setEnabled(enabled)

        self.cavity.daq_in_cb.setEnabled(enabled)
        self.cavity.daq_out_cb.setEnabled(enabled)

        for laser in self.laser_list:
            laser.daq_in_cb.setEnabled(enabled)
            laser.daq_out_cb.setEnabled(enabled)

    # update DAQ channel comboBoxes for available DAQ devices and channels
    def update_daq_channel(self):
        counter_ch = self.counter_cb.currentText()
        self.counter_cb.clear()
        # get available DAQ devices
        dev_collect = nidaqmx.system._collections.device_collection.DeviceCollection()
        for i in dev_collect.device_names:
            # get available CO channels for each DAQ device
            ch_collect = nidaqmx.system._collections.physical_channel_collection.COPhysicalChannelCollection(i)
            for j in ch_collect.channel_names:
                # add available CO channels to comboBox option list
                self.counter_cb.addItem(j)
        self.counter_cb.setCurrentText(counter_ch)

        counter_pfi = self.counter_pfi_cb.currentText()
        self.counter_pfi_cb.clear()
        trigger_ch = self.trigger_cb.currentText()
        self.trigger_cb.clear()
        for i in dev_collect.device_names:
            dev = nidaqmx.system.device.Device(i)
            # For wach DAq terminal
            for j in dev.terminals:
                if "PFI" in j:
                    # add available PFI lines to comboBox option list
                    self.counter_pfi_cb.addItem(j)
                    self.trigger_cb.addItem(j)
        self.counter_pfi_cb.setCurrentText(counter_pfi)
        self.trigger_cb.setCurrentText(trigger_ch)

    # update widgets to indicate TCP connection status
    @PyQt5.QtCore.pyqtSlot(dict)
    def update_tcp_widget(self, dict):
        if dict["type"] == "open connection":
            addr = dict["client addr"]
            self.client_addr_la.setText(addr[0]+" ("+str(addr[1])+")")
            self.tcp_la.setText("Client PC connected!")
            self.tcp_la.setStyleSheet("QLabel{background: green}")
        elif dict["type"] == "close connection":
            self.client_addr_la.setText("No connection")
            self.tcp_la.setText("Client PC NOT connected")
            self.tcp_la.setStyleSheet("QLabel{background: #304249;}")
        elif dict["type"] == "data":
            self.laser_list[dict["laser"]].global_freq_la.setText("{:.1f} MHz".format(dict["freq"]))
        else:
            print("TCP thread return dict type not supported")

    def tcp_restart(self):
        self.tcp_stop()
        self.tcp_start()

    # stop tcp thread
    def tcp_stop(self):
        self.tcp_active = False
        try:
            self.tcp_thread.wait() # wait until closed
        except AttributeError as err:
            pass

        self.client_addr_la.setText("No connection")
        self.tcp_la.setText("Client PC NOT connected")
        self.tcp_la.setStyleSheet("QLabel{background: #304249;}")

    # start tcp thread
    def tcp_start(self):
        self.tcp_active = True
        self.tcp_thread = tcpThread(self)
        self.tcp_thread.signal.connect(self.update_tcp_widget)
        self.tcp_thread.start()

if __name__ == '__main__':
    app = qt.QApplication(sys.argv)
    # screen = app.screens()
    # monitor_dpi = screen[0].physicalDotsPerInch()
    monitor_dpi = 96
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    prog = mainWindow(app)
    app.exec_()
    # make sure daq and tcp threads are closed
    prog.tcp_stop()
    prog.daq_stop()
    sys.exit()
