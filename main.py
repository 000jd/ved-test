from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json
import asyncio
from typing import Dict, List
import uuid

app = FastAPI(title="WebRTC Video Chat Server")

# Store active connections
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.rooms: Dict[str, List[str]] = {}
    
    async def connect(self, websocket: WebSocket, client_id: str):
        await websocket.accept()
        self.active_connections[client_id] = websocket
        print(f"Client {client_id} connected")
    
    def disconnect(self, client_id: str):
        if client_id in self.active_connections:
            del self.active_connections[client_id]
        # Remove from all rooms
        for room_id in list(self.rooms.keys()):
            if client_id in self.rooms[room_id]:
                self.rooms[room_id].remove(client_id)
                if not self.rooms[room_id]:
                    del self.rooms[room_id]
        print(f"Client {client_id} disconnected")
    
    def join_room(self, client_id: str, room_id: str):
        if room_id not in self.rooms:
            self.rooms[room_id] = []
        if client_id not in self.rooms[room_id]:
            self.rooms[room_id].append(client_id)
        print(f"Client {client_id} joined room {room_id}")
    
    async def send_to_client(self, client_id: str, message: dict):
        if client_id in self.active_connections:
            websocket = self.active_connections[client_id]
            await websocket.send_text(json.dumps(message))
    
    async def broadcast_to_room(self, room_id: str, message: dict, sender_id: str = None):
        if room_id in self.rooms:
            for client_id in self.rooms[room_id]:
                if client_id != sender_id:  # Don't send back to sender
                    await self.send_to_client(client_id, message)

manager = ConnectionManager()

@app.get("/")
async def get_index():
    return FileResponse("static/index.html")

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await manager.connect(websocket, client_id)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            message_type = message.get("type")
            room_id = message.get("room_id", "default")
            
            if message_type == "join_room":
                manager.join_room(client_id, room_id)
                # Notify others in room about new user
                await manager.broadcast_to_room(room_id, {
                    "type": "user_joined",
                    "user_id": client_id
                }, client_id)
                
                # Send room info to new user
                room_users = manager.rooms.get(room_id, [])
                await manager.send_to_client(client_id, {
                    "type": "room_users",
                    "users": [u for u in room_users if u != client_id]
                })
            
            elif message_type in ["offer", "answer", "ice_candidate"]:
                # Forward WebRTC signaling messages
                target_id = message.get("target_id")
                if target_id:
                    await manager.send_to_client(target_id, {
                        **message,
                        "sender_id": client_id
                    })
                else:
                    # Broadcast to room if no specific target
                    await manager.broadcast_to_room(room_id, {
                        **message,
                        "sender_id": client_id
                    }, client_id)
            
            elif message_type == "chat_message":
                # Handle text chat
                await manager.broadcast_to_room(room_id, {
                    "type": "chat_message",
                    "message": message.get("message"),
                    "sender_id": client_id,
                    "timestamp": message.get("timestamp")
                }, client_id)
                
    except WebSocketDisconnect:
        manager.disconnect(client_id)

@app.get("/room/{room_id}")
async def get_room(room_id: str):
    return FileResponse("static/index.html")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)
