# -*- coding: utf-8 -*-
"""Прогон Graphiti на одном наборе: py -3.11 прогон_graphiti.py А|Б|В|проба → сырые_<набор>_graphiti.json.

Условия (СР2, те же, что у Mem0 в 1-м раунде): graphiti-core 0.31.2 по умолчанию, её подсказки не тронуты; LLM —
claude-sonnet-5-5 (model и small_model) через переходник клиента (клиент_sonnet55.py — см. там почему); векторы — OpenAI
text-embedding-3-small (её OpenAIEmbedder, размерность по умолчанию); переранжировщик — её по умолчанию (OpenAIRerankerClient,
в обычном поиске не вызывается, вызовы считаются ниже); хранилище — Neo4j Desktop (локальная база, Bolt; выбор Олега
07.11.2026 после поломок встроенного Kuzu — см. прогон_graphiti_kuzu.py и отчёт2.md), перед каждым набором база очищается
её же clear_data и индексы строятся её же build_indices_and_constraints; группа "oleg" (как user_id у Mem0);
телеметрия выключена (GRAPHITI_TELEMETRY_ENABLED=false).
Перевод шагов — из строки mem0 набора, один в один: сообщение пользователя → эпизод «Олег: …», ассистента → «Эва: …»
(EpisodeType.message, каждая фраза — отдельный эпизод, reference_time = день, когда сказано: А и Б — 19.10.2026, В —
26.10.2026; часы — 09:00 UTC + № шага в минутах, чтобы порядок эпизодов совпадал с порядком шагов); search → её обычный
graphiti.search(вопрос как есть); get_all («что поменялось сегодня») → все факты группы EntityEdge.get_by_group_ids —
ближайшее к get_all у Mem0 (своей кнопки «что поменялось» у Graphiti нет).
Ключи — из C:\\EVA_MEMORY\\.env (API) и graphiti\\.env (адрес и пароль Neo4j) в память процесса, не печатаются и никуда
не пишутся. Адреса API заданы явно.
Расход считается обёрткой над create SDK — только счёт токенов, поведение не меняется."""
import asyncio
import io
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta, timezone

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ПАПКА = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ПАПКА)
sys.path.insert(0, os.path.dirname(ПАПКА))

ИМЯ = sys.argv[1]
ЦЕНА = {"sonnet_in": 2.0, "sonnet_out": 10.0, "emb": 0.02}   # $ за 1 млн токенов (Sonnet 5.5; text-embedding-3-small)
ПОТОЛОК_Б = 3.0   # условие Олега: если расход Graphiti на Б больше $3 — остановиться и доложить


def _env(путь=r"C:\EVA_MEMORY\.env"):
    из = {}
    for с in io.open(путь, encoding="utf-8-sig", errors="ignore").read().splitlines():
        с = с.strip()
        if с and not с.startswith("#") and "=" in с:
            к, _, з = с.partition("=")
            из[к.strip()] = з.strip().strip('"').strip("'")
    return из


if ИМЯ == "проба":
    НАБОР = [{"№": 1, "mem0": [("add", "user", "пробная запись: Нина берёт за подшив брюк 320 крон")]},
             {"№": 2, "mem0": [("search", "сколько Нина берёт за подшив?")]},
             {"№": 3, "mem0": [("get_all",)]}]
    ДЕНЬ = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
elif ИМЯ == "В":
    import набор_В
    НАБОР, ДЕНЬ = набор_В.В, datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)
else:
    import наборы
    НАБОР, ДЕНЬ = (наборы.А if ИМЯ == "А" else наборы.Б), datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)

е = _env()
н4 = _env(os.path.join(ПАПКА, ".env"))
os.environ.update(GRAPHITI_TELEMETRY_ENABLED="false", ANTHROPIC_API_KEY=е["ANTHROPIC_API_KEY"],
                  OPENAI_API_KEY=е["OPENAI_API_KEY"], ANTHROPIC_BASE_URL="https://api.anthropic.com",
                  OPENAI_BASE_URL="https://api.openai.com/v1")

import logging  # noqa: E402
import anthropic  # noqa: E402
import openai  # noqa: E402

# Предупреждения сервера Neo4j (устаревший db.index.fulltext.*, нет свойства reference_time) — только шум в логе; поведение
# не меняется
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

расход = {"sonnet_вызовов": 0, "sonnet_in": 0, "sonnet_out": 0, "sonnet_сбоев": 0, "emb_вызовов": 0, "emb_токенов": 0,
          "openai_chat_вызовов": 0, "usd": 0.0}


def _usd():
    return round((расход["sonnet_in"] * ЦЕНА["sonnet_in"] + расход["sonnet_out"] * ЦЕНА["sonnet_out"]
                  + расход["emb_токенов"] * ЦЕНА["emb"]) / 1_000_000, 4)


_create = anthropic.resources.messages.AsyncMessages.create


async def _счёт_create(self, *a, **k):
    try:
        r = await _create(self, *a, **k)
    except Exception:
        расход["sonnet_сбоев"] += 1
        raise
    у = getattr(r, "usage", None)
    расход["sonnet_вызовов"] += 1
    расход["sonnet_in"] += int(getattr(у, "input_tokens", 0) or 0)
    расход["sonnet_out"] += int(getattr(у, "output_tokens", 0) or 0)
    return r
anthropic.resources.messages.AsyncMessages.create = _счёт_create
_emb = openai.resources.embeddings.AsyncEmbeddings.create


async def _счёт_emb(self, *a, **k):
    r = await _emb(self, *a, **k)
    расход["emb_вызовов"] += 1
    расход["emb_токенов"] += int(getattr(getattr(r, "usage", None), "total_tokens", 0) or 0)
    return r
openai.resources.embeddings.AsyncEmbeddings.create = _счёт_emb
_chat = openai.resources.chat.completions.AsyncCompletions.create


async def _счёт_chat(self, *a, **k):   # переранжировщик Graphiti (gpt-4.1-nano) — в обычном поиске его быть не должно
    расход["openai_chat_вызовов"] += 1
    return await _chat(self, *a, **k)
openai.resources.chat.completions.AsyncCompletions.create = _счёт_chat

import graphiti_core  # noqa: E402
from graphiti_core import Graphiti  # noqa: E402
from graphiti_core.driver.neo4j_driver import Neo4jDriver  # noqa: E402
from graphiti_core.edges import EntityEdge  # noqa: E402
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig  # noqa: E402
from graphiti_core.errors import GroupsEdgesNotFoundError  # noqa: E402
from graphiti_core.llm_client.config import LLMConfig  # noqa: E402
from graphiti_core.nodes import EpisodeType  # noqa: E402
from graphiti_core.utils.maintenance.graph_data_operations import clear_data  # noqa: E402
from клиент_sonnet55 import СЧЁТ, AnthropicClientSonnet55  # noqa: E402
from importlib.metadata import version as _версия  # noqa: E402

МОДЕЛЬ = "claude-sonnet-5-5"
ПОРОГ_ОБВЯЗКИ_Б = 0.05   # условие Олега: если на Б неразобранных вызовов без инструмента больше 5% — стоп до набора А
_ПОЛЯ_СЧЁТА = ("вызовов", "с_инструментом", "без_инструмента", "без_инструмента_разобран_из_текста",
               "без_инструмента_не_разобран")
ГРУППА = "oleg"
ИМЕНА = {}   # uuid сущности → имя (для читаемости сырых данных)


def _д(x):
    return x.isoformat() if isinstance(x, datetime) else x


def _ребро(р):
    return {"uuid": р.uuid, "name": р.name, "fact": р.fact, "valid_at": _д(р.valid_at), "invalid_at": _д(р.invalid_at),
            "expired_at": _д(р.expired_at), "created_at": _д(р.created_at), "reference_time": _д(р.reference_time),
            "от": ИМЕНА.get(р.source_node_uuid, р.source_node_uuid), "к": ИМЕНА.get(р.target_node_uuid, р.target_node_uuid),
            "episodes": list(р.episodes or []), "attributes": р.attributes or {}}


async def main():
    драйвер = Neo4jDriver(uri=н4.get("NEO4J_URI", "bolt://localhost:7687"), user=н4.get("NEO4J_USER", "neo4j"),
                          password=н4["NEO4J_PASSWORD"], database=н4.get("NEO4J_DATABASE", "neo4j"))
    версия_neo4j = await драйвер.execute_query("CALL dbms.components() YIELD name, versions, edition "
                                               "RETURN name, versions, edition")
    версия_neo4j = [dict(r) for r in версия_neo4j[0]]
    await clear_data(драйвер)   # свежая база на набор — её же функцией
    ллм = AnthropicClientSonnet55(
        config=LLMConfig(api_key=е["ANTHROPIC_API_KEY"], model=МОДЕЛЬ, small_model=МОДЕЛЬ,
                         base_url="https://api.anthropic.com"),
        client=anthropic.AsyncAnthropic(api_key=е["ANTHROPIC_API_KEY"], base_url="https://api.anthropic.com",
                                        max_retries=1))   # max_retries=1 — как в её AnthropicClient
    вектора = OpenAIEmbedder(OpenAIEmbedderConfig(api_key=е["OPENAI_API_KEY"], embedding_model="text-embedding-3-small",
                                                  base_url="https://api.openai.com/v1"))
    г = Graphiti(graph_driver=драйвер, llm_client=ллм, embedder=вектора)
    await г.build_indices_and_constraints()
    шаги, t0, стоп = [], time.time(), ""
    try:
        for ш in НАБОР:
            t = time.time()
            до = {к: СЧЁТ[к] for к in _ПОЛЯ_СЧЁТА}
            до_журнала = len(СЧЁТ["журнал"])
            выходы = []
            for оп in ш["mem0"]:
                try:
                    if оп[0] == "add":
                        текст = ("Олег: " if оп[1] == "user" else "Эва: ") + оп[2]
                        когда = ДЕНЬ + timedelta(minutes=ш["№"])
                        вызов = ["add_episode", текст, когда.isoformat()]
                        р = await г.add_episode(name=f"шаг {ш['№']}", episode_body=текст,
                                                source_description="разговор Олега и Эвы", reference_time=когда,
                                                source=EpisodeType.message, group_id=ГРУППА)
                        for у in р.nodes:
                            ИМЕНА[у.uuid] = у.name
                        ответ = {"episode": {"uuid": р.episode.uuid, "content": р.episode.content,
                                             "valid_at": _д(р.episode.valid_at)},
                                 "nodes": [{"uuid": у.uuid, "name": у.name, "labels": у.labels, "summary": у.summary,
                                            "attributes": у.attributes or {}} for у in р.nodes],
                                 "edges": [_ребро(x) for x in р.edges]}
                    elif оп[0] == "search":
                        вызов = ["search", оп[1]]
                        ответ = {"edges": [_ребро(x) for x in await г.search(оп[1], group_ids=[ГРУППА])]}
                    else:
                        вызов = ["get_by_group_ids", [ГРУППА]]
                        try:
                            все = await EntityEdge.get_by_group_ids(драйвер, [ГРУППА])
                        except GroupsEdgesNotFoundError:
                            все = []
                        ответ = {"edges": [_ребро(x) for x in все]}
                    выходы.append({"вызов": вызов, "ответ": ответ})
                except Exception as e:
                    выходы.append({"вызов": list(оп), "сбой": f"{type(e).__name__}: {e}"[:600],
                                   "след": traceback.format_exc()[-1500:]})
            обвязка = {к: СЧЁТ[к] - до[к] for к in _ПОЛЯ_СЧЁТА}
            обвязка["журнал"] = СЧЁТ["журнал"][до_журнала:]
            обвязка["сбой_обвязки"] = обвязка["без_инструмента_не_разобран"] > 0
            шаги.append({"№": ш["№"], "выходы": выходы, "мс": int((time.time() - t) * 1000), "обвязка": обвязка})
            расход["usd"] = _usd()
            print(f"graphiti {ИМЯ} шаг {ш['№']}: {шаги[-1]['мс']} мс, итого ${расход['usd']}"
                  + (f", без инструмента {обвязка['без_инструмента']} (не разобрано {обвязка['без_инструмента_не_разобран']})"
                     if обвязка["без_инструмента"] else "")
                  + ("  СБОЙ" if any("сбой" in в for в in выходы) else ""), flush=True)
            if ИМЯ == "Б" and расход["usd"] > ПОТОЛОК_Б:
                стоп = f"остановлено после шага {ш['№']}: расход ${расход['usd']} > ${ПОТОЛОК_Б} (условие Олега)"
                print(стоп, flush=True)
                break
    finally:
        await г.close()
    расход["usd"] = _usd()
    обвязка = {к: СЧЁТ[к] for к in _ПОЛЯ_СЧЁТА}
    обвязка["доля_не_разобрано"] = round(обвязка["без_инструмента_не_разобран"] / обвязка["вызовов"], 4) if обвязка["вызовов"] else 0
    обвязка["доля_без_инструмента"] = round(обвязка["без_инструмента"] / обвязка["вызовов"], 4) if обвязка["вызовов"] else 0
    обвязка["шагов_со_сбоем_обвязки"] = [ш["№"] for ш in шаги if ш["обвязка"]["сбой_обвязки"]]
    стоп_обвязки = ""
    if ИМЯ == "Б" and обвязка["доля_не_разобрано"] > ПОРОГ_ОБВЯЗКИ_Б:
        стоп_обвязки = (f"СТОП до набора А: неразобранных вызовов без инструмента {обвязка['без_инструмента_не_разобран']}"
                        f" из {обвязка['вызовов']} ({обвязка['доля_не_разобрано']:.1%}) > 5% (условие Олега)")
        print(стоп_обвязки, flush=True)
    итог = {"система": "graphiti", "набор": ИМЯ, "сек": round(time.time() - t0, 1), "расход": расход, "шаги": шаги,
            "стоп": стоп, "обвязка": обвязка, "стоп_обвязки": стоп_обвязки,
            "версии": {п: _версия(п) for п in ("graphiti-core", "anthropic", "openai", "neo4j")},
            "хранилище": "Neo4j Desktop (локально, Bolt)", "версия_neo4j": версия_neo4j, "модель": МОДЕЛЬ,
            "когда": time.strftime("%Y-%m-%d %H:%M:%S")}
    json.dump(итог, io.open(os.path.join(ПАПКА, f"сырые_{ИМЯ}_graphiti.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1, default=str)
    print(f"ГОТОВО graphiti {ИМЯ}: {итог['сек']} с, {расход}" + (f" · {стоп}" if стоп else ""))


asyncio.run(main())
