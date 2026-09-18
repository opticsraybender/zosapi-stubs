"""
zosapi-stubs — type stubs *and* a robust connection helper for the Zemax
OpticStudio ZOS-API.

The PEP 561 stub package ``ZOSAPI-stubs`` (shipped in the same wheel) gives
editors autocomplete and hover docs for the runtime ``ZOSAPI`` CLR module. This
``zosapi_stubs`` package adds the runtime conveniences:

    import zosapi_stubs
    ZOSAPI, TheSystem = zosapi_stubs.Connect()                 # standalone
    ZOSAPI, TheSystem = zosapi_stubs.Connect(extension=True)   # attach to a running instance
"""

from __future__ import annotations

from .connection import (
    Connect,
    Connection,
    ConnectionException,
    InitializationException,
    LicenseException,
    SystemNotPresentException,
    ZOSAPIError,
    find_opticstudio_directory,
)

__all__ = [
    "Connect",
    "Connection",
    "find_opticstudio_directory",
    "ZOSAPIError",
    "InitializationException",
    "ConnectionException",
    "LicenseException",
    "SystemNotPresentException",
]
__version__ = "1.1.5"
