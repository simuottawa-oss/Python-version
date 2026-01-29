# This is the setup file to allow cython to compile our C++ code
# Do not touch unless changing the language or extension 


from setuptools import setup, Extension
from Cython.Build import cythonize
ext = Extension (
    "cppCalculations", # Name
    sources=["cppCalculations.pyx"], # Our Cython source file
    language="c++" # Set to C++
)

setup(
    ext_modules = cythonize(ext)
)
