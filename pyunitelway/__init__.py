from importlib.metadata import PackageNotFoundError, version

from .client import UnitelwayClient
from . import constants

try:
    __version__ = version("pyunitelway")  # pyproject.toml is the single source
except PackageNotFoundError:  # running from a checkout that was never installed
    __version__ = "0+unknown"
