import socket
import threading
import json
import struct
import time
from typing import Dict, Callable, Optional

from lan_transfer.config import (
    TCP_FILE_PORT,
    TCP_CHAT_PORT,
    BUFFER_SIZE,
)


class ConnectionManager:
    def __init__(self):
        self.file_server_sock = None
        self.chat_server_sock = None
        self.file_connections: Dict[str, socket.socket] = {}
        self.chat_connections: Dict[str, socket.socket] = {}
        self.receive_connections: Dict[str, socket.socket] = {}
        self.file_server_thread = None
        self.chat_server_thread = None
        self.running = False
        self.callbacks = {
            "file_request": [],
            "file_data": [],
            "chat_message": [],
            "resume_request": [],
        }
        self._lock = threading.Lock()

    def register_callback(self, event: str, callback: Callable):
        if event in self.callbacks:
            self.callbacks[event].append(callback)

    def _trigger_event(self, event: str, *args, **kwargs):
        for callback in self.callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"Callback error for {event}: {e}")

    def start(self):
        if self.running:
            return

        self.running = True
        self.file_server_thread = threading.Thread(target=self._file_server_loop, daemon=True)
        self.chat_server_thread = threading.Thread(target=self._chat_server_loop, daemon=True)
        self.file_server_thread.start()
        self.chat_server_thread.start()

    def stop(self):
        self.running = False

        with self._lock:
            for conn in list(self.file_connections.values()):
                try:
                    conn.close()
                except Exception:
                    pass
            for conn in list(self.chat_connections.values()):
                try:
                    conn.close()
                except Exception:
                    pass
            self.file_connections.clear()
            self.chat_connections.clear()

        try:
            if self.file_server_sock:
                self.file_server_sock.close()
        except Exception:
            pass

        try:
            if self.chat_server_sock:
                self.chat_server_sock.close()
        except Exception:
            pass

    def _file_server_loop(self):
        self.file_server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.file_server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.file_server_sock.bind(("", TCP_FILE_PORT))
            self.file_server_sock.listen(5)
            self.file_server_sock.settimeout(1)
        except OSError as e:
            print(f"File server bind error: {e}")
            return

        while self.running:
            try:
                conn, addr = self.file_server_sock.accept()
                threading.Thread(
                    target=self._handle_file_connection,
                    args=(conn, addr[0]),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"File server accept error: {e}")

    def _chat_server_loop(self):
        self.chat_server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.chat_server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self.chat_server_sock.bind(("", TCP_CHAT_PORT))
            self.chat_server_sock.listen(5)
            self.chat_server_sock.settimeout(1)
        except OSError as e:
            print(f"Chat server bind error: {e}")
            return

        while self.running:
            try:
                conn, addr = self.chat_server_sock.accept()
                threading.Thread(
                    target=self._handle_chat_connection,
                    args=(conn, addr[0]),
                    daemon=True,
                ).start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Chat server accept error: {e}")

    def _handle_file_connection(self, conn: socket.socket, ip: str):
        connection_key = f"{ip}_{int(time.time() * 1000)}"
        with self._lock:
            self.receive_connections[connection_key] = conn

        is_receiving = threading.Event()

        def _start_receiving():
            is_receiving.set()

        self.callbacks.setdefault("start_receiving", []).append(_start_receiving)

        try:
            while self.running and not is_receiving.is_set():
                msg = self._receive_message(conn)
                if msg is None:
                    break
                msg_type = msg.get("type")
                if msg_type in ["FILE_REQUEST", "RESUME_REQUEST"]:
                    msg["_connection_key"] = connection_key
                    self._trigger_event("file_request", ip, msg)
                elif msg_type in ["FILE_RESPONSE", "FILE_COMPLETE"]:
                    self._trigger_event("file_request", ip, msg)
        except Exception as e:
            print(f"File connection error with {ip}: {e}")
        finally:
            try:
                self.callbacks["start_receiving"].remove(_start_receiving)
            except Exception:
                pass

            if not is_receiving.is_set():
                with self._lock:
                    if connection_key in self.receive_connections:
                        del self.receive_connections[connection_key]
                    if ip in self.file_connections:
                        if self.file_connections[ip] is conn:
                            del self.file_connections[ip]
                try:
                    conn.close()
                except Exception:
                    pass

    def release_receive_connection(self, connection_key: str):
        with self._lock:
            if connection_key in self.receive_connections:
                del self.receive_connections[connection_key]

    def get_receive_connection(self, connection_key: str) -> Optional[socket.socket]:
        with self._lock:
            return self.receive_connections.get(connection_key)

    def _handle_chat_connection(self, conn: socket.socket, ip: str):
        with self._lock:
            self.chat_connections[ip] = conn

        try:
            while self.running:
                msg = self._receive_message(conn)
                if msg is None:
                    break
                if msg.get("type") == "CHAT":
                    self._trigger_event("chat_message", ip, msg)
        except Exception as e:
            print(f"Chat connection error with {ip}: {e}")
        finally:
            conn.close()
            with self._lock:
                if ip in self.chat_connections:
                    del self.chat_connections[ip]

    def _receive_message(self, conn: socket.socket) -> Optional[dict]:
        try:
            header = conn.recv(4)
            if not header:
                return None
            msg_len = struct.unpack("!I", header)[0]
            data = b""
            while len(data) < msg_len:
                chunk = conn.recv(min(msg_len - len(data), BUFFER_SIZE))
                if not chunk:
                    return None
                data += chunk
            return json.loads(data.decode("utf-8"))
        except Exception as e:
            print(f"Receive message error: {e}")
            return None

    def _send_message(self, conn: socket.socket, msg: dict) -> bool:
        try:
            data = json.dumps(msg).encode("utf-8")
            header = struct.pack("!I", len(data))
            conn.sendall(header + data)
            return True
        except Exception as e:
            print(f"Send message error: {e}")
            return False

    def _get_or_create_connection(self, ip: str, port: int, connections_dict: Dict) -> Optional[socket.socket]:
        with self._lock:
            if ip in connections_dict:
                return connections_dict[ip]

        try:
            conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            conn.settimeout(5)
            conn.connect((ip, port))
            conn.settimeout(None)
            with self._lock:
                connections_dict[ip] = conn
            return conn
        except Exception as e:
            print(f"Connect to {ip}:{port} error: {e}")
            return None

    def send_file_message(self, ip: str, msg: dict) -> bool:
        conn = self._get_or_create_connection(ip, TCP_FILE_PORT, self.file_connections)
        if conn:
            return self._send_message(conn, msg)
        return False

    def send_chat_message(self, ip: str, msg: dict) -> bool:
        conn = self._get_or_create_connection(ip, TCP_CHAT_PORT, self.chat_connections)
        if conn:
            return self._send_message(conn, msg)
        return False

    def send_file_chunk(self, ip: str, chunk_data: bytes, metadata: dict) -> bool:
        conn = self._get_or_create_connection(ip, TCP_FILE_PORT, self.file_connections)
        if not conn:
            return False

        try:
            meta_json = json.dumps(metadata).encode("utf-8")
            header = struct.pack("!II", len(meta_json), len(chunk_data))
            conn.sendall(header + meta_json + chunk_data)
            return True
        except Exception as e:
            print(f"Send file chunk error: {e}")
            return False

    def receive_file_chunk(self, conn: socket.socket):
        try:
            header = conn.recv(8)
            if len(header) < 8:
                return None, None
            meta_len, chunk_len = struct.unpack("!II", header)

            meta_data = b""
            while len(meta_data) < meta_len:
                chunk = conn.recv(min(meta_len - len(meta_data), BUFFER_SIZE))
                if not chunk:
                    return None, None
                meta_data += chunk
            metadata = json.loads(meta_data.decode("utf-8"))

            chunk_data = b""
            while len(chunk_data) < chunk_len:
                chunk = conn.recv(min(chunk_len - len(chunk_data), BUFFER_SIZE))
                if not chunk:
                    return None, None
                chunk_data += chunk

            return metadata, chunk_data
        except Exception as e:
            print(f"Receive file chunk error: {e}")
            return None, None
