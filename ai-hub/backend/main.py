"""
AI Hub - backend FastAPI.

Serve a interface estática (frontend/) e expõe a API em /api/*.
Rode com:  uvicorn main:app --reload --port 8000
"""
import json
import os
import re
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import ai_engine
import bridge as bridge_engine
from auth import (
    SESSION_COOKIE,
    create_session,
    destroy_session,
    get_current_user,
    hash_password,
    require_admin,
    verify_password,
)
from database import NVIDIA_DEFAULT_URL, get_db, init_db

init_db()

app = FastAPI(title="AI Hub")

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-_]{1,30}$")


# ---------------------------------------------------------------------------
# Modelos de request
# ---------------------------------------------------------------------------
class RegisterBody(BaseModel):
    username: str
    password: str


class LoginBody(BaseModel):
    username: str
    password: str


class ChatBody(BaseModel):
    conversation_id: int | None = None
    message: str
    image_data_url: str | None = None


class AgentCreateBody(BaseModel):
    slug: str
    display_name: str
    model: str
    api_key: str
    base_url: str | None = None
    supports_vision: bool = False
    color: str = "#8B8FA3"
    temperature: float = 1.0
    top_p: float = 1.0
    max_tokens: int = 8192
    reasoning_effort: str | None = None


class AgentUpdateBody(BaseModel):
    display_name: str | None = None
    model: str | None = None
    api_key: str | None = None
    base_url: str | None = None
    supports_vision: bool | None = None
    color: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None


class BridgeStartBody(BaseModel):
    agent_slugs: list[str]
    topic: str
    rounds: int = 2


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def agent_public_dict(row) -> dict:
    d = dict(row)
    has_key = bool(d.get("api_key")) or bool(d.get("api_key_env") and os.getenv(d.get("api_key_env"), ""))
    d.pop("api_key", None)
    d.pop("api_key_env", None)
    d["has_api_key"] = has_key
    try:
        d["extra_params"] = json.loads(d.get("extra_params") or "{}")
    except json.JSONDecodeError:
        d["extra_params"] = {}
    d["supports_vision"] = bool(d["supports_vision"])
    return d


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.post("/api/auth/register")
def register(body: RegisterBody, response: Response):
    username = body.username.strip()
    if not (3 <= len(username) <= 30):
        raise HTTPException(400, "Usuário deve ter entre 3 e 30 caracteres")
    if len(body.password) < 6:
        raise HTTPException(400, "Senha deve ter ao menos 6 caracteres")

    with get_db() as conn:
        existing = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise HTTPException(400, "Esse usuário já existe")
        is_first_user = conn.execute("SELECT COUNT(*) c FROM users").fetchone()["c"] == 0
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
            (username, hash_password(body.password), int(is_first_user)),
        )
        user_id = cur.lastrowid

    token = create_session(user_id)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"id": user_id, "username": username, "is_admin": is_first_user}


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (body.username.strip(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Usuário ou senha inválidos")

    token = create_session(row["id"])
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        destroy_session(token)
    response.delete_cookie(SESSION_COOKIE)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return user


# ---------------------------------------------------------------------------
# Agentes
# ---------------------------------------------------------------------------
@app.get("/api/agents")
def list_agents(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM agents ORDER BY created_at").fetchall()
    return [agent_public_dict(r) for r in rows]


@app.post("/api/agents")
def create_agent(body: AgentCreateBody, user: dict = Depends(require_admin)):
    slug = body.slug.strip().lower()
    if not SLUG_RE.match(slug):
        raise HTTPException(400, "Identificador inválido: use letras minúsculas, números, - ou _ (2 a 31 caracteres)")
    if not body.display_name.strip() or not body.model.strip():
        raise HTTPException(400, "Nome e modelo são obrigatórios")
    if not body.api_key.strip():
        raise HTTPException(400, "Informe a chave de API do agente")

    extra = {"temperature": body.temperature, "top_p": body.top_p, "max_tokens": body.max_tokens}
    if body.reasoning_effort:
        extra["reasoning_effort"] = body.reasoning_effort

    with get_db() as conn:
        if conn.execute("SELECT slug FROM agents WHERE slug = ?", (slug,)).fetchone():
            raise HTTPException(400, "Já existe um agente com esse identificador")
        conn.execute(
            """INSERT INTO agents (slug, display_name, model, base_url, api_key, supports_vision, color, extra_params)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                slug, body.display_name.strip(), body.model.strip(),
                (body.base_url or NVIDIA_DEFAULT_URL).strip(),
                body.api_key.strip(), int(body.supports_vision), body.color, json.dumps(extra),
            ),
        )
        row = conn.execute("SELECT * FROM agents WHERE slug = ?", (slug,)).fetchone()
    return agent_public_dict(row)


@app.put("/api/agents/{slug}")
def update_agent(slug: str, body: AgentUpdateBody, user: dict = Depends(require_admin)):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM agents WHERE slug = ?", (slug,)).fetchone()
        if not row:
            raise HTTPException(404, "Agente não encontrado")
        agent = dict(row)
        try:
            extra = json.loads(agent["extra_params"] or "{}")
        except json.JSONDecodeError:
            extra = {}

        if body.temperature is not None:
            extra["temperature"] = body.temperature
        if body.top_p is not None:
            extra["top_p"] = body.top_p
        if body.max_tokens is not None:
            extra["max_tokens"] = body.max_tokens
        if body.reasoning_effort is not None:
            extra["reasoning_effort"] = body.reasoning_effort

        conn.execute(
            """UPDATE agents SET display_name = ?, model = ?, base_url = ?,
                   api_key = COALESCE(?, api_key), supports_vision = ?, color = ?, extra_params = ?
               WHERE slug = ?""",
            (
                (body.display_name or agent["display_name"]).strip(),
                (body.model or agent["model"]).strip(),
                (body.base_url or agent["base_url"]).strip(),
                body.api_key.strip() if body.api_key else None,
                int(body.supports_vision) if body.supports_vision is not None else agent["supports_vision"],
                body.color or agent["color"],
                json.dumps(extra),
                slug,
            ),
        )
        updated = conn.execute("SELECT * FROM agents WHERE slug = ?", (slug,)).fetchone()
    return agent_public_dict(updated)


@app.delete("/api/agents/{slug}")
def delete_agent(slug: str, user: dict = Depends(require_admin)):
    with get_db() as conn:
        if not conn.execute("SELECT slug FROM agents WHERE slug = ?", (slug,)).fetchone():
            raise HTTPException(404, "Agente não encontrado")
        conn.execute("DELETE FROM agents WHERE slug = ?", (slug,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Chat com um único agente (streaming SSE)
# ---------------------------------------------------------------------------
@app.post("/api/agents/{slug}/chat")
def chat_with_agent(slug: str, body: ChatBody, user: dict = Depends(get_current_user)):
    message = body.message.strip()
    if not message:
        raise HTTPException(400, "Mensagem vazia")

    with get_db() as conn:
        agent_row = conn.execute("SELECT * FROM agents WHERE slug = ?", (slug,)).fetchone()
        if not agent_row:
            raise HTTPException(404, "Agente não encontrado")
        agent = dict(agent_row)

        conv_id = body.conversation_id
        if conv_id:
            conv = conn.execute(
                "SELECT id FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"])
            ).fetchone()
            if not conv:
                raise HTTPException(404, "Conversa não encontrada")
        else:
            cur = conn.execute(
                "INSERT INTO conversations (user_id, mode, agent_slugs, title) VALUES (?, 'single', ?, ?)",
                (user["id"], json.dumps([slug]), message[:60]),
            )
            conv_id = cur.lastrowid

        conn.execute(
            "INSERT INTO messages (conversation_id, role, agent_slug, content, image_data_url) VALUES (?, 'user', NULL, ?, ?)",
            (conv_id, message, body.image_data_url),
        )
        history_rows = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id", (conv_id,)
        ).fetchall()

    api_messages = [
        {"role": ("assistant" if r["role"] == "agent" else "user"), "content": r["content"]}
        for r in history_rows
    ]

    if body.image_data_url and agent["supports_vision"]:
        api_messages[-1] = {
            "role": "user",
            "content": [
                {"type": "text", "text": message},
                {"type": "image_url", "image_url": {"url": body.image_data_url}},
            ],
        }

    def event_stream():
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        try:
            resp = ai_engine.call_agent_stream(agent, api_messages)
            for kind, text in ai_engine.iter_stream_deltas(resp):
                if kind == "reasoning":
                    reasoning_parts.append(text)
                    yield sse({"type": "reasoning", "text": text})
                else:
                    content_parts.append(text)
                    yield sse({"type": "content", "text": text})
        except ai_engine.AgentCallError as e:
            yield sse({"type": "error", "text": str(e)})
        except Exception as e:  # noqa: BLE001 - queremos sempre informar o front-end
            yield sse({"type": "error", "text": f"Erro inesperado: {e}"})

        final_content = "".join(content_parts)
        final_reasoning = "".join(reasoning_parts) or None
        if final_content:
            with get_db() as conn2:
                conn2.execute(
                    "INSERT INTO messages (conversation_id, role, agent_slug, content, reasoning) VALUES (?, 'agent', ?, ?, ?)",
                    (conv_id, slug, final_content, final_reasoning),
                )
        yield sse({"type": "done", "conversation_id": conv_id})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Conversas / histórico
# ---------------------------------------------------------------------------
@app.get("/api/conversations")
def list_conversations(agent_slug: str | None = None, mode: str | None = None, user: dict = Depends(get_current_user)):
    query = "SELECT id, mode, agent_slugs, title, created_at FROM conversations WHERE user_id = ?"
    params: list = [user["id"]]
    if mode:
        query += " AND mode = ?"
        params.append(mode)
    if agent_slug:
        query += " AND agent_slugs LIKE ?"
        params.append(f'%"{agent_slug}"%')
    query += " ORDER BY id DESC"

    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [{**dict(r), "agent_slugs": json.loads(r["agent_slugs"])} for r in rows]


@app.get("/api/conversations/{conv_id}/messages")
def get_conversation_messages(conv_id: int, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        conv = conn.execute(
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"])
        ).fetchone()
        if not conv:
            raise HTTPException(404, "Conversa não encontrada")
        rows = conn.execute(
            "SELECT id, role, agent_slug, content, reasoning, image_data_url, created_at FROM messages WHERE conversation_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()
    return {
        "conversation": {**dict(conv), "agent_slugs": json.loads(conv["agent_slugs"])},
        "messages": [dict(r) for r in rows],
    }


@app.delete("/api/conversations/{conv_id}")
def delete_conversation(conv_id: int, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        conv = conn.execute(
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user["id"])
        ).fetchone()
        if not conv:
            raise HTTPException(404, "Conversa não encontrada")
        conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Ponte multi-IA (streaming SSE)
# ---------------------------------------------------------------------------
@app.post("/api/bridge/start")
def start_bridge(body: BridgeStartBody, user: dict = Depends(get_current_user)):
    slugs = list(dict.fromkeys(s.strip() for s in body.agent_slugs if s.strip()))
    if len(slugs) < 2:
        raise HTTPException(400, "Selecione ao menos 2 agentes para a ponte")
    if len(slugs) > 6:
        raise HTTPException(400, "Selecione no máximo 6 agentes")

    rounds = max(1, min(body.rounds, 5))
    topic = body.topic.strip()
    if not topic:
        raise HTTPException(400, "Informe um tópico para iniciar a ponte")

    with get_db() as conn:
        placeholders = ",".join("?" * len(slugs))
        rows = conn.execute(f"SELECT * FROM agents WHERE slug IN ({placeholders})", slugs).fetchall()
        agents_by_slug = {r["slug"]: dict(r) for r in rows}
        missing = [s for s in slugs if s not in agents_by_slug]
        if missing:
            raise HTTPException(404, f"Agente(s) não encontrado(s): {', '.join(missing)}")

        cur = conn.execute(
            "INSERT INTO conversations (user_id, mode, agent_slugs, title) VALUES (?, 'bridge', ?, ?)",
            (user["id"], json.dumps(slugs), f"Ponte: {topic[:50]}"),
        )
        conv_id = cur.lastrowid
        conn.execute(
            "INSERT INTO messages (conversation_id, role, agent_slug, content) VALUES (?, 'user', NULL, ?)",
            (conv_id, topic),
        )

    def event_stream():
        transcript = [{"speaker": user["username"], "agent_slug": None, "content": topic}]
        yield sse({"type": "start", "conversation_id": conv_id})

        for round_num in range(rounds):
            for s in slugs:
                agent = agents_by_slug[s]
                api_messages = bridge_engine.build_messages_for_turn(transcript, s)
                try:
                    resp = ai_engine.call_agent_blocking(agent, api_messages)
                    reply = ai_engine.extract_content(resp.json()) or "(sem resposta)"
                except ai_engine.AgentCallError as e:
                    reply = f"[erro: {e}]"
                except Exception as e:  # noqa: BLE001
                    reply = f"[erro inesperado: {e}]"

                transcript.append({"speaker": agent["display_name"], "agent_slug": s, "content": reply})
                with get_db() as conn2:
                    conn2.execute(
                        "INSERT INTO messages (conversation_id, role, agent_slug, content) VALUES (?, 'agent', ?, ?)",
                        (conv_id, s, reply),
                    )
                yield sse({
                    "type": "turn", "round": round_num, "agent_slug": s,
                    "display_name": agent["display_name"], "color": agent["color"], "content": reply,
                })
        yield sse({"type": "done", "conversation_id": conv_id})

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Frontend estático
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))
