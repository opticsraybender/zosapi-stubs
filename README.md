# zosapi-stubs

**PEP 561 type stubs for the Zemax OpticStudio ZOS-API** — full autocomplete,
inline type hints, signature help, go-to-definition, and **hover documentation**
in VS Code (Pylance/Pyright) and PyCharm, for an API that ships no stubs of its
own.

The ZOS-API is a .NET Framework 4.8 assembly accessed from Python through
[pythonnet](https://pythonnet.github.io/). Because the types only exist as a
dynamically loaded CLR module at runtime, editors have nothing to introspect and
give you no completion. This package solves that by **reflecting over
`ZOSAPI.dll` and `ZOSAPI_Interfaces.dll`** and emitting `.pyi` stub files, with
**docstrings lifted from the API's `.xml` documentation** so you also get hover
help.

It ships three things in one wheel:

1. **`ZOSAPI-stubs/`** — the prebuilt stub package your editor reads.
2. **`zosapi_stubs.Connect()`** — a one-line, registry-discovered connection
   helper (no hard-coded path, no `ZOSAPI_NetHelper.dll`).
3. **`zosapi-stubgen`** — a console command that *rebuilds* the stubs against a
   newer OpticStudio install, in place, with no source checkout.

---

## Table of contents

- [What's included](#whats-included)
- [Installation](#installation)
- [Connecting to the ZOS-API](#connecting-to-the-zos-api)
- [Using the stubs](#using-the-stubs)
- [Rebuilding for a new OpticStudio version](#rebuilding-for-a-new-opticstudio-version)
- [How it works](#how-it-works)
- [Limitations & caveats](#limitations--caveats)
- [Project layout](#project-layout)
- [License](#license)

---

## What's included

The wheel covers the **complete public surface** of the two ZOS-API assemblies:

| | |
|---|---|
| Top-level types | **831** (interfaces, classes, enums) |
| Namespaces | **39** (one `__init__.pyi` per namespace) |
| Docstrings | **1,432** injected, drawn from **1,161** documented members in the `.xml` docs |
| Top-level packages | `ZOSAPI`, plus `Analysis`, `Common`, `Editors`, `Preferences`, `SystemData`, `Tools`, `Wizards` and their sub-namespaces |

For **every type** the stubs describe:

- **Properties** — as `@property` (with `.setter` when the .NET property is
  writable), correctly typed.
- **Methods** — full signatures with typed parameters and return types;
  multiple .NET overloads become `@overload` blocks.
- **`out` / `ref` parameters** — folded into the return type as a `Tuple[...]`,
  matching how pythonnet actually returns them.
- **Indexers** — emitted as `__getitem__` / `__setitem__`.
- **Enums** — as `IntEnum` (or `IntFlag` for `[Flags]` enums), with every member
  and its integer value.
- **Inheritance** — base classes and implemented interfaces are preserved, so
  inherited members resolve.
- **Generics** — generic interfaces/containers map to `typing` equivalents
  (`IList<T>` → `List[T]`, `IEnumerable<T>` → `Iterable[T]`, etc.).
- **Cross-namespace references** — e.g. `IOpticalSystem.LDE` is correctly typed
  as `ZOSAPI.Editors.LDE.ILensDataEditor`.

### Docstrings (`__doc__`)

Docstrings are taken from `ZOSAPI_Interfaces.xml` / `ZOSAPI.xml` (shipped next to
the DLLs by OpticStudio) and rendered as proper Python docstrings — summary,
`Args:`, and `Returns:` sections, with `<see cref="...">` references resolved to
plain names. Example of a generated stub entry:

```python
def RemoveSurfaceAt(self, SurfaceNumber: int) -> bool:
    """Removes the surface at the specified location.

    Args:
        SurfaceNumber: The surface number to remove (1 to NumberOfSurfaces-1).

    Returns:
        true if the surface was successfully remove; otherwise, false.
    """
    ...
```

These appear on hover and in signature-help popups in any editor that reads
docstrings from stubs (Pylance, Pyright, PyCharm).

---

## Installation

```bash
pip install zosapi-stubs
```

That is the whole setup. **No `settings.json` edits, no `extraPaths`, no
`stubPath`.** Because this is a PEP 561 `*-stubs` package, any standards-
compliant type checker discovers it automatically as long as it's installed in
the same environment your editor uses for the project.

`pythonnet` (pinned to `3.1.0`, the version this package is verified against) is
installed automatically as a dependency, so `zosapi_stubs.Connect()` and
`zosapi-stubgen` work out of the box. This pins the supported interpreters to
**CPython 3.10–3.14**, matching the wheels pythonnet 3.1.0 ships.

> **Install it into the same interpreter/venv your project uses** — that's how
> the editor finds it. If VS Code/PyCharm is pointed at a venv, `pip install`
> into that venv.

To install from the locally built wheel instead of an index:

```bash
pip install dist/zosapi_stubs-1.1.5-py3-none-any.whl
```

---

## Connecting to the ZOS-API

The wheel includes a small runtime package, `zosapi_stubs`, that opens a robust
connection in one line — no hard-coded install path, no `ZOSAPI_NetHelper.dll`:

```python
import zosapi_stubs

ZOSAPI, TheSystem = zosapi_stubs.Connect()                 # launch a new standalone instance
ZOSAPI, TheSystem = zosapi_stubs.Connect(extension=True)   # attach to a running OpticStudio
```

Both returned objects are fully typed by the bundled stubs: `ZOSAPI` is the CLR
namespace module and `TheSystem` is the primary `IOpticalSystem`, so completion
and hover docs work immediately.

The install directory is discovered automatically from the Windows registry: it
checks the COM `CodeBase` entry and the `HKCU\Software\Zemax\ZemaxRoot` key,
validates that a candidate holds `ZOSAPI.dll`, `ZOSAPI_Interfaces.dll` and
`OpticStudio.exe`/`ZemaxServer.exe`, and registers a .NET `AssemblyResolve` hook
so dependent assemblies load from that directory. Pass an explicit path to
override discovery: `Connect(path=r"C:\Zemax\OpticStudio")`.

For finer control, use the `Connection` class directly:

```python
from zosapi_stubs import Connection

conn = Connection()                 # connects on construction (extension=, path= optional)
conn.directory                      # resolved install dir
conn.edition                        # 'Premium' | 'Professional' | 'Standard' | 'Invalid'
conn.TheApplication                 # IZOSAPI_Application
conn.TheSystem                      # IOpticalSystem
conn.open_file(r"C:\lens.zmx", False)
conn.close()                        # also works as a context manager

with Connection() as conn:
    print(conn.TheSystem.SystemName)
```

Connection problems raise specific exceptions you can catch:
`InitializationException` (OpticStudio not found / app won't start),
`ConnectionException`, `LicenseException`, `SystemNotPresentException` — all
subclasses of `ZOSAPIError`.

> **`Connect()` needs a local OpticStudio install** — it runs the API for real.
> `pythonnet` is installed automatically with this package; OpticStudio you
> supply yourself.

---

## Using the stubs

You can also connect manually; the stubs type everything either way. Nothing
about the runtime changes — the stubs are invisible to Python at execution time
and only inform the editor.

Write your ZOS-API code exactly as you already do. Nothing about the runtime
changes — the stubs are invisible to Python at execution time and only inform
the editor.

```python
import clr
from pathlib import Path

zos_path = r"C:\Program Files\Zemax OpticStudio"
clr.AddReference(str(Path(zos_path) / "ZOSAPI.dll"))
clr.AddReference(str(Path(zos_path) / "ZOSAPI_Interfaces.dll"))
import ZOSAPI                          # runtime: the real CLR module

conn = ZOSAPI.ZOSAPI_Connection()      # ← autocompletes
app = conn.CreateNewApplication()      # ← ConnectAsExtension(0) for an extension
system = app.PrimarySystem             # ← inferred as IOpticalSystem
lde = system.LDE                       # ← inferred as ILensDataEditor (hover docs)
row = lde.AddSurface()                 # ← inferred as ILDERow
```

What your editor now knows (verified with Pyright against the installed wheel):

| Expression | Inferred type |
|---|---|
| `system` | `IOpticalSystem` |
| `system.LDE` | `ILensDataEditor` |
| `system.LDE.AddSurface()` | `ILDERow` |

You get completion on `system.`, `lde.`, etc., parameter hints while typing a
call, and docstrings on hover.

---

## Rebuilding for a new OpticStudio version

When you upgrade OpticStudio, regenerate the stubs so they match the new API.
The wheel installs a console command that rewrites the stubs **in place** (right
where `pip` installed them), so you never need this repo:

```bash
zosapi-stubgen    # reflects over the installed DLLs, rewrites the stubs in place
```

Options:

```bash
# non-default OpticStudio install location
zosapi-stubgen --dll-dir "C:\Zemax\OpticStudio"

# write to a folder instead of rebuilding in place (e.g. a project-local typings dir)
zosapi-stubgen -o ./typings
```

`zosapi-stubgen` reads `ZOSAPI.dll`, `ZOSAPI_Interfaces.dll` **and** their
`ZOSAPI*.xml` doc files from `--dll-dir` (default
`C:\Program Files\Zemax OpticStudio`). Restart your editor's language server (or
the editor) afterward so it re-reads the refreshed stubs.

---

## How it works

- **`zosapi_stubs/connection.py`** is the runtime helper: registry-based install
  discovery + a .NET `AssemblyResolve` hook, exposing `Connect()` / `Connection`.
- **`zosapi_stubs/stubgen/generator.py`** loads the assemblies through pythonnet
  and walks every public type with .NET reflection (`System.Reflection`), mapping
  .NET types to Python annotations and writing one `__init__.pyi` per namespace.
- **`zosapi_stubs/stubgen/xmldocs.py`** parses the `.xml` documentation. To attach
  a docstring to the right member it **reconstructs each member's .NET XML
  documentation-comment ID** (e.g.
  `M:ZOSAPI.Editors.LDE.ILensDataEditor.RemoveSurfaceAt(System.Int32)`) from the
  reflected metadata and looks it up — handling byref/array/generic parameter
  encodings — so signatures and docs line up exactly.
- **`zosapi_stubs/stubgen/cli.py`** is the `zosapi-stubgen` entry point; with no
  `-o` it locates the installed `ZOSAPI-stubs` directory and rebuilds it there.

### Why it's runtime-safe

The stub directory is named **`ZOSAPI-stubs`** (the PEP 561 stub-package suffix)
and contains **only `.pyi` files — no `__init__.py`**. This is deliberate:

- A directory literally named `ZOSAPI` (or any dir with an `__init__.py`/just
  `.pyi` files on `sys.path`) would **shadow** `import ZOSAPI` and hide
  pythonnet's dynamically generated CLR module, breaking
  `ZOSAPI.ZOSAPI_Connection()` at runtime.
- The `-stubs` suffix is recognized by type checkers as "stubs *for* the
  `ZOSAPI` module" while being impossible to import at runtime. Your code keeps
  importing and running against the real DLL; the stubs are consulted only by
  the editor.

---

## Limitations & caveats

- **Editing the stubs is pointless** — they're regenerated wholesale. Don't
  hand-edit; change the generator and re-run `zosapi-stubgen`.
- **Stubs describe shape, not runtime behavior.** They reflect the API surface
  of the OpticStudio version they were generated from. After an upgrade,
  [rebuild](#rebuilding-for-a-new-opticstudio-version) to stay accurate.
- **`pythonnet` is pinned to `3.1.0`.** It installs automatically as a hard
  dependency (the version this package is verified against). `Connect()` and
  `zosapi-stubgen` additionally need a local OpticStudio install — the DLLs are
  read at runtime / generation time, not bundled.
- **Python 3.10–3.14 only.** The pin to pythonnet 3.1.0 (which dropped 3.7–3.9
  and added 3.14) sets `requires-python` to `>=3.10,<3.15`. The *stubs
  themselves* are plain text with no version limit, but the wheel as a whole
  installs on 3.10–3.14.
- **`reportMissingModuleSource` warning is expected.** Pyright/Pylance may emit a
  *warning* (not an error) like `Import "ZOSAPI" could not be resolved from
  source` — it found the stubs but no `.py` source, which is correct: the source
  is a compiled DLL. Type checking and completion work fully; you can silence it
  in your project's Pyright config if desired.
- **`out`/`ref` returns are modeled as tuples.** Where a .NET method has `out`
  parameters, the stub return type is a `Tuple[...]` of the return value followed
  by the out values — matching pythonnet's behavior. Confirm ordering against
  the API help when a method has several.
- **`System.Object` and unmapped types fall back to `Any`.** A small number of
  exotic or pointer types are annotated `Any` rather than guessing.
- **Windows / OpticStudio required for generation.** The DLLs and their `.xml`
  docs come from a local OpticStudio installation; the prebuilt stubs in the
  wheel were generated from one specific install and version.

---

## Project layout

```
zosapi-stubs/
├── ZOSAPI-stubs/              # prebuilt PEP 561 stub package (ships in the wheel)
│   ├── __init__.pyi           #   top-level ZOSAPI namespace
│   ├── py.typed               #   PEP 561 marker
│   └── Analysis/ Editors/ …   #   one __init__.pyi per sub-namespace
├── src/zosapi_stubs/          # runtime package (ships in the wheel)
│   ├── __init__.py            #   exposes Connect / Connection
│   ├── connection.py          #   registry discovery + Connect()
│   └── stubgen/               #   the rebuild tool
│       ├── generator.py       #     reflects over the DLLs → .pyi
│       ├── xmldocs.py         #     parses .xml docs → docstrings
│       └── cli.py             #     `zosapi-stubgen` entry point
├── pyproject.toml             # hatchling build; force-includes ZOSAPI-stubs
├── README.md
└── dist/                      # built wheel
```

---

## License

MIT
