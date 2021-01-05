import sys
import h5py
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
import re
from collections import deque

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

    def place_peak_box(self):
        peak_box = newBox(layout_type="form")
        self.frame.addWidget(peak_box)

        self.peak_height_dsb = newDoubleSpinBox(range=(0, 10), decimal=3, stepsize=0.01, suffix=" V")
        self.peak_height_dsb.valueChanged[float].connect(lambda val, text="peak height": self.update_config_elem(text, val))
        peak_box.frame.addRow("Peak height:", self.peak_height_dsb)

        self.peak_width_sb = qt.QSpinBox()
        self.peak_width_sb.setRange(0, 1000)
        self.peak_width_sb.setSuffix(" pts")
        self.peak_width_sb.valueChanged[int].connect(lambda val, text="peak width": self.update_config_elem(text, val))
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
        self.kp_dsb.valueChanged[float].connect(lambda val, text="kp": self.update_config_elem(text, val))

        self.kp_chb = qt.QCheckBox()
        self.kp_chb.toggled[bool].connect(lambda val, text="kp on": self.update_config_elem(text, val))
        self.kp_chb.setTristate(False)

        kp_box = newBox(layout_type="hbox")
        kp_box.frame.addWidget(self.kp_dsb)
        kp_box.frame.addWidget(self.kp_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KP:", kp_box)

        self.ki_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=1, suffix=None)
        self.ki_dsb.valueChanged[float].connect(lambda val, text="ki": self.update_config_elem(text, val))

        self.ki_chb = qt.QCheckBox()
        self.ki_chb.toggled[bool].connect(lambda val, text="ki on": self.update_config_elem(text, val))
        self.ki_chb.setTristate(False)

        ki_box = newBox(layout_type="hbox")
        ki_box.frame.addWidget(self.ki_dsb)
        ki_box.frame.addWidget(self.ki_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KI:", ki_box)

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

    def place_voltage_box(self):
        voltage_box = newBox(layout_type="form")
        self.frame.addWidget(voltage_box)

        self.offset_dsb = newDoubleSpinBox(range=(-10, 10), decimal=2, stepsize=0.1, suffix=" V")
        self.offset_dsb.valueChanged[float].connect(lambda val, text="offset": self.update_config_elem(text, val))
        voltage_box.frame.addRow("Offset:", self.offset_dsb)

        self.limit_dsb = newDoubleSpinBox(range=(-10, 10), decimal=3, stepsize=0.01, suffix=" V")
        self.limit_dsb.valueChanged[float].connect(lambda val, text="limit": self.update_config_elem(text, val))
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

    def update_config_elem(self, text, val):
        self.config[text] = val

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
        self.config["daq ai"] = self.daq_in_cb.currentText()
        self.daq_out_cb.setCurrentText(self.config["daq ao"])
        self.config["daq ao"] = self.daq_out_cb.currentText()
        self.wavenum_dsb.setValue(self.config["wavenumber"])

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
        self.update_daq_channel()

    def place_label(self):
        la = qt.QLabel("Cavity/HeNe")
        la.setStyleSheet("QLabel{font: 16pt;}")
        self.frame.addWidget(la, alignment=PyQt5.QtCore.Qt.AlignHCenter)
        # self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_freq_widget(self):
        self.first_peak_la = qt.QLabel("0 ms")
        self.freq_box.frame.addRow("First peak:", self.first_peak_la)

        self.peak_sep_la = qt.QLabel("0 ms")
        self.freq_box.frame.addRow("Pk-pk sep.:", self.peak_sep_la)

        self.setpoint_dsb = newDoubleSpinBox(range=(-100, 100), decimal=2, stepsize=0.1, suffix=" ms")
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
        self.update_daq_channel()

    def place_label(self):
        self.label_box = newBox(layout_type="hbox")
        la = qt.QLabel("  Laser:")
        la.setStyleSheet("QLabel{font: 16pt; background: transparent;}")
        self.label_box.frame.addWidget(la, alignment=PyQt5.QtCore.Qt.AlignRight)

        self.label_le = qt.QLineEdit()
        self.label_le.setStyleSheet("QLineEdit{font: 16pt; background: transparent;}")
        self.label_le.setMaximumWidth(pt_to_px(30))
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
        if self.config["freq source"] != "global":
            self.local_rb.setChecked(True)
        else:
            self.global_rb.setChecked(True)

    def save_config(self):
        config = super().save_config()
        config["label"] = self.config["label"]
        config["local freq/MHz"] = str(self.config["local freq"])
        config["freq source"] = self.config["freq source"]

        return config

    def set_freq_source(self, source, val):
        if val:
            self.update_config_elem("freq source", source)

class daqThread(PyQt5.QtCore.QThread):
    signal = PyQt5.QtCore.pyqtSignal(dict)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.counter = 0
        self.samp_rate = 400000
        self.dt = 1.0/self.samp_rate
        self.samp_num = round(self.parent.config["scan time"]/1000*self.samp_rate)
        self.dev_name = re.search(r"Dev\d+", self.parent.cavity.config["daq ao"])[0] # sync ai to cavity ao

        self.ai_task_init()
        self.cavity_ao_task_init()
        self.laser_ao_task_init()
        self.do_task_init()

        self.laser_output = []
        self.laser_last_err = []
        self.laser_last_feedback = []
        for laser in self.parent.laser_list:
            self.laser_output.append(laser.config["offset"])
            self.laser_last_err.append(deque([0, 0], maxlen=2))
            self.laser_last_feedback.append(0)

        self.cavity_scan = np.linspace(self.parent.config["scan amp"], 0, self.samp_num)
        self.cavity_output = self.parent.cavity.config["offset"]
        self.cavity_last_err = deque([0, 0], maxlen=2)
        self.cavity_last_feedback = 0

    def run(self):
        self.laser_ao_task.write(self.laser_output)
        self.cavity_ao_task.write(self.cavity_scan + self.parent.cavity.config["offset"])

        self.ai_task.start()
        self.cavity_ao_task.start()
        self.laser_ao_task.start()
        self.do_task.start()
        self.do_task.write([True, False])

        while self.parent.active:
            pd_data = self.ai_task.read(number_of_samples_per_channel=self.samp_num, timeout=10.0)
            pd_data = np.reshape(pd_data, (len(pd_data), -1)) # force it to be a 2D array

            # chop array?

            cavity_peaks, _ = signal.find_peaks(pd_data[0], height=self.parent.cavity.config["peak height"], width=self.parent.cavity.config["peak width"])

            if len(cavity_peaks) == 2:
                cavity_first_peak = cavity_peaks[0]*self.dt*1000 # in ms
                cavity_pk_sep = (cavity_peaks[1] - cavity_peaks[0])*self.dt*1000 # in ms
                # calculate cavity error signal
                cavity_err = (self.parent.cavity.config["set point"] - cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"] # in MHz
                # calculate cavity feedback volatge
                cavity_feedback = self.cavity_last_feedback + \
                                  (cavity_err-self.cavity_last_err[1])*self.parent.cavity.config["kp"]*self.parent.cavity.config["kp multiplier"]*self.parent.cavity.config["kp on"] + \
                                  cavity_err*self.parent.cavity.config["ki"]*self.parent.cavity.config["ki multiplier"]*self.parent.cavity.config["ki on"]*self.parent.config["scan time"]/1000 + \
                                  (cavity_err+self.cavity_last_err[0]-2*self.cavity_last_err[1])*self.parent.cavity.config["kd"]*self.parent.cavity.config["kd multiplier"]*self.parent.cavity.config["kd on"]/(self.parent.config["scan time"]/1000)
                # coerce cavity feedbak voltage
                cavity_feedback = np.clip(cavity_feedback, self.cavity_last_feedback-self.parent.cavity.config["limit"], self.cavity_last_feedback+self.parent.cavity.config["limit"])
                self.cavity_output = self.parent.cavity.config["offset"] + cavity_feedback
                self.cavity_last_feedback = cavity_feedback
                self.cavity_last_err.append(cavity_err)

                for i, laser in enumerate(self.parent.laser_list):
                    laser_peak, _ = signal.find_peaks(pd_data[i+1], height=laser.config["peak height"], width=laser.config["peak width"])
                    # calculate laser error signal
                    laser_err = laser.config["local freq"] - (laser_peak[0]-cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"]*(laser.config["wavenumber"]/self.parent.cavity.config["wavenumber"])
                    # calculate laser feedback volatge
                    laser_feedback = self.laser_last_feedback[i] + \
                                     (laser_err-self.laser_last_err[i][1])*laser.config["kp"]*laser.config["kp multiplier"]*laser.config["kp on"] + \
                                     laser_err*laser.config["ki"]*laser.config["ki multiplier"]*laser.config["ki on"]*self.parent.config["scan time"]/1000 + \
                                     (laser_err+self.laser_last_err[i][0]-2*self.laser_last_err[i][1])*laser.config["kd"]*laser.config["kd multiplier"]*laser.config["kd on"]/(self.parent.config["scan time"]/1000)
                    # coerce cavity feedbak voltage
                    laser_feedback = np.clip(laser_feedback, self.laser_last_feedback-self.parent.cavity.config["limit"], self.laser_last_feedback+self.parent.cavity.config["limit"])
                    self.laser_output[i] = laser.config["offset"] + laser_feedback
                    self.laser_last_feeback[i] = laser_feedback
                    self.laser_last_err[i].append(laser_err)

            else:
                cavity_first_peak = cavity_peaks[0]*self.dt*1000 if len(cavity_peaks)>0 else np.nan# in ms
                cavity_pk_sep = np.nan
                self.cavity_output = self.parent.cavity.config["offset"] + self.cavity_last_feedback
                for i, laser in enumerate(self.parent.laser_list):
                    self.laser_output[i] = laser.config["offset"] + self.laser_last_feedback[i]

            self.laser_ao_task.write(self.laser_output)
            self.cavity_ao_task.write(self.cavity_scan + self.cavity_output)
            self.do_task.write([True, False])

            if self.counter%5 == 0:
                data_dict = {}
                data_dict["cavity pd_data"] = pd_data[0]
                data_dict["cavity first peak"] = cavity_first_peak
                data_dict["cavity pk sep"] = cavity_pk_sep
                data_dict["cavity error"] = self.cavity_last_err
                data_dict["cavity output"] = self.cavity_output
                data_dict["laser pd_data"] = pd_data[1:]
                data_dict["laser error"] = self.laser_last_err
                data_dict["laser output"] = self.laser_output
                self.signal.emit(data_dict)

            self.counter += 1

        self.ai_task.close()
        self.cavity_ao_task.close()
        self.laser_ao_task.close()
        self.do_task.close()
        self.counter = 0

    def ai_task_init(self):
        self.ai_task = nidaqmx.Task()
        self.ai_task.ai_channels.add_ai_voltage_chan(self.parent.cavity.config["daq ai"], min_val=-2.0, max_val=5.0, units=nidaqmx.constants.VoltageUnits.VOLTS)
        for laser in self.parent.laser_list:
            self.ai_task.ai_channels.add_ai_voltage_chan(laser.config["daq ai"], min_val=-2.0, max_val=5.0, units=nidaqmx.constants.VoltageUnits.VOLTS)
        self.ai_task.timing.cfg_samp_clk_timing(
                                                rate = self.samp_rate,
                                                source = "/"+self.dev_name+"/ao/SampleClock",
                                                active_edge = nidaqmx.constants.Edge.RISING,
                                                sample_mode = nidaqmx.constants.AcquisitionType.FINITE,
                                                samps_per_chan = self.samp_num
                                            )
        self.ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source="/"+self.dev_name+"/PFI1", trigger_edge=nidaqmx.constants.Edge.RISING)
        # self.ai_task.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source="/Dev1/PFI1", trigger_edge=nidaqmx.constants.Edge.RISING)
        self.ai_task.triggers.start_trigger.retriggerable = True

    def cavity_ao_task_init(self):
        self.cavity_ao_task = nidaqmx.Task()
        self.cavity_ao_task.ao_channels.add_ao_voltage_chan(self.parent.cavity.config["daq ao"], min_val=-5.0, max_val=5.0, units=nidaqmx.constants.VoltageUnits.VOLTS)
        self.cavity_ao_task.timing.cfg_samp_clk_timing(
                                            rate = self.samp_rate,
                                            # source = "/Dev1/ao/SampleClock", # same source from this channel
                                            active_edge = nidaqmx.constants.Edge.RISING,
                                            sample_mode = nidaqmx.constants.AcquisitionType.FINITE,
                                            samps_per_chan = self.samp_num
                                        )
        self.cavity_ao_task.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source="/"+self.dev_name+"/PFI1", trigger_edge=nidaqmx.constants.Edge.RISING)
        self.cavity_ao_task.triggers.start_trigger.retriggerable = True
        self.cavity_ao_task.out_stream.regen_mode = nidaqmx.constants.RegenerationMode.DONT_ALLOW_REGENERATION
        # self.cavity_ao_task.out_stream.regen_mode = nidaqmx.constants.RegenerationMode.ALLOW_REGENERATION

    def laser_ao_task_init(self):
        self.laser_ao_task = nidaqmx.Task()
        for laser in self.parent.laser_list:
            self.laser_ao_task.ao_channels.add_ao_voltage_chan(laser.config["daq ao"], min_val=-5.0, max_val=5.0, units=nidaqmx.constants.VoltageUnits.VOLTS)
        # no sample clock timing or trigger is specified, this task is running in "on demand" mode.

    def do_task_init(self):
        self.do_task = nidaqmx.Task()
        self.do_task.do_channels.add_do_chan("Dev1/port0/line0")

    # def counter_task_init(self):
    #     self.counter_task = nidaqmx.Task()
    #     self.counter_task.co_channels.add_co_pulse_chan_time(counter="Dev1/ctr0", units=nidaqmx.constants.TimeUnits.SECONDS, low_time=0.02, high_time=self.parent.config["scan time"]/1000)
    #     self.counter_task.timing.cfg_implicit_timing(sample_mode=nidaqmx.constants.AcquisitionType.CONTINUOUS)

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

        self.scan_plot = newPlot(self)
        self.box.frame.addWidget(self.scan_plot, 0, 0)

        self.err_plot = newPlot(self)
        self.box.frame.addWidget(self.err_plot, 2, 0)

        ctrl_box = self.place_controls()
        self.box.frame.addWidget(ctrl_box, 1, 0)

        self.setCentralWidget(self.box)
        self.resize(pt_to_px(500), pt_to_px(500))
        self.show()

        cf = configparser.ConfigParser()
        cf.optionxform = str # make config key name case sensitive
        cf.read("defaults.ini")

        self.update_config(cf)
        self.update_widgets()

    def place_controls(self):
        control_box = scrollArea(layout_type="vbox", scroll_type="both")

        start_box = newBox(layout_type="hbox")
        control_box.frame.addWidget(start_box)

        self.start_pb = qt.QPushButton("Start Lock")
        self.start_pb.clicked[bool].connect(lambda val:self.start())
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

        self.refresh_daq_pb = qt.QPushButton("Refresh DAQ channel")
        self.refresh_daq_pb.clicked[bool].connect(lambda val: self.refreh_daq_ch())
        self.file_box.frame.addWidget(self.refresh_daq_pb)

        self.laser_box = newBox(layout_type="hbox")
        control_box.frame.addWidget(self.laser_box)

        self.cavity = cavityColumn(self)
        self.cavity.scan_curve = self.scan_plot.plot(np.linspace(0, 100, 100)*4)
        self.cavity.scan_curve.setPen('w')
        self.cavity.err_curve = self.err_plot.plot(np.linspace(0, 100, 100)*4)
        self.cavity.err_curve.setPen('w')
        self.laser_box.frame.addWidget(self.cavity)
        self.laser_list = []

        return control_box

    def update_lasers(self, num_lasers):
        while num_lasers > len(self.laser_list):
            laser = laserColumn(self)
            laser.scan_curve = self.scan_plot.plot(np.linspace(0, 100, 100)*len(self.laser_list))
            laser.scan_curve.setPen(self.color_list[len(self.laser_list)%3])
            laser.err_curve = self.err_plot.plot(np.linspace(0, 100, 100)*len(self.laser_list))
            laser.err_curve.setPen(self.color_list[len(self.laser_list)%3])
            laser.label_box.setStyleSheet("QGroupBox{background: "+self.color_list[len(self.laser_list)%3]+"}")
            self.laser_list.append(laser)
            self.laser_box.frame.addWidget(laser)

        while num_lasers < len(self.laser_list):
            self.laser_list[-1].scan_curve.clear()
            self.laser_list[-1].err_curve.clear()
            self.laser_list[-1].setParent(None)
            del self.laser_list[-1]

    def update_config(self, config):

        self.config["scan amp"] = config["Setting"].getfloat("scan amp/V")
        self.config["scan time"] = config["Setting"].getfloat("scan time/ms")
        self.config["scan ignore"] = config["Setting"].getfloat("scan ignore/ms")
        self.config["cavity FSR"] = config["Setting"].getfloat("cavity FSR/MHz")
        self.config["lock criteria"] = config["Setting"].getfloat("lock criteria/MHz")
        self.config["RMS length"] = config["Setting"].getint("RMS length")
        self.config["num of lasers"] = config["Setting"].getint("num of lasers")

        self.update_lasers(self.config["num of lasers"])
        self.cavity.update_config(config["Cavity"])
        for i, laser in enumerate(self.laser_list):
            laser.update_config(config[f"Laser{i}"])

    def update_widgets(self):
        self.scan_amp_dsb.setValue(self.config["scan amp"])
        self.scan_time_dsb.setValue(self.config["scan time"])
        self.scan_ignore_dsb.setValue(self.config["scan ignore"])
        self.cavity_fsr_dsb.setValue(self.config["cavity FSR"])
        self.lock_criteria_dsb.setValue(self.config["lock criteria"])
        self.rms_length_sb.setValue(self.config["RMS length"])

        self.cavity.update_widgets()
        for laser in self.laser_list:
            laser.update_widgets()

    def load_setting(self):
        # open a file dialog to choose a configuration file to load
        file_name, _ = qt.QFileDialog.getOpenFileName(self,"Load settigns", "saved_settings/", "All Files (*);;INI File (*.ini)")
        if not file_name:
            return

        config = configparser.ConfigParser()
        config.read(file_name)

        self.update_config(config)
        self.update_widgets()

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

        config["Setting"] = {}
        config["Setting"]["scan amp/V"] = str(self.config["scan amp"])
        config["Setting"]["scan time/ms"] = str(self.config["scan time"])
        config["Setting"]["scan ignore/ms"] = str(self.config["scan ignore"])
        config["Setting"]["cavity FSR/MHz"] = str(self.config["cavity FSR"])
        config["Setting"]["lock criteria/MHz"] = str(self.config["lock criteria"])
        config["Setting"]["RMS length"] = str(self.config["RMS length"])
        config["Setting"]["num of lasers"] = str(len(self.laser_list))

        config["Cavity"] = self.cavity.save_config()
        for i, laser in enumerate(self.laser_list):
            config[f"Laser{i}"] = laser.save_config()

        configfile = open(file_name, "w")
        config.write(configfile)
        configfile.close()

    def toggle_more_ctrl(self):
        if self.scan_box.isVisible():
            self.scan_box.hide()
        else:
            self.scan_box.show()

        if self.file_box.isVisible():
            self.file_box.hide()
        else:
            self.file_box.show()

    def refreh_daq_ch(self):
        self.cavity.update_daq_channel()
        for laser in self.laser_list:
            laser.update_daq_channel()

    def start(self):
        self.active = True
        self.daq_thread = daqThread(self)
        self.daq_thread.signal.connect(self.feedback)
        self.daq_thread.start()

        self.start_pb.setText("Stop Lock")
        self.start_pb.disconnect()
        self.start_pb.clicked[bool].connect(self.stop)

        self.enable_widgets(False)

        self.cavity_err_queue = deque([], maxlen=self.config["RMS length"])
        self.laser_err_list = []
        for laser in self.laser_list:
            self.laser_err_list.append(deque([], maxlen=self.config["RMS length"]))

    @PyQt5.QtCore.pyqtSlot(dict)
    def feedback(self, dict):
        self.cavity.scan_curve.setData(dict["cavity pd_data"])
        self.cavity.first_peak_la.setText("{:.2f} ms".format(dict["cavity first peak"]))
        self.cavity.peak_sep_la.setText("{:.2f} ms".format(dict["cavity pk sep"]))
        self.cavity.daq_output_la.setText("{:.3f} V".format(dict["cavity output"]))
        self.cavity_err_queue.append(dict["cavity error"])
        self.cavity.rms_width_la.setText("{:.2f} MHz".format(np.std(self.cavity_err_queue)))
        self.cavity.err_curve.setData(np.array(self.cavity_err_queue))
        for i, laser in enumerate(self.laser_list):
            laser.scan_curve.setData(dict["laser pd_data"][i])
            laser.daq_output_la.setText("{:.3f} V".format(dict["laser output"][i]))
            self.laser_err_list[i].append(dict["laser error"][i])
            laser.rms_width_la.setText("{:.2f} MHz".format(np.std(self.laser_err_list[i])))
            laser.err_curve.setData(np.array(self.laser_err_list[i]))


    def stop(self):
        self.active = False

        self.start_pb.setText("Start Lock")
        self.start_pb.disconnect()
        self.start_pb.clicked[bool].connect(self.start)

        self.enable_widgets(True)

    def enable_widgets(self, enabled):
        pass


if __name__ == '__main__':
    app = qt.QApplication(sys.argv)
    # screen = app.screens()
    # monitor_dpi = screen[0].physicalDotsPerInch()
    monitor_dpi = 96
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    prog = mainWindow(app)
    sys.exit(app.exec_())
