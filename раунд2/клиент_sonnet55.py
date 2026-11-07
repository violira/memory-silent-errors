# -*- coding: utf-8 -*-
"""Переходник клиента Anthropic для Graphiti 0.31.2 под claude-sonnet-5-5 (решение Олега 07.11.2026, «Переходник»).

Штатный graphiti_core.llm_client.anthropic_client.AnthropicClient с этой моделью не работает по двум причинам, не связанным
с памятью:
  1) шлёт temperature=self.temperature — в SDK anthropic 1.15+ (здесь 2.6.0) такого аргумента у messages.create больше нет,
     вызов падает TypeError ещё до запроса;
  2) шлёт tool_choice={'type': 'tool', 'name': ...} — claude-sonnet-5-5 отвечает 400
     «tool_choice: type "tool" and "any" are not supported for this model».
Переходник — копия AnthropicClient._generate_response слово в слово, кроме двух строк: temperature не передаётся (Graphiti
и так ставит 1 = значение модели по умолчанию) и tool_choice={'type': 'auto'}. Подсказки, схемы, инструмент (один, тот же),
разбор ответа и повторы — её собственные, не тронуты.

Условие Олега к переходнику (07.11.2026): считать вызовы, где модель не вызвала инструмент, и отдельно — те из них, где
Graphiti из-за этого не смогла разобрать ответ (её запасной разбор JSON из текста упал). Счёт — в СЧЁТ ниже, только
подсчёт и короткая запись (stop_reason, виды блоков, начало текста); поведение не меняется."""
import json
import typing

import anthropic
from anthropic.types import MessageParam

from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.config import ModelSize
from graphiti_core.llm_client.errors import RateLimitError, RefusalError
from graphiti_core.prompts.models import Message
from pydantic import BaseModel

СЧЁТ = {"вызовов": 0, "с_инструментом": 0, "без_инструмента": 0, "без_инструмента_разобран_из_текста": 0,
        "без_инструмента_не_разобран": 0, "журнал": []}


class AnthropicClientSonnet55(AnthropicClient):
    async def _generate_response(
        self,
        messages: list[Message],
        response_model: type[BaseModel] | None = None,
        max_tokens: int | None = None,
        model_size: ModelSize = ModelSize.medium,
        *,
        model: str | None = None,
    ) -> tuple[dict[str, typing.Any], int, int]:
        system_message = messages[0]
        user_messages = [{'role': m.role, 'content': m.content} for m in messages[1:]]
        user_messages_cast = typing.cast(list[MessageParam], user_messages)

        effective_model: str = model or self.model
        max_creation_tokens: int = self._resolve_max_tokens(max_tokens, effective_model)

        try:
            tools, _ = self._create_tool(response_model)
            result = await self.client.messages.create(
                system=system_message.content,
                max_tokens=max_creation_tokens,
                # ПЕРЕХОДНИК (1): temperature не передаётся — в SDK нет аргумента, у модели по умолчанию 1.
                messages=user_messages_cast,
                model=effective_model,
                tools=tools,
                tool_choice={'type': 'auto'},  # ПЕРЕХОДНИК (2): было {'type': 'tool', 'name': tool_name}.
            )

            input_tokens = 0
            output_tokens = 0
            if hasattr(result, 'usage') and result.usage:
                input_tokens = getattr(result.usage, 'input_tokens', 0) or 0
                output_tokens = getattr(result.usage, 'output_tokens', 0) or 0

            СЧЁТ['вызовов'] += 1
            for content_item in result.content:
                if content_item.type == 'tool_use':
                    if isinstance(content_item.input, dict):
                        tool_args: dict[str, typing.Any] = content_item.input
                    else:
                        tool_args = json.loads(str(content_item.input))
                    СЧЁТ['с_инструментом'] += 1
                    return tool_args, input_tokens, output_tokens

            # Модель не вызвала инструмент — дальше её же запасной разбор, только со счётом (условие Олега).
            СЧЁТ['без_инструмента'] += 1
            запись = {'инструмент': tools[0]['name'] if tools else '', 'stop_reason': result.stop_reason,
                      'блоки': [б.type for б in result.content],
                      'текст': next((б.text for б in result.content if б.type == 'text'), '')[:300]}
            СЧЁТ['журнал'].append(запись)
            try:
                for content_item in result.content:
                    if content_item.type == 'text':
                        разобрано = self._extract_json_from_text(content_item.text)
                        СЧЁТ['без_инструмента_разобран_из_текста'] += 1
                        запись['разобран'] = True
                        return (
                            разобрано,
                            input_tokens,
                            output_tokens,
                        )
                    else:
                        raise ValueError(
                            f'Could not extract structured data from model response: {result.content}'
                        )

                raise ValueError(
                    f'Could not extract structured data from model response: {result.content}'
                )
            except ValueError:
                СЧЁТ['без_инструмента_не_разобран'] += 1
                запись['разобран'] = False
                raise

        except anthropic.RateLimitError as e:
            raise RateLimitError(f'Rate limit exceeded. Please try again later. Error: {e}') from e
        except anthropic.APIError as e:
            if 'refused to respond' in str(e).lower():
                raise RefusalError(str(e)) from e
            raise e
        except Exception as e:
            raise e
