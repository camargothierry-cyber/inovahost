"""
Camada de integração com os modelos de IA.

Todos os agentes fornecidos (GLM, Step-3.7, MiniMax, Mistral) são
servidos pelo mesmo endpoint compatível com a API da OpenAI
(https://integrate.api.nvidia.com/v1/chat/completions), então um único
adaptador consegue falar com qualquer um deles - a diferença entre eles
é só o modelo, a chave de API e os parâmetros extras (temperature,
top_p, reasoning_effort etc.), que ficam guardados por agente no banco.
"""
import json
import os

import requests

REQUEST_TIMEOUT = 120


class AgentCallError(Exception):
    pass


def get_api_key(agent: dict) -> str:
    if agent.get("api_key_env"):
        key = os.getenv(agent["api_key_env"], "")
        if key:
            return key
    if agent.get("api_key"):
        return agent["api_key"]
    raise AgentCallError(
        f"Nenhuma chave de API configurada para '{agent['display_name']}'. "
        f"Defina {agent.get('api_key_env') or 'a chave'} no arquivo .env ou edite o agente."
    )


def build_payload(agent: dict, messages: list) -> dict:
    extra = {}
    if agent.get("extra_params"):
        try:
            extra = json.loads(agent["extra_params"])
        except json.JSONDecodeError:
            extra = {}
    return {"model": agent["model"], "messages": messages, **extra}


def call_agent_blocking(agent: dict, messages: list) -> requests.Response:
    """Chamada síncrona (não-streaming), usada pela ponte multi-IA."""
    api_key = get_api_key(agent)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    payload = build_payload(agent, messages)
    payload["stream"] = False
    try:
        resp = requests.post(
            agent.get("base_url") or "https://integrate.api.nvidia.com/v1/chat/completions",
            headers=headers, json=payload, timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as e:
        raise AgentCallError(f"Falha de rede ao chamar {agent['display_name']}: {e}") from e

    if resp.status_code >= 400:
        raise AgentCallError(
            f"{agent['display_name']} retornou erro {resp.status_code}: {resp.text[:300]}"
        )
    return resp


def extract_content(response_json: dict) -> str:
    try:
        content = response_json["choices"][0]["message"]["content"]
        return content or ""
    except (KeyError, IndexError, TypeError):
        return ""


def call_agent_stream(agent: dict, messages: list):
    """Chamada em streaming (SSE) para o chat individual de um agente."""
    api_key = get_api_key(agent)
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
    }
    payload = build_payload(agent, messages)
    payload["stream"] = True
    try:
        resp = requests.post(
            agent.get("base_url") or "https://integrate.api.nvidia.com/v1/chat/completions",
            headers=headers, json=payload, timeout=REQUEST_TIMEOUT, stream=True,
        )
    except requests.RequestException as e:
        raise AgentCallError(f"Falha de rede ao chamar {agent['display_name']}: {e}") from e

    if resp.status_code >= 400:
        raise AgentCallError(
            f"{agent['display_name']} retornou erro {resp.status_code}: {resp.text[:300]}"
        )
    return resp


def iter_stream_deltas(resp: requests.Response):
    """
    Gerador que devolve tuplas (tipo, texto) a partir de uma resposta SSE:
    tipo é 'content' para o texto normal ou 'reasoning' para o raciocínio
    (alguns modelos de raciocínio expõem 'reasoning_content' no delta).
    """
    for line in resp.iter_lines():
        if not line:
            continue
        line = line.decode("utf-8", errors="ignore")
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            continue
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        reasoning = delta.get("reasoning_content")
        if reasoning:
            yield ("reasoning", reasoning)
        content = delta.get("content")
        if content:
            yield ("content", content)
