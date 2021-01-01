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
    def __init__(self):
        super().__init__()
        self.setFocusPolicy(PyQt5.QtCore.Qt.StrongFocus)

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
        # self.setSizePolicy(QtGui.QSizePolicy.Fixed, QtGui.QSizePolicy.Fixed)
        # self.setGeometry(100,100, 200, 200)
        # self.resize(500,150)
        tickstyle = {"showValues": False}
        fontstyle = {"color": "#919191", "font-size": "11pt"}

        self.showGrid(True, True)
        self.setLabel("top")
        self.getAxis("top").setStyle(**tickstyle)
        self.setLabel("right")
        self.getAxis("right").setStyle(**tickstyle)

        self.setLabel("bottom", "time", **fontstyle)
        self.getAxis("bottom").enableAutoSIPrefix(False)
        self.cavity_curve = self.plot()
        self.cavity_curve.setPen('w')  ## white pen
        self.laser_curves = []
        color_list = ['r', 'b', 'g']
        for i in range(3):
            curve = self.plot()
            curve.setPen(color_list[i])
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

        self.peak_height_dsb = newDoubleSpinBox()
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
        self.freq_box = newBox(layout_type="form")
        self.frame.addWidget(self.freq_box)

        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_pid_box(self):
        pid_box = newBox(layout_type="form")
        self.frame.addWidget(pid_box)

        self.kp_dsb = newDoubleSpinBox()
        self.kp_dsb.setRange(-100, 100)
        self.kp_dsb.setDecimals(2)
        self.kp_dsb.setSingleStep(1)
        self.kp_multiplier = "1e-5"
        self.kp_dsb.setSuffix("  "+self.kp_multiplier)

        self.kp_chb = qt.QCheckBox()
        self.kp_chb.setTristate(False)

        kp_box = newBox(layout_type="hbox")
        kp_box.frame.addWidget(self.kp_dsb)
        kp_box.frame.addWidget(self.kp_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow(r"KP:", kp_box)

        self.ki_dsb = newDoubleSpinBox()
        self.ki_dsb.setRange(-100, 100)
        self.ki_dsb.setDecimals(2)
        self.ki_dsb.setSingleStep(1)
        self.ki_multiplier = "1e-3"
        self.ki_dsb.setSuffix("  "+self.ki_multiplier)

        self.ki_chb = qt.QCheckBox()
        self.ki_chb.setTristate(False)

        ki_box = newBox(layout_type="hbox")
        ki_box.frame.addWidget(self.ki_dsb)
        ki_box.frame.addWidget(self.ki_chb, alignment = PyQt5.QtCore.Qt.AlignRight)
        pid_box.frame.addRow("KI:", ki_box)

        self.kd_dsb = newDoubleSpinBox()
        self.kd_dsb.setRange(-100, 100)
        self.kd_dsb.setDecimals(2)
        self.kd_dsb.setSingleStep(1)
        self.kd_multiplier = "1e-7"
        self.kd_dsb.setSuffix("  "+self.kd_multiplier)

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

        self.offset_dsb = newDoubleSpinBox()
        self.offset_dsb.setRange(-10, 10)
        self.offset_dsb.setDecimals(2)
        self.offset_dsb.setSingleStep(0.1)
        self.offset_dsb.setSuffix(" V")
        voltage_box.frame.addRow("Offset:", self.offset_dsb)

        self.limit_dsb = newDoubleSpinBox()
        self.limit_dsb.setRange(-10, 10)
        self.limit_dsb.setDecimals(3)
        self.limit_dsb.setSingleStep(0.01)
        self.limit_dsb.setSuffix(" V")
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

        self.wavenum_dsb = newDoubleSpinBox()
        self.wavenum_dsb.setMaximumWidth(pt_to_px(74))
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
        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

    def place_freq_widget(self):
        self.first_peak_la = qt.QLabel("0")
        self.freq_box.frame.addRow("First peak:", self.first_peak_la)

        self.peak_sep_la = qt.QLabel("0")
        self.freq_box.frame.addRow("Pk-pk sep.:", self.peak_sep_la)

        self.setpoint_dsb = newDoubleSpinBox()
        self.setpoint_dsb.setRange(-100, 100)
        self.setpoint_dsb.setDecimals(5)
        self.setpoint_dsb.setSingleStep(0.001)
        self.freq_box.frame.addRow("Set point:", self.setpoint_dsb)


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
        label_box = newBox(layout_type="hbox")
        la = qt.QLabel("  Laser:")
        la.setStyleSheet("QLabel{font: 16pt;}")
        label_box.frame.addWidget(la, alignment=PyQt5.QtCore.Qt.AlignRight)

        self.label_le = qt.QLineEdit()
        self.label_le.setStyleSheet("QLineEdit{font: 16pt;}")
        self.label_le.setMaximumWidth(pt_to_px(30))
        label_box.frame.addWidget(self.label_le, alignment=PyQt5.QtCore.Qt.AlignLeft)
        self.frame.addWidget(label_box)

        self.frame.addWidget(hLine(), alignment=PyQt5.QtCore.Qt.AlignHCenter)

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

        self.local_freq_dsb = newDoubleSpinBox()
        self.local_freq_dsb.setToolTip("Local Frequency")
        self.local_freq_dsb.setRange(0, 1500)
        self.local_freq_dsb.setDecimals(1)
        self.local_freq_dsb.setSingleStep(1)
        self.local_freq_dsb.setSuffix(" MHz")

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


class mainWindow(qt.QMainWindow):
    def __init__(self, app):
        super().__init__()
        self.app = app
        self.setWindowTitle("Transfer Cavity Laser Lock")

        self.box = newBox(layout_type="grid")
        self.box.frame.setRowStretch(0, 3)
        self.box.frame.setRowStretch(1, 8)
        self.box.frame.setRowStretch(2, 3)

        self.scan_plot = newPlot(self)
        self.box.frame.addWidget(self.scan_plot, 0, 0)

        ctrl_box = self.place_controls()
        self.box.frame.addWidget(ctrl_box, 1, 0)

        self.err_plot = newPlot(self)
        self.box.frame.addWidget(self.err_plot, 2, 0)

        self.setCentralWidget(self.box)
        self.resize(pt_to_px(500), pt_to_px(500))
        self.show()

    def place_controls(self):
        control_box = scrollArea(layout_type="vbox", scroll_type="both")
        laser_box = newBox(layout_type="hbox")
        control_box.frame.addWidget(laser_box)

        self.cavity = cavityColumn(self)
        laser_box.frame.addWidget(self.cavity)
        self.laser_list = []
        for i in range(3):
            self.laser_list.append(laserColumn(self))
            laser_box.frame.addWidget(self.laser_list[-1])

        file_box = newBox(layout_type="grid")
        control_box.frame.addWidget(file_box)
        file_box.frame.addWidget(qt.QLabel("file names888888888888888888888"), 0, 0)

        return control_box


if __name__ == '__main__':
    app = qt.QApplication(sys.argv)
    # screen = app.screens()
    # monitor_dpi = screen[0].physicalDotsPerInch()
    monitor_dpi = 92
    app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
    prog = mainWindow(app)
    sys.exit(app.exec_())
