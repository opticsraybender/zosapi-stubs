"""
ZOS-API stub generator
=======================

Reflects over ``ZOSAPI.dll`` and ``ZOSAPI_Interfaces.dll`` (via pythonnet) and
emits a PEP 561 *stub-only* package named ``ZOSAPI-stubs`` whose ``.pyi`` files
give Pylance / Pyright / PyCharm full autocomplete, type hints, go-to-definition
and — by injecting the .NET XML documentation — hover docstrings.

Two rules make the result runtime-safe (so ``import ZOSAPI`` keeps resolving to
pythonnet's CLR module, not to these files):

    1. the top-level directory is ``ZOSAPI-stubs`` (the PEP 561 stub suffix),
       which can never shadow ``import ZOSAPI``;
    2. no ``__init__.py`` is written — only ``.pyi`` — so the directory never
       becomes an importable runtime package.
"""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .xmldocs import XmlDocs

DLL_NAMES: list[str] = ["ZOSAPI.dll", "ZOSAPI_Interfaces.dll"]
XML_NAMES: list[str] = ["ZOSAPI.xml", "ZOSAPI_Interfaces.xml"]
STUB_PACKAGE_SUFFIX = "-stubs"

# ---------------------------------------------------------------------------
# .NET -> Python type maps
# ---------------------------------------------------------------------------

PRIMITIVES: dict[str, str] = {
    "System.Boolean": "bool", "System.Byte": "int", "System.SByte": "int",
    "System.Int16": "int", "System.UInt16": "int", "System.Int32": "int",
    "System.UInt32": "int", "System.Int64": "int", "System.UInt64": "int",
    "System.Single": "float", "System.Double": "float", "System.Decimal": "float",
    "System.Char": "str", "System.String": "str", "System.Void": "None",
    "System.Object": "Any", "System.Type": "type", "System.Exception": "Exception",
    "System.Enum": "int", "System.ValueType": "Any", "System.IntPtr": "int",
    "System.UIntPtr": "int", "System.DateTime": "datetime",
    "System.TimeSpan": "timedelta", "System.Guid": "str",
}

GENERIC_CONTAINERS: dict[str, str] = {
    "System.Nullable": "Optional",
    "System.Collections.Generic.IList": "List",
    "System.Collections.Generic.List": "List",
    "System.Collections.Generic.IEnumerable": "Iterable",
    "System.Collections.Generic.ICollection": "Sequence",
    "System.Collections.Generic.IDictionary": "Dict",
    "System.Collections.Generic.Dictionary": "Dict",
    "System.Collections.Generic.IReadOnlyList": "Sequence",
    "System.Collections.Generic.IReadOnlyCollection": "Sequence",
    "System.Collections.Generic.IReadOnlyDictionary": "Dict",
    "System.Collections.Generic.KeyValuePair": "Tuple",
    "System.Collections.Generic.IEnumerator": "Iterator",
    "System.Collections.Generic.HashSet": "Set",
    "System.Collections.Generic.ISet": "Set",
    "System.Collections.Generic.Queue": "List",
    "System.Collections.Generic.Stack": "List",
}

_RESERVED: frozenset[str] = frozenset({
    "False", "None", "True", "and", "as", "assert", "async", "await", "break",
    "class", "continue", "def", "del", "elif", "else", "except", "finally",
    "for", "from", "global", "if", "import", "in", "is", "lambda", "nonlocal",
    "not", "or", "pass", "raise", "return", "try", "while", "with", "yield",
    "abs", "dict", "filter", "id", "input", "iter", "len", "list", "map", "max",
    "min", "next", "object", "open", "print", "range", "reversed", "round",
    "set", "sorted", "sum", "type", "zip",
})


def strip_arity(name: str) -> str:
    return re.sub(r"`\d+$", "", name)


def safe_name(name: str) -> str:
    return (name + "_") if name in _RESERVED else name


# ---------------------------------------------------------------------------
# .NET XML documentation-comment ID reconstruction (must match xmldocs keys)
# ---------------------------------------------------------------------------

def _doc_type_prefix(t) -> str:
    """Full name of a type as used in a member-id PREFIX (nested '+' -> '.', keep arity)."""
    full = t.FullName or t.Name or ""
    full = full.split("[")[0]               # drop assembly-qualified / array junk
    return full.replace("+", ".")


def _doc_param_type(t) -> str:
    """Encode a parameter type the way the .NET doc-comment IDs do."""
    if t.IsByRef:
        return _doc_param_type(t.GetElementType()) + "@"
    if t.IsPointer:
        return _doc_param_type(t.GetElementType()) + "*"
    if t.IsArray:
        inner = _doc_param_type(t.GetElementType())
        rank = t.GetArrayRank()
        if rank == 1:
            return inner + "[]"
        return inner + "[" + ",".join(["0:"] * rank) + "]"
    if t.IsGenericParameter:
        # `n for type params, ``n for method params
        owner_is_method = t.DeclaringMethod is not None
        prefix = "``" if owner_is_method else "`"
        return f"{prefix}{t.GenericParameterPosition}"
    if t.IsGenericType:
        gd = t.GetGenericTypeDefinition()
        base = (gd.FullName or gd.Name or "").split("`")[0].replace("+", ".")
        args = ",".join(_doc_param_type(a) for a in t.GetGenericArguments())
        return f"{base}{{{args}}}"
    return _doc_type_prefix(t)


def _method_doc_id(m, declaring_prefix: str, is_ctor: bool) -> str:
    name = "#ctor" if is_ctor else m.Name
    # generic method arity marker:  Method``2
    arity = ""
    try:
        if not is_ctor and m.IsGenericMethodDefinition:
            arity = "``" + str(len(list(m.GetGenericArguments())))
    except Exception:
        pass
    params = list(m.GetParameters())
    if params:
        plist = ",".join(_doc_param_type(p.ParameterType) for p in params)
        sig = f"({plist})"
    else:
        sig = ""
    return f"M:{declaring_prefix}.{name}{arity}{sig}"


# ---------------------------------------------------------------------------
# Type-annotation formatter
# ---------------------------------------------------------------------------

def fmt(t, ns: str) -> tuple[str, set[str]]:
    extra: set[str] = set()
    if t is None:
        return "Any", extra
    if t.IsByRef:
        return fmt(t.GetElementType(), ns)
    if t.IsPointer:
        return "Any", extra
    if t.IsArray:
        inner, imp = fmt(t.GetElementType(), ns)
        return f"List[{inner}]", imp
    if t.IsGenericParameter:
        return t.Name, extra
    full = (t.FullName or t.Name or "Any").replace("+", ".")
    if full in PRIMITIVES:
        return PRIMITIVES[full], extra
    if t.IsGenericType:
        return _fmt_generic(t, ns)
    if t.Namespace and t.Namespace.startswith("ZOSAPI"):
        simple = strip_arity(t.Name)
        if t.Namespace == ns:
            return simple, extra
        extra.add(f"import {t.Namespace}")
        return f"{t.Namespace}.{simple}", extra
    return "Any", extra


def _fmt_generic(t, ns: str) -> tuple[str, set[str]]:
    extra: set[str] = set()
    gd = t.GetGenericTypeDefinition()
    gd_full = re.sub(r"`\d+.*$", "", gd.FullName or gd.Name or "")
    arg_strs: list[str] = []
    for a in t.GetGenericArguments():
        s, imp = fmt(a, ns)
        arg_strs.append(s)
        extra |= imp
    args = ", ".join(arg_strs)
    if gd_full in GENERIC_CONTAINERS:
        py = GENERIC_CONTAINERS[gd_full]
        if py == "Optional" and len(arg_strs) == 1:
            return f"Optional[{args}]", extra
        return (f"{py}[{args}]" if args else py), extra
    if gd.Namespace and gd.Namespace.startswith("ZOSAPI"):
        simple = strip_arity(gd.Name)
        if gd.Namespace == ns:
            ann = f"{simple}[{args}]" if args else simple
        else:
            extra.add(f"import {gd.Namespace}")
            qualified = f"{gd.Namespace}.{simple}"
            ann = f"{qualified}[{args}]" if args else qualified
        return ann, extra
    return "Any", extra


# ---------------------------------------------------------------------------
# Docstring emission
# ---------------------------------------------------------------------------

def _docstring_lines(text: str | None, indent: str) -> list[str]:
    """Render *text* as a triple-quoted docstring, properly indented, or []."""
    if not text:
        return []
    safe = text.replace("\\", "\\\\").replace('"""', '\\"\\"\\"')
    raw_lines = safe.split("\n")
    if len(raw_lines) == 1:
        return [f'{indent}"""{raw_lines[0]}"""']
    out = [f'{indent}"""{raw_lines[0]}']
    for ln in raw_lines[1:]:
        out.append(f"{indent}{ln}" if ln else "")
    out.append(f'{indent}"""')
    return out


def _enum_param_hint(method) -> str | None:
    """List the fully-qualified names of any ZOSAPI enum parameters of *method*.

    Pylance always renders a parameter's type with its short name in the
    signature line (and a stub cannot change that). So for methods that take an
    enum we prepend a hint to the docstring telling the user exactly what to
    type, e.g.::

        Enum parameter:
            type -> ZOSAPI.Editors.MFE.MeritOperandType

    Returns the hint text (no surrounding quotes), or ``None`` if the method has
    no enum parameters.
    """
    rows: list[str] = []
    for p in method.GetParameters():
        pt = p.ParameterType
        # Skip out/ref-out params: they are folded into the return tuple, not
        # values the caller types in, so naming them as "what to type" misleads.
        if p.IsOut or (pt.IsByRef and not p.IsIn):
            continue
        if pt.IsByRef:
            pt = pt.GetElementType()
        if pt.IsEnum and pt.Namespace and pt.Namespace.startswith("ZOSAPI"):
            qualified = _doc_type_prefix(pt)
            pname = safe_name(p.Name or "arg")
            rows.append(f"    {pname} -> {qualified}")
    if not rows:
        return None
    label = "Enum parameter:" if len(rows) == 1 else "Enum parameters:"
    return label + "\n" + "\n".join(rows)


def _type_docstring_lines(qualified_name: str, summary: str | None, indent: str) -> list[str]:
    """Class/enum docstring whose first line is the fully-qualified .NET name.

    Hover help on a short name like ``MeritOperandType`` then shows its real
    location (``ZOSAPI.Editors.MFE.MeritOperandType``) — useful because the
    name alone, especially via auto-import, doesn't reveal which namespace it
    came from.
    """
    body = f"{qualified_name}\n\n{summary}" if summary else qualified_name
    return _docstring_lines(body, indent)


# ---------------------------------------------------------------------------
# Per-type stub builders
# ---------------------------------------------------------------------------

def build_enum(t, docs: XmlDocs) -> tuple[str, set[str]]:
    name = strip_arity(t.Name)
    is_flags = any(
        a.AttributeType.Name == "FlagsAttribute" for a in t.GetCustomAttributesData()
    )
    base = "IntFlag" if is_flags else "IntEnum"
    lines = [f"class {name}({base}):"]

    type_prefix = _doc_type_prefix(t)
    cls_doc = docs.get(f"T:{type_prefix}")
    lines += _type_docstring_lines(type_prefix, cls_doc, "    ")

    fields = [
        f for f in t.GetFields()
        if f.IsLiteral and f.IsStatic and not f.Name.startswith("_")
    ]
    if fields:
        for f in fields:
            # Reserved-word members (e.g. a .NET enum value literally named
            # ``None``) are not valid Python identifiers and can't be written in
            # Python source anyway; suffix them so the stub stays parseable.
            field_name = safe_name(f.Name)
            try:
                lines.append(f"    {field_name} = {int(f.GetRawConstantValue())}")
            except Exception:
                lines.append(f"    {field_name}: int")
            fdoc = docs.get(f"F:{type_prefix}.{f.Name}")
            lines += _docstring_lines(fdoc, "    ")
    elif not cls_doc:
        lines.append("    ...")

    return "\n".join(lines), set()


def _collect_bases(t, ns: str) -> tuple[list[str], set[str]]:
    bases: list[str] = []
    extra: set[str] = set()
    if not t.IsInterface:
        bt = t.BaseType
        if bt and bt.FullName not in (None, "System.Object", "System.ValueType", "System.Enum"):
            ann, imp = fmt(bt, ns)
            if ann not in ("Any", "None"):
                bases.append(ann)
                extra |= imp
    for iface in t.GetInterfaces():
        if iface.Namespace and iface.Namespace.startswith("ZOSAPI"):
            ann, imp = fmt(iface, ns)
            bases.append(ann)
            extra |= imp
    return bases, extra


def _collect_members(t, ns: str, docs: XmlDocs, indent: str = "    ") -> tuple[list[str], set[str]]:
    from System.Reflection import BindingFlags

    lines: list[str] = []
    extra: set[str] = set()
    type_prefix = _doc_type_prefix(t)

    binding = (
        BindingFlags.Public | BindingFlags.Instance
        | BindingFlags.Static | BindingFlags.DeclaredOnly
    )

    # Properties and indexers
    for prop in t.GetProperties(binding):
        idx_params = prop.GetIndexParameters()
        if len(idx_params) > 0:
            idx_ann, imp = fmt(idx_params[0].ParameterType, ns)
            val_ann, imp2 = fmt(prop.PropertyType, ns)
            extra |= imp | imp2
            lines.append(f"{indent}def __getitem__(self, index: {idx_ann}) -> {val_ann}: ...")
            if prop.CanWrite:
                lines.append(
                    f"{indent}def __setitem__(self, index: {idx_ann}, value: {val_ann}) -> None: ..."
                )
        else:
            ann, imp = fmt(prop.PropertyType, ns)
            extra |= imp
            pdoc = docs.get(f"P:{type_prefix}.{prop.Name}")
            lines.append(f"{indent}@property")
            lines.append(f"{indent}def {prop.Name}(self) -> {ann}:")
            doc_lines = _docstring_lines(pdoc, indent + "    ")
            if doc_lines:
                lines += doc_lines
                lines.append(f"{indent}    ...")
            else:
                lines[-1] = f"{indent}def {prop.Name}(self) -> {ann}: ..."
            if prop.CanWrite:
                lines.append(f"{indent}@{prop.Name}.setter")
                lines.append(f"{indent}def {prop.Name}(self, value: {ann}) -> None: ...")

    # Events
    for ev in t.GetEvents(binding):
        lines.append(f"{indent}{ev.Name}: Any")

    # Methods
    methods = [
        m for m in t.GetMethods(binding)
        if not m.IsSpecialName and not m.Name.startswith("_")
    ]
    by_name: dict[str, list] = defaultdict(list)
    for m in methods:
        by_name[m.Name].append(m)

    for mname in sorted(by_name):
        overloads = by_name[mname]
        use_overload = len(overloads) > 1
        for m in overloads:
            param_parts = [] if m.IsStatic else ["self"]
            out_types: list[str] = []
            for p in m.GetParameters():
                pname = safe_name(p.Name or f"arg{p.Position}")
                pt = p.ParameterType
                is_out = p.IsOut or (pt.IsByRef and not p.IsIn)
                ann, imp = fmt(pt, ns)
                extra |= imp
                if is_out:
                    out_types.append(ann)
                else:
                    try:
                        has_default = p.HasDefaultValue and p.DefaultValue is not None
                    except Exception:
                        has_default = False
                    suffix = " = ..." if has_default else ""
                    param_parts.append(f"{pname}: {ann}{suffix}")
            ret, imp = fmt(m.ReturnType, ns)
            extra |= imp
            if out_types:
                all_outs = ([] if ret == "None" else [ret]) + out_types
                ret = all_outs[0] if len(all_outs) == 1 else f"Tuple[{', '.join(all_outs)}]"
            sig = f"({', '.join(param_parts)}) -> {ret}"
            if m.IsStatic:
                lines.append(f"{indent}@staticmethod")
            if use_overload:
                lines.append(f"{indent}@overload")
            mdoc = docs.get(_method_doc_id(m, type_prefix, is_ctor=False))
            # Prepend a hint naming the fully-qualified type of any enum
            # parameter, since the signature line only ever shows its short name.
            enum_hint = _enum_param_hint(m)
            if enum_hint:
                mdoc = enum_hint + "\n\n" + mdoc if mdoc else enum_hint
            doc_lines = _docstring_lines(mdoc, indent + "    ")
            if doc_lines:
                lines.append(f"{indent}def {mname}{sig}:")
                lines += doc_lines
                lines.append(f"{indent}    ...")
            else:
                lines.append(f"{indent}def {mname}{sig}: ...")

    # Nested public types
    from System.Reflection import BindingFlags as BF
    for nt in t.GetNestedTypes(BF.Public):
        if any(c in (nt.Name or "") for c in ("<", ">")):
            continue
        try:
            if nt.IsEnum:
                nested_block, n_imp = build_enum(nt, docs)
                nested_block = "\n".join(indent + ln if ln else ln
                                         for ln in nested_block.split("\n"))
            else:
                nested_block, n_imp = _build_type_body(nt, ns, docs, indent=indent + "    ")
                name_part = f"class {strip_arity(nt.Name)}:"
                nested_block = indent + name_part + "\n" + nested_block
            extra |= n_imp
            lines.append(nested_block)
        except Exception as e:
            lines.append(f"{indent}# Skipped nested type {nt.Name}: {e}")

    return lines, extra


def _build_type_body(t, ns: str, docs: XmlDocs, indent: str = "    ") -> tuple[str, set[str]]:
    extra: set[str] = set()
    lines: list[str] = []
    type_prefix = _doc_type_prefix(t)

    if not t.IsInterface:
        for c in (c for c in t.GetConstructors() if c.IsPublic):
            param_parts = ["self"]
            for p in c.GetParameters():
                pname = safe_name(p.Name or f"arg{p.Position}")
                ann, imp = fmt(p.ParameterType, ns)
                extra |= imp
                param_parts.append(f"{pname}: {ann}")
            lines.append(f"{indent}def __init__({', '.join(param_parts)}) -> None: ...")

    members, mimp = _collect_members(t, ns, docs, indent=indent)
    extra |= mimp
    lines.extend(members)
    if not lines:
        lines.append(f"{indent}...")
    return "\n".join(lines), extra


def build_type_stub(t, ns: str, docs: XmlDocs) -> tuple[str, set[str]]:
    extra: set[str] = set()
    name = strip_arity(t.Name)
    bases, b_imp = _collect_bases(t, ns)
    extra |= b_imp
    gparams = list(t.GetGenericArguments()) if t.IsGenericTypeDefinition else []
    if gparams:
        gp = ", ".join(p.Name for p in gparams)
        bases = [f"Generic[{gp}]"] + bases
    base_str = f"({', '.join(bases)})" if bases else ""
    header = f"class {name}{base_str}:"

    type_prefix = _doc_type_prefix(t)
    cls_doc = docs.get(f"T:{type_prefix}")
    doc_lines = _type_docstring_lines(type_prefix, cls_doc, "    ")

    body, b_imp = _build_type_body(t, ns, docs, indent="    ")
    extra |= b_imp
    return header + "\n" + ("\n".join(doc_lines) + "\n" if doc_lines else "") + body, extra


# ---------------------------------------------------------------------------
# Assembly loading & type gathering
# ---------------------------------------------------------------------------

def load_assemblies(dll_dir: Path) -> list:
    import clr
    from System.Reflection import Assembly
    result = []
    for name in DLL_NAMES:
        path = str(dll_dir / name)
        clr.AddReference(path)
        result.append(Assembly.LoadFrom(path))
        print(f"  Loaded {name}")
    return result


def gather_types(assemblies: list) -> list:
    types = []
    for asm in assemblies:
        try:
            batch = list(asm.GetTypes())
        except Exception as e:
            print(f"  Warning: GetTypes() failed ({e}); using ExportedTypes")
            try:
                batch = list(asm.GetExportedTypes())
            except Exception:
                batch = []
        for t in batch:
            if t.IsNested:
                continue
            if not (t.IsPublic or t.IsNestedPublic):
                continue
            if not t.Namespace:
                continue
            if any(c in (t.Name or "") for c in ("<", ">")):
                continue
            types.append(t)
    return types


# ---------------------------------------------------------------------------
# File output  (PEP 561 stub-only package: ZOSAPI-stubs, NO __init__.py)
# ---------------------------------------------------------------------------

_FILE_HEADER = """\
# Auto-generated by zosapi-stubgen — do not edit by hand.
# Re-run `zosapi-stubgen` to refresh after an OpticStudio upgrade.
from __future__ import annotations
from typing import (
    Any, Dict, Generic, Iterable, Iterator, List,
    Optional, overload, Sequence, Set, Tuple, TypeVar, Union,
)
from enum import IntEnum, IntFlag
from datetime import datetime, timedelta
"""


def _collect_typevar_names(t) -> set[str]:
    if t.IsGenericTypeDefinition:
        return {p.Name for p in t.GetGenericArguments()}
    return set()


def _typevar_declarations(types: list) -> str:
    names: set[str] = set()
    for t in types:
        names |= _collect_typevar_names(t)
    if not names:
        return ""
    return "\n".join(f'{n} = TypeVar("{n}")' for n in sorted(names)) + "\n"


def _ns_to_stub_dir(ns: str) -> list[str]:
    """ZOSAPI.Editors.LDE -> ['ZOSAPI-stubs', 'Editors', 'LDE']."""
    parts = ns.split(".")
    parts[0] = parts[0] + STUB_PACKAGE_SUFFIX
    return parts


def _immediate_children(ns: str, all_namespaces: set[str]) -> list[str]:
    """Return the leaf names of namespaces that are direct children of *ns*."""
    prefix = ns + "."
    depth = ns.count(".") + 1
    children = {
        other.split(".")[depth]
        for other in all_namespaces
        if other.startswith(prefix) and other.count(".") >= depth
    }
    return sorted(children)


def write_stubs(by_ns: dict[str, list], docs: XmlDocs, output_dir: Path) -> list[str]:
    # Build the complete set of namespaces that must exist as packages: every
    # namespace that has types, plus all of their ancestors. Ancestors with no
    # types of their own still need an __init__.pyi so that attribute access
    # chains (e.g. ZOSAPI.Editors.MFE) resolve for type checkers.
    all_namespaces: set[str] = set()
    for ns in by_ns:
        parts = ns.split(".")
        for i in range(1, len(parts) + 1):
            all_namespaces.add(".".join(parts[:i]))

    top_level: set[str] = set()
    for ns in sorted(all_namespaces):
        types = by_ns.get(ns, [])
        blocks: list[str] = []
        ns_imports: set[str] = set()
        for t in sorted(types, key=lambda x: x.Name):
            try:
                if t.IsEnum:
                    block, imp = build_enum(t, docs)
                else:
                    block, imp = build_type_stub(t, ns, docs)
                blocks.append(block)
                ns_imports |= imp
            except Exception as e:
                print(f"    Skipped {t.FullName}: {e}")

        ns_imports.discard(f"import {ns}")

        # Explicitly re-export immediate child subpackages. PEP 484 requires the
        # `import ... as ...` (redundant alias) form for a name to be considered
        # re-exported from a stub; without it, `ZOSAPI.Editors` and deeper
        # attribute access is "Unknown" to Pyright/Pylance even though the
        # subpackage exists on disk.
        children = _immediate_children(ns, all_namespaces)
        reexports = "\n".join(f"from . import {c} as {c}" for c in children)

        typevar_section = _typevar_declarations(types)
        import_section = "\n".join(sorted(ns_imports))
        parts = [_FILE_HEADER]
        if typevar_section:
            parts.append(typevar_section)
        if import_section:
            parts.append(import_section + "\n")
        if reexports:
            parts.append(reexports + "\n")
        if blocks:
            parts.append("\n\n".join(blocks))
        content = "\n".join(parts) + "\n"

        top_level.add(ns.split(".")[0])
        ns_path = output_dir.joinpath(*_ns_to_stub_dir(ns))
        ns_path.mkdir(parents=True, exist_ok=True)
        (ns_path / "__init__.pyi").write_text(content, encoding="utf-8")
        print(f"  {ns:<60s} {len(blocks):4d} types")
    return sorted(top_level)


def generate(dll_dir: Path, output_dir: Path) -> None:
    print("ZOS-API Stub Generator")
    print(f"  DLL dir    : {dll_dir}")
    print(f"  Output dir : {output_dir}\n")

    print("Loading assemblies...")
    assemblies = load_assemblies(dll_dir)

    print("\nLoading XML documentation...")
    docs = XmlDocs().load(*[dll_dir / n for n in XML_NAMES])
    print(f"  {docs.member_count} documented members")

    print("\nCollecting types...")
    all_types = gather_types(assemblies)
    print(f"  {len(all_types)} public top-level types found")

    by_ns: dict[str, list] = defaultdict(list)
    for t in all_types:
        by_ns[t.Namespace].append(t)
    print(f"  {len(by_ns)} namespaces\n")

    output_dir.mkdir(parents=True, exist_ok=True)
    print("Generating stubs...")
    write_stubs(by_ns, docs, output_dir)
    print("\nDone.")
