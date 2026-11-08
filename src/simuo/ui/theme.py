"""Load Qt styles from package resources, independently of the working directory."""

from importlib.resources import files


def load_stylesheet(name):
    return files("simuo.resources").joinpath("styles", f"{name}.qss").read_text(encoding="utf-8")
