import sys
import time
import logging
import traceback
import configparser
import numpy as np
from scipy import signal
from scipy import sparse
from scipy.sparse import linalg
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
import ctypes
import h5py

from widgets import NewBox, NewComboBox, NewDoubleSpinBox, NewPlot, NewScrollArea, NewSpinBox, hLine, pt_to_px, ScientificDoubleSpinBox


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
        peak_box = NewBox(layout_type="form")
        self.frame.addWidget(peak_box)

        self.peak_height_dsb = NewDoubleSpinBox(range=(0, 10), decimals=3, suffix=" V")
        self.peak_height_dsb.valueChanged[float].connect(lambda val, text="peak height": self.update_config_elem(text, val))
        peak_box.frame.addRow("Peak height:", self.peak_height_dsb)

        self.peak_width_sb = NewSpinBox(range=(0, 1000), suffix=" pt")
        self.peak_width_sb.valueChanged[int].connect(lambda val, text="peak width": self.update_config_elem(text, val))
        peak_box.frame.addRow("Peak width:", self.peak_width_sb)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    # place a box and layout for frequency widgets, which will be added later in cavityColumn and laserColumn class
    def place_freq_box(self):
        self.freq_box = NewBox(layout_type="form")
        self.frame.addWidget(self.freq_box)

        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    # place PID parameter widgets
    def place_pid_box(self):
        pid_box = NewBox(layout_type="form")
        self.frame.addWidget(pid_box)

        # proportional feedback
        self.kp_dsb = ScientificDoubleSpinBox(range=(-100, 100), decimals=2, suffix=None)
        self.kp_dsb.valueChanged[float].connect(lambda val, text="kp": self.update_config_elem(text, val))

        self.kp_chb = qt.QCheckBox()
        self.kp_chb.toggled[bool].connect(lambda val, text="kp on": self.update_config_elem(text, val))
        self.kp_chb.setTristate(False)

        kp_box = NewBox(layout_type="hbox")
        kp_box.frame.addWidget(self.kp_dsb)
        kp_box.frame.addWidget(self.kp_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KP:", kp_box)

        # integral feedback
        self.ki_dsb = ScientificDoubleSpinBox(range=(-100, 100), decimals=2, suffix=None)
        self.ki_dsb.valueChanged[float].connect(lambda val, text="ki": self.update_config_elem(text, val))

        self.ki_chb = qt.QCheckBox()
        self.ki_chb.toggled[bool].connect(lambda val, text="ki on": self.update_config_elem(text, val))
        self.ki_chb.setTristate(False)

        ki_box = NewBox(layout_type="hbox")
        ki_box.frame.addWidget(self.ki_dsb)
        ki_box.frame.addWidget(self.ki_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KI:", ki_box)

        # derivative feedback
        self.kd_dsb = ScientificDoubleSpinBox(range=(-100, 100), decimals=2, suffix=None)
        self.kd_dsb.valueChanged[float].connect(lambda val, text="kd": self.update_config_elem(text, val))

        self.kd_chb = qt.QCheckBox()
        self.kd_chb.toggled[bool].connect(lambda val, text="kd on": self.update_config_elem(text, val))
        self.kd_chb.setTristate(False)

        kd_box = NewBox(layout_type="hbox")
        kd_box.frame.addWidget(self.kd_dsb)
        kd_box.frame.addWidget(self.kd_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KD:", kd_box)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    # place widgets related to DAQ analog output voltage and laser frequency noise
    def place_voltage_box(self):
        voltage_box = NewBox(layout_type="form")
        self.frame.addWidget(voltage_box)

        self.offset_dsb = NewDoubleSpinBox(range=(-10, 10), decimals=2, suffix=" V")
        self.offset_dsb.valueChanged[float].connect(lambda val, text="offset": self.update_config_elem(text, val))
        voltage_box.frame.addRow("Offset:", self.offset_dsb)

        self.limit_dsb = NewDoubleSpinBox(range=(-10, 10), decimals=3, suffix=" V")
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
        daq_box = NewBox(layout_type="form")
        self.frame.addWidget(daq_box)

        self.daq_in_cb = NewComboBox()
        self.daq_in_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.daq_in_cb.setMaximumWidth(pt_to_px(74))
        self.daq_in_cb.currentTextChanged[str].connect(lambda val, text="daq ai": self.update_config_elem(text, val))
        daq_box.frame.addRow("DAQ ai:", self.daq_in_cb)

        self.daq_out_cb = NewComboBox()
        self.daq_out_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.daq_out_cb.setMaximumWidth(pt_to_px(74))
        self.daq_out_cb.currentTextChanged[str].connect(lambda val, text="daq ao": self.update_config_elem(text, val))
        daq_box.frame.addRow("DAQ ao:", self.daq_out_cb)

        self.wavenum_dsb = NewDoubleSpinBox(range=(0, 20000), decimals=1, suffix="  1/cm")
        self.wavenum_dsb.setMaximumWidth(pt_to_px(74))
        self.wavenum_dsb.valueChanged[float].connect(lambda val, text="wavenumber": self.update_config_elem(text, val))
        daq_box.frame.addRow("Wave #:", self.wavenum_dsb)

        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_clear_box(self):
        clear_box = NewBox(layout_type="grid")
        self.frame.addWidget(clear_box)
        self.clear_fb_pb = qt.QPushButton("Clear feedback voltage")
        clear_box.frame.addWidget(self.clear_fb_pb, 0, 0)

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
        self.config["kp"] = config.getfloat("kp")
        self.config["kp on"] = config.getboolean("kp on")
        self.config["ki"] = config.getfloat("ki")
        self.config["ki on"] = config.getboolean("ki on")
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
        self.kp_dsb.setValue(self.config["kp"])
        self.kp_chb.setChecked(self.config["kp on"])
        self.ki_dsb.setValue(self.config["ki"])
        self.ki_chb.setChecked(self.config["ki on"])
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
        config["kp"] = str(self.config["kp"])
        config["kp on"] = str(self.config["kp on"])
        config["ki"] = str(self.config["ki"])
        config["ki on"] = str(self.config["ki on"])
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
        self.place_clear_box()

        # update DAQ channel combboxes
        self.update_daq_channel()

    # place "Cavity/HeNe" label
    def place_label(self):
        la = qt.QLabel("Cavity/1550nm")
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
        self.setpoint_dsb = NewDoubleSpinBox(range=(0, 100), decimals=2, suffix=" ms")
        self.setpoint_dsb.valueChanged[float].connect(lambda val, text="set point": self.update_config_elem(text, val))
        self.freq_box.frame.addRow("Set point:", self.setpoint_dsb)

    def place_clear_box(self):
        super().place_clear_box()
        self.clear_fb_pb.clicked[bool].connect(lambda val:self.clear_feedback())

    def clear_feedback(self):
        try:
            self.parent.daq_thread.cavity_last_feedback = 0
        except AttributeError:
            pass

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
    def __init__(self, index, parent):
        super().__init__(parent)
        self.index = index
        self.config["global freq"] = 0

        # place GUI widgets
        self.place_label()
        self.place_peak_box()
        self.place_freq_box()
        self.place_freq_widget()
        self.place_pid_box()
        self.place_voltage_box()
        self.place_daq_box()
        self.place_clear_box()

        # update DAQ channel combboxes
        self.update_daq_channel()

    # place laser label
    def place_label(self):
        self.label_box = NewBox(layout_type="hbox")
        la = qt.QLabel("Laser:")
        la.setStyleSheet("QLabel{font: 16pt; background: transparent;}")
        self.label_box.frame.addWidget(la, alignment=PyQt5.QtCore.Qt.AlignLeft)

        self.label_le = qt.QLineEdit()
        self.label_le.setStyleSheet("QLineEdit{font: 14pt; background: transparent;}")
        self.label_le.setFixedWidth(pt_to_px(62))
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

        global_box = NewBox(layout_type="hbox")
        global_box.frame.addWidget(self.global_freq_la)
        global_box.frame.addWidget(self.global_rb, alignment=PyQt5.QtCore.Qt.AlignRight)
        self.freq_box.frame.addRow("G. F.:", global_box)

        self.local_freq_dsb = NewDoubleSpinBox(range=(-750, 1500), decimals=1, suffix=" MHz")
        self.local_freq_dsb.setToolTip("Local Frequency")
        self.local_freq_dsb.valueChanged[float].connect(lambda val, text="local freq": self.update_config_elem(text, val))
        self.local_rb = qt.QRadioButton()
        self.local_rb.toggled[bool].connect(lambda val, source="local": self.set_freq_source(source, val))
        self.local_rb.setChecked(True)
        rbgroup.addButton(self.local_rb)

        local_box = NewBox(layout_type="hbox")
        local_box.frame.addWidget(self.local_freq_dsb)
        local_box.frame.addWidget(self.local_rb, alignment=PyQt5.QtCore.Qt.AlignRight)
        self.freq_box.frame.addRow("L. F.:", local_box)

        self.actual_freq_la = qt.QLabel("0 MHz")
        self.actual_freq_la.setToolTip("Actual Frequency")
        self.freq_box.frame.addRow("A. F.:", self.actual_freq_la)

    def place_clear_box(self):
        super().place_clear_box()
        self.clear_fb_pb.clicked[bool].connect(lambda val:self.clear_feedback())

    def clear_feedback(self):
        try:
            self.parent.daq_thread.laser_last_feedback[self.index] = 0
        except AttributeError:
            pass

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
            logging.info("LaserColumn: invalid frequency setpoint source")

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

        self.rampupsamp_num = round((self.parent.config["ramp up time"])/1000.0*self.samp_rate)
        self.scansamp_num = round((self.parent.config["scan time"])/1000.0*self.samp_rate)
        self.samp_num = self.rampupsamp_num + self.scansamp_num
        self.laser_num = len(self.parent.laser_list)

        # initialize all DAQ tasks
        self.ai_task_init() # read data for cavity and all lasers
        self.cavity_ao_task_init() # cavity sanning voltage, synchronized with ai_task
        self.laser_ao_task_init() # control laser piezo voltage, running in "on demand" mode
        self.counter_task_init() # configure a counter to use as the clock for ai_task and cavity_ao_task, for synchronization and retriggerability
        self.do_task_init() # trigger the counter to generate a pulse train, running in "on demand" mode

    def run(self):
        self.laser_output = np.empty(self.laser_num, dtype=np.float64)
        self.laser_last_err = np.zeros((self.laser_num, 2), dtype=np.float64) # save frequency errors in laset two cycles, used for PID calculation
        self.laser_last_feedback = self.parent.laser_last_feedback # use feedback voltage from last run as the initial feedback voltage of this run, to avoid laser freq jump
        self.laser_peak_found = np.zeros(self.laser_num, dtype=np.bool_) # initially all False
        for i, laser in enumerate(self.parent.laser_list):
            self.laser_output[i] = laser.config["offset"] + self.laser_last_feedback[i]

        self.cavity_scan = np.concatenate((np.linspace(0, self.parent.config["scan amp"], self.rampupsamp_num, dtype=np.float64), np.linspace(self.parent.config["scan amp"], 0, self.scansamp_num, dtype=np.float64))) # cavity scanning voltage, reversed sawtooth wave
        self.cavity_last_err = np.zeros(2, dtype=np.float64) # save frequency errors in laset two cycles, used for PID calculation
        self.cavity_last_feedback = self.parent.cavity_last_feedback # use feedback voltage from last run as the initial feedback voltage of this run, to avoid laser freq jump
        self.cavity_output = self.parent.cavity.config["offset"] + self.cavity_last_feedback
        self.cavity_peak_found = False

        self.ao_task_write()

        # start all tasks
        self.ai_task.start()
        self.cavity_ao_task.start()
        self.laser_ao_task.start()
        self.counter_task.start()
        self.do_task.start()

        while self.parent.active:
            # Thanks O. Grasdijk for pointing this out,
            # nidaqmx.Task.read() uses windows timer for timing, higher timer resolution can improve loop performance
            # default resolution can vary in differnt computers
            current_res = ctypes.c_ulong()
            # units are 100 ns, set windows timer resolution to be 1 ms.
            ctypes.windll.ntdll.NtSetTimerResolution(10000, True, ctypes.byref(current_res))

            num_run = self.parent.config["average"]
            for i in range(num_run):
                # trigger counter, to start AI/AO for the first cycle
                self.do_task.write([False, True, False])
                if i == 0:
                    pd_data = np.array(self.ai_task.read(number_of_samples_per_channel=self.samp_num, timeout=10.0), dtype=np.float64)
                else:
                    ai_read = np.array(self.ai_task.read(number_of_samples_per_channel=self.samp_num, timeout=10.0), dtype=np.float64)
                    pd_data = (ai_read + pd_data*i)/(i+1)

                if i < num_run - 1:
                    self.ao_task_write()

            # force pd_data to be a 2D array (in case there's only one channel in ai_task so ai_task.read() returns a 1D array)
            if pd_data.ndim != 2:
                pd_data = np.reshape(pd_data, (len(pd_data), -1))

            # chop array, because the beginning part of the data array usually have undesired peaks
            start_length = round(self.parent.config["scan ignore"]/1000*self.samp_rate)
            pd_data = pd_data[:, start_length:]

            # remove baseline
            if self.parent.config["baseline remove"]:
                for i in range(len(pd_data)):
                    # logging.info(pd_data[i])
                    # _, pd_data_arPLS, info = self.baseline_arPLS(pd_data[i], ratio=1e-2, lam=1e5, niter=100, full_output=True) # great algorithm, just too slow for us
                    # pd_data[i] = pd_data_arPLS
                    pd_data[i] = pd_data[i] - np.mean(pd_data[i])

            # find cavity peaks using "peak height/width" criteria
            cavity_peaks, _ = signal.find_peaks(pd_data[0], height=self.parent.cavity.config["peak height"], width=self.parent.cavity.config["peak width"])

            # normally this frequency lock method requires two cavity scanning peaks
            if len(cavity_peaks) == 2:
                self.cavity_peak_found = True
                # convert the position of the first peak into unit ms
                cavity_first_peak = cavity_peaks[0]*self.dt*1000
                # convert the separation of peaks into unit ms
                cavity_pk_sep = (cavity_peaks[1] - cavity_peaks[0])*self.dt*1000
                # calculate cavity error signal in unit MHz
                cavity_err = (self.parent.cavity.config["set point"] - self.parent.config["scan ignore"] - cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"]
                # calculate cavity PID feedback voltage, use "scan time" for an approximate loop time
                cavity_feedback = self.cavity_last_feedback + \
                                  (cavity_err-self.cavity_last_err[1])*self.parent.cavity.config["kp"]*self.parent.cavity.config["kp on"] + \
                                  cavity_err*self.parent.cavity.config["ki"]*self.parent.cavity.config["ki on"]*(self.parent.config["scan time"]+self.parent.config["ramp up time"])/1000 + \
                                  (cavity_err+self.cavity_last_err[0]-2*self.cavity_last_err[1])*self.parent.cavity.config["kd"]*self.parent.cavity.config["kd on"]/((self.parent.config["scan time"]+self.parent.config["ramp up time"])/1000)
                # coerce cavity feedbak voltage to avoid big jump
                cavity_feedback = np.clip(cavity_feedback, self.cavity_last_feedback-self.parent.cavity.config["limit"], self.cavity_last_feedback+self.parent.cavity.config["limit"])
                # check if cavity feedback voltage is NaN, use feedback voltage from last cycle if it is
                if not np.isnan(cavity_feedback):
                    self.cavity_last_feedback = cavity_feedback
                    self.cavity_output = self.parent.cavity.config["offset"] + cavity_feedback
                else:
                    logging.warning("cavity feedback voltage is NaN.")
                    self.cavity_output = self.parent.cavity.config["offset"] + self.cavity_last_feedback
                self.cavity_last_err[0] = self.cavity_last_err[1]
                self.cavity_last_err[1] = cavity_err

                for i, laser in enumerate(self.parent.laser_list):
                    # find laser peak using "peak height/width" criteria
                    laser_peak, _ = signal.find_peaks(pd_data[i+1], height=laser.config["peak height"], width=laser.config["peak width"])
                    if len(laser_peak) > 0:
                        self.laser_peak_found[i] = True
                        # choose a frequency setpoint source
                        freq_setpoint = laser.config["global freq"] if laser.config["freq source"] == "global" else laser.config["local freq"]
                        
                        # calculate laser frequency error signal, use the peak that's closest to the setpoint
                        laser_err = freq_setpoint - (laser_peak*self.dt*1000-cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"]*(laser.config["wavenumber"]/self.parent.cavity.config["wavenumber"])
                        min_pos = np.argmin(abs(laser_err))
                        laser_err = laser_err[min_pos]

                        # below is the old calculated error using the first peak
                        # calculate laser frequency error signal, use the position of the first peak
                        # laser_err = freq_setpoint - (laser_peak[0]*self.dt*1000-cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"]*(laser.config["wavenumber"]/self.parent.cavity.config["wavenumber"])
                        
                        # calculate laser PID feedback volatge, use "scan time" for an approximate loop time
                        laser_feedback = self.laser_last_feedback[i] + \
                                         (laser_err-self.laser_last_err[i][1])*laser.config["kp"]*laser.config["kp on"] + \
                                         laser_err*laser.config["ki"]*laser.config["ki on"]*(self.parent.config["scan time"]+self.parent.config["ramp up time"])/1000 + \
                                         (laser_err+self.laser_last_err[i][0]-2*self.laser_last_err[i][1])*laser.config["kd"]*laser.config["kd on"]/((self.parent.config["scan time"]+self.parent.config["ramp up time"])/1000)
                        
                        # coerce laser feedbak voltage to avoid big jump
                        laser_feedback = np.clip(laser_feedback, self.laser_last_feedback[i]-self.parent.cavity.config["limit"], self.laser_last_feedback[i]+self.parent.cavity.config["limit"])
                        
                        # check if laser feedback voltage is NaN, use feedback voltage from last cycle if it is
                        if not np.isnan(laser_feedback):
                            self.laser_last_feedback[i] = laser_feedback
                            self.laser_output[i] = laser.config["offset"] + laser_feedback
                        else:
                            logging.warning(f"laser {i} feedback voltage is NaN.")
                            self.laser_output[i] = laser.config["offset"] + self.laser_last_feedback[i]
                        self.laser_last_err[i][0] = self.laser_last_err[i][1]
                        self.laser_last_err[i][1] = laser_err

                    else:
                        self.laser_peak_found[i] = False
                        self.laser_output[i] = laser.config["offset"] + self.laser_last_feedback[i]

            else:
                self.cavity_peak_found = False
                # otherwise use feedback voltage from last cycle
                cavity_first_peak = cavity_peaks[0]*self.dt*1000 if len(cavity_peaks)>0 else np.nan # in ms
                cavity_pk_sep = np.nan
                self.cavity_output = self.parent.cavity.config["offset"] + self.cavity_last_feedback
                for i, laser in enumerate(self.parent.laser_list):
                    self.laser_output[i] = laser.config["offset"] + self.laser_last_feedback[i]

            self.ao_task_write()

            # update GUI widgets every certain number of cycles
            if self.counter%self.parent.config["display per"] == 0:
                data_dict = {}
                data_dict["cavity pd_data"] = pd_data[0]
                data_dict["cavity first peak"] = cavity_first_peak
                data_dict["cavity pk sep"] = cavity_pk_sep
                data_dict["cavity error"] = self.cavity_last_err[1]
                data_dict["cavity output"] = self.cavity_output
                data_dict["cavity peak found"] = self.cavity_peak_found
                data_dict["laser pd_data"] = pd_data[1:, :]
                data_dict["laser error"] = self.laser_last_err[:, 1]
                data_dict["laser output"] = self.laser_output
                data_dict["laser peak found"] = self.laser_peak_found
                self.signal.emit(data_dict)

            self.counter += 1

        # save feedback voltage to parent data attribute
        self.parent.cavity_last_feedback = self.cavity_last_feedback
        self.parent.laser_last_feedback = self.laser_last_feedback

        # close all tasks and release resources when this loop finishes
        self.ai_task.close()
        self.cavity_ao_task.close()
        self.laser_ao_task.close()
        self.counter_task.close()
        self.do_task.close()
        self.counter = 0

    # initialize ai_task, which will handle analog read for all ai channels
    def ai_task_init(self):
        self.ai_task = nidaqmx.Task("ai task "+time.strftime("%Y%m%d_%H%M%S"))
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
        self.cavity_ao_task = nidaqmx.Task("cavity ao task "+time.strftime("%Y%m%d_%H%M%S"))
        # add cavity ao channel to this task
        cavity_ao_ch = self.cavity_ao_task.ao_channels.add_ao_voltage_chan(self.parent.cavity.config["daq ao"], min_val= self.parent.config["min cav ao"], max_val=self.parent.config["max cav ao"], units=nidaqmx.constants.VoltageUnits.VOLTS)
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
        self.laser_ao_task = nidaqmx.Task("laser ao task "+time.strftime("%Y%m%d_%H%M%S"))
        # add laser ao channel to this task
        for laser in self.parent.laser_list:
            self.laser_ao_task.ao_channels.add_ao_voltage_chan(laser.config["daq ao"], min_val= self.parent.config["min laser ao"], max_val= self.parent.config["max laser ao"], units=nidaqmx.constants.VoltageUnits.VOLTS)
        # no sample clock timing or trigger is specified, this task is running in "on demand" mode.

    # initialize a do task, it will be used to trigger the counter
    def do_task_init(self):
        self.do_task = nidaqmx.Task("do task "+time.strftime("%Y%m%d_%H%M%S"))
        self.do_task.do_channels.add_do_chan(self.parent.config["trigger channel"])
        # no sample clock timing or trigger is specified, this task is running in "on demand" mode.

    # initialize a counter task, it will be used as the clock for ai_task and cavity_ao_task
    def counter_task_init(self):
        self.counter_task = nidaqmx.Task("counter task "+time.strftime("%Y%m%d_%H%M%S"))
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

    def ao_task_write(self):
        # check if laser feedback voltage exceeds limits allowed value set by user, and cap it to the allowed value if so
        for i, laser in enumerate(self.parent.laser_list):  
            self.laser_output[i] = np.clip(self.laser_output[i], self.parent.config["min laser ao"], self.parent.config["max laser ao"])

        try:
            # generate laser piezo feedback voltage from ao channels
            self.laser_ao_task.write(self.laser_output)
        except nidaqmx.errors.DaqError as err:
            logging.error(f"A DAQ error happened at laser ao channels \n{err}")

        # check if cavity feedback voltage exceeds the limit allowed value set by user, and cap it to the allowed value if so
        self.cavity_output = np.clip(self.cavity_output, self.parent.config["min cav ao"], self.parent.config["max cav ao"] - self.parent.config["scan amp"])

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
            logging.info(f"This is the {self.err_counter}-th time error occurs. \n{err}")
            # Abort task, see https://zone.ni.com/reference/en-XX/help/370466AH-01/mxcncpts/taskstatemodel/
            self.cavity_ao_task.control(nidaqmx.constants.TaskMode.TASK_ABORT)
            # write to and and restart task
            self.cavity_ao_task.write(self.cavity_scan + self.cavity_output, auto_start=True)
            self.err_counter += 1

    # code from https://stackoverflow.com/a/67509948
    def baseline_arPLS(self, y, ratio=1e-6, lam=100, niter=50, full_output=False):
        # lam for lambda, smoothness parameter
        L = len(y)

        diag = np.ones(L - 2)
        D = sparse.spdiags([diag, -2*diag, diag], [0, -1, -2], L, L - 2)

        H = lam * D.dot(D.T)  # The transposes are flipped w.r.t the Algorithm on pg. 252

        w = np.ones(L)
        W = sparse.spdiags(w, 0, L, L)

        crit = 1
        count = 0

        while crit > ratio:
            z = linalg.spsolve(W + H, W * y)
            d = y - z
            dn = d[d < 0]

            m = np.mean(dn)
            s = np.std(dn)

            w_new = 1 / (1 + np.exp(2 * (d - (2*s - m))/s))

            crit = np.linalg.norm(w_new - w) / np.linalg.norm(w)

            w = w_new
            W.setdiag(w)  # Do not create a new matrix, just update diagonal values

            count += 1

            if count > niter:
                logging.warning('Maximum number of iterations exceeded')
                break

        if full_output:
            info = {'num_iter': count, 'stop_criterion': crit}
            return z, d, info
        else:
            return z

# There is a great tutorial about socket programming: https://realpython.com/python-sockets/
# part of my code is adapted from here.
class tcpThread(PyQt5.QtCore.QThread):
    signal = PyQt5.QtCore.pyqtSignal(dict)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.data = bytes()
        if self.parent.config["host address"] == "None":
            self.host = socket.gethostbyname(socket.gethostname())
        else:
            self.host = self.parent.config["host address"]
        self.port = self.parent.config["port"]
        self.sel = selectors.DefaultSelector()

        self.server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Avoid bind() exception: OSError: [Errno 48] Address already in use
        self.server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_sock.bind((self.host, self.port))
        self.server_sock.listen()
        logging.info(f"listening on: ({self.host}, {self.port})")
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
                        logging.error(f"TCP connection error: \n{err}")
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
                                # logging.info(f"laser {laser_num}: freq = {laser_freq}")
                                self.signal.emit({"type": "data", "laser": laser_num, "freq": laser_freq})
                                s.sendall(self.data[:10])
                                # self.do_task.write([True, False]*20)
                            except Exception as err:
                                logging.error(f"TCP Thread error: \n{err}")
                            finally:
                                self.data = self.data[10:]
                    else:
                        # empty data will be interpreted as the signal of client shutting down
                        logging.info("client shutting down...")
                        self.sel.unregister(s)
                        s.close()
                        self.signal.emit({"type": "close connection"})

        self.sel.unregister(self.server_sock)
        self.server_sock.close()
        self.sel.close()
        # self.do_task.close()

    def accept_wrapper(self, sock):
        conn, addr = sock.accept()  # Should be ready to read
        logging.info(f"accepted connection from: {addr}")
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
        self.config = {}
        self.active = False
        logging.getLogger().setLevel("INFO")

        self.box = NewBox(layout_type="grid")
        self.box.frame.setRowStretch(0, 3)
        self.box.frame.setRowStretch(1, 8)
        self.box.frame.setRowStretch(2, 3)

        # top part of this GUI, a plot
        self.scan_plot = NewPlot(self)
        fontstyle = {"color": "#919191", "font-size": "11pt"}
        self.scan_plot.setLabel("bottom", "time (ms)", **fontstyle)
        self.box.frame.addWidget(self.scan_plot, 0, 0)

        # bottom part of this GUI, another plot
        self.err_plot = NewPlot(self)
        self.err_plot.setLabel("left", "freq. error (MHz)", **fontstyle)
        self.box.frame.addWidget(self.err_plot, 2, 0)

        # middle part of this GUI, a box for control widgets
        ctrl_box = self.place_controls()
        self.box.frame.addWidget(ctrl_box, 1, 0)

        self.setCentralWidget(self.box)
        self.resize(pt_to_px(540), pt_to_px(750))
        self.show()

        cf = configparser.ConfigParser()
        cf.optionxform = str # make config key name case sensitive
        cf.read("saved_settings\config_latest.ini")

        self.update_daq_channel()
        self.update_config(cf)
        self.update_widgets()

        self.scan_plot.setRange(yRange=(0, self.cavity.config["peak height"]*2.6))

        # type of data that will be written into a hdf file for logging
        self.dtp = [('time', h5py.string_dtype(encoding='utf-8')), ('cavity DAQ voltage/V', 'f')]
        for i in range(len(self.laser_list)):
            self.dtp.append((f'laser{i} freq/MHz', 'f'))

        # used to save feedback voltage for daq_thread
        self.cavity_last_feedback = 0
        self.laser_last_feedback = np.zeros(len(self.laser_list), dtype=np.float64)

        # hide some control boxes
        self.toggle_more_ctrl()

    # place controls in the middle part of this GUI
    def place_controls(self):
        control_box = NewScrollArea(layout_type="vbox", scroll_type="both")

        # first sub-box in this part
        start_box = NewBox(layout_type="grid")
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
        self.scan_box = NewBox(layout_type="grid")
        self.scan_box.setMaximumWidth(pt_to_px(520))
        self.scan_box.setStyleSheet("QGroupBox {border: 1px solid #304249;}")
        control_box.frame.addWidget(self.scan_box)

        self.scan_box.frame.addWidget(qt.QLabel("Scan amp:"), 0, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_amp_dsb = NewDoubleSpinBox(range=(0, 10), decimals=2, suffix=" V")
        self.scan_amp_dsb.valueChanged[float].connect(lambda val, text="scan amp": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.scan_amp_dsb, 0, 1)

        self.scan_box.frame.addWidget(qt.QLabel("Scan time:"), 0, 2, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_time_dsb = NewDoubleSpinBox(range=(0, 100), decimals=1, suffix=" ms")
        self.scan_time_dsb.valueChanged[float].connect(lambda val, text="scan time": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.scan_time_dsb, 0, 3)

        self.scan_box.frame.addWidget(qt.QLabel("Scan ignore:"), 0, 4, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.scan_ignore_dsb = NewDoubleSpinBox(range=(0, 100), decimals=2, suffix=" ms")
        self.scan_ignore_dsb.valueChanged[float].connect(lambda val, text="scan ignore": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.scan_ignore_dsb, 0, 5)

        self.scan_box.frame.addWidget(qt.QLabel("Sample rate:"), 0, 6, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.samp_rate_sb = NewSpinBox(range=(0, 1000000), suffix=" S/s")
        self.samp_rate_sb.valueChanged[int].connect(lambda val, text="sampling rate": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.samp_rate_sb, 0, 7)

        self.scan_box.frame.addWidget(qt.QLabel("Cavity FSR:"), 1, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.cavity_fsr_dsb = NewDoubleSpinBox(range=(0, 10000), decimals=1, suffix=" MHz")
        self.cavity_fsr_dsb.valueChanged[float].connect(lambda val, text="cavity FSR": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.cavity_fsr_dsb, 1, 1)

        self.scan_box.frame.addWidget(qt.QLabel("Lock Criteria:"), 1, 2, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.lock_criteria_dsb = NewDoubleSpinBox(range=(0, 100), decimals=1, suffix=" MHz")
        self.lock_criteria_dsb.valueChanged[float].connect(lambda val, text="lock criteria": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.lock_criteria_dsb, 1, 3)

        self.scan_box.frame.addWidget(qt.QLabel("RMS Length:"), 1, 4, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.rms_length_sb = NewSpinBox(range=(0, 10000), suffix=None)
        self.rms_length_sb.valueChanged[int].connect(lambda val, text="RMS length": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.rms_length_sb, 1, 5)

        self.scan_box.frame.addWidget(qt.QLabel("Display per:"), 1, 6, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.disp_rate_sb = NewSpinBox(range=(5, 10000), suffix=" Cycles")
        self.disp_rate_sb.valueChanged[int].connect(lambda val, text="display per": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.disp_rate_sb, 1, 7)

        self.scan_box.frame.addWidget(qt.QLabel("Average:"), 2, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.ave_rate_sb = NewSpinBox(range=(1, 10000), suffix=" run(s)")
        self.ave_rate_sb.valueChanged[int].connect(lambda val, text="average": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.ave_rate_sb, 2, 1)

        self.scan_box.frame.addWidget(qt.QLabel("Baseline reomove:"), 2, 2, 1, 2, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.baseline_chb = qt.QCheckBox()
        self.baseline_chb.setTristate(False)
        self.baseline_chb.toggled[bool].connect(lambda val, text="baseline remove": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.baseline_chb, 2, 4)     
        
        self.scan_box.frame.addWidget(qt.QLabel("Counter ch:"), 3, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.counter_cb = NewComboBox()
        self.counter_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.counter_cb.currentTextChanged[str].connect(lambda val, text="counter channel": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.counter_cb, 3, 1, 1, 2)

        self.scan_box.frame.addWidget(qt.QLabel("Counter PFI:"), 3, 4, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.counter_pfi_cb = NewComboBox()
        self.counter_pfi_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.counter_pfi_cb.currentTextChanged[str].connect(lambda val, text="counter PFI line": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.counter_pfi_cb, 3, 5, 1, 2)

        self.scan_box.frame.addWidget(qt.QLabel("Trigger ch:"), 4, 0, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.trigger_cb = NewComboBox()
        self.trigger_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.trigger_cb.currentTextChanged[str].connect(lambda val, text="trigger channel": self.update_config_elem(text, val))
        self.scan_box.frame.addWidget(self.trigger_cb, 4, 1, 1, 2)

        self.refresh_daq_pb = qt.QPushButton("Refresh DAQ channels")
        self.refresh_daq_pb.clicked[bool].connect(lambda val: self.refresh_all_daq_ch())
        self.scan_box.frame.addWidget(self.refresh_daq_pb, 4, 4, 1, 3)

        # third sub-box in this part, used for setting saving/loading control
        self.file_box = NewBox(layout_type="hbox")
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
        self.tcp_box = NewBox(layout_type="hbox")
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

        self.laser_box = NewBox(layout_type="hbox")
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
            i = len(self.laser_list)
            laser = laserColumn(i, self)
            laser.scan_curve = self.scan_plot.plot()
            # laser.scan_curve.setPen(self.color_list[i%3], width=1)
            laser.err_curve = self.err_plot.plot()
            # laser.err_curve.setPen(self.color_list[i%3])
            # laser.label_box.setStyleSheet("QGroupBox{background: "+self.color_list[i%3]+"}")
            self.laser_list.append(laser)
            self.laser_box.frame.addWidget(laser)

        # delete laser columns
        while num_lasers < len(self.laser_list):
            self.laser_list[-1].scan_curve.clear()
            self.laser_list[-1].err_curve.clear()
            self.laser_list[-1].setParent(None)
            del self.laser_list[-1]

        num_color = len(self.config["color list"])
        for i, laser in enumerate(self.laser_list):
            laser.scan_curve.setPen(self.config["color list"][i%num_color], width=1)
            laser.err_curve.setPen(self.config["color list"][i%num_color])
            laser.label_box.setStyleSheet("QGroupBox{background: "+self.config["color list"][i%num_color]+"}")

    # update self.config from config
    def update_config(self, config):
        self.tcp_stop()

        self.config["scan amp"] = config["Setting"].getfloat("scan amp/V")
        self.config["min cav ao"] = config["Setting"].getfloat("min cav ao/V")
        self.config["max cav ao"] = config["Setting"].getfloat("max cav ao/V")
        self.config["min laser ao"] = config["Setting"].getfloat("min laser ao/V")
        self.config["max laser ao"] = config["Setting"].getfloat("max laser ao/V")
        self.config["scan time"] = config["Setting"].getfloat("scan time/ms")
        self.config["ramp up time"] = config["Setting"].getfloat("ramp up time/ms")
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
        self.config["hdf_filename"] = config["Setting"].get("hdf_filename")
        self.config["window title"] = config["Setting"].get("window title")
        self.config["color list"] = [x.strip() for x in config["Setting"].get("color list").split(",")]
        self.config["average"] = config["Setting"].getint("average")
        self.config["baseline remove"] = config["Setting"].getboolean("baseline remove")

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
        self.setWindowTitle(self.config["window title"])

        self.scan_amp_dsb.setValue(self.config["scan amp"])
        self.samp_rate_sb.setValue(self.config["sampling rate"])
        self.cavity_fsr_dsb.setValue(self.config["cavity FSR"])
        self.lock_criteria_dsb.setValue(self.config["lock criteria"])
        self.rms_length_sb.setValue(self.config["RMS length"])
        self.disp_rate_sb.setValue(self.config["display per"])
        self.ave_rate_sb.setValue(self.config["average"])
        self.baseline_chb.setChecked(self.config["baseline remove"])

        self.counter_cb.setCurrentText(self.config["counter channel"])
        self.config["counter channel"] = self.counter_cb.currentText()
        self.counter_pfi_cb.setCurrentText(self.config["counter PFI line"])
        self.config["counter PFI line"] = self.counter_pfi_cb.currentText()
        self.trigger_cb.setCurrentText(self.config["trigger channel"])
        self.config["trigger channel"] = self.trigger_cb.currentText()

        if self.config["host address"] == "None":
            self.server_addr_la.setText(socket.gethostbyname(socket.gethostname())+" ("+str(self.config["port"])+")")
        else:
            self.server_addr_la.setText(self.config["host address"]+" ("+str(self.config["port"])+")")

        self.cavity.update_widgets()
        for laser in self.laser_list:
            laser.update_widgets()

        # update this two after updating cavity.setpoint_dsb, because they may change its config value
        # see self.update_config_elem function
        self.scan_ignore_dsb.setValue(self.config["scan ignore"])
        self.scan_time_dsb.setValue(self.config["scan time"])

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

        config = self.compile_config()

        configfile = open(file_name, "w")
        config.write(configfile)
        configfile.close()

    def compile_config(self):
        config = configparser.ConfigParser(allow_no_value=True)
        config.optionxform = str

        config["Setting"] = {}
        config["Setting"]["scan amp/V"] = str(self.config["scan amp"])
        config["Setting"]["min cav ao/V"] = str(self.config["min cav ao"])
        config["Setting"]["max cav ao/V"] = str(self.config["max cav ao"])
        config["Setting"]["min laser ao/V"] = str(self.config["min laser ao"])
        config["Setting"]["max laser ao/V"] = str(self.config["max laser ao"])
        config["Setting"]["scan time/ms"] = str(self.config["scan time"])
        config["Setting"]["ramp up time/ms"] = str(self.config["ramp up time"])
        config["Setting"]["scan ignore/ms"] = str(self.config["scan ignore"])
        config["Setting"]["sampling rate"] = str(self.config["sampling rate"])
        config["Setting"]["cavity FSR/MHz"] = str(self.config["cavity FSR"])
        config["Setting"]["lock criteria/MHz"] = str(self.config["lock criteria"])
        config["Setting"]["RMS length"] = str(self.config["RMS length"])
        config["Setting"]["display per"] = str(self.config["display per"])
        config["Setting"]["counter channel"] = self.config["counter channel"]
        config["Setting"]["counter PFI line"] = self.config["counter PFI line"]
        config["Setting"]["trigger channel"] = self.config["trigger channel"]
        config["Setting"]["# host address can be None or a valid address"] = None
        config["Setting"]["host address"] = self.config["host address"]
        config["Setting"]["port"] = str(self.config["port"])
        config["Setting"]["num of lasers"] = str(len(self.laser_list))
        config["Setting"]["hdf_filename"] = self.config["hdf_filename"]
        config["Setting"]["window title"] = self.config["window title"]
        config["Setting"]["color list"] = ", ".join(self.config["color list"])
        config["Setting"]["average"] = str(self.config["average"])
        config["Setting"]["baseline remove"] = str(self.config["baseline remove"])

        # export cavity/laser config
        config["Cavity"] = self.cavity.save_config()
        for i, laser in enumerate(self.laser_list):
            config[f"Laser{i}"] = laser.save_config()

        return config

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

        self.last_time_logging = 0
        self.daq_start()

    # update GUI indicators to show feedback loop status
    @PyQt5.QtCore.pyqtSlot(dict)
    def feedback(self, dict):
        data_len = len(dict["cavity pd_data"])
        self.cavity.scan_curve.setData(np.linspace(self.config["scan ignore"], self.config["scan time"]+self.config["ramp up time"], data_len), dict["cavity pd_data"])
        self.cavity.first_peak_la.setText("{:.2f} ms".format(self.config["scan ignore"]+dict["cavity first peak"]))
        self.cavity.peak_sep_la.setText("{:.2f} ms".format(dict["cavity pk sep"]))
        if dict["cavity output"] == self.config["min cav ao"] or dict["cavity output"] == self.config["max cav ao"]-self.config["scan amp"]:
            self.cavity.daq_output_la.setText("{:.3f} V (CAPPED!!)".format(dict["cavity output"]))
        else:
            self.cavity.daq_output_la.setText("{:.3f} V".format(dict["cavity output"]))
        self.cavity_err_queue.append(dict["cavity error"])
        rms = np.std(self.cavity_err_queue)
        self.cavity.rms_width_la.setText("{:.2f} MHz".format(rms))
        if rms < self.config["lock criteria"] and np.abs(dict["cavity error"]) < self.config["lock criteria"] and dict["cavity peak found"]:
            if not self.cavity.locked:
                self.cavity.locked = True
                self.cavity.locked_la.setStyleSheet("QLabel{background: green}")
        else:
            if self.cavity.locked:
                self.cavity.locked = False
                self.cavity.locked_la.setStyleSheet("QLabel{background: #304249}")
        self.cavity.err_curve.setData(np.array(self.cavity_err_queue))

        act_freq = []
        for i, laser in enumerate(self.laser_list):
            laser.scan_curve.setData(np.linspace(self.config["scan ignore"], self.config["scan time"]+self.config["ramp up time"], data_len), dict["laser pd_data"][i])
            if dict["laser output"][i] == self.config["min laser ao"] or dict["laser output"][i] == self.config["max laser ao"]:
                laser.daq_output_la.setText("{:.3f} V (CAPPED!!)".format(dict["laser output"][i]))
            else:
                laser.daq_output_la.setText("{:.3f} V".format(dict["laser output"][i]))
            self.laser_err_list[i].append(dict["laser error"][i])
            freq_setpoint = laser.config["local freq"] if laser.config["freq source"] == "local" else laser.config["global freq"]
            act_freq.append(freq_setpoint-dict["laser error"][i] if dict["laser peak found"][i] else np.NaN)
            laser.actual_freq_la.setText("{:.1f} MHz".format(act_freq[i]))
            rms = np.std(self.laser_err_list[i])
            laser.rms_width_la.setText("{:.2f} MHz".format(rms))
            if (rms < self.config["lock criteria"]) and (np.abs(dict["laser error"][i]) < self.config["lock criteria"]) and dict["cavity peak found"] and dict["laser peak found"][i]:
                if not laser.locked:
                    laser.locked = True
                    laser.locked_la.setStyleSheet("QLabel{background: green}")
            else:
                if laser.locked:
                    laser.locked = False
                    laser.locked_la.setStyleSheet("QLabel{background: #304249}")
            laser.err_curve.setData(np.array(self.laser_err_list[i]))

        # log laser frequency and cavity PZT voltage
        t = time.time()
        if t - self.last_time_logging > 120: # in second
            data = [time.strftime("%H:%M:%S"), dict["cavity output"]] + act_freq
            with h5py.File(self.config["hdf_filename"] + "_" + time.strftime("%Y%b") + ".hdf", "a") as hdf_file:
                key = time.strftime("%b%d")
                if key in hdf_file.keys():
                    dset = hdf_file[key]
                    counter = 2
                    # if the number of lasers changes, data can't be written to the old dset, because of its different format
                    # if the number of lasers changes, search if there's a dset that has the right format, otherwise create a new one
                    # dset is named after time.strftime("%b%d") or time.strftime("%b%d") + f"_{counter}" (e.g. Jan24 or Jan24_2)
                    while len(dset[0]) != len(data):
                        if (key + f"_{counter}") in hdf_file.keys():
                            dset = hdf_file[key + f"_{counter}"]
                            counter += 1
                        else:
                            dset = hdf_file.create_dataset(key + f"_{counter}", shape=(0,), dtype=self.dtp, maxshape=(None,), compression="gzip", compression_opts=4)
                            break
                else:
                    dset = hdf_file.create_dataset(key, shape=(0,), dtype=self.dtp, maxshape=(None,), compression="gzip", compression_opts=4)

                dset.resize(dset.shape[0]+1, axis=0)
                dset[-1:] = [tuple(data)]
                self.last_time_logging = t

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
            logging.warning("TCP thread return dict type not supported")

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

    def closeEvent(self, event):
        if not self.active:
            config = self.compile_config()
            configfile = open("saved_settings\config_latest.ini", "w")
            config.write(configfile)
            configfile.close()

            super().closeEvent(event)

        else:
            # ask if continue to close
            ans = qt.QMessageBox.warning(self, 'Program warning',
                                'Warning: the program is running. Conitnue to close the program?',
                                qt.QMessageBox.Yes | qt.QMessageBox.No,
                                qt.QMessageBox.No)
            if ans == qt.QMessageBox.Yes:
                config = self.compile_config()
                configfile = open("saved_settings\config_latest.ini", "w")
                config.write(configfile)
                configfile.close()

                super().closeEvent(event)
            else:
                event.ignore()

if __name__ == '__main__':

    app = qt.QApplication(sys.argv)
    # screen = app.screens()
    # monitor_dpi = screen[0].physicalDotsPerInch()
    # monitor_dpi = 96
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    prog = mainWindow(app)
    app.exec_()

    # make sure daq and tcp threads are closed
    prog.tcp_stop()
    prog.daq_stop()
    sys.exit()
