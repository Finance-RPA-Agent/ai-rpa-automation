"""无须人工操作窗口的回归测试；Excel 和 CSV 均在临时目录生成。"""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from openpyxl import Workbook

from rpa import excel_file_tool as tool


class ExcelFileToolTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.directory = Path(self.temp_dir.name)

    def create_workbook(self, name="orders.xlsx"):
        path = self.directory / name
        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["order_id", "amount"])
        for number in range(1, 8):
            sheet.append([f"ORDER_{number}", number * 10])
        workbook.create_sheet("Another sheet").append(["SHOULD_NOT_BE_READ"])
        workbook.save(path)
        workbook.close()
        return path

    def create_csv(self, encoding="utf-8", name="订单 数据.csv"):
        path = self.directory / name
        rows = ["order_id,客户,amount"]
        rows.extend(f"ORDER_{i},客户甲,{i * 10}" for i in range(1, 8))
        path.write_text("\n".join(rows), encoding=encoding)
        return path

    def test_selection_returns_absolute_path_and_closes_window(self):
        selected = self.directory / "子目录" / ".." / "订单 数据.csv"
        with patch.object(tool.tk, "Tk") as root_factory, patch.object(
            tool.filedialog, "askopenfilename", return_value=str(selected)
        ) as dialog:
            result = tool.select_local_file()
        self.assertEqual(result, selected.resolve())
        self.assertTrue(result.is_absolute())
        root_factory.return_value.destroy.assert_called_once()
        default_filter = dialog.call_args.kwargs["filetypes"][0][1]
        self.assertIn("*.xlsx", default_filter)
        self.assertIn("*.csv", default_filter)

    def test_cancel_returns_none_and_closes_window(self):
        with patch.object(tool.tk, "Tk") as root_factory, patch.object(
            tool.filedialog, "askopenfilename", return_value=""
        ):
            self.assertIsNone(tool.select_local_file())
        root_factory.return_value.destroy.assert_called_once()

    def test_dialog_failure_preserves_cause_and_closes_window(self):
        error = tool.tk.TclError("Cannot open dialog")
        with patch.object(tool.tk, "Tk") as root_factory, patch.object(
            tool.filedialog, "askopenfilename", side_effect=error
        ):
            with self.assertRaises(tool.FileSelectionError) as caught:
                tool.select_local_file()
        self.assertIs(caught.exception.__cause__, error)
        root_factory.return_value.destroy.assert_called_once()

    def test_window_creation_failure_is_wrapped(self):
        error = tool.tk.TclError("Cannot initialize Tk")
        with patch.object(tool.tk, "Tk", side_effect=error):
            with self.assertRaises(tool.FileSelectionError) as caught:
                tool.select_local_file()
        self.assertIs(caught.exception.__cause__, error)

    def test_reads_all_rows_from_first_sheet(self):
        dataframe = tool.read_local_file(self.create_workbook())
        self.assertEqual(dataframe.columns.tolist(), ["order_id", "amount"])
        self.assertEqual(dataframe["order_id"].tolist(), [f"ORDER_{i}" for i in range(1, 8)])
        self.assertEqual(dataframe["amount"].tolist(), list(range(10, 80, 10)))

    def test_accepts_string_path_and_uppercase_extension(self):
        dataframe = tool.read_excel_file(str(self.create_workbook("订单.XLSX")))
        self.assertEqual(dataframe.shape, (7, 2))

    def test_reads_utf8_csv_with_bom_and_compatible_entry_point(self):
        for encoding in ("utf-8", "utf-8-sig"):
            path = self.create_csv(encoding=encoding, name="订单 数据.CSV")
            for reader in (tool.read_local_file, tool.read_excel_file):
                with self.subTest(encoding=encoding, reader=reader.__name__):
                    dataframe = reader(str(path))
                    self.assertEqual(dataframe.columns.tolist(), ["order_id", "客户", "amount"])
                    self.assertEqual(dataframe["客户"].tolist(), ["客户甲"] * 7)
                    self.assertEqual(dataframe["order_id"].tolist(), [f"ORDER_{i}" for i in range(1, 8)])
                    self.assertEqual(dataframe["amount"].tolist(), list(range(10, 80, 10)))

    def test_missing_file(self):
        with self.assertRaises(FileNotFoundError):
            tool.read_local_file(self.directory / "missing.xlsx")

    def test_directory_is_not_a_file(self):
        with self.assertRaises(IsADirectoryError):
            tool.read_local_file(self.directory)

    def test_unsupported_file_type(self):
        path = self.directory / "orders.txt"
        path.write_text("order_id,amount\nORDER_1,10\n", encoding="utf-8")
        with self.assertRaises(tool.UnsupportedFileTypeError):
            tool.read_local_file(path)

    def test_corrupted_workbook(self):
        path = self.directory / "corrupted.xlsx"
        path.write_bytes(b"This is not an Excel workbook.")
        with self.assertRaises(tool.ExcelReadError) as caught:
            tool.read_local_file(path)
        self.assertIsNotNone(caught.exception.__cause__)

    def test_invalid_csv_preserves_cause(self):
        cases = (
            ("empty", b"", tool.pd.errors.EmptyDataError),
            ("invalid_utf8", b"name\n\xff\n", UnicodeDecodeError),
            ("invalid_quotes", b'name,value\n"unclosed,1\n', tool.pd.errors.ParserError),
        )
        for name, content, cause_type in cases:
            with self.subTest(case=name):
                path = self.directory / f"{name}.csv"
                path.write_bytes(content)
                with self.assertRaises(tool.CSVReadError) as caught:
                    tool.read_local_file(path)
                self.assertIsInstance(caught.exception.__cause__, cause_type)

    def test_read_permission_failure_preserves_cause(self):
        path = self.create_workbook()
        error = PermissionError("Access denied")
        with patch.object(tool.pd, "read_excel", side_effect=error):
            with self.assertRaises(tool.ExcelReadError) as caught:
                tool.read_excel_file(path)
        self.assertIs(caught.exception.__cause__, error)

    def test_main_prints_path_then_only_five_rows(self):
        for path in (self.create_workbook(), self.create_csv()):
            with self.subTest(extension=path.suffix):
                output = StringIO()
                with patch.object(tool, "select_local_file", return_value=path), redirect_stdout(output):
                    status = tool.main()
                text = output.getvalue()
                self.assertEqual(status, 0)
                self.assertIn(str(path), text)
                self.assertLess(text.index(str(path)), text.index("ORDER_1"))
                for number in range(1, 6):
                    self.assertIn(f"ORDER_{number}", text)
                self.assertNotIn("ORDER_6", text)
                self.assertNotIn("ORDER_7", text)

    def test_main_cancel_does_not_read(self):
        output = StringIO()
        with patch.object(tool, "select_local_file", return_value=None), patch.object(
            tool, "read_local_file"
        ) as reader, redirect_stdout(output):
            self.assertEqual(tool.main(), 0)
        reader.assert_not_called()
        self.assertIn("取消", output.getvalue())

    def test_main_reports_known_errors(self):
        for error_type in (
            FileNotFoundError,
            IsADirectoryError,
            tool.UnsupportedFileTypeError,
            tool.ExcelReadError,
            tool.CSVReadError,
        ):
            with self.subTest(error=error_type.__name__):
                output = StringIO()
                with patch.object(tool, "select_local_file", return_value=self.directory / "orders.xlsx"), patch.object(
                    tool, "read_local_file", side_effect=error_type("测试错误")
                ), redirect_stdout(output):
                    self.assertEqual(tool.main(), 1)
                self.assertIn("失败", output.getvalue())
                self.assertIn("测试错误", output.getvalue())


if __name__ == "__main__":
    unittest.main()
