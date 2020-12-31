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


class hBox(qt.QWidget):
    def __init__(self):
        super().__init__()
        self.frame = qt.QHBoxLayout()
        self.frame.setContentsMargins(0,0,0,0)
        self.setLayout(self.frame)


class abstractLaserColumn(qt.QGroupBox):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent

        self.frame = qt.QVBoxLayout()
        self.setLayout(self.frame)

    def place_peak_box(self):
        peak_box = qt.QGroupBox()
        self.frame.addWidget(peak_box)
        peak_frame = qt.QFormLayout()
        peak_box.setLayout(peak_frame)

        self.peak_height_dsb = qt.QDoubleSpinBox()
        self.peak_height_dsb.setRange(0, 10000)
        self.peak_height_dsb.setDecimals(0)
        self.peak_height_dsb.setSingleStep(10)
        self.peak_height_dsb.setSuffix(" mV")
        peak_frame.addRow("Peak height:", self.peak_height_dsb)

        self.peak_width_sb = qt.QSpinBox()
        self.peak_width_sb.setRange(0, 1000)
        self.peak_width_sb.setSuffix(" pts")
        peak_frame.addRow("Peak width:", self.peak_width_sb)

    def place_freq_box(self):
        freq_box = qt.QGroupBox()
        self.frame.addWidget(freq_box)
        self.freq_frame = qt.QFormLayout()
        freq_box.setLayout(self.freq_frame)

    def place_pid_box(self):
        pid_box = qt.QGroupBox()
        self.frame.addWidget(pid_box)
        pid_frame = qt.QFormLayout()
        pid_box.setLayout(pid_frame)

        self.kp_dsb = qt.QDoubleSpinBox()
        self.kp_dsb.setRange(-100, 100)
        self.kp_dsb.setDecimals(5)
        self.kp_dsb.setSingleStep(0.0001)
        self.kp_dsb.setSuffix("")

        self.kp_chb = qt.QCheckBox()
        self.kp_chb.setTristate(False)

        kp_box = hBox()
        kp_box.frame.addWidget(self.kp_dsb)
        kp_box.frame.addWidget(self.kp_chb)
        pid_frame.addRow("KP:", kp_box)

        self.ki_dsb = qt.QDoubleSpinBox()
        self.ki_dsb.setRange(-100, 100)
        self.ki_dsb.setDecimals(5)
        self.ki_dsb.setSingleStep(0.0001)
        self.ki_dsb.setSuffix("")

        self.ki_chb = qt.QCheckBox()
        self.ki_chb.setTristate(False)

        ki_box = hBox()
        ki_box.frame.addWidget(self.ki_dsb)
        ki_box.frame.addWidget(self.ki_chb)
        pid_frame.addRow("KI:", ki_box)

        self.kd_dsb = qt.QDoubleSpinBox()
        self.kd_dsb.setRange(-100, 100)
        self.kd_dsb.setDecimals(5)
        self.kd_dsb.setSingleStep(0.0001)
        self.kd_dsb.setSuffix("")

        self.kd_chb = qt.QCheckBox()
        self.kd_chb.setTristate(False)

        kd_box = hBox()
        kd_box.frame.addWidget(self.kd_dsb)
        kd_box.frame.addWidget(self.kd_chb)
        pid_frame.addRow("KD:", kd_box)

        self.offset_dsb = qt.QDoubleSpinBox()
        self.offset_dsb.setRange(-10, 10)
        self.offset_dsb.setDecimals(2)
        self.offset_dsb.setSingleStep(0.1)
        self.offset_dsb.setSuffix(" V")
        pid_frame.addRow("Offset:", self.offset_dsb)

        self.limit_dsb = qt.QDoubleSpinBox()
        self.limit_dsb.setRange(-10, 10)
        self.limit_dsb.setDecimals(5)
        self.limit_dsb.setSingleStep(0.001)
        self.limit_dsb.setSuffix(" V")
        pid_frame.addRow("Limit:", self.limit_dsb)

        self.daq_output_la = qt.QLabel("0 V")
        pid_frame.addRow("DAQ output:", self.daq_output_la)

        self.rms_width_la = qt.QLabel("0 MHz")
        pid_frame.addRow("RMS linewidth:", self.rms_width_la)

        self.locked_la = qt.QLabel()
        pid_frame.addRow("Locked:", self.locked_la)

    def place_daq_box(self):
        daq_box = qt.QGroupBox()
        self.frame.addWidget(daq_box)
        self.daq_frame = qt.QFormLayout()
        daq_box.setLayout(self.daq_frame)

        self.daq_in_cb = qt.QComboBox()
        self.daq_frame.addRow("DAQ input:", self.daq_in_cb)

        self.daq_out_cb = qt.QComboBox()
        self.daq_frame.addRow("DAQ input:", self.daq_out_cb)

        self.wavenum_dsb = qt.QDoubleSpinBox()
        self.wavenum_dsb.setRange(0, 20000)
        self.wavenum_dsb.setDecimals(1)
        self.wavenum_dsb.setSingleStep(1)
        self.wavenum_dsb.setSuffix("  1/cm")
        self.daq_frame.addRow("Wave Number:", self.wavenum_dsb)


class cavityColumn(abstractLaserColumn):
    def __init__(self, parent):
        super().__init__(parent)


class laserColumn(abstractLaserColumn):
    def __init__(self, parent):
        super().__init__(parent)

        self.place_peak_box()
        self.place_freq_box()
        self.place_freq_widget()
        self.place_pid_box()
        self.place_daq_box()

    def place_freq_widget(self):
        self.global_freq_la = qt.QLabel("0 MHz")

        self.global_rb = qt.QRadioButton()
        rbgroup = qt.QButtonGroup(self.parent)
        rbgroup.addButton(self.global_rb)

        global_box = hBox()
        global_box.frame.addWidget(self.global_freq_la)
        global_box.frame.addWidget(self.global_rb)
        self.freq_frame.addRow("Global Freq.:", global_box)

        self.local_freq_dsb = qt.QDoubleSpinBox()
        self.local_freq_dsb.setRange(0, 1500)
        self.local_freq_dsb.setDecimals(1)
        self.local_freq_dsb.setSingleStep(1)
        self.local_freq_dsb.setSuffix(" MHz")

        self.local_rb = qt.QRadioButton()
        self.local_rb.setChecked(True)
        rbgroup.addButton(self.local_rb)

        local_box = hBox()
        local_box.frame.addWidget(self.local_freq_dsb)
        local_box.frame.addWidget(self.local_rb)
        self.freq_frame.addRow("Local Freq.:", local_box)

        self.actual_freq_la = qt.QLabel("0 MHz")
        self.freq_frame.addRow("Actual Freq.:", self.actual_freq_la)


class mainWindow(qt.QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setCentralWidget(laserColumn(self))

        self.resize(600, 900)
        self.show()


if __name__ == '__main__':
    app = qt.QApplication(sys.argv)
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    prog = mainWindow(app)
    app.exec_()
    sys.exit(0)
