import os
import sys
import threading
import queue
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from datetime import datetime

project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from lan_transfer.config import (
    APP_NAME,
    APP_VERSION,
    LOCAL_IP,
    HOSTNAME,
    DOWNLOAD_DIR,
    STATUS_TRANSFERRING,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_REJECTED,
    STATUS_CANCELLED,
)
from lan_transfer.utils import format_file_size, format_speed, format_time
from lan_transfer.network import DeviceDiscovery, ConnectionManager
from lan_transfer.transfer import FileTransfer, FolderTransfer
from lan_transfer.transfer.file_transfer import TransferTask
from lan_transfer.chat import ChatManager
from lan_transfer.chat.chat_manager import ChatMessage
from lan_transfer.history import HistoryManager


class FileConfirmDialog(tk.Toplevel):
    def __init__(self, parent, file_name, file_size, sender_ip, sender_name=""):
        super().__init__(parent)
        self.title("文件接收确认")
        self.result = None
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self._create_widgets(file_name, file_size, sender_ip, sender_name)
        self._center_window()

    def _create_widgets(self, file_name, file_size, sender_ip, sender_name):
        main_frame = ttk.Frame(self, padding="20")
        main_frame.pack(fill=tk.BOTH, expand=True)

        icon_frame = ttk.Frame(main_frame)
        icon_frame.pack(pady=(0, 15))

        icon_label = tk.Label(
            icon_frame,
            text="📁",
            font=("Segoe UI Emoji", 32),
        )
        icon_label.pack()

        title_label = ttk.Label(
            main_frame,
            text="收到文件传输请求",
            font=("Microsoft YaHei", 14, "bold"),
        )
        title_label.pack(pady=(0, 10))

        info_frame = ttk.Frame(main_frame)
        info_frame.pack(fill=tk.X, pady=10)

        info_text = (
            f"发送方: {sender_name or sender_ip}\n"
            f"文件名: {file_name}\n"
            f"大小: {format_file_size(file_size)}"
        )

        info_label = ttk.Label(
            info_frame,
            text=info_text,
            font=("Microsoft YaHei", 10),
            justify=tk.LEFT,
        )
        info_label.pack()

        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(20, 0))

        reject_btn = ttk.Button(
            btn_frame,
            text="拒绝",
            width=12,
            command=self._on_reject,
        )
        reject_btn.pack(side=tk.RIGHT, padx=(10, 0))

        accept_btn = ttk.Button(
            btn_frame,
            text="接受",
            width=12,
            command=self._on_accept,
        )
        accept_btn.pack(side=tk.RIGHT)

        accept_btn.focus_set()

    def _center_window(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def _on_accept(self):
        self.result = True
        self.destroy()

    def _on_reject(self):
        self.result = False
        self.destroy()

    def show(self):
        self.wait_window()
        return self.result


class ChatWindow(tk.Toplevel):
    def __init__(self, parent, peer_ip, peer_name, chat_manager):
        super().__init__(parent)
        self.peer_ip = peer_ip
        self.peer_name = peer_name
        self.chat_manager = chat_manager
        self.title(f"聊天 - {peer_name} ({peer_ip})")
        self.geometry("400x500")
        self.transient(parent)

        self._create_widgets()
        self._load_history()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.chat_manager.register_callback("message_received", self._on_message_received)

    def _create_widgets(self):
        main_frame = ttk.Frame(self, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        self.messages_text = tk.Text(
            main_frame,
            wrap=tk.WORD,
            font=("Microsoft YaHei", 10),
            state=tk.DISABLED,
            bg="#f5f5f5",
        )
        self.messages_text.pack(fill=tk.BOTH, expand=True, pady=(0, 10))

        self.messages_text.tag_configure("me", foreground="#2196F3", justify=tk.RIGHT)
        self.messages_text.tag_configure("other", foreground="#333333", justify=tk.LEFT)
        self.messages_text.tag_configure("time", foreground="#999999", font=("Microsoft YaHei", 8))

        input_frame = ttk.Frame(main_frame)
        input_frame.pack(fill=tk.X)

        self.input_text = tk.Text(
            input_frame,
            height=3,
            font=("Microsoft YaHei", 10),
            wrap=tk.WORD,
        )
        self.input_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        self.input_text.bind("<Return>", self._on_return_pressed)

        send_btn = ttk.Button(
            input_frame,
            text="发送",
            width=8,
            command=self._send_message,
        )
        send_btn.pack(side=tk.RIGHT)

    def _load_history(self):
        messages = self.chat_manager.get_chat_history(self.peer_ip)
        for msg in messages:
            self._add_message(msg)

    def _on_message_received(self, msg):
        if msg.from_ip == self.peer_ip:
            self.after(0, lambda: self._add_message(msg))

    def _add_message(self, msg):
        self.messages_text.config(state=tk.NORMAL)

        time_str = datetime.fromtimestamp(msg.timestamp).strftime("%H:%M:%S")
        sender = "我" if msg.from_me else msg.sender_name

        if msg.from_me:
            self.messages_text.insert(tk.END, f"\n{msg.content}\n", "me")
            self.messages_text.insert(tk.END, f"{sender} {time_str}\n", "time")
        else:
            self.messages_text.insert(tk.END, f"\n{sender} {time_str}\n", "time")
            self.messages_text.insert(tk.END, f"{msg.content}\n", "other")

        self.messages_text.see(tk.END)
        self.messages_text.config(state=tk.DISABLED)

    def _on_return_pressed(self, event):
        if event.state & 0x0001:
            return
        self._send_message()
        return "break"

    def _send_message(self):
        content = self.input_text.get("1.0", tk.END).strip()
        if not content:
            return

        if self.chat_manager.send_message(self.peer_ip, content):
            self.input_text.delete("1.0", tk.END)
            msg = ChatMessage(
                from_ip="",
                to_ip=self.peer_ip,
                content=content,
                from_me=True,
                sender_name=HOSTNAME,
            )
            self._add_message(msg)

    def _on_close(self):
        self.destroy()


class MainWindow:
    def __init__(self):
        self.dnd_available = False
        try:
            from tkinterdnd2 import TkinterDnD
            self.root = TkinterDnD.Tk()
            self.dnd_available = True
        except ImportError:
            self.root = tk.Tk()

        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("1000x700")
        self.root.minsize(900, 600)

        self._init_managers()
        self._setup_styles()
        self._create_widgets()
        self._setup_callbacks()
        self._start_services()

        self.event_queue = queue.Queue()
        self._process_events()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _init_managers(self):
        self.discovery = DeviceDiscovery()
        self.connection = ConnectionManager()
        self.file_transfer = FileTransfer(self.connection)
        self.folder_transfer = FolderTransfer(self.file_transfer)
        self.chat_manager = ChatManager(self.connection)
        self.history_manager = HistoryManager()

    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure("Treeview", font=("Microsoft YaHei", 10), rowheight=30)
        style.configure("Treeview.Heading", font=("Microsoft YaHei", 10, "bold"))
        style.configure("TNotebook.Tab", font=("Microsoft YaHei", 11), padding=[15, 8])
        style.configure("TButton", font=("Microsoft YaHei", 10), padding=[10, 5])
        style.configure("Title.TLabel", font=("Microsoft YaHei", 12, "bold"))
        style.configure("SubTitle.TLabel", font=("Microsoft YaHei", 10))

    def _create_widgets(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        header_frame = ttk.Frame(main_frame)
        header_frame.pack(fill=tk.X, pady=(0, 10))

        title_label = ttk.Label(
            header_frame,
            text=f"{APP_NAME}",
            style="Title.TLabel",
        )
        title_label.pack(side=tk.LEFT)

        info_label = ttk.Label(
            header_frame,
            text=f"本机: {HOSTNAME} ({LOCAL_IP})",
            style="SubTitle.TLabel",
            foreground="#666",
        )
        info_label.pack(side=tk.LEFT, padx=(15, 0))

        ttk.Button(
            header_frame,
            text="打开下载目录",
            command=self._open_download_dir,
        ).pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self._create_devices_tab()
        self._create_transfers_tab()
        self._create_history_tab()

        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(10, 0))

        self.status_label = ttk.Label(
            status_frame,
            text="正在扫描局域网设备...",
            style="SubTitle.TLabel",
            foreground="#666",
        )
        self.status_label.pack(side=tk.LEFT)

        self.device_count_label = ttk.Label(
            status_frame,
            text="在线设备: 0",
            style="SubTitle.TLabel",
            foreground="#4CAF50",
        )
        self.device_count_label.pack(side=tk.RIGHT)

    def _create_devices_tab(self):
        tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab, text="🎯 设备列表")

        left_panel = ttk.Frame(tab)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

        ttk.Label(left_panel, text="在线设备", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 10))

        btn_frame = ttk.Frame(left_panel)
        btn_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(
            btn_frame,
            text="🔄 刷新",
            command=self._refresh_devices,
        ).pack(side=tk.LEFT)

        ttk.Button(
            btn_frame,
            text="📁 发送文件",
            command=self._send_files_dialog,
        ).pack(side=tk.LEFT, padx=(10, 0))

        ttk.Button(
            btn_frame,
            text="📂 发送文件夹",
            command=self._send_folder_dialog,
        ).pack(side=tk.LEFT, padx=(10, 0))

        columns = ("hostname", "ip", "status")
        self.devices_tree = ttk.Treeview(left_panel, columns=columns, show="tree headings", selectmode="browse")
        self.devices_tree.heading("#0", text="", anchor=tk.W)
        self.devices_tree.heading("hostname", text="设备名", anchor=tk.W)
        self.devices_tree.heading("ip", text="IP地址", anchor=tk.W)
        self.devices_tree.heading("status", text="状态", anchor=tk.W)

        self.devices_tree.column("#0", width=40, stretch=tk.NO)
        self.devices_tree.column("hostname", width=200)
        self.devices_tree.column("ip", width=150)
        self.devices_tree.column("status", width=80)

        scrollbar = ttk.Scrollbar(left_panel, orient=tk.VERTICAL, command=self.devices_tree.yview)
        self.devices_tree.configure(yscrollcommand=scrollbar.set)

        self.devices_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.devices_tree.bind("<Double-1>", self._on_device_double_click)
        self.devices_tree.bind("<<TreeviewSelect>>", self._on_device_select)

        right_panel = ttk.Frame(tab)
        right_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        ttk.Label(right_panel, text="设备详情", style="Title.TLabel").pack(anchor=tk.W, pady=(0, 10))

        self.detail_frame = ttk.Frame(right_panel, relief=tk.GROOVE, padding="15")
        self.detail_frame.pack(fill=tk.BOTH, expand=True)

        self.avatar_canvas = tk.Canvas(self.detail_frame, width=80, height=80, highlightthickness=0)
        self.avatar_canvas.pack(pady=(0, 15))

        self.detail_name = ttk.Label(self.detail_frame, text="-", style="Title.TLabel")
        self.detail_name.pack()

        self.detail_ip = ttk.Label(self.detail_frame, text="-", style="SubTitle.TLabel", foreground="#666")
        self.detail_ip.pack(pady=(5, 0))

        self.detail_status = ttk.Label(self.detail_frame, text="", foreground="#4CAF50")
        self.detail_status.pack(pady=(5, 0))

        action_frame = ttk.Frame(self.detail_frame)
        action_frame.pack(fill=tk.X, pady=(20, 0))

        ttk.Button(
            action_frame,
            text="📁 发送文件",
            command=self._send_files_to_selected,
        ).pack(fill=tk.X, pady=5)

        ttk.Button(
            action_frame,
            text="📂 发送文件夹",
            command=self._send_folder_to_selected,
        ).pack(fill=tk.X, pady=5)

        ttk.Button(
            action_frame,
            text="💬 聊天",
            command=self._open_chat_with_selected,
        ).pack(fill=tk.X, pady=5)

        hint_label = ttk.Label(
            right_panel,
            text="💡 提示: 可以拖拽文件到设备列表进行发送",
            style="SubTitle.TLabel",
            foreground="#888",
        )
        hint_label.pack(pady=(15, 0))

        self._update_detail_panel(None)
        self._setup_drag_drop()

    def _setup_drag_drop(self):
        if self.dnd_available:
            try:
                from tkinterdnd2 import DND_FILES

                self.devices_tree.drop_target_register(DND_FILES)
                self.devices_tree.dnd_bind("<<Drop>>", self._on_drop_files)
            except Exception as e:
                print(f"Drag drop setup error: {e}")

    def _on_drop_files(self, event):
        files = self._parse_dropped_files(event.data)
        if not files:
            return

        item = self.devices_tree.identify_row(event.y)
        if not item:
            messagebox.showinfo("提示", "请将文件拖放到目标设备上")
            return

        device = self._get_device_from_tree_item(item)
        if not device:
            return

        if messagebox.askyesno(
            "确认发送",
            f"确定发送 {len(files)} 个文件/文件夹到 {device.hostname} ({device.ip})?"
        ):
            self._send_paths_to_device(files, device.ip)

    def _parse_dropped_files(self, data):
        files = []
        if "{" in data:
            parts = data.split("} {")
            for part in parts:
                file = part.strip("{}")
                if os.path.exists(file):
                    files.append(file)
        else:
            if os.path.exists(data):
                files.append(data)
        return files

    def _create_transfers_tab(self):
        tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab, text="📤 传输中")

        columns = ("direction", "filename", "peer", "size", "progress", "speed", "status")
        self.transfers_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="extended")

        self.transfers_tree.heading("direction", text="方向", anchor=tk.CENTER)
        self.transfers_tree.heading("filename", text="文件名", anchor=tk.W)
        self.transfers_tree.heading("peer", text="对方", anchor=tk.W)
        self.transfers_tree.heading("size", text="大小", anchor=tk.CENTER)
        self.transfers_tree.heading("progress", text="进度", anchor=tk.CENTER)
        self.transfers_tree.heading("speed", text="速度", anchor=tk.CENTER)
        self.transfers_tree.heading("status", text="状态", anchor=tk.CENTER)

        self.transfers_tree.column("direction", width=60, anchor=tk.CENTER, stretch=tk.NO)
        self.transfers_tree.column("filename", width=200, anchor=tk.W)
        self.transfers_tree.column("peer", width=150, anchor=tk.W)
        self.transfers_tree.column("size", width=100, anchor=tk.CENTER)
        self.transfers_tree.column("progress", width=120, anchor=tk.CENTER)
        self.transfers_tree.column("speed", width=100, anchor=tk.CENTER)
        self.transfers_tree.column("status", width=100, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.transfers_tree.yview)
        self.transfers_tree.configure(yscrollcommand=scrollbar.set)

        self.transfers_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        btn_frame = ttk.Frame(tab)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        ttk.Button(
            btn_frame,
            text="⏹ 取消选中",
            command=self._cancel_selected_transfers,
        ).pack(side=tk.LEFT)

        ttk.Button(
            btn_frame,
            text="🧹 清除已完成",
            command=self._clear_completed_transfers,
        ).pack(side=tk.LEFT, padx=(10, 0))

    def _create_history_tab(self):
        tab = ttk.Frame(self.notebook, padding="10")
        self.notebook.add(tab, text="📋 历史记录")

        filter_frame = ttk.Frame(tab)
        filter_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(filter_frame, text="筛选:").pack(side=tk.LEFT)

        self.filter_direction = ttk.Combobox(
            filter_frame,
            values=["全部", "发送", "接收"],
            width=10,
            state="readonly",
        )
        self.filter_direction.current(0)
        self.filter_direction.pack(side=tk.LEFT, padx=(5, 10))
        self.filter_direction.bind("<<ComboboxSelected>>", lambda e: self._refresh_history())

        self.filter_status = ttk.Combobox(
            filter_frame,
            values=["全部", "成功", "失败"],
            width=10,
            state="readonly",
        )
        self.filter_status.current(0)
        self.filter_status.pack(side=tk.LEFT, padx=(0, 10))
        self.filter_status.bind("<<ComboboxSelected>>", lambda e: self._refresh_history())

        ttk.Button(
            filter_frame,
            text="🔄 刷新",
            command=self._refresh_history,
        ).pack(side=tk.LEFT)

        ttk.Button(
            filter_frame,
            text="🗑 清空历史",
            command=self._clear_all_history,
        ).pack(side=tk.LEFT, padx=(10, 0))

        columns = ("direction", "filename", "peer", "size", "speed", "completion_time", "status")
        self.history_tree = ttk.Treeview(tab, columns=columns, show="headings", selectmode="browse")

        self.history_tree.heading("direction", text="方向", anchor=tk.CENTER)
        self.history_tree.heading("filename", text="文件名", anchor=tk.W)
        self.history_tree.heading("peer", text="对方", anchor=tk.W)
        self.history_tree.heading("size", text="大小", anchor=tk.CENTER)
        self.history_tree.heading("speed", text="平均速度", anchor=tk.CENTER)
        self.history_tree.heading("completion_time", text="完成时间", anchor=tk.CENTER)
        self.history_tree.heading("status", text="状态", anchor=tk.CENTER)

        self.history_tree.column("direction", width=60, anchor=tk.CENTER, stretch=tk.NO)
        self.history_tree.column("filename", width=200, anchor=tk.W)
        self.history_tree.column("peer", width=150, anchor=tk.W)
        self.history_tree.column("size", width=100, anchor=tk.CENTER)
        self.history_tree.column("speed", width=100, anchor=tk.CENTER)
        self.history_tree.column("completion_time", width=150, anchor=tk.CENTER)
        self.history_tree.column("status", width=80, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(tab, orient=tk.VERTICAL, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=scrollbar.set)

        self.history_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.history_tree.bind("<Double-1>", self._on_history_double_click)

        stats_frame = ttk.Frame(tab)
        stats_frame.pack(fill=tk.X, pady=(10, 0))

        self.stats_label = ttk.Label(
            stats_frame,
            text="统计: 共 0 条 | 成功 0 | 失败 0 | 发送 0 | 接收 0",
            style="SubTitle.TLabel",
            foreground="#666",
        )
        self.stats_label.pack(side=tk.LEFT)

        self._refresh_history()

    def _setup_callbacks(self):
        self.discovery.register_callback("device_added", self._on_device_added)
        self.discovery.register_callback("device_removed", self._on_device_removed)
        self.discovery.register_callback("device_updated", self._on_device_updated)

        self.file_transfer.register_callback("file_request", self._on_file_request)
        self.file_transfer.register_callback("task_started", self._on_task_started)
        self.file_transfer.register_callback("task_progress", self._on_task_progress)
        self.file_transfer.register_callback("task_completed", self._on_task_completed)
        self.file_transfer.register_callback("task_failed", self._on_task_failed)

        self.chat_manager.register_callback("message_received", self._on_chat_message_received)

    def _start_services(self):
        self.discovery.start()
        self.connection.start()
        self.status_label.config(text="服务已启动，正在扫描局域网设备...")

    def _process_events(self):
        try:
            while True:
                event = self.event_queue.get_nowait()
                event()
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._process_events)

    def _queue_event(self, func):
        self.event_queue.put(func)

    def _on_device_added(self, device):
        self._queue_event(lambda: self._add_device_to_tree(device))

    def _on_device_removed(self, device):
        self._queue_event(lambda: self._remove_device_from_tree(device))

    def _on_device_updated(self, device):
        self._queue_event(lambda: self._update_device_in_tree(device))

    def _add_device_to_tree(self, device):
        item = self.devices_tree.insert(
            "",
            tk.END,
            values=(device.hostname, device.ip, "在线"),
            tags=("online",),
        )
        self._draw_avatar(item, device)
        self.devices_tree.tag_configure("online", foreground="#4CAF50")
        self._update_device_count()
        self.status_label.config(text=f"发现新设备: {device.hostname} ({device.ip})")

    def _remove_device_from_tree(self, device):
        for item in self.devices_tree.get_children():
            values = self.devices_tree.item(item, "values")
            if values and values[1] == device.ip:
                self.devices_tree.delete(item)
                break
        self._update_device_count()

        selected = self.devices_tree.selection()
        if not selected:
            self._update_detail_panel(None)

    def _update_device_in_tree(self, device):
        for item in self.devices_tree.get_children():
            values = self.devices_tree.item(item, "values")
            if values and values[1] == device.ip:
                self.devices_tree.item(
                    item,
                    values=(device.hostname, device.ip, "在线"),
                )
                break

    def _draw_avatar(self, item, device):
        initial = device.hostname[0].upper() if device.hostname else "?"

        try:
            img = tk.PhotoImage(width=30, height=30)
            for x in range(30):
                for y in range(30):
                    dist = ((x - 15) ** 2 + (y - 15) ** 2) ** 0.5
                    if dist <= 13:
                        img.put(device.avatar, (x, y))

            self.devices_tree.item(item, image=img)
            if not hasattr(self, "_avatar_images"):
                self._avatar_images = {}
            self._avatar_images[item] = img
        except Exception as e:
            self.devices_tree.item(item, text=f"  {initial}")

    def _update_device_count(self):
        count = len(self.devices_tree.get_children())
        self.device_count_label.config(text=f"在线设备: {count}")

    def _refresh_devices(self):
        self.status_label.config(text="正在刷新设备列表...")
        for item in self.devices_tree.get_children():
            self.devices_tree.delete(item)
        self._update_device_count()

        threading.Thread(target=self._force_discovery, daemon=True).start()

    def _force_discovery(self):
        from lan_transfer.config import MSG_TYPE_HELLO
        import json
        import socket
        from lan_transfer.config import UDP_DISCOVERY_PORT, LOCAL_IP, HOSTNAME
        from lan_transfer.utils import get_subnet

        for _ in range(3):
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                msg = json.dumps({
                    "type": MSG_TYPE_HELLO,
                    "ip": LOCAL_IP,
                    "hostname": HOSTNAME,
                }).encode("utf-8")
                sock.sendto(msg, (get_subnet(LOCAL_IP), UDP_DISCOVERY_PORT))
                sock.close()
            except Exception:
                pass

    def _on_device_select(self, event):
        item = self.devices_tree.selection()
        if item:
            device = self._get_device_from_tree_item(item[0])
            self._update_detail_panel(device)
        else:
            self._update_detail_panel(None)

    def _on_device_double_click(self, event):
        item = self.devices_tree.selection()
        if item:
            device = self._get_device_from_tree_item(item[0])
            if device:
                self._open_chat(device)

    def _get_device_from_tree_item(self, item):
        values = self.devices_tree.item(item, "values")
        if values:
            ip = values[1]
            return self.discovery.get_device(ip)
        return None

    def _update_detail_panel(self, device):
        if device is None:
            self.avatar_canvas.delete("all")
            self.avatar_canvas.create_oval(5, 5, 75, 75, fill="#e0e0e0", outline="")
            self.avatar_canvas.create_text(40, 42, text="?", font=("Microsoft YaHei", 24, "bold"), fill="#999")

            self.detail_name.config(text="-")
            self.detail_ip.config(text="-")
            self.detail_status.config(text="")
            return

        self.avatar_canvas.delete("all")
        self.avatar_canvas.create_oval(5, 5, 75, 75, fill=device.avatar, outline="")
        initial = device.hostname[0].upper() if device.hostname else "?"
        self.avatar_canvas.create_text(40, 42, text=initial, font=("Microsoft YaHei", 24, "bold"), fill="white")

        self.detail_name.config(text=device.hostname)
        self.detail_ip.config(text=device.ip)
        self.detail_status.config(text="● 在线", foreground="#4CAF50")

    def _send_files_dialog(self):
        files = filedialog.askopenfilenames(title="选择要发送的文件")
        if not files:
            return

        device = self._get_selected_device()
        if not device:
            messagebox.showinfo("提示", "请先选择目标设备")
            return

        self._send_paths_to_device(list(files), device.ip)

    def _send_folder_dialog(self):
        folder = filedialog.askdirectory(title="选择要发送的文件夹")
        if not folder:
            return

        device = self._get_selected_device()
        if not device:
            messagebox.showinfo("提示", "请先选择目标设备")
            return

        self._send_paths_to_device([folder], device.ip)

    def _send_files_to_selected(self):
        self._send_files_dialog()

    def _send_folder_to_selected(self):
        self._send_folder_dialog()

    def _get_selected_device(self):
        item = self.devices_tree.selection()
        if item:
            return self._get_device_from_tree_item(item[0])
        return None

    def _send_paths_to_device(self, paths, target_ip):
        device = self.discovery.get_device(target_ip)
        peer_name = device.hostname if device else target_ip

        tasks = self.folder_transfer.send_paths(paths, target_ip)
        for task in tasks:
            self._add_transfer_to_tree(task, peer_name)

        if tasks:
            self.notebook.select(1)
            self.status_label.config(text=f"已发送 {len(tasks)} 个传输请求")

    def _open_chat_with_selected(self):
        device = self._get_selected_device()
        if device:
            self._open_chat(device)

    def _open_chat(self, device):
        chat_window = ChatWindow(self.root, device.ip, device.hostname, self.chat_manager)

    def _on_file_request(self, ip, msg):
        file_id = msg.get("file_id")
        file_name = msg.get("file_name")
        file_size = msg.get("file_size")

        device = self.discovery.get_device(ip)
        sender_name = device.hostname if device else ip

        def show_dialog():
            dialog = FileConfirmDialog(
                self.root,
                file_name,
                file_size,
                ip,
                sender_name,
            )
            accepted = dialog.show()

            if accepted:
                self.file_transfer.accept_file(file_id)
                device = self.discovery.get_device(ip)
                peer_name = device.hostname if device else ip
                task = self.file_transfer.get_task(file_id)
                if task:
                    self._add_transfer_to_tree(task, peer_name)
                self.notebook.select(1)
            else:
                self.file_transfer.reject_file(file_id)

        self._queue_event(show_dialog)

    def _on_task_started(self, task):
        self._queue_event(lambda: self._update_transfer_in_tree(task))

    def _on_task_progress(self, task):
        self._queue_event(lambda: self._update_transfer_in_tree(task))

    def _on_task_completed(self, task):
        self._queue_event(lambda: self._on_task_completed_ui(task))

    def _on_task_completed_ui(self, task):
        self._update_transfer_in_tree(task)
        device = self.discovery.get_device(task.target_ip)
        peer_name = device.hostname if device else task.target_ip
        self.history_manager.add_from_transfer_task(task, peer_name)
        self.status_label.config(text=f"传输完成: {task.file_name}")

    def _on_task_failed(self, task):
        self._queue_event(lambda: self._on_task_failed_ui(task))

    def _on_task_failed_ui(self, task):
        self._update_transfer_in_tree(task)
        device = self.discovery.get_device(task.target_ip)
        peer_name = device.hostname if device else task.target_ip
        self.history_manager.add_from_transfer_task(task, peer_name)
        if task.status == STATUS_REJECTED:
            self.status_label.config(text=f"对方拒绝了: {task.file_name}")
        elif task.error:
            self.status_label.config(text=f"传输失败: {task.file_name} - {task.error}")

    def _on_chat_message_received(self, msg):
        device = self.discovery.get_device(msg.from_ip)
        sender_name = device.hostname if device else msg.sender_name or msg.from_ip
        self.status_label.config(text=f"收到来自 {sender_name} 的消息")

    def _add_transfer_to_tree(self, task, peer_name=""):
        direction = "↑" if task.direction == "send" else "↓"
        status_text = self._get_status_text(task.status)

        values = (
            direction,
            task.file_name,
            peer_name or task.target_ip,
            format_file_size(task.file_size),
            f"{task.get_progress():.1f}%",
            format_speed(task.speed),
            status_text,
        )

        existing = self._find_transfer_item(task.file_id)
        if existing:
            self.transfers_tree.item(existing, values=values)
            return

        item = self.transfers_tree.insert("", tk.END, values=values, tags=(task.status,))
        self.transfers_tree.set(item, "file_id", task.file_id)

        self._set_row_color(item, task.status)

    def _update_transfer_in_tree(self, task):
        item = self._find_transfer_item(task.file_id)
        if not item:
            device = self.discovery.get_device(task.target_ip)
            peer_name = device.hostname if device else task.target_ip
            self._add_transfer_to_tree(task, peer_name)
            return

        direction = "↑" if task.direction == "send" else "↓"
        status_text = self._get_status_text(task.status)

        values = list(self.transfers_tree.item(item, "values"))
        values[0] = direction
        values[4] = f"{task.get_progress():.1f}%"
        values[5] = format_speed(task.speed)
        values[6] = status_text

        self.transfers_tree.item(item, values=values, tags=(task.status,))
        self._set_row_color(item, task.status)

    def _find_transfer_item(self, file_id):
        for item in self.transfers_tree.get_children():
            try:
                if self.transfers_tree.set(item, "file_id") == file_id:
                    return item
            except Exception:
                pass
        return None

    def _get_status_text(self, status):
        status_map = {
            STATUS_PENDING: "等待中",
            STATUS_TRANSFERRING: "传输中",
            STATUS_COMPLETED: "已完成",
            STATUS_REJECTED: "已拒绝",
            STATUS_CANCELLED: "已取消",
            STATUS_FAILED: "失败",
        }
        return status_map.get(status, status)

    def _set_row_color(self, item, status):
        color_map = {
            STATUS_TRANSFERRING: "#2196F3",
            STATUS_COMPLETED: "#4CAF50",
            STATUS_REJECTED: "#FF9800",
            STATUS_CANCELLED: "#9E9E9E",
            STATUS_FAILED: "#F44336",
            STATUS_PENDING: "#FFC107",
        }
        color = color_map.get(status, "#333")
        self.transfers_tree.tag_configure(status, foreground=color)

    def _cancel_selected_transfers(self):
        for item in self.transfers_tree.selection():
            try:
                file_id = self.transfers_tree.set(item, "file_id")
                if file_id:
                    self.file_transfer.cancel_task(file_id)
            except Exception:
                pass

    def _clear_completed_transfers(self):
        to_remove = []
        for item in self.transfers_tree.get_children():
            values = self.transfers_tree.item(item, "values")
            if values and values[6] in ["已完成", "已拒绝", "已取消", "失败"]:
                to_remove.append(item)

        for item in to_remove:
            self.transfers_tree.delete(item)

        self.file_transfer.cleanup_completed_tasks()

    def _refresh_history(self):
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)

        direction_filter = self.filter_direction.get()
        status_filter = self.filter_status.get()

        direction_map = {"发送": "send", "接收": "receive"}
        status_map = {"成功": "completed", "失败": "failed"}

        direction = direction_map.get(direction_filter)
        status = status_map.get(status_filter)

        records = self.history_manager.get_records(direction=direction, status=status)

        for record in records:
            direction_icon = "↑" if record.direction == "send" else "↓"
            status_text = self._get_status_text(record.status)

            values = (
                direction_icon,
                record.file_name,
                record.peer_name or record.peer_ip,
                format_file_size(record.file_size),
                format_speed(record.speed),
                format_time(record.end_time),
                status_text,
            )

            item = self.history_tree.insert("", tk.END, values=values, tags=(record.status,))
            self._set_history_row_color(item, record.status)

        self._update_history_stats()

    def _set_history_row_color(self, item, status):
        color_map = {
            STATUS_COMPLETED: "#4CAF50",
            STATUS_REJECTED: "#FF9800",
            STATUS_CANCELLED: "#9E9E9E",
            STATUS_FAILED: "#F44336",
        }
        color = color_map.get(status, "#333")
        self.history_tree.tag_configure(status, foreground=color)

    def _update_history_stats(self):
        stats = self.history_manager.get_statistics()
        self.stats_label.config(
            text=f"统计: 共 {stats['total']} 条 | 成功 {stats['completed']} | 失败 {stats['failed']} | 发送 {stats['sent']} | 接收 {stats['received']}"
        )

    def _on_history_double_click(self, event):
        item = self.history_tree.selection()
        if item:
            values = self.history_tree.item(item, "values")
            if values and values[6] == "已完成":
                records = self.history_manager.get_records()
                for record in records:
                    if record.file_name == values[1]:
                        if os.path.exists(record.file_path):
                            os.startfile(os.path.dirname(record.file_path))
                        break

    def _clear_all_history(self):
        if messagebox.askyesno("确认", "确定要清空所有历史记录吗？"):
            self.history_manager.clear_history()
            self._refresh_history()

    def _open_download_dir(self):
        if os.path.exists(DOWNLOAD_DIR):
            os.startfile(DOWNLOAD_DIR)
        else:
            messagebox.showinfo("提示", "下载目录不存在")

    def _on_close(self):
        if messagebox.askokcancel("退出", "确定要退出吗？"):
            try:
                self.discovery.stop()
                self.connection.stop()
                self.folder_transfer.cleanup_all_temp()
            except Exception:
                pass
            self.root.destroy()

    def run(self):
        self.root.mainloop()
