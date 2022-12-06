import numpy as np
import time
import nidaqmx


feedfwdratio = -0.057 # this is 0.3z where z is calculated from scanning laser over 1 MHFTR, and accounting for labjack being before PZT
#feedfwdratio = -0.002664*0

#our program would read applied piezo voltage from locking program and write the corresponding output voltage to current control.
#also needs a signal at end to know when to stop reading and close LabJack/end task.

ai_task = nidaqmx.Task("ai task "+time.strftime("%Y%m%d_%H%M%S"))
ai_task.ai_channels.add_ai_voltage_chan("Dev9/ai0", min_val=-5, max_val=5, units=nidaqmx.constants.VoltageUnits.VOLTS)
ai_task.start()

ao_task = nidaqmx.Task("ao task "+time.strftime("%Y%m%d_%H%M%S"))
ao_task.ao_channels.add_ao_voltage_chan("Dev9/ao0", min_val= -1, max_val= 1, units=nidaqmx.constants.VoltageUnits.VOLTS)

try:
    while (True):
        aivolt = np.round(np.mean(ai_task.read(number_of_samples_per_channel=1, timeout=2.0)), 3)
        # print("Input voltage (V):", aivolt)
        aovolt = aivolt * feedfwdratio
        ao_task.write(aovolt, auto_start=True, timeout=2.0)
except KeyboardInterrupt:
    ao_task.stop()
    ao_task.close()
    ai_task.stop()
    ai_task.close()
    print("Feedforward stopped.")











#time.sleep(5) #wait 5 s
#LabJack.analog_out(blocknum, aonum, aoclose) #write 0 V to close



