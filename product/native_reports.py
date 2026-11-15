"""Keep generated reports in a separate folder, without a Save As dialog."""
import os
import filecmp
from pathlib import Path
import secrets
import shutil


def save_report(source, filename):
    source = Path(source).resolve(strict=True)
    folder = source.parent if source.parent.name == "Reports" else source.parent / "Reports"
    folder.mkdir(exist_ok=True)
    destination = folder / source.name
    if destination != source:
        if destination.is_file() and filecmp.cmp(source, destination, shallow=False):
            return {"handled": True, "saved": True, "path": str(destination), "folder": str(folder)}
        # Keep legacy originals intact so stored hashes and old links stay valid.
        for _ in range(10):
            try:
                with destination.open("xb") as target:
                    try:
                        with source.open("rb") as original:
                            shutil.copyfileobj(original, target)
                    except BaseException:
                        # Close before unlink on Windows.
                        target.close()
                        destination.unlink(missing_ok=True)
                        raise
                break
            except FileExistsError:
                destination = folder / f"{source.stem}-{secrets.token_hex(5)}{source.suffix}"
        else:
            raise OSError("A unique report filename could not be created.")
    return {"handled": True, "saved": True, "path": str(destination), "folder": str(folder)}


def open_report_folder(folder):
    folder = Path(folder).resolve(strict=True)
    if not folder.is_dir():
        raise ValueError("The report folder was not found.")
    if os.name == "nt":
        os.startfile(str(folder))
        return {"opened": True, "path": str(folder)}
    return {"opened": False, "path": str(folder)}
