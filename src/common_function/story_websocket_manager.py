"""
WebSocket Connection Manager for Story Generation Notifications
"""
import json
import asyncio
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import WebSocket, WebSocketDisconnect
from dataclasses import dataclass

@dataclass
class WebSocketConnection:
    websocket: WebSocket
    user_id: str
    story_ids: List[str]
    connected_at: datetime
    last_ping: Optional[datetime] = None
    
class StoryWebSocketManager:
    """Manages WebSocket connections for story generation notifications"""
    
    def __init__(self):
        # Map story_id -> list of connections interested in that story
        self.story_connections: Dict[str, List[WebSocketConnection]] = {}
        # Map user_id -> list of connections for that user
        self.user_connections: Dict[str, List[WebSocketConnection]] = {}
        # All active connections
        self.active_connections: List[WebSocketConnection] = []
        
    async def connect(self, websocket: WebSocket, user_id: str) -> WebSocketConnection:
        """Accept a new WebSocket connection"""
        await websocket.accept()
        
        connection = WebSocketConnection(
            websocket=websocket,
            user_id=user_id,
            story_ids=[],
            connected_at=datetime.utcnow()
        )
        
        self.active_connections.append(connection)
        
        # Add to user connections
        if user_id not in self.user_connections:
            self.user_connections[user_id] = []
        self.user_connections[user_id].append(connection)
        
        print(f"📡 WebSocket connected for user {user_id}")
        
        # Send connection confirmation
        await self._send_to_connection(connection, {
            "event": "connected",
            "user_id": user_id,
            "message": "WebSocket connection established",
            "timestamp": datetime.utcnow().isoformat()
        })
        
        return connection
    
    async def disconnect(self, connection: WebSocketConnection):
        """Handle WebSocket disconnection"""
        try:
            print(f"🔌 WebSocket disconnecting for user {connection.user_id}")
            
            # Remove from active connections
            if connection in self.active_connections:
                self.active_connections.remove(connection)
            
            # Remove from user connections
            user_connections = self.user_connections.get(connection.user_id, [])
            if connection in user_connections:
                user_connections.remove(connection)
                if not user_connections:
                    del self.user_connections[connection.user_id]
            
            # Remove from story subscriptions
            subscribed_stories = list(connection.story_ids)
            for story_id in subscribed_stories:
                story_connections = self.story_connections.get(story_id, [])
                if connection in story_connections:
                    story_connections.remove(connection)
                    if not story_connections:
                        del self.story_connections[story_id]
            
            print(f"📡 WebSocket disconnected for user {connection.user_id} (was subscribed to {len(subscribed_stories)} stories)")
            
        except Exception as e:
            print(f"❌ Error during disconnect: {e}")
    
    async def subscribe_to_story(self, connection: WebSocketConnection, story_id: str):
        """Subscribe a connection to story updates"""
        if story_id not in connection.story_ids:
            connection.story_ids.append(story_id)
        
        if story_id not in self.story_connections:
            self.story_connections[story_id] = []
        
        if connection not in self.story_connections[story_id]:
            self.story_connections[story_id].append(connection)
        
        print(f"📡 User {connection.user_id} subscribed to story {story_id}")
        
        # Confirm subscription
        await self._send_to_connection(connection, {
            "event": "subscribed",
            "story_id": story_id,
            "message": f"Subscribed to story {story_id} updates",
            "timestamp": datetime.utcnow().isoformat()
        })
    
    async def unsubscribe_from_story(self, connection: WebSocketConnection, story_id: str):
        """Unsubscribe a connection from story updates"""
        if story_id in connection.story_ids:
            connection.story_ids.remove(story_id)
        
        story_connections = self.story_connections.get(story_id, [])
        if connection in story_connections:
            story_connections.remove(connection)
            if not story_connections:
                del self.story_connections[story_id]
        
        print(f"📡 User {connection.user_id} unsubscribed from story {story_id}")
    
    async def broadcast_to_story(self, story_id: str, message: Dict):
        """Send a message to all connections subscribed to a story"""
        connections = self.story_connections.get(story_id, [])
        if not connections:
            print(f"📡 No WebSocket connections for story {story_id}")
            return
        
        print(f"📡 Broadcasting to {len(connections)} connections for story {story_id}")
        
        # Send to all connections for this story
        tasks = []
        for connection in connections.copy():  # Use copy to avoid modification during iteration
            tasks.append(self._send_to_connection_safe(connection, message))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def broadcast_to_user(self, user_id: str, message: Dict):
        """Send a message to all connections for a specific user"""
        connections = self.user_connections.get(user_id, [])
        if not connections:
            print(f"⚠️ No active connections found for user {user_id} to broadcast message")
            return
        
        event_type = message.get("event", "unknown")
        print(f"📡 Broadcasting '{event_type}' to {len(connections)} connections for user {user_id}")
        
        tasks = []
        for connection in connections.copy():
            tasks.append(self._send_to_connection_safe(connection, message))
        
        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            success_count = sum(1 for r in results if not isinstance(r, Exception))
            print(f"✅ Successfully sent '{event_type}' to {success_count}/{len(connections)} connections")
    
    async def _send_to_connection(self, connection: WebSocketConnection, message: Dict):
        """Send a message to a specific connection"""
        try:
            event_type = message.get("event", "unknown")
            print(f"📤 Attempting to send '{event_type}' to user {connection.user_id}")
            await connection.websocket.send_text(json.dumps(message))
            print(f"✅ Successfully sent '{event_type}' to user {connection.user_id}")
        except Exception as e:
            print(f"❌ Error sending '{event_type}' to WebSocket {connection.user_id}: {e}")
            await self.disconnect(connection)
            raise e
    
    async def _send_to_connection_safe(self, connection: WebSocketConnection, message: Dict):
        """Send a message to a connection with error handling"""
        try:
            await self._send_to_connection(connection, message)
        except Exception as e:
            print(f"⚠️ Failed to send to connection {connection.user_id}: {e}")
            # Connection will be cleaned up automatically
    
    async def handle_message(self, connection: WebSocketConnection, message: Dict):
        """Handle incoming WebSocket message from client"""
        try:
            action = message.get("action")
            
            if action == "subscribe":
                story_id = message.get("story_id")
                if story_id:
                    await self.subscribe_to_story(connection, story_id)
                else:
                    await self._send_to_connection(connection, {
                        "event": "error",
                        "message": "story_id is required for subscribe action"
                    })
            
            elif action == "unsubscribe":
                story_id = message.get("story_id")
                if story_id:
                    await self.unsubscribe_from_story(connection, story_id)
                else:
                    await self._send_to_connection(connection, {
                        "event": "error", 
                        "message": "story_id is required for unsubscribe action"
                    })
            
            elif action == "ping":
                connection.last_ping = datetime.utcnow()
                await self._send_to_connection(connection, {
                    "event": "pong",
                    "timestamp": datetime.utcnow().isoformat()
                })
            
            else:
                await self._send_to_connection(connection, {
                    "event": "error",
                    "message": f"Unknown action: {action}"
                })
                
        except Exception as e:
            print(f"❌ Error handling WebSocket message: {e}")
            await self._send_to_connection(connection, {
                "event": "error",
                "message": f"Error processing message: {str(e)}"
            })
    
    def get_connection_stats(self) -> Dict:
        """Get statistics about current connections"""
        return {
            "total_connections": len(self.active_connections),
            "unique_users": len(self.user_connections),
            "stories_with_subscribers": len(self.story_connections),
            "connections_by_user": {
                user_id: len(connections) 
                for user_id, connections in self.user_connections.items()
            },
            "subscribers_by_story": {
                story_id: len(connections)
                for story_id, connections in self.story_connections.items()
            }
        }
    
    async def cleanup_stale_connections(self, max_idle_minutes: int = 30):
        """Remove connections that haven't sent a ping in max_idle_minutes"""
        now = datetime.utcnow()
        stale_connections = []
        
        for connection in self.active_connections:
            last_activity = connection.last_ping or connection.connected_at
            idle_minutes = (now - last_activity).total_seconds() / 60
            
            if idle_minutes > max_idle_minutes:
                stale_connections.append(connection)
        
        for connection in stale_connections:
            await self.disconnect(connection)
        
        if stale_connections:
            print(f"🧹 Cleaned up {len(stale_connections)} stale WebSocket connections")

# Global instance
story_websocket_manager = StoryWebSocketManager()