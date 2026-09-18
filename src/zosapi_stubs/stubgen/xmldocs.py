"""
Parse the ZOS-API .NET XML documentation files and expose docstrings keyed by
the standard .NET XML documentation member ID (e.g. ``M:ZOSAPI.Foo.Bar(System.Int32)``).

The member IDs are reconstructed from reflection metadata in :mod:`generator`,
so the two sides must agree on the encoding rules.  Those rules are defined by
the C#/ECMA spec for documentation comment IDs:

    * type ........ ``T:Namespace.Type``                     (nested: dot, generic: `Name`1`)
    * field ....... ``F:Namespace.Type.Field``
    * property .... ``P:Namespace.Type.Prop``                (indexer: ``Prop(paramtypes)``)
    * method ...... ``M:Namespace.Type.Method(paramtypes)``  (ctor: ``#ctor``)
    * event ....... ``E:Namespace.Type.Event``

    parameter type encodings:
        byref ........... ``Type@``
        pointer ......... ``Type*``
        sz-array ........ ``Type[]``
        md-array ........ ``Type[0:,0:]``
        type generic .... `` `n ``   (position n)
        method generic .. ``  ``n `` (position n)
        constructed ..... ``Outer{Arg1,Arg2}``
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET


class XmlDocs:
    """Holds the parsed ``<summary>``/``<param>``/``<returns>`` text for every member."""

    def __init__(self) -> None:
        # member-id -> structured doc parts (summary / params / returns / remarks)
        self._struct: dict[str, dict] = {}
        # type-or-member name with params stripped -> id, for single-overload fallback
        self._by_noparen: dict[str, list[str]] = {}

    # ------------------------------------------------------------------ loading
    def load(self, *xml_paths) -> "XmlDocs":
        for path in xml_paths:
            try:
                tree = ET.parse(str(path))
            except (ET.ParseError, FileNotFoundError, OSError):
                continue
            for member in tree.getroot().iterfind(".//member"):
                mid = member.get("name")
                if not mid:
                    continue
                struct = self._parse_member(member)
                if struct["summary"] or struct["params"] or struct["returns"] or struct["remarks"]:
                    self._struct[mid] = struct
                # index by id-without-parentheses for the single-overload fallback
                noparen = mid.split("(", 1)[0]
                self._by_noparen.setdefault(noparen, []).append(mid)
        return self

    # ------------------------------------------------------------------ lookup
    def _lookup(self, member_id: str) -> dict | None:
        s = self._struct.get(member_id)
        if s is not None:
            return s
        # Fall back to a name-only match when the exact (parameter-typed) id is
        # absent but exactly one overload of that member is documented.
        noparen = member_id.split("(", 1)[0]
        candidates = [c for c in self._by_noparen.get(noparen, []) if c in self._struct]
        if len(candidates) == 1:
            return self._struct[candidates[0]]
        return None

    def get(self, member_id: str) -> str | None:
        """Return the rendered docstring for *member_id*, or ``None``."""
        s = self._lookup(member_id)
        return self._render(s) if s else None

    @property
    def member_count(self) -> int:
        return len(self._struct)

    # ------------------------------------------------------------------ parsing
    def _parse_member(self, member: ET.Element) -> dict:
        summary = member.find("summary")
        params: list[tuple[str, str]] = []
        for p in member.findall("param"):
            name = p.get("name", "").strip()
            if name:
                params.append((name, _clean(p)))
        ret = member.find("returns")
        remarks = member.find("remarks")
        return {
            "summary": _clean(summary) if summary is not None else "",
            "params": params,
            "returns": _clean(ret) if ret is not None else "",
            "remarks": _clean(remarks) if remarks is not None else "",
        }

    # ------------------------------------------------------------------ rendering
    def _render(self, struct: dict) -> str:
        parts: list[str] = []

        if struct["summary"]:
            parts.append(struct["summary"])

        if struct["params"]:
            param_lines: list[str] = []
            for name, desc in struct["params"]:
                param_lines.append(f"    {name}: {desc}" if desc else f"    {name}")
            parts.append("Args:\n" + "\n".join(param_lines))

        if struct["returns"]:
            parts.append("Returns:\n    " + struct["returns"])

        if struct["remarks"]:
            parts.append(struct["remarks"])

        return "\n\n".join(parts).strip()


# ---------------------------------------------------------------------------
# XML inline-markup cleanup
# ---------------------------------------------------------------------------

_WS = re.compile(r"[ \t]*\n[ \t]*")
_MULTISPACE = re.compile(r"  +")


def _crefname(cref: str) -> str:
    """``P:ZOSAPI.Editors.LDE.ILensDataEditor.NumberOfSurfaces`` -> ``NumberOfSurfaces``."""
    cref = cref.split(":", 1)[-1]          # drop the leading T:/M:/P:/F:/E:
    cref = cref.split("(", 1)[0]            # drop method parameter list
    cref = re.sub(r"`+\d+", "", cref)       # drop generic arity markers
    return cref.rsplit(".", 1)[-1] or cref


def _clean(elem: ET.Element) -> str:
    """Flatten a doc element's mixed content into clean one-or-more-line text."""
    out: list[str] = []

    def walk(node: ET.Element) -> None:
        if node.text:
            out.append(node.text)
        for child in node:
            tag = child.tag
            if tag in ("see", "seealso"):
                ref = child.get("cref") or child.get("langword") or child.get("href") or ""
                txt = (child.text or "").strip()
                out.append(txt if txt else _crefname(ref))
            elif tag == "paramref" or tag == "typeparamref":
                out.append(child.get("name", ""))
            elif tag == "c" or tag == "code":
                out.append((child.text or "").strip())
            elif tag == "para":
                out.append("\n")
                walk(child)
                out.append("\n")
            elif tag in ("list", "item", "term", "description"):
                walk(child)
                out.append(" ")
            else:
                walk(child)
            if child.tail:
                out.append(child.tail)

    walk(elem)
    text = "".join(out)
    text = _WS.sub(" ", text)               # collapse newlines+indent from the XML layout
    text = text.replace("\\\\", "\\")        # XML double-escaped backslashes
    text = _MULTISPACE.sub(" ", text)
    # restore intentional paragraph breaks (we inserted lone spaces around them above)
    return text.strip()
