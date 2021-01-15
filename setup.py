from setuptools import setup
from Cython.Build import cythonize

setup(
    name='daqthread',
    ext_modules=cythonize("daqthread.pyx"),
    zip_safe=False,
)
