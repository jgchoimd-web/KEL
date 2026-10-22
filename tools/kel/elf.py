"""Minimal ELF reader: interpreter, SONAME, NEEDED, RPATH/RUNPATH.

Used when packaging to derive "so:" provides/depends automatically (the
apk convention) and to check for build-path leaks. Only the standard
library is used, so it works on any architecture's binaries.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path

ELF_MAGIC = b"\x7fELF"
PT_INTERP = 3
SHT_DYNAMIC = 6
DT_NEEDED, DT_SONAME, DT_RPATH, DT_RUNPATH = 1, 14, 15, 29
ET_EXEC, ET_DYN = 2, 3


@dataclass
class ElfInfo:
    elf_class: int  # 32 or 64
    machine: int
    etype: int
    interpreter: str | None = None
    soname: str | None = None
    needed: list[str] = field(default_factory=list)
    rpath: list[str] = field(default_factory=list)
    runpath: list[str] = field(default_factory=list)


def is_elf(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(4) == ELF_MAGIC
    except OSError:
        return False


def read_elf(path: Path) -> ElfInfo | None:
    """Return dynamic-linking information, or None if path is not ELF."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 52 or data[:4] != ELF_MAGIC:
        return None
    cls = {1: 32, 2: 64}.get(data[4])
    endian = {1: "<", 2: ">"}.get(data[5])
    if cls is None or endian is None:
        return None
    if cls == 64:
        hdr = struct.unpack_from(endian + "HHIQQQIHHHHHH", data, 16)
        etype, machine, _, _, phoff, shoff, _, _, phentsize, phnum, shentsize, shnum, _ = hdr
    else:
        hdr = struct.unpack_from(endian + "HHIIIIIHHHHHH", data, 16)
        etype, machine, _, _, phoff, shoff, _, _, phentsize, phnum, shentsize, shnum, _ = hdr
    info = ElfInfo(elf_class=cls, machine=machine, etype=etype)

    # Program headers: the requested interpreter.
    for i in range(phnum):
        off = phoff + i * phentsize
        if off + phentsize > len(data):
            break
        if cls == 64:
            p_type, _, p_offset, _, _, p_filesz, _, _ = struct.unpack_from(endian + "IIQQQQQQ", data, off)
        else:
            p_type, p_offset, _, _, p_filesz, _, _, _ = struct.unpack_from(endian + "IIIIIIII", data, off)
        if p_type == PT_INTERP:
            info.interpreter = data[p_offset:p_offset + p_filesz].split(b"\0", 1)[0].decode(errors="replace")

    # Section headers: .dynamic and its string table (sh_link).
    sections = []
    for i in range(shnum):
        off = shoff + i * shentsize
        if off + shentsize > len(data):
            break
        if cls == 64:
            _, sh_type, _, _, sh_offset, sh_size, sh_link, _, _, sh_entsize = struct.unpack_from(
                endian + "IIQQQQIIQQ", data, off)
        else:
            _, sh_type, _, _, sh_offset, sh_size, sh_link, _, _, sh_entsize = struct.unpack_from(
                endian + "IIIIIIIIII", data, off)
        sections.append((sh_type, sh_offset, sh_size, sh_link, sh_entsize))
    for sh_type, sh_offset, sh_size, sh_link, _ in sections:
        if sh_type != SHT_DYNAMIC or sh_link >= len(sections):
            continue
        _, str_off, str_size, _, _ = sections[sh_link]
        strtab = data[str_off:str_off + str_size]

        def string(idx: int) -> str:
            return strtab[idx:].split(b"\0", 1)[0].decode(errors="replace")

        entsize = 16 if cls == 64 else 8
        fmt = endian + ("qQ" if cls == 64 else "iI")
        for off in range(sh_offset, sh_offset + sh_size - entsize + 1, entsize):
            tag, val = struct.unpack_from(fmt, data, off)
            if tag == 0:
                break
            if tag == DT_NEEDED:
                info.needed.append(string(val))
            elif tag == DT_SONAME:
                info.soname = string(val)
            elif tag == DT_RPATH:
                info.rpath.extend(p for p in string(val).split(":") if p)
            elif tag == DT_RUNPATH:
                info.runpath.extend(p for p in string(val).split(":") if p)
        break
    return info
