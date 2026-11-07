# -*- coding: utf-8 -*-
"""Сверка: судья3.py против ..\\судья.py — подсказки, схемы, модель и общие функции совпадают слово в слово (по AST,
без запуска судьи). py сверка_судьи.py"""
import ast
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ПАПКА = os.path.dirname(os.path.abspath(__file__))


def разбор(путь):
    д = ast.parse(io.open(путь, encoding="utf-8").read())
    знач, функ = {}, {}
    for у in д.body:
        if isinstance(у, ast.Assign) and len(у.targets) == 1 and isinstance(у.targets[0], ast.Name):
            знач[у.targets[0].id] = ast.dump(у.value)
        elif isinstance(у, ast.FunctionDef):
            функ[у.name] = ast.dump(у)
    return знач, функ


с1, ф1 = разбор(os.path.join(os.path.dirname(ПАПКА), "судья.py"))
с3, ф3 = разбор(os.path.join(ПАПКА, "судья3.py"))
for имя in ("МОДЕЛЬ", "ПОДСКАЗКА_ОТВЕТ", "ПОДСКАЗКА_СВЕРКА", "СХ_ОТВЕТ", "СХ_СВЕРКА", "_ЗАПИСЬ_ПОЛЯ", "_ЛИШНЕЕ_MEM0"):
    print(f"{имя:18} {'совпадает' if с1.get(имя) == с3.get(имя) else 'РАЗНИЦА'}")
for имя in ("спросить", "_запись", "сжать_эва", "сжать_mem0", "знак"):
    print(f"{имя:18} {'совпадает' if ф1.get(имя) == ф3.get(имя) else 'РАЗНИЦА'}")
print("судить            ", "отличается только подсказкой-параметром (для В — дата)" if ф1.get("судить") != ф3.get("судить") else "совпадает")
