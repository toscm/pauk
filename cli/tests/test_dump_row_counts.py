"""Unit tests for the dump row counter used by scripts/restore-local.sh."""

import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "dump_row_counts",
    Path(__file__).resolve().parents[2] / "scripts" / "dump_row_counts.py",
)
dump_row_counts = importlib.util.module_from_spec(spec)
sys.modules["dump_row_counts"] = dump_row_counts
spec.loader.exec_module(dump_row_counts)
count_tuples = dump_row_counts.count_tuples
row_counts = dump_row_counts.row_counts


def test_simple_tuples():
    assert count_tuples("(1,'a'),(2,'b'),(3,NULL);") == 3


def test_parentheses_and_quotes_inside_strings():
    values = r"""(1,'f(x) = (a,b)'),(2,'it\'s (not) a tuple'),(3,'say ''(hi)'''),(4,'back\\'),(5,'x');"""
    assert count_tuples(values) == 5


def test_json_and_double_quotes():
    values = """(1,'{"a": "(", "b": [1,2]}'),(2,"dq (x)");"""
    assert count_tuples(values) == 2


def test_row_counts_sums_split_inserts_and_ignores_other_lines():
    lines = [
        "-- comment (1)",
        "DROP TABLE IF EXISTS `cards`;",
        "INSERT INTO `cards` VALUES (1,'a'),(2,'b');",
        "INSERT INTO `cards` VALUES (3,'c');",
        "INSERT INTO `users` VALUES (1,'me','2026-01-01 00:00:00');",
    ]
    assert row_counts(lines) == {"cards": 3, "users": 1}


def test_row_counts_one_tuple_per_line():
    # mariadb-dump 11.x layout
    lines = [
        "INSERT INTO `cards` VALUES\n",
        "(1,'a;'),\n",
        "(2,'(b),'),\n",
        "(3,'c');\n",
        "INSERT INTO `users` VALUES\n",
        "(1,'me');\n",
    ]
    assert row_counts(lines) == {"cards": 3, "users": 1}
