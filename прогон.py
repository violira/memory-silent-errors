# -*- coding: utf-8 -*-
"""Прогон одной системы на одном наборе: python прогон.py эва|mem0 А|Б → сырые_<набор>_<система>.json.

Эва — как живой клиент: MCP по HTTP с ключом (C:\\EVA_MEMORY\\server.py, код не трогается), свежая временная база,
EVA_MEMORY_TODAY=2026-10-19. Mem0 — по умолчанию (mem0ai из этого окружения): LLM anthropic claude-sonnet-5-5, векторы
openai text-embedding-3-small, хранилище по умолчанию (qdrant, локально) — свежая папка на набор внутри этой папки;
телеметрия Mem0 выключена (MEM0_TELEMETRY=False — наружу ничего). Ключи — из C:\\EVA_MEMORY\\.env в память процесса, не
печатаются и никуда не пишутся. Адреса API заданы явно (в окружении машины стоит чужой ANTHROPIC_BASE_URL).
Расход Mem0 считается обёрткой над create SDK — только счёт токенов, поведение не меняется."""
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ПАПКА = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ПАПКА)
import наборы  # noqa: E402

СИСТЕМА, ИМЯ = sys.argv[1], sys.argv[2]
НАБОР = наборы.А if ИМЯ == "А" else наборы.Б
ЦЕНА = {"sonnet_in": 2.0, "sonnet_out": 10.0, "emb": 0.02}   # $ за 1 млн токенов (Sonnet 5.5; text-embedding-3-small)


def _env():
    из = {}
    for с in io.open(r"C:\EVA_MEMORY\.env", encoding="utf-8-sig", errors="ignore").read().splitlines():
        с = с.strip()
        if с and not с.startswith("#") and "=" in с:
            к, _, з = с.partition("=")
            из[к.strip()] = з.strip().strip('"').strip("'")
    return из


шаги, t0 = [], time.time()
расход = {"sonnet_вызовов": 0, "sonnet_in": 0, "sonnet_out": 0, "emb_токенов": 0, "usd": 0.0, "deepseek_вызовов": 0}

if СИСТЕМА == "эва":
    ПОРТ = 18772
    ключ = io.open(r"C:\EVA_MEMORY\ключ.txt", encoding="utf-8").read().strip()
    база = tempfile.mkdtemp(prefix=f"сравнение_эва_{ИМЯ}_")
    дом = open(os.path.join(ПАПКА, "venv", "pyvenv.cfg"), encoding="utf-8").read()
    системный = os.path.join(next(с.split("=", 1)[1].strip() for с in дом.splitlines() if с.startswith("home")), "python.exe")
    env = {к: v for к, v in os.environ.items() if к != "EVA_MEMORY_KEY"}
    env.update(PYTHONIOENCODING="utf-8", EVA_MEMORY_TODAY="2026-10-19")
    лог = os.path.join(ПАПКА, f"сервер_эвы_{ИМЯ}.log")
    _л = open(лог, "w", encoding="utf-8")
    сервер = subprocess.Popen([системный, r"C:\EVA_MEMORY\server.py", "--port", str(ПОРТ), "--db",
                               os.path.join(база, "эва.db")], env=env, stdout=_л, stderr=subprocess.STDOUT)

    def rpc(метод, параметры=None):
        тело = {"jsonrpc": "2.0", "id": 1, "method": метод, "params": параметры or {}}
        з = {"Content-Type": "application/json", "Authorization": "Bearer " + ключ}
        req = urllib.request.Request(f"http://127.0.0.1:{ПОРТ}/mcp", data=json.dumps(тело).encode("utf-8"), headers=з)
        with urllib.request.urlopen(req, timeout=240) as r:
            return json.loads(r.read().decode("utf-8"))

    def вызов(кнопка, арг):
        if кнопка == "tools/list":
            return {"кнопки": [и["name"] for и in rpc("tools/list")["result"]["tools"]]}
        о = rpc("tools/call", {"name": кнопка, "arguments": арг})
        if "error" in о:
            return {"ok": False, "ошибка_rpc": о["error"]}
        р = о["result"].get("structuredContent") or {"ok": False, "ошибка": о["result"]}
        for м in ((р.get("тема_решена") or {}).get("модель"), (р.get("тема_решена") or {}).get("модель_расход"), р.get("модель")):
            if isinstance(м, dict) and (м.get("токены_in") or м.get("токены_out")):
                расход["sonnet_вызовов"] += 1
                расход["sonnet_in"] += int(м.get("токены_in") or 0)
                расход["sonnet_out"] += int(м.get("токены_out") or 0)
        return р
    try:
        for _ in range(120):
            try:
                rpc("ping")
                break
            except Exception:
                time.sleep(0.5)
        for ш in НАБОР:
            t = time.time()
            выходы = []
            for кнопка, арг in ш["эва"]:
                try:
                    выходы.append({"вызов": [кнопка, арг], "ответ": вызов(кнопка, арг)})
                except Exception as e:
                    выходы.append({"вызов": [кнопка, арг], "сбой": f"{type(e).__name__}: {e}"})
            шаги.append({"№": ш["№"], "выходы": выходы, "мс": int((time.time() - t) * 1000)})
            print(f"эва {ИМЯ} шаг {ш['№']}: {шаги[-1]['мс']} мс", flush=True)
    finally:
        сервер.terminate()
        try:
            сервер.wait(10)
        except Exception:
            сервер.kill()
        _л.close()
    расход["deepseek_вызовов"] = sum(1 for с in io.open(лог, encoding="utf-8", errors="replace") if "Stage 2 LLM" in с)
else:
    е = _env()
    хран = os.path.join(ПАПКА, f"хранилище_mem0_{ИМЯ}")
    shutil.rmtree(хран, ignore_errors=True)
    os.makedirs(хран)
    os.environ.update(MEM0_TELEMETRY="False", MEM0_DIR=os.path.join(хран, "mem0_dir"),
                      ANTHROPIC_API_KEY=е["ANTHROPIC_API_KEY"], OPENAI_API_KEY=е["OPENAI_API_KEY"],
                      ANTHROPIC_BASE_URL="https://api.anthropic.com", OPENAI_BASE_URL="https://api.openai.com/v1")
    import anthropic
    import openai
    _create = anthropic.resources.messages.Messages.create

    def _счёт_create(self, *a, **k):
        r = _create(self, *a, **k)
        у = getattr(r, "usage", None)
        расход["sonnet_вызовов"] += 1
        расход["sonnet_in"] += int(getattr(у, "input_tokens", 0) or 0)
        расход["sonnet_out"] += int(getattr(у, "output_tokens", 0) or 0)
        return r
    anthropic.resources.messages.Messages.create = _счёт_create
    _emb = openai.resources.embeddings.Embeddings.create

    def _счёт_emb(self, *a, **k):
        r = _emb(self, *a, **k)
        расход["emb_токенов"] += int(getattr(getattr(r, "usage", None), "total_tokens", 0) or 0)
        return r
    openai.resources.embeddings.Embeddings.create = _счёт_emb

    from mem0 import Memory
    import mem0
    конфиг = {"llm": {"provider": "anthropic", "config": {"model": "claude-sonnet-5-5"}},
              "embedder": {"provider": "openai", "config": {"model": "text-embedding-3-small"}},
              "vector_store": {"provider": "qdrant", "config": {"path": os.path.join(хран, "qdrant")}},
              "history_db_path": os.path.join(хран, "history.db")}
    m = Memory.from_config(конфиг)
    for ш in НАБОР:
        t = time.time()
        выходы = []
        for оп in ш["mem0"]:
            try:
                if оп[0] == "add":
                    о = m.add([{"role": оп[1], "content": оп[2]}], user_id="oleg")
                elif оп[0] == "search":
                    о = m.search(оп[1], filters={"user_id": "oleg"})
                else:
                    о = m.get_all(filters={"user_id": "oleg"})
                выходы.append({"вызов": list(оп), "ответ": json.loads(json.dumps(о, ensure_ascii=False, default=str))})
            except Exception as e:
                выходы.append({"вызов": list(оп), "сбой": f"{type(e).__name__}: {e}"[:600]})
        шаги.append({"№": ш["№"], "выходы": выходы, "мс": int((time.time() - t) * 1000)})
        print(f"mem0 {ИМЯ} шаг {ш['№']}: {шаги[-1]['мс']} мс" + ("  СБОЙ" if any("сбой" in в for в in выходы) else ""),
              flush=True)
    расход["версия_mem0"] = getattr(mem0, "__version__", "")

расход["usd"] = round((расход["sonnet_in"] * ЦЕНА["sonnet_in"] + расход["sonnet_out"] * ЦЕНА["sonnet_out"]
                       + расход["emb_токенов"] * ЦЕНА["emb"]) / 1_000_000, 4)
итог = {"система": СИСТЕМА, "набор": ИМЯ, "сек": round(time.time() - t0, 1), "расход": расход, "шаги": шаги,
        "когда": time.strftime("%Y-%m-%d %H:%M:%S")}
json.dump(итог, io.open(os.path.join(ПАПКА, f"сырые_{ИМЯ}_{СИСТЕМА}.json"), "w", encoding="utf-8"), ensure_ascii=False,
          indent=1)
print(f"ГОТОВО {СИСТЕМА} {ИМЯ}: {итог['сек']} с, {расход}")
