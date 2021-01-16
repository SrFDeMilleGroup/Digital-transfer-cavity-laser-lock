import PyQt5
import nidaqmx
from scipy import signal
import numpy as np
cimport numpy as np

class daqThread(PyQt5.QtCore.QThread):
    signal = PyQt5.QtCore.pyqtSignal(dict)

    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.samp_rate = self.parent.config["sampling rate"]
        # number of samples to write/read
        self.samp_num = round(self.parent.config["scan time"]/1000.0*self.samp_rate)

        # initialize all DAQ tasks
        self.ai_task_init() # read data for cavity and all lasers
        self.cavity_ao_task_init() # cavity sanning voltage, synchronized with ai_task
        self.laser_ao_task_init() # control laser piezo voltage, running in "on demand" mode
        self.counter_task_init() # configure a counter to use as the clock for ai_task and cavity_ao_task, for synchronization and retriggerability
        self.do_task_init() # trigger the counter to generate a pulse train, running in "on demand" mode

    def run(self):
        # define and redefine some variables to make them in c type
        cdef int i, j
        cdef int counter = 0
        cdef int err_count = 0
        cdef int samp_rate = self.samp_rate
        cdef double dt = 1000.0/self.samp_rate # in ms
        cdef int samp_num = self.samp_num
        cdef int laser_num = len(self.parent.laser_list)

        cdef np.ndarray[np.float64_t, ndim=1] laser_output = np.empty(laser_num, dtype=np.float64)
        # save frequency errors in laset two cycles, used for PID calculation
        cdef np.ndarray[np.float64_t, ndim=2] laser_last_err = np.zeros((laser_num, 2), dtype=np.float64)
        # initial feedback voltage is zero
        cdef np.ndarray[np.float64_t, ndim=1] laser_last_feedback = np.zeros(laser_num, dtype=np.float64)
        cdef np.ndarray[np.npy_bool, ndim=1] laser_peak_found = np.zeros(laser_num, dtype=np.bool_) # initially all False
        for i, laser in enumerate(self.parent.laser_list):
            laser_output[i] = laser.config["offset"] # initial output voltage is the "offset"

        # cavity scanning voltage, reversed sawtooth wave
        cdef np.ndarray[np.float64_t, ndim=1] cavity_scan = np.linspace(self.parent.config["scan amp"], 0, samp_num, dtype=np.float64)
        cdef np.ndarray[np.float64_t, ndim=1] cavity_scan_output = np.zeros(samp_num, dtype=np.float64)
        # initial output voltage is the "offset"
        cdef double cavity_output = self.parent.cavity.config["offset"]
        for i in range(samp_num):
            cavity_scan_output[i] = cavity_scan[i] + cavity_output
        # save frequency errors in laset two cycles, used for PID calculation
        cdef np.ndarray[np.float64_t, ndim=1] cavity_last_err = np.zeros(2, dtype=np.float64)
        # initial feedback voltage is zero
        cdef double cavity_last_feedback = 0
        cdef bint cavity_peak_found = False

        # photodetector data
        cdef np.ndarray[np.float64_t, ndim=2] pd_data
        cdef int start_length

        cdef np.ndarray[np.float64_t, ndim=1] cavity_pd_data
        cdef np.ndarray[np.longlong_t, ndim=1] cavity_peaks
        cdef double cavity_first_peak
        cdef double cavity_pk_sep
        cdef double cavity_err
        cdef double cavity_feedback

        cdef np.ndarray[np.float64_t, ndim=1] laser_pd_data
        cdef np.ndarray[np.longlong_t, ndim=1] laser_peak
        cdef double freq_setpoint
        cdef double laser_err
        cdef double laser_feedback

        self.laser_ao_task.write(laser_output)
        self.cavity_ao_task.write(cavity_scan + cavity_output)

        # start all tasks
        self.ai_task.start()
        self.cavity_ao_task.start()
        self.laser_ao_task.start()
        self.counter_task.start()
        self.do_task.start()

        # trigger counter, to start AI/AO for the first cycle
        self.do_task.write([False, True, False])

        while self.parent.active:
            pd_data = np.array(self.ai_task.read(number_of_samples_per_channel=self.samp_num, timeout=10.0), dtype=np.float64)

            # chop array, because the beginning part of the data array usually has undesired peaks
            start_length = round(self.parent.config["scan ignore"]/1000.0*samp_rate)
            cavity_pd_data = np.zeros(samp_num-start_length, dtype=np.float64)
            laser_pd_data = np.zeros(samp_num-start_length, dtype=np.float64)
            for i in range(samp_num-start_length):
                cavity_pd_data[i] = pd_data[0][i+start_length]

            # find cavity peaks using "peak height/width" criteria
            cavity_peaks, _ = signal.find_peaks(cavity_pd_data, height=self.parent.cavity.config["peak height"], width=self.parent.cavity.config["peak width"])

            # normally this frequency lock method requires two cavity scanning peaks
            if len(cavity_peaks) == 2:
                cavity_peak_found = True
                # convert the position of the first peak into unit ms
                cavity_first_peak = cavity_peaks[0]*dt
                # convert the separation of peaks into unit ms
                cavity_pk_sep = (cavity_peaks[1] - cavity_peaks[0])*dt
                # calculate cavity error signal in unit MHz
                cavity_err = (self.parent.cavity.config["set point"] - self.parent.config["scan ignore"] - cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"]
                # calculate cavity PID feedback voltage, use "scan time" for an approximate loop time
                cavity_feedback = cavity_last_feedback + \
                                  (cavity_err-cavity_last_err[1])*self.parent.cavity.config["kp"]*self.parent.cavity.config["kp multiplier"]*self.parent.cavity.config["kp on"] + \
                                  cavity_err*self.parent.cavity.config["ki"]*self.parent.cavity.config["ki multiplier"]*self.parent.cavity.config["ki on"]*self.parent.config["scan time"]/1000 + \
                                  (cavity_err+cavity_last_err[0]-2*cavity_last_err[1])*self.parent.cavity.config["kd"]*self.parent.cavity.config["kd multiplier"]*self.parent.cavity.config["kd on"]/(self.parent.config["scan time"]/1000)
                # coerce cavity feedbak voltage to avoid big jump
                cavity_feedback = np.clip(cavity_feedback, cavity_last_feedback-self.parent.cavity.config["limit"], cavity_last_feedback+self.parent.cavity.config["limit"])
                # check if cavity feedback voltage is NaN, use feedback voltage from last cycle if it is
                if not np.isnan(cavity_feedback):
                    cavity_last_feedback = cavity_feedback
                else:
                    print("cavity feedback voltage is NaN.")
                cavity_output = self.parent.cavity.config["offset"] + cavity_last_feedback
                cavity_last_err[0] = cavity_last_err[1]
                cavity_last_err[1] = cavity_err

                for i, laser in enumerate(self.parent.laser_list):
                    for j in range(samp_num-start_length):
                        laser_pd_data[j] = pd_data[i+1][j+start_length]
                    # find laser peak using "peak height/width" criteria
                    laser_peak, _ = signal.find_peaks(laser_pd_data, height=laser.config["peak height"], width=laser.config["peak width"])
                    if len(laser_peak) > 0:
                        laser_peak_found[i] = True
                        # choose a frequency setpoint source
                        freq_setpoint = laser.config["global freq"] if laser.config["freq source"] == "global" else laser.config["local freq"]
                        # calculate laser frequency error signal, use the position of the first peak
                        laser_err = freq_setpoint - (laser_peak[0]*dt-cavity_first_peak)/cavity_pk_sep*self.parent.config["cavity FSR"]*(laser.config["wavenumber"]/self.parent.cavity.config["wavenumber"])
                        # calculate laser PID feedback volatge, use "scan time" for an approximate loop time
                        laser_feedback = laser_last_feedback[i] + \
                                         (laser_err-laser_last_err[i][1])*laser.config["kp"]*laser.config["kp multiplier"]*laser.config["kp on"] + \
                                         laser_err*laser.config["ki"]*laser.config["ki multiplier"]*laser.config["ki on"]*self.parent.config["scan time"]/1000 + \
                                         (laser_err+laser_last_err[i][0]-2*laser_last_err[i][1])*laser.config["kd"]*laser.config["kd multiplier"]*laser.config["kd on"]/(self.parent.config["scan time"]/1000)
                        # coerce laser feedbak voltage to avoid big jump
                        laser_feedback = np.clip(laser_feedback, laser_last_feedback[i]-self.parent.cavity.config["limit"], laser_last_feedback[i]+self.parent.cavity.config["limit"])
                        # check if laser feedback voltage is NaN, use feedback voltage from last cycle if it is
                        if not np.isnan(laser_feedback):
                            laser_last_feedback[i] = laser_feedback
                        else:
                            print(f"laser {i} feedback voltage is NaN.")
                        laser_output[i] = laser.config["offset"] + laser_last_feedback[i]
                        laser_last_err[i][0] = laser_last_err[i][1]
                        laser_last_err[i][1] = laser_err

                    else:
                        laser_peak_found[i] = False
                        laser_output[i] = laser.config["offset"] + laser_last_feedback[i]

            else:
                cavity_peak_found = False
                # otherwise use feedback voltage from last cycle
                cavity_first_peak = cavity_peaks[0]*dt if len(cavity_peaks)>0 else np.nan # in ms
                cavity_pk_sep = np.nan
                cavity_output = self.parent.cavity.config["offset"] + cavity_last_feedback
                for i, laser in enumerate(self.parent.laser_list):
                    laser_output[i] = laser.config["offset"] + laser_last_feedback[i]

            # generate laser piezo feedback voltage from ao channels
            self.laser_ao_task.write(laser_output)

            for i in range(samp_num):
                cavity_scan_output[i] = cavity_scan[i] + cavity_output

            try:
                # update cavity scanning voltage
                self.cavity_ao_task.write(cavity_scan_output)
            except nidaqmx.errors.DaqError as err:
                # This is to handle error -50410, which occurs randomly.
                # "There was no space in buffer when new data was written.
                # The oldest unread data in the buffer was lost as a result"

                # The only way I know now to avoid this error is to release buffer in EVERY cycle,
                # by calling "self.cavity_ao_task.control(nidaqmx.constants.TaskMode.TASK_UNRESERVE)"
                # and then write to buffer "self.cavity_ao_task.write(self.cavity_scan + self.cavity_output, auto_start=True)".
                # But this way reduces performance.

                # This error may only occur in PCIe-6259 or similar DAQs
                print(f"This is the {err_counter}-th time error occurs. \n{err}")
                # Abort task, see https://zone.ni.com/reference/en-XX/help/370466AH-01/mxcncpts/taskstatemodel/
                self.cavity_ao_task.control(nidaqmx.constants.TaskMode.TASK_ABORT)
                # write to and and restart task
                self.cavity_ao_task.write(cavity_output, auto_start=True)
                err_counter += 1

            # trigger counter again, so AI/AO will work
            self.do_task.write([True, False])

            # update GUI widgets every certain number of cycles
            if counter%self.parent.config["display per"] == -1:
                data_dict = {}
                data_dict["cavity pd_data"] = pd_data[0][start_length:]
                data_dict["cavity first peak"] = cavity_first_peak
                data_dict["cavity pk sep"] = cavity_pk_sep
                data_dict["cavity error"] = cavity_last_err[1]
                data_dict["cavity output"] = cavity_output
                data_dict["cavity peak found"] = cavity_peak_found
                data_dict["laser pd_data"] = pd_data[1:, start_length:]
                data_dict["laser error"] = laser_last_err[:, 1]
                data_dict["laser output"] = laser_output
                data_dict["laser peak found"] = laser_peak_found
                self.signal.emit(data_dict)

            counter += 1

        # close all tasks and release resources when this loop finishes
        self.ai_task.close()
        self.cavity_ao_task.close()
        self.laser_ao_task.close()
        self.counter_task.close()
        self.do_task.close()

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
