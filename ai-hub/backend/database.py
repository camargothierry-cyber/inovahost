"""
Camada de banco de dados (SQLite).

Guarda usuários, sessões de login, agentes de IA configurados e o
histórico de conversas de cada usuário. Usamos sqlite3 puro (sem ORM)
para manter o projeto fácil de auditar e sem dependências extras.
"""
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "app_data.db"

NVIDIA_DEFAULT_URL = "https://integrate.api.nvidia.com/v1/chat/completions"

# Agentes pré-configurados a partir dos scripts fornecidos.
# `api_key_env` aponta para uma variável no arquivo .env. Agentes
# adicionados depois pela interface (admin) usam a coluna `api_key` no
# lugar (veja get_api_key em ai_engine.py).
DEFAULT_AGENTS = [
    {
        "slug": "glm",
        "display_name": "GLM-5.2",
        "model": "z-ai/glm-5.2",
        "api_key_env": "NVIDIA_API_KEY_GLM",
        "supports_vision": 0,
        "color": "#B794F6",
        "extra_params": json.dumps({"temperature": 1.0, "top_p": 1.0, "max_tokens": 16384}),
    },
    {
        "slug": "step3",
        "display_name": "Step-3.7 Flash",
        "model": "stepfun-ai/step-3.7-flash",
        "api_key_env": "NVIDIA_API_KEY_STEP3",
        "supports_vision": 1,
        "color": "#4FD1C5",
        "extra_params": json.dumps({"temperature": 1.0, "top_p": 0.95, "max_tokens": 16384}),
    },
    {
        "slug": "minimax",
        "display_name": "MiniMax M3",
        "model": "minimaxai/minimax-m3",
        "api_key_env": "NVIDIA_API_KEY_MINIMAX",
        "supports_vision": 1,
        "color": "#F6AD55",
        "extra_params": json.dumps({"temperature": 1.0, "top_p": 0.95, "max_tokens": 8192}),
    },
    {
        "slug": "mistral",
        "display_name": "Mistral Medium 3.5",
        "model": "mistralai/mistral-medium-3.5-128b",
        "api_key_env": "NVIDIA_API_KEY_MISTRAL",
        "supports_vision": 0,
        "color": "#68D391",
        "extra_params": json.dumps({
            "temperature": 0.70, "top_p": 1.0, "max_tokens": 16384, "reasoning_effort": "high"
        }),
    },
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS agents (
                slug TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                model TEXT NOT NULL,
                base_url TEXT NOT NULL DEFAULT 'https://integrate.api.nvidia.com/v1/chat/completions',
                api_key_env TEXT,
                api_key TEXT,
                supports_vision INTEGER NOT NULL DEFAULT 0,
                color TEXT NOT NULL DEFAULT '#8B8FA3',
                extra_params TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                mode TEXT NOT NULL DEFAULT 'single',
                agent_slugs TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT 'Nova conversa',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                agent_slug TEXT,
                content TEXT NOT NULL,
                reasoning TEXT,
                image_data_url TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_user ON conversations(user_id);
            CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
            CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
            """
        )

        existing = conn.execute("SELECT COUNT(*) c FROM agents").fetchone()["c"]
        if existing == 0:
            for agent in DEFAULT_AGENTS:
                conn.execute(
                    """
                    INSERT INTO agents
                        (slug, display_name, model, base_url, api_key_env, supports_vision, color, extra_params)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent["slug"],
                        agent["display_name"],
                        agent["model"],
                        NVIDIA_DEFAULT_URL,
                        agent["api_key_env"],
                        agent["supports_vision"],
                        agent["color"],
                        agent["extra_params"],
                    ),
                )
