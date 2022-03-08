import nidaqmx
import time
import numpy as np

class daqtask:
    def __init__(self):
        self.samp_rate = 384000
        self.samp_num = round(2.5/1000*self.samp_rate) # spend 2.5 ms to generate/acquire data

        self.ai_task = nidaqmx.Task()
        for i in range(3):
            self.ai_task.ai_channels.add_ai_voltage_chan(f"Dev2/ai{i}", min_val=-0.5, max_val=1.2, units=nidaqmx.constants.VoltageUnits.VOLTS)
        self.ai_task.timing.cfg_samp_clk_timing(
                                                rate = self.samp_rate,
                                                # rate = 1000,
                                                source = "/Dev2/PFI13",
                                                active_edge = nidaqmx.constants.Edge.RISING,
                                                sample_mode = nidaqmx.constants.AcquisitionType.CONTINUOUS,
                                                samps_per_chan = self.samp_num
                                            )

        self.cavity_ao_task = nidaqmx.Task()
        cavity_ao_ch = self.cavity_ao_task.ao_channels.add_ao_voltage_chan("Dev2/ao0", min_val=-5.0, max_val=10.0, units=nidaqmx.constants.VoltageUnits.VOLTS)
        cavity_ao_ch.ao_data_xfer_mech = nidaqmx.constants.DataTransferActiveTransferMode.DMA
        cavity_ao_ch.ao_data_xfer_req_cond = nidaqmx.constants.OutputDataTransferCondition.ON_BOARD_MEMORY_LESS_THAN_FULL
        self.cavity_ao_task.timing.cfg_samp_clk_timing(
                                            rate = self.samp_rate,
                                            source = "/Dev2/PFI13",
                                            active_edge = nidaqmx.constants.Edge.RISING,
                                            sample_mode = nidaqmx.constants.AcquisitionType.CONTINUOUS,
                                            samps_per_chan = self.samp_num
                                        )
        self.cavity_ao_task.out_stream.regen_mode = nidaqmx.constants.RegenerationMode.DONT_ALLOW_REGENERATION

        self.do_task = nidaqmx.Task()
        self.do_task.do_channels.add_do_chan("/Dev2/PFI8")

        self.counter_task = nidaqmx.Task()
        self.counter_task.co_channels.add_co_pulse_chan_freq(
                                                            counter="Dev2/ctr1", # another name of "/Dev2/PFI13"
                                                            units=nidaqmx.constants.FrequencyUnits.HZ,
                                                            freq=self.samp_rate,
                                                            duty_cycle=0.5)
        self.counter_task.timing.cfg_implicit_timing(sample_mode=nidaqmx.constants.AcquisitionType.FINITE, samps_per_chan=self.samp_num)
        self.counter_task.triggers.start_trigger.cfg_dig_edge_start_trig(trigger_source="/Dev2/PFI8", trigger_edge=nidaqmx.constants.Edge.RISING)
        self.counter_task.triggers.start_trigger.retriggerable = True

    def start(self):
        self.ai_task.start()
        self.cavity_ao_task.start()
        self.do_task.start()
        self.counter_task.start()

    def close(self):
        self.ai_task.close()
        self.cavity_ao_task.close()
        self.do_task.close()
        self.counter_task.close()


a = daqtask()
write_data = a.cavity_ao_task.write(np.linspace(4, 0, a.samp_num))
a.start()
a.do_task.write([False, True, False])

start = time.time()
for i in range(1000):
    # data = a.ai_task.read(number_of_samples_per_channel=a.samp_num)
    # data = np.reshape(data, (len(data), -1))
    # write_data = a.cavity_ao_task.write(np.linspace(4, 0, a.samp_num))
    a.do_task.write([True, False])
stop = time.time()
print(stop-start)
a.close()
