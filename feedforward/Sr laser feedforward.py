import numpy as np
import time
#import dateutil
#from datetime import datetime
#import matplotlib.dates as mdates
#import os
#import matplotlib.pyplot as plt

from labjack import ljm

#set up for controlling Labjack with Python
class LabJackAnalog:
    """
    Control class for a LabJack (any model), designed with only Analog
    IO in mind. This class assumes LJTick-DACs are attached to the
    digital IO blocks.
    """

    def __init__(self, model="ANY", connection="ANY", identifier="ANY"):
        self.device = ljm.openS(model, connection, identifier)

    def stream_read_single(self, pin_name, scanrate, period):
        num_samples = int(period * scanrate)

        ljm.eStreamStart(self.device, 1, 1, ljm.namesToAddresses(1, [pin_name])[0], scanrate)

        data = []
        for i in range(0, num_samples, 1):
            measurement = ljm.eStreamRead(self.device)[0][0]
            if abs(measurement) < 20: ## Accounts for overflow garbage
                data.append(measurement)
        ljm.eStreamStop(self.device)

        return data

    def analog_out(self, block_num, dac_num, val):
        """
        Write a voltage using an LJTick-DAC. The block number refers
        to the number of the digital IO screw block the LJTick-DAC is
        connected to. The block containing digital pins 0 and 1 is
        block 0, the one containing pins 2 and 3 is block 1, and so
        on. DAC number refers to the DAC being used on the LJTick-DAC.
        DACA is 0 and DACB is 1.
        """

        # Extract block number and DAC number if they were given as
        # names. This assumes that the name is of the form
        # "BlahBlahBlah<pin number>", where <pin number> is a single
        # digit.
        if isinstance(block_num, str):
            block_num = block_num[-1]
        if isinstance(dac_num, str):
            dac_num = dac_num[-1]

        ljm.eWriteName(self.device, "TDAC{}".format(block_num*2+dac_num), val)

    def dac_out(self, analog_pin, val):
        #Writes a voltage to DAC1 or DAC2

        ljm.eWriteName(self.device, "DAC{}".format(analog_pin), val)

    def mio_out(self, analog_pin, val):
        #Writes a voltage to MIO# pins

        ljm.eWriteName(self.device, "MIO{}".format(analog_pin), val)

    def fio_out(self, analog_pin, val):
        #Writes a voltage to FIO# pins
        ljm.eWriteName(self.device, "FIO{}".format(analog_pin), val)

    def analog_in(self, analog_pin):
        """
        Read a voltage from the builtin ADCs. analog_pin can be either
        the full name of the pin (e.g. "AIN1") or just a number (e.g.
        1). Returns the voltage currently applied to the ADC as a
        float.
        """

        # Extract the pin number from the name, if given in that
        # form. This assumes that the name is of the form
        # "BlahBlahBlah<pin number>" where <pin number> is a single
        # digit.
        if isinstance(analog_pin, str):
            analog_pin = int(analog_pin[-1])

        return ljm.eReadName(self.device, "AIN{}".format(analog_pin))

    def ramp_analog_out(self, block_num, dac_num, amplitude, frequency, offset, init_phase, n_cycles, step_size):
        """
        Applies a ramp function with the specified parameters to the specified
        LabJack block and DAC. IMPORTANT: Confirm that the output frequency is
        accurate. If not, increase the step size.
        Amplitude [V], Frequency [Hz], Offset [V], Phase [degrees], Step Size [V]


        Example: amplitude 1, frequency 1, offset 0, init_phase 90, n_cycles 3
        The output would begin at +0.5 V, decrease linearly to -0.5 V during
        500 ms and increase linearly to +0.5 V during another 500 ms. This would
        then repeat 2 more times.
        """
        n_steps = amplitude / step_size * 2
        period = 1 / frequency
        step_time = period / n_steps

        for phase in np.linspace(init_phase, 360 * n_cycles + init_phase, n_cycles * n_steps):
            val = amplitude * self.__unit_ramp(phase) + offset
            start = time.time()
            self.analog_out(block_num, dac_num, val)
            now = time.time()
            while (now - start) < step_time:
                now = time.time()

    def __unit_ramp(self, phase):
        """
        Returns the value corresponding to the input phase of the 1 V ramp
        function (0 offset, 0 degrees starting phase)
        """
        reduced_phase = phase % 360

        if reduced_phase <= 90:
            return (reduced_phase / 90) * 0.5
        elif reduced_phase <= 180:
            return ((180 - reduced_phase) / 90) * 0.5
        elif reduced_phase <= 270:
            return ((reduced_phase - 180) / 90) * -0.5
        elif reduced_phase <= 360:
            return ((360 - reduced_phase) / 90) * -0.5

    def close(self):
        """
        Close the connection to the LabJack so that another program
        can use it.
        """

        try:
            ljm.close(self.device)
        except ljm.LJMError as e:
            # Silently ignore the error if it's due to the LabJack
            # already being closed. Otherwise, something else went
            # wrong so pass it on the the calling program.
            if e.errorCode == 1224: # Error code 1224 is LabJack not open
                pass
            else:
                raise e # Reraise the exception if it isn't specifically the one we were looking for

    def __del__(self):
        self.close()

#run feedforward for 461 nm blue laser
LabJack = LabJackAnalog() #create instance of this

#parameters
blocknum = 0
aonum = 1 #AO channel (for current controller)
ainum = 2 #AI channel (from locking program, teed off from PZT)
#aovolt = 0.25
#aoclose = 0.0
feedfwdratio = -0.02664 # this is 0.3z where z is calculated from scanning laser over 1 MHFTR, and accounting for labjack being before PZT

#our program would read applied piezo voltage from locking program and write the corresponding output voltage to current control.
#also needs a signal at end to know when to stop reading and close LabJack/end task.

# LabJack.close()

try:
    while (True):
        aivolt = np.round(LabJack.analog_in(ainum),2)
        # print("Input voltage (V):", aivolt)
        aovolt = aivolt * feedfwdratio
        LabJack.analog_out(blocknum, aonum, aovolt) #test that labjack can output analog voltage
except KeyboardInterrupt:
    LabJack.close()
    print("Feedforward stopped.")











#time.sleep(5) #wait 5 s
#LabJack.analog_out(blocknum, aonum, aoclose) #write 0 V to close



