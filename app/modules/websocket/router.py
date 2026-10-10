import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.database import AsyncSessionLocal
from app.modules.auth.dependencies import get_current_user_from_token
from app.modules.projects.manager import project_manager
from app.modules.websocket.manager import manager

router = APIRouter()


@router.websocket("/global")
async def global_websocket_endpoint(
    websocket: WebSocket,
    token: str | None = None,
):
    """
    Global WebSocket endpoint for real-time app-wide notifications.
    Auth: Pass JWT access token via ?token= query param.
    Receives: personal notifications (not project specific).
    """
    await websocket.accept()
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return

    async with AsyncSessionLocal() as db:
        try:
            user = await get_current_user_from_token(token, db)
        except Exception:
            await websocket.close(code=1008, reason="Invalid or expired token")
            return

    user_id_str = str(user.id)
    manager.user_connections.setdefault(user_id_str, []).append(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, project_id=None, user_id=user_id_str)
    except Exception:
        manager.disconnect(websocket, project_id=None, user_id=user_id_str)


@router.websocket("/projects/{project_id}")
async def websocket_endpoint(
    websocket: WebSocket,
    project_id: uuid.UUID,
    token: str | None = None,
):
    """
    WebSocket endpoint for real-time project updates.

    Auth: Pass JWT access token via ?token= query param.
    Receives: invalidation events + personal notifications.
    """
    await websocket.accept()
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return

    async with AsyncSessionLocal() as db:
        try:
            user = await get_current_user_from_token(token, db)
        except Exception:
            await websocket.close(code=1008, reason="Invalid or expired token")
            return

        project = await project_manager.get_project_for_user(db, project_id, user.id)
        if not project:
            await websocket.close(code=1008, reason="Not authorized for this project")
            return

    user_id_str = str(user.id)
    manager.active_connections.setdefault(project_id, []).append(websocket)
    manager.user_connections.setdefault(user_id_str, []).append(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            if msg == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket, project_id, user_id=user_id_str)
    except Exception:
        manager.disconnect(websocket, project_id, user_id=user_id_str)
