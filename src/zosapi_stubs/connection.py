"""
Robust ZOS-API connection — no ``ZOSAPI_NetHelper.dll`` required.

Locates the OpticStudio installation from the Windows registry, registers a .NET
``AssemblyResolve`` hook so dependent assemblies load from that directory, then
opens the API connection.

Typical use::

    import zosapi_stubs
    ZOSAPI, TheSystem = zosapi_stubs.Connect()                 # standalone
    ZOSAPI, TheSystem = zosapi_stubs.Connect(extension=True)   # connect to a running OpticStudio

For full control (the application object, license checks, helpers) use the
:class:`Connection` class directly::

    conn = zosapi_stubs.Connection()          # connects on construction
    conn.TheApplication.SamplesDir
    conn.open_file(r"C:\\lens.zmx", False)
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Optional, Tuple

if TYPE_CHECKING:
    # Resolved by the ZOSAPI-stubs package at type-check time only; at runtime
    # ZOSAPI is the dynamically loaded CLR module.
    import ZOSAPI


# ---------------------------------------------------------------------------
# Exceptions  (mirror the granular errors in PythonStandalone_01.py)
# ---------------------------------------------------------------------------

class ZOSAPIError(Exception):
    """Base class for all connection errors."""


class InitializationException(ZOSAPIError):
    """OpticStudio could not be located, or the application could not start."""


class ConnectionException(ZOSAPIError):
    """The .NET connection object could not be created."""


class LicenseException(ZOSAPIError):
    """The installed license is not valid for ZOS-API use."""


class SystemNotPresentException(ZOSAPIError):
    """No primary optical system is available."""


# ---------------------------------------------------------------------------
# Installation discovery
# ---------------------------------------------------------------------------

# COM CLSID whose InprocServer32\CodeBase points at the ZOS-API libraries dir.
_ZOSAPI_CLSID = r"CLSID\{B44B0A5F-7A80-45A5-8BC4-405FF36AEB02}\InprocServer32"


def _is_zemax_dir(directory: Optional[str]) -> bool:
    """True if *directory* holds the API DLLs and an OpticStudio/Zemax server."""
    if not directory or not os.path.isdir(directory):
        return False
    has_api = os.path.isfile(os.path.join(directory, "ZOSAPI.dll")) and os.path.isfile(
        os.path.join(directory, "ZOSAPI_Interfaces.dll")
    )
    has_app = os.path.isfile(os.path.join(directory, "OpticStudio.exe")) or os.path.isfile(
        os.path.join(directory, "ZemaxServer.exe")
    )
    return has_api and has_app


def _registry_codebase_dir() -> Optional[str]:
    """Read the ZOS-API COM CodeBase path from HKCR."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, _ZOSAPI_CLSID) as key:
            codebase, _ = winreg.QueryValueEx(key, "CodeBase")
        if not codebase:
            return None
        codebase = codebase.strip()
        # CodeBase is a file:// URI, e.g. file:///C:/Program Files/.../ZOSAPI.dll
        if codebase.lower().startswith("file:///"):
            codebase = codebase[8:]
        codebase = codebase.replace("/", os.sep)
        return os.path.dirname(codebase)
    except OSError:
        return None


def _registry_zemax_root() -> Optional[str]:
    """Read HKCU\\Software\\Zemax\\ZemaxRoot (as PythonStandalone_01.py does)."""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Zemax") as key:
            root, _ = winreg.QueryValueEx(key, "ZemaxRoot")
        return root or None
    except OSError:
        return None


def find_opticstudio_directory(override: Optional[str] = None) -> Optional[str]:
    """Locate the OpticStudio install directory containing the ZOS-API DLLs.

    Search order (first that validates wins):

        1. an explicit *override* path
        2. the COM CodeBase registry entry (HKCR)
        3. the ZemaxRoot registry entry (HKCU)
        4. common default install locations

    Returns the directory, or ``None`` if OpticStudio cannot be found.
    """
    candidates = [override, _registry_codebase_dir()]

    zemax_root = _registry_zemax_root()
    if zemax_root:
        # ZemaxRoot is the data folder; the program dir is typically its sibling.
        candidates.append(zemax_root)
        candidates.append(os.path.join(zemax_root, "ZOS-API", "Libraries"))

    program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
    candidates.append(os.path.join(program_files, "Zemax OpticStudio"))
    candidates.append(os.path.join(program_files, "ANSYS Zemax OpticStudio"))

    for directory in candidates:
        if _is_zemax_dir(directory):
            return directory
    return None


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

class Connection:
    """An open ZOS-API connection. Connects on construction.

    Attributes
    ----------
    ZOSAPI          : the ZOSAPI CLR namespace module
    TheConnection   : ZOSAPI.IZOSAPI_Connection
    TheApplication  : ZOSAPI.IZOSAPI_Application
    TheSystem       : ZOSAPI.IOpticalSystem (the primary system)
    directory       : the resolved OpticStudio install directory
    """

    def __init__(
        self,
        extension: bool = False,
        instance_number: int = 0,
        path: Optional[str] = None,
    ) -> None:
        self.directory = find_opticstudio_directory(path)
        if self.directory is None:
            raise InitializationException(
                "Unable to locate Zemax OpticStudio. Pass path=... with the "
                "directory containing ZOSAPI.dll, or check that OpticStudio is installed."
            )

        import clr

        clr.AddReference(os.path.join(self.directory, "ZOSAPI.dll"))
        clr.AddReference(os.path.join(self.directory, "ZOSAPI_Interfaces.dll"))
        self._register_assembly_resolver()

        import ZOSAPI

        self.ZOSAPI = ZOSAPI
        self.TheConnection = ZOSAPI.ZOSAPI_Connection()
        if self.TheConnection is None:
            raise ConnectionException("Unable to initialize .NET connection to ZOSAPI")

        if extension:
            self.TheApplication = self.TheConnection.ConnectAsExtension(instance_number)
            if self.TheApplication is None:
                raise InitializationException(
                    "Unable to connect as an extension. Is OpticStudio running with "
                    "the Interactive Extension enabled?"
                )
        else:
            self.TheApplication = self.TheConnection.CreateNewApplication()
            if self.TheApplication is None:
                raise InitializationException("Unable to acquire ZOSAPI application")

        if not self.TheApplication.IsValidLicenseForAPI:
            raise LicenseException("License is not valid for ZOSAPI use")

        self.TheSystem = self.TheApplication.PrimarySystem
        if self.TheSystem is None:
            raise SystemNotPresentException("Unable to acquire primary system")

    # -- the .NET AssemblyResolve hook ----------------------------------------
    def _register_assembly_resolver(self) -> None:
        """Resolve dependent ZOS-API assemblies from the install directory.

        Uses pythonnet's documented delegate binding (no internals) so .NET can
        call back into Python.
        """
        try:
            from System import AppDomain, ResolveEventHandler
            from System.IO import Path as NetPath, File
            from System.Reflection import Assembly, AssemblyName
        except ImportError:
            return  # pythonnet/.NET not available; AddReference already handled the core DLLs

        directory = self.directory

        def _resolve(sender, args):  # noqa: ANN001 - .NET delegate signature
            try:
                name = AssemblyName(args.Name).Name
                candidate = NetPath.Combine(directory, name + ".dll")
                if File.Exists(candidate):
                    return Assembly.LoadFrom(candidate)
            except Exception:
                pass
            return None

        # Keep a reference so the delegate isn't garbage-collected.
        self._resolver = ResolveEventHandler(_resolve)
        AppDomain.CurrentDomain.AssemblyResolve += self._resolver

    # -- convenience -----------------------------------------------------------
    @property
    def edition(self) -> str:
        """License edition name: 'Premium' | 'Professional' | 'Standard' | 'Invalid'."""
        status = self.TheApplication.LicenseStatus
        Z = self.ZOSAPI.LicenseStatusType
        return {
            Z.PremiumEdition: "Premium",
            Z.ProfessionalEdition: "Professional",
            Z.StandardEdition: "Standard",
        }.get(status, "Invalid")

    def open_file(self, filepath: str, save_if_needed: bool = False) -> None:
        if self.TheSystem is None:
            raise SystemNotPresentException("Unable to acquire primary system")
        self.TheSystem.LoadFile(filepath, save_if_needed)

    def close_file(self, save: bool = False) -> None:
        if self.TheSystem is None:
            raise SystemNotPresentException("Unable to acquire primary system")
        self.TheSystem.Close(save)

    def close(self) -> None:
        """Close the application (only meaningful for a standalone connection)."""
        app = getattr(self, "TheApplication", None)
        if app is not None:
            try:
                app.CloseApplication()
            except Exception:
                pass
            self.TheApplication = None
        self.TheConnection = None

    def __enter__(self) -> "Connection":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def Connect(
    extension: bool = False,
    instance_number: int = 0,
    path: Optional[str] = None,
) -> Tuple["ZOSAPI", "ZOSAPI.IOpticalSystem"]:
    """Open a ZOS-API connection and return ``(ZOSAPI, TheSystem)``.

    Parameters
    ----------
    extension : if True, connect to an already-running OpticStudio in
        Interactive Extension mode; otherwise launch a new standalone instance.
    instance_number : extension instance to attach to (extension mode only).
    path : optional explicit OpticStudio directory; auto-detected when omitted.

    Returns
    -------
    (ZOSAPI, TheSystem)
        ``ZOSAPI`` is the CLR namespace module (typed by the bundled stubs);
        ``TheSystem`` is the primary ``IOpticalSystem``.

    Examples
    --------
    >>> ZOSAPI, TheSystem = Connect()
    >>> ZOSAPI, TheSystem = Connect(extension=True)
    """
    conn = Connection(extension=extension, instance_number=instance_number, path=path)
    return conn.ZOSAPI, conn.TheSystem
