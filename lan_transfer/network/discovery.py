import socket
import threading
import time
import json
from collections import OrderedDict

from lan_transfer.config import (
    UDP_DISCOVERY_PORT,
    DISCOVERY_INTERVAL,
    DEVICE_TIMEOUT,
    MSG_TYPE_HELLO,
    MSG_TYPE_BYE,
    LOCAL_IP,
    HOSTNAME,
)
from lan_transfer.utils import get_subnet


class Device:
    def __init__(self, ip, hostname, last_seen=None, online=True):
        self.ip = ip
        self.hostname = hostname
        self.last_seen = last_seen or time.time()
        self.online = online
        self.avatar = self._generate_avatar()

    def _generate_avatar(self):
        colors = [
            "#3498db", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6",
            "#1abc9c", "#e67e22", "#34495e", "#95a5a6", "#d35400",
        ]
        idx = hash(self.ip) % len(colors)
        return colors[idx]

    def update_last_seen(self):
        self.last_seen = time.time()
        self.online = True

    def is_timed_out(self):
        return (time.time() - self.last_seen) > DEVICE_TIMEOUT


class DeviceDiscovery:
    def __init__(self):
        self.devices = OrderedDict()
        self.running = False
        self.broadcast_thread = None
        self.listen_thread = None
        self.callbacks = {
            "device_added": [],
            "device_removed": [],
            "device_updated": [],
        }

    def register_callback(self, event, callback):
        if event in self.callbacks:
            self.callbacks[event].append(callback)

    def _trigger_event(self, event, *args, **kwargs):
        for callback in self.callbacks.get(event, []):
            try:
                callback(*args, **kwargs)
            except Exception as e:
                print(f"Callback error for {event}: {e}")

    def start(self):
        if self.running:
            return

        self.running = True
        self.broadcast_thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.broadcast_thread.start()
        self.listen_thread.start()

        threading.Thread(target=self._check_timeout_loop, daemon=True).start()

    def stop(self):
        self.running = False
        try:
            self._send_broadcast(MSG_TYPE_BYE)
        except Exception:
            pass

    def _broadcast_loop(self):
        while self.running:
            try:
                self._send_broadcast(MSG_TYPE_HELLO)
            except Exception as e:
                print(f"Broadcast error: {e}")
            time.sleep(DISCOVERY_INTERVAL)

    def _send_broadcast(self, msg_type):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        message = json.dumps({
            "type": msg_type,
            "ip": LOCAL_IP,
            "hostname": HOSTNAME,
            "timestamp": time.time(),
        }).encode("utf-8")

        subnet = get_subnet(LOCAL_IP)
        try:
            sock.sendto(message, (subnet, UDP_DISCOVERY_PORT))
            sock.sendto(message, ("255.255.255.255", UDP_DISCOVERY_PORT))
        finally:
            sock.close()

    def _listen_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", UDP_DISCOVERY_PORT))
        except OSError as e:
            print(f"Listen bind error: {e}")
            sock.close()
            return

        sock.settimeout(1)

        while self.running:
            try:
                data, addr = sock.recvfrom(4096)
                try:
                    message = json.loads(data.decode("utf-8"))
                    self._handle_message(message, addr[0])
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    print(f"Message parse error: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Listen error: {e}")

        sock.close()

    def _handle_message(self, message, sender_ip):
        msg_type = message.get("type")
        ip = message.get("ip")
        hostname = message.get("hostname")

        if not ip or not hostname:
            return

        if ip == LOCAL_IP:
            return

        if msg_type == MSG_TYPE_HELLO:
            self._add_or_update_device(ip, hostname)
        elif msg_type == MSG_TYPE_BYE:
            self._remove_device(ip)

    def _add_or_update_device(self, ip, hostname):
        if ip in self.devices:
            device = self.devices[ip]
            was_offline = not device.online
            device.update_last_seen()
            if was_offline:
                self._trigger_event("device_added", device)
            self._trigger_event("device_updated", device)
        else:
            device = Device(ip, hostname)
            self.devices[ip] = device
            self._trigger_event("device_added", device)

    def _remove_device(self, ip):
        if ip in self.devices:
            device = self.devices[ip]
            device.online = False
            self._trigger_event("device_removed", device)
            del self.devices[ip]

    def _check_timeout_loop(self):
        while self.running:
            try:
                to_remove = []
                for ip, device in list(self.devices.items()):
                    if device.is_timed_out():
                        device.online = False
                        to_remove.append(ip)
                        self._trigger_event("device_removed", device)

                for ip in to_remove:
                    del self.devices[ip]
            except Exception as e:
                print(f"Timeout check error: {e}")
            time.sleep(2)

    def get_devices(self):
        return list(self.devices.values())

    def get_device(self, ip):
        return self.devices.get(ip)
