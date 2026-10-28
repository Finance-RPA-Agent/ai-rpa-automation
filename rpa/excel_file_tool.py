"""选择本地文件并读取 Excel 或 CSV；导入本模块不会弹窗或读取文件。"""

from pathlib import Path
import tkinter as tk
from tkinter import filedialog

import pandas as pd


class FileSelectionError(RuntimeError):
    """无法打开或使用文件选择窗口。"""


class UnsupportedFileTypeError(ValueError):
    """选择了不支持的文件类型。"""


class ExcelReadError(RuntimeError):
    """文件存在，但无法作为 Excel 工作簿读取。"""


class CSVReadError(RuntimeError):
    """文件存在，但无法作为 CSV 表格读取。"""


def select_local_file() -> Path | None:
    """弹出单文件选择框，返回绝对路径；用户取消时返回 None。

    请在桌面程序的主线程调用此函数。
    """
    root = None
    try:
        root = tk.Tk()
        root.withdraw()  # 隐藏空白主窗口，只显示文件选择框。
        selected = filedialog.askopenfilename(
            parent=root,
            title="请选择要读取的 Excel 或 CSV 文件",
            filetypes=[
                ("Excel 或 CSV 文件", ("*.xlsx", "*.csv")),
                ("Excel 工作簿", "*.xlsx"),
                ("CSV 文件", "*.csv"),
                ("所有文件", "*.*"),
            ],
        )
    except tk.TclError as exc:
        raise FileSelectionError(f"文件选择窗口打开失败：{exc}") from exc
    finally:
        # 选择成功、取消或窗口报错时，都释放本函数创建的 Tk 窗口。
        if root is not None:
            try:
                root.destroy()
            except tk.TclError:
                pass  # 窗口可能已经被关闭，避免清理错误覆盖原始错误。

    if not selected:
        return None
    return Path(selected).expanduser().resolve()


def read_local_file(file_path: str | Path) -> pd.DataFrame:
    """校验本地 .xlsx/.csv 文件并返回完整 DataFrame。

    Excel 读取第一个工作表，CSV 使用逗号分隔和 UTF-8（兼容 BOM）编码。
    两种格式都将第一行作为列名。支持字符串和 Path，不弹窗、不打印、不修改源文件。
    不存在的路径抛出 FileNotFoundError，目录抛出 IsADirectoryError，
    不支持的后缀抛出 UnsupportedFileTypeError，其他读取失败抛出
    ExcelReadError 或 CSVReadError，并保留原始异常，便于调用方排查问题。
    """
    read_error: type[RuntimeError] = ExcelReadError
    file_kind = "Excel"
    try:
        path = Path(file_path).expanduser().resolve()
        suffix = path.suffix.lower()
        if suffix == ".csv":
            read_error = CSVReadError
            file_kind = "CSV"
        if not path.exists():
            raise FileNotFoundError(f"文件不存在：{path}")
        if not path.is_file():
            raise IsADirectoryError(f"所选路径不是文件：{path}")
        # 文件选择框的过滤器不能代替校验；扩展名不区分大小写。
        if suffix not in (".xlsx", ".csv"):
            raise UnsupportedFileTypeError(
                f"不支持的文件类型：{path.suffix or '无扩展名'}，仅支持 .xlsx 和 .csv。"
            )

        if suffix == ".xlsx":
            return pd.read_excel(path, sheet_name=0, engine="openpyxl")
        # utf-8-sig 同时支持普通 UTF-8 和带 BOM 的 UTF-8 CSV 文件。
        return pd.read_csv(path, encoding="utf-8-sig")
    except (FileNotFoundError, IsADirectoryError, UnsupportedFileTypeError):
        raise
    except Exception as exc:
        # pandas 对损坏、编码错误、无权限等情况可能抛出不同异常。
        raise read_error(f"{file_kind} 文件读取失败：{file_path}（{exc}）") from exc


def read_excel_file(file_path: str | Path) -> pd.DataFrame:
    """兼容原有调用名称；支持 .xlsx/.csv，新代码建议使用 read_local_file。"""
    return read_local_file(file_path)


def main() -> int:
    """交互测试入口：成功或取消返回 0，选择/读取失败返回 1。"""
    try:
        file_path = select_local_file()
        if file_path is None:
            print("已取消文件选择，未读取任何文件。")
            return 0

        # 在读取之前输出路径，文件无效时也能确认选择了哪个文件。
        print(f"文件完整路径：{file_path}")
        dataframe = read_local_file(file_path)
        print("读取成功，前 5 行：")
        print(dataframe.head(5))
        return 0
    except (
        FileSelectionError,
        UnsupportedFileTypeError,
        ExcelReadError,
        CSVReadError,
        OSError,
    ) as exc:
        print(f"操作失败：{exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
