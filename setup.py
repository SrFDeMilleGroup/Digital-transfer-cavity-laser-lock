from setuptools import setup
from Cython.Build import cythonize
import numpy as np

setup(
    name='daqthread',
    ext_modules=cythonize("daqthread.pyx"),
    zip_safe=False,
    include_dirs = [np.get_include(),]
)
