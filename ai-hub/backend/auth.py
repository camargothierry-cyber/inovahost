"""
Autenticação simples baseada em sessão (sem JWT).

Cada login gera um token aleatório opaco, guardado na tabela `sessions`
e enviado ao navegador como cookie httpOnly. Isso evita qualquer segredo
de assinatura no servidor: para invalidar uma sessão basta apagar a
linha correspondente no banco.
"""
import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request

from database import get_db

SESSION_COOKIE = "session_token"
SESSION_MAX_AGE_DAYS = 30


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_session(user_id: int) -> str:
    token = secrets.token_hex(32)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id)
        )
    return token


def destroy_session(token: str):
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def _session_is_expired(created_at: str) -> bool:
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return True
    return datetime.utcnow() - created > timedelta(days=SESSION_MAX_AGE_DAYS)


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Não autenticado")

    with get_db() as conn:
        row = conn.execute(
            """
            SELECT sessions.token, sessions.created_at as session_created_at,
                   users.id, users.username, users.is_admin
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token = ?
            """,
            (token,),
        ).fetchone()

        if not row:
            raise HTTPException(status_code=401, detail="Sessão inválida")

        if _session_is_expired(row["session_created_at"]):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            raise HTTPException(status_code=401, detail="Sessão expirada")

    return {"id": row["id"], "username": row["username"], "is_admin": bool(row["is_admin"])}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Apenas administradores podem fazer isso")
    return user
