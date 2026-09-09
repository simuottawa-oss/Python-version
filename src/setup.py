# This is the setup file to allow cython to compile our C++ code
# Do not touch unless changing the language or extension 


from setuptools import setup, Extension
from Cython.Build import cythonize
import numpy as np
ext = Extension (
    "cppCalculations", # Name
    sources=["cppCalculations.pyx"], # Our Cython source file
    language="c++", # Set to C++
    include_dirs=[np.get_include()]  # Include directories for NumPy
)

setup(
    ext_modules = cythonize(ext)
)
