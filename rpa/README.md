# 本地文件选择与 Excel / CSV 读取

使用 `tkinter.filedialog` 选择一个本地文件，输出其完整绝对路径，读取后打印前 5 行。
当前支持 `.xlsx` 和 `.csv`（扩展名不区分大小写）：

- `.xlsx`：使用 `pandas.read_excel(..., engine="openpyxl")` 读取第一个工作表。
- `.csv`：使用 `pandas.read_csv(..., encoding="utf-8-sig")` 读取逗号分隔的表格，
  支持 UTF-8 和带 BOM 的 UTF-8 编码。其他编码（如 GBK）请先转换为 UTF-8。

两种格式都以第一行作为列名；不足 5 行时打印全部数据。Excel 空表或只有列名的
CSV 显示 `Empty DataFrame`；完全空白的 CSV 会提示读取失败。代码不会修改源文件。

## 安装依赖

使用 Python 3.10 或更高版本。在项目根目录打开 PowerShell，执行：

```powershell
python -m venv rpa/.venv
.\rpa\.venv\Scripts\python.exe -m pip install -r rpa/requirements.txt
```

依赖为 `pandas` 和读取 `.xlsx` 所需的 `openpyxl`，不需要安装 Microsoft Excel。
CSV 读取无需新增依赖。
`tkinter` 由 Python 的 Tcl/Tk 支持提供，不要执行 `pip install tkinter`。
如果 Python 提示缺少 `tkinter`，请通过 Windows Python 安装器添加 Tcl/Tk 支持。
可以执行 `python -m tkinter` 检查 Tk 是否可用，检查后关闭测试窗口。

## 直接运行

仍在项目根目录执行：

```powershell
.\rpa\.venv\Scripts\python.exe rpa/excel_file_tool.py
```

也可以使用已安装依赖的 Python：

```powershell
python rpa/excel_file_tool.py
```

1. 程序弹出 Windows 文件选择对话框。
2. 选择 `.xlsx` 或 `.csv` 文件，例如 `C:\Users\xxx\Documents\orders.xlsx`。
3. 终端先显示 `文件完整路径：C:\Users\xxx\Documents\orders.xlsx`。
4. 若读取成功，显示前 5 行及 pandas 的行索引；Excel 默认读取第一个工作表。

取消选择时显示取消提示并正常退出。文件不存在、选择目录、格式不支持、
Excel 损坏/加密、CSV 解析或编码错误、无读取权限等情况会显示错误提示；
运行入口不会输出异常堆栈。
文件选择框默认同时显示 `.xlsx` 和 `.csv`，也可分别筛选两种格式，
或切换为“所有文件”来测试不支持的文件类型。
退出码：成功或取消为 `0`，失败为 `1`。

## 模块调用

在项目根目录的 Python 环境中可单独调用读取函数，无须弹窗：

```python
from rpa.excel_file_tool import read_local_file

df = read_local_file(r"C:\Users\xxx\Documents\orders.xlsx")
print(df.head(5))

csv_df = read_local_file(r"C:\Users\xxx\Documents\orders.csv")
print(csv_df.head(5))
```

也可以组合文件选择和读取：

```python
from rpa.excel_file_tool import select_local_file, read_local_file

path = select_local_file()
if path is not None:
    print(str(path))  # 完整路径；转换成字符串后可交给其他模块。
    df = read_local_file(path)
```

- `select_local_file()` 返回 `Path | None`，取消返回 `None`；窗口异常为 `FileSelectionError`。
- `read_local_file(path)` 按后缀选择读取方式，返回完整 `pandas.DataFrame`；
  只有演示入口截取前 5 行显示。
- 保留原有 `read_excel_file(path)` 名称作为兼容入口，内部调用 `read_local_file`，
  同样支持 `.xlsx` 和 `.csv`，已有 Excel 调用无需修改。
- 读取函数向调用方抛出 `FileNotFoundError`、`IsADirectoryError`、
  `UnsupportedFileTypeError`、`ExcelReadError`（Excel 读取失败）或
  `CSVReadError`（CSV 读取失败），由调用方决定如何处理。
  两种读取失败异常都保留原始异常，可通过 `__cause__` 查看。
- 导入模块不会弹出窗口。文件选择函数应在桌面程序主线程调用。

## 自动测试

在项目根目录执行：

```powershell
.\rpa\.venv\Scripts\python.exe -m unittest discover -s rpa/tests -v
```

测试使用真实的临时 Excel 和 CSV 文件，并模拟文件选择框，不需要人工点击。
真实 Windows 对话框的交互效果请按“直接运行”步骤检查。

API 参考：[pandas.read_excel](https://pandas.pydata.org/docs/reference/api/pandas.read_excel.html)、
[pandas.read_csv](https://pandas.pydata.org/docs/reference/api/pandas.read_csv.html)、
[Python 文件选择对话框](https://docs.python.org/3/library/dialog.html#native-load-save-dialogs)。
