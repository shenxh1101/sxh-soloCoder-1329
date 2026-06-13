import time
from typing import Dict, Callable, List, Optional
from collections import deque

from lan_transfer.config import MSG_TYPE_CHAT, HOSTNAME
from lan_transfer.network.connection import ConnectionManager


class ChatMessage:
    def __init__(
        self,
        from_ip: str,
        to_ip: str,
        content: str,
        timestamp: float = None,
        from_me: bool = False,
        sender_name: str = "",
    ):
        self.from_ip = from_ip
        self.to_ip = to_ip
        self.content = content
        self.timestamp = timestamp or time.time()
        self.from_me = from_me
        self.sender_name = sender_name

    def to_dict(self) -> dict:
        return {
            "from_ip": self.from_ip,
            "to_ip": self.to_ip,
            "content": self.content,
            "timestamp": self.timestamp,
            "from_me": self.from_me,
            "sender_name": self.sender_name,
        }


class ChatManager:
    def __init__(self, connection_manager: ConnectionManager):
        self.conn_manager = connection_manager
        self.chat_history: Dict[str, deque] = {}
        self.callbacks = {
            "message_received": [],
            "message_sent": [],
        }
        self.max_history = 100

        self.conn_manager.register_callback("chat_message", self._handle_chat_message)

    def register_callback(self, event: str, callback: Callable):
        if event in self.callbacks and callback not in self.callbacks[event]:
            self.callbacks[event].append(callback)

    def unregister_callback(self, event: str, callback: Callable):
        if event in self.callbacks and callback in self.callbacks[event]:
            self.callbacks[event].remove(callback)

    def _trigger_event(self, event: str, *args, **kwargs):
        callbacks_copy = list(self.callbacks.get(event, []))
        for callback in callbacks_copy:
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"Callback error for {event}: {e}")

    def _handle_chat_message(self, ip: str, msg: dict):
        content = msg.get("content", "")
        sender_name = msg.get("sender_name", "")
        from_ip = msg.get("from_ip", ip)
        to_ip = msg.get("to_ip", "")

        chat_msg = ChatMessage(
            from_ip=from_ip,
            to_ip=to_ip,
            content=content,
            timestamp=msg.get("timestamp"),
            from_me=False,
            sender_name=sender_name,
        )

        self._add_to_history(from_ip, chat_msg)
        self._trigger_event("message_received", chat_msg)

    def send_message(self, to_ip: str, content: str, sender_name: str = "") -> bool:
        if not content.strip():
            return False

        msg = {
            "type": MSG_TYPE_CHAT,
            "from_ip": "",
            "to_ip": to_ip,
            "content": content.strip(),
            "timestamp": time.time(),
            "sender_name": sender_name or HOSTNAME,
        }

        if self.conn_manager.send_chat_message(to_ip, msg):
            chat_msg = ChatMessage(
                from_ip="",
                to_ip=to_ip,
                content=content.strip(),
                timestamp=msg["timestamp"],
                from_me=True,
                sender_name=sender_name or HOSTNAME,
            )
            self._add_to_history(to_ip, chat_msg)
            self._trigger_event("message_sent", chat_msg)
            return True
        return False

    def _add_to_history(self, peer_ip: str, message: ChatMessage):
        if peer_ip not in self.chat_history:
            self.chat_history[peer_ip] = deque(maxlen=self.max_history)
        self.chat_history[peer_ip].append(message)

    def get_chat_history(self, peer_ip: str) -> List[ChatMessage]:
        return list(self.chat_history.get(peer_ip, []))

    def clear_chat_history(self, peer_ip: Optional[str] = None):
        if peer_ip:
            if peer_ip in self.chat_history:
                del self.chat_history[peer_ip]
        else:
            self.chat_history.clear()
