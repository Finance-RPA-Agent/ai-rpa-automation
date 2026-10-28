"""Save generated reports through the desktop's native Save As dialog."""
import os
from pathlib import Path
import shutil
import tempfile

import webview


def save_report(source, filename):
    if not webview.windows:
        return {"handled": False}
    selected = webview.windows[0].create_file_dialog(
        webview.FileDialog.SAVE, save_filename=filename,
        file_types=("Excel workbook (*.xlsx)",))
    if not selected:
        return {"handled": True, "saved": False, "cancelled": True}
    destination = Path(selected if isinstance(selected, str) else selected[0])
    if not destination.is_absolute():
        raise ValueError("Choose a complete local destination path.")
    if not destination.suffix:
        destination = destination.with_suffix(".xlsx")
    if destination.suffix.lower() != ".xlsx":
        raise ValueError("Save the report with an .xlsx filename.")
    if destination.resolve() != Path(source).resolve():
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".financeflow-", suffix=".xlsx", delete=False) as handle:
                temporary = Path(handle.name)
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    return {"handled": True, "saved": True, "path": str(destination)}
