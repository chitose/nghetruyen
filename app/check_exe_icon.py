"""Checks the icon that ended up inside the built exe.

Run from the app venv, which has pefile (a PyInstaller dependency):

    venv\\Scripts\\python.exe check_exe_icon.py [exe]

Prints every RT_ICON image the exe carries and whether its bytes match
`assets/nghetruyen.ico`'s entry of the same size. The point is that `icon=` in
NgheTruyen.spec could be wrong -- a missing file, a stale asset, a build that
skipped the resource step -- and nothing else would say so: the exe would just
show a generic icon in the taskbar.

Windows-only tooling for a Windows-only artifact (ADR-0012, ADR-0017), and
`pefile` is imported where it is used rather than at the top, so that this file
is still importable -- and collectable by `unittest discover` -- on Linux.
"""
import sys
from pathlib import Path

HERE = Path(__file__).parent
RT_ICON = 3
RT_GROUP_ICON = 14


def embedded_icons(exe: Path):
    """(size, bytes) for every RT_ICON image in `exe`'s resources.

    An icon image does not record its own size -- the first bytes of a PNG blob
    are the PNG signature, of a DIB one its header -- so the sizes come from the
    RT_GROUP_ICON directory that sits beside the images.
    """
    import pefile

    pe = pefile.PE(str(exe), fast_load=True)
    pe.parse_data_directories(
        directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]],
    )
    sizes, images = {}, {}
    for entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        for resource in entry.directory.entries:
            data = resource.directory.entries[0].data.struct
            blob = pe.get_data(data.OffsetToData, data.Size)
            if entry.struct.Id == RT_GROUP_ICON:
                count = int.from_bytes(blob[4:6], "little")
                for index in range(count):
                    item = blob[6 + index * 14:20 + index * 14]
                    ident = int.from_bytes(item[12:14], "little")
                    sizes[ident] = (item[0] or 256, item[1] or 256)
            elif entry.struct.Id == RT_ICON:
                images[resource.struct.Id] = blob
    return [(sizes[ident], images[ident]) for ident in sorted(images)]


def ico_entries(icon: Path):
    """(size, bytes) for every image in the .ico, with no Pillow needed."""
    data = icon.read_bytes()
    count = int.from_bytes(data[4:6], "little")
    out = {}
    for index in range(count):
        entry = data[6 + index * 16:22 + index * 16]
        width, height = entry[0] or 256, entry[1] or 256
        size = int.from_bytes(entry[8:12], "little")
        offset = int.from_bytes(entry[12:16], "little")
        out[(width, height)] = data[offset:offset + size]
    return out


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "NgheTruyen.exe"
    asset = ico_entries(HERE / "assets" / "nghetruyen.ico")
    embedded = embedded_icons(exe)

    print(f"{exe.name}: {len(embedded)} icon images, asset has {len(asset)}")
    failures = []
    for size, blob in sorted(embedded):
        same = asset.get(size) == blob
        print(f"  {size[0]}x{size[1]}: {len(blob)} bytes, "
              f"{'matches the asset' if same else 'DIFFERS from the asset'}")
        if not same:
            failures.append(size)
    missing = sorted(set(asset) - {size for size, _ in embedded})
    if missing:
        print(f"  missing from the exe: {missing}")
        failures.extend(missing)
    print("OK" if not failures else f"FAILED: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
