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
        self.setStyleSheet("QWidget{padding-left:0}")
        self.frame = qt.QHBoxLayout()
        self.frame.setContentsMargins(0,0,0,0)
        self.setLayout(self.frame)

class hLine(qt.QLabel):
    def __init__(self):
        super().__init__()
        self.setText("-"*50)
        self.setMaximumHeight(8)

class formBox(qt.QGroupBox):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("QGroupBox{border: 0; padding-left: 0; padding-right: 0;}")
        self.frame = qt.QFormLayout()
        self.frame.setContentsMargins(0,0,0,0)
        self.setLayout(self.frame)

# create a scroll area of a specific layout, e.g. form, grid, vbox, etc
class scrollArea(qt.QGroupBox):
    def __init__(self):
        super().__init__()
        self.setStyleSheet("QGroupBox{margin-top: 0;}")
        outer_layout = qt.QGridLayout()
        outer_layout.setContentsMargins(0,0,0,0)
        self.setLayout(outer_layout)

        scroll = qt.QScrollArea()
        scroll.setWidgetResizable(True)
        # scroll.setFrameStyle(0x10) # see https://doc.qt.io/qt-5/qframe.html for different frame styles
        scroll.setStyleSheet("QFrame{border: 0px}")
        outer_layout.addWidget(scroll)

        box = qt.QWidget()
        scroll.setWidget(box)
        self.frame = qt.QHBoxLayout()
        self.frame.setContentsMargins(0,0,0,0)
        box.setLayout(self.frame)


class abstractLaserColumn(qt.QGroupBox):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.setMaximumWidth(160)

        self.frame = qt.QVBoxLayout()
        self.frame.setContentsMargins(0,0,0,0)
        self.frame.setSpacing(0)
        self.setLayout(self.frame)

    def place_label(self, text):
        label_box = hBox()
        label_box.frame.addWidget(qt.QLabel(text))

        self.label_la = qt.QLineEdit()
        label_box.frame.addWidget(self.label_la)
        self.frame.addWidget(label_box)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    def place_peak_box(self):
        peak_box = formBox()
        self.frame.addWidget(peak_box)

        self.peak_height_dsb = qt.QDoubleSpinBox()
        self.peak_height_dsb.setRange(0, 10000)
        self.peak_height_dsb.setDecimals(0)
        self.peak_height_dsb.setSingleStep(10)
        self.peak_height_dsb.setSuffix(" mV")
        peak_box.frame.addRow("Peak height:", self.peak_height_dsb)

        self.peak_width_sb = qt.QSpinBox()
        self.peak_width_sb.setRange(0, 1000)
        self.peak_width_sb.setSuffix(" pts")
        peak_box.frame.addRow("Peak width:", self.peak_width_sb)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    def place_freq_box(self):
        self.freq_box = formBox()
        self.frame.addWidget(self.freq_box)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    def place_pid_box(self):
        pid_box = formBox()
        self.frame.addWidget(pid_box)

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
        pid_box.frame.addRow("KP:", kp_box)

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
        pid_box.frame.addRow("KI:", ki_box)

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
        pid_box.frame.addRow("KD:", kd_box)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    def place_voltage_box(self):
        voltage_box = formBox()
        self.frame.addWidget(voltage_box)

        self.offset_dsb = qt.QDoubleSpinBox()
        self.offset_dsb.setRange(-10, 10)
        self.offset_dsb.setDecimals(2)
        self.offset_dsb.setSingleStep(0.1)
        self.offset_dsb.setSuffix(" V")
        voltage_box.frame.addRow("Offset:", self.offset_dsb)

        self.limit_dsb = qt.QDoubleSpinBox()
        self.limit_dsb.setRange(-10, 10)
        self.limit_dsb.setDecimals(3)
        self.limit_dsb.setSingleStep(0.01)
        self.limit_dsb.setSuffix(" mV")
        voltage_box.frame.addRow("Limit:", self.limit_dsb)

        self.daq_output_la = qt.QLabel("0 V")
        voltage_box.frame.addRow("DAQ ao:", self.daq_output_la)

        self.rms_width_la = qt.QLabel("0 MHz")
        voltage_box.frame.addRow("RMS width:", self.rms_width_la)

        self.locked_la = qt.QLabel()
        voltage_box.frame.addRow("Locked:", self.locked_la)

        self.frame.addWidget(hLine(), alignment = PyQt5.QtCore.Qt.AlignHCenter)

    def place_daq_box(self):
        daq_box = formBox()
        self.frame.addWidget(daq_box)

        self.daq_in_cb = qt.QComboBox()
        self.daq_in_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.daq_in_cb.setMaximumWidth(95)
        daq_box.frame.addRow("DAQ ai:", self.daq_in_cb)

        self.daq_out_cb = qt.QComboBox()
        self.daq_out_cb.setStyleSheet("QComboBox {padding-right: 0px;}")
        self.daq_out_cb.setMaximumWidth(95)
        self.daq_out_cb.setMinimumContentsLength(20)
        daq_box.frame.addRow("DAQ ao:", self.daq_out_cb)

        self.wavenum_dsb = qt.QDoubleSpinBox()
        self.wavenum_dsb.setMaximumWidth(95)
        self.wavenum_dsb.setRange(0, 20000)
        self.wavenum_dsb.setDecimals(1)
        self.wavenum_dsb.setSingleStep(1)
        self.wavenum_dsb.setSuffix("  1/cm")
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


class cavityColumn(abstractLaserColumn):
    def __init__(self, parent):
        super().__init__(parent)

        self.place_label("Cavity:")
        self.place_peak_box()
        self.place_freq_box()
        self.place_pid_box()
        self.place_voltage_box()
        self.place_daq_box()
        self.update_daq_channel()


class laserColumn(abstractLaserColumn):
    def __init__(self, parent):
        super().__init__(parent)

        self.place_label("Laser:")
        self.place_peak_box()
        self.place_freq_box()
        self.place_freq_widget()
        self.place_pid_box()
        self.place_voltage_box()
        self.place_daq_box()
        self.update_daq_channel()

    def place_freq_widget(self):
        self.global_freq_la = qt.QLabel("0 MHz")
        self.global_freq_la.setToolTip("Global Frequency")

        self.global_rb = qt.QRadioButton()
        rbgroup = qt.QButtonGroup(self.parent)
        rbgroup.addButton(self.global_rb)

        global_box = hBox()
        global_box.frame.addWidget(self.global_freq_la)
        global_box.frame.addWidget(self.global_rb, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.freq_box.frame.addRow("G. F.:", global_box)

        self.local_freq_dsb = qt.QDoubleSpinBox()
        self.local_freq_dsb.setToolTip("Local Frequency")
        self.local_freq_dsb.setRange(0, 1500)
        self.local_freq_dsb.setDecimals(1)
        self.local_freq_dsb.setSingleStep(1)
        self.local_freq_dsb.setSuffix(" MHz")

        self.local_rb = qt.QRadioButton()
        self.local_rb.setChecked(True)
        rbgroup.addButton(self.local_rb)

        local_box = hBox()
        local_box.frame.addWidget(self.local_freq_dsb)
        local_box.frame.addWidget(self.local_rb, alignment = PyQt5.QtCore.Qt.AlignRight)
        self.freq_box.frame.addRow("L. F.:", local_box)

        self.actual_freq_la = qt.QLabel("0 MHz")
        self.actual_freq_la.setToolTip("Actual Frequency")
        self.freq_box.frame.addRow("A. F.:", self.actual_freq_la)


class mainWindow(qt.QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Transfer Cavity Laser Lock")

        scrollregion = scrollArea()
        self.setCentralWidget(scrollregion)

        self.cavity = cavityColumn(self)
        scrollregion.frame.addWidget(self.cavity)
        self.laser_list = []
        for i in range(3):
            self.laser_list.append(laserColumn(self))
            scrollregion.frame.addWidget(self.laser_list[-1])

        self.resize(600, 600)
        self.show()


if __name__ == '__main__':
    app = qt.QApplication(sys.argv)
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    prog = mainWindow(app)
    app.exec_()
    sys.exit(0)
