"""Validate the independently selected processing and BI reference folders."""
from pathlib import Path
import os


def select_inputs(folder, bi_folder, app_root):
    def selected(value, label):
        path = Path(value).expanduser()
        if not path.is_absolute() or not path.is_dir() or str(path).startswith(("\\\\", "//")):
            raise ValueError(f"Choose an existing absolute local {label}.")
        path = path.resolve()
        if path == app_root or path.is_relative_to(app_root):
            raise ValueError(f"Choose an {label} outside application data.")
        return path
    source = selected(folder, "input folder")
    bi = selected(bi_folder, "BI system folder") if bi_folder else None
    if bi and (source == bi or source.is_relative_to(bi) or bi.is_relative_to(source)):
        raise ValueError("Input folder and BI system folder must be separate, non-overlapping folders.")
    return source, bi


def input_files(folder, app_root):
    def unreadable(error):
        raise ValueError("An input subfolder cannot be read. Check permissions.") from error
    for base, directories, names in os.walk(folder, followlinks=False, onerror=unreadable):
        base = Path(base)
        directories[:] = sorted(name for name in directories if not name.startswith('.')
            and name.lower() not in ('node_modules', 'runtime', 'exports', 'backups', '__pycache__')
            and len(base.relative_to(folder).parts) < 5 and not (base / name).is_symlink()
            and not (base / name).is_junction() and not (base / name).resolve().is_relative_to(app_root))
        for name in sorted(names):
            path = base / name
            if name.startswith(('~$', '.')) or path.suffix.lower() not in ('.xlsx', '.csv') or path.is_symlink(): continue
            if not path.resolve().is_relative_to(folder): raise ValueError("An input is outside the selected folder.")
            yield path
