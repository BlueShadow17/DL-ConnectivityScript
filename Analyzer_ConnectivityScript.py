import ttkbootstrap as tb
from ttkbootstrap.constants import *
import tkinter as tk
from tkinter import messagebox, filedialog
from collections import deque
import subprocess
import threading
import time
import os
import sys
import json
import datetime
from queue import Queue

# ----------------------------
# Network Utilities (ICMP & TCP Fallback)
# ----------------------------

def no_window_subprocess():
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    return startupinfo

def quick_ping(target):

    startupinfo = no_window_subprocess()
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=startupinfo
        )
        return "TTL=" in result.stdout
    except Exception:
        return False

def ping_host(target):
    startupinfo = no_window_subprocess()
    try:
        result = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", target],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            startupinfo=startupinfo
        )
        return "TTL=" in result.stdout
    except Exception:
        return False
    
import socket

def tcp_fallback_check(target, ports=None, timeout=1):
    if ports is None:
        ports = [80, 443, 3389, 22]

    for port in ports:
        try:
            with socket.create_connection((target, port), timeout=timeout):
                return True
        except:
            continue
    return False

# ----------------------------
# Main Application
# ----------------------------

class LogManager:

    def __init__(self, data_dir, max_size_mb=5, retention_days=90):
        self.data_dir = data_dir
        self.max_size = max_size_mb * 1024 * 1024
        self.retention_days = retention_days
        self.log_queue = Queue()
        self.hidden_process = subprocess.STARTUPINFO()
        self.hidden_process.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        self.cleanup_old_logs()

    # -------------------------------------------------
    # Generate today's log file path
    # -------------------------------------------------
    def get_log_path(self):
        today = datetime.date.today().strftime("%Y-%m-%d")
        return os.path.join(self.data_dir, f"{today}_monitoring_log.json")

    # -------------------------------------------------
    # Rotate if size exceeded
    # -------------------------------------------------
    def rotate_if_needed(self, path):
        if not os.path.exists(path):
            return

        if os.path.getsize(path) >= self.max_size:
            base = path.replace(".json", "")
            counter = 1
            while True:
                new_name = f"{base}_{counter}.json"
                if not os.path.exists(new_name):
                    os.rename(path, new_name)
                    break
                counter += 1

    # -------------------------------------------------
    # Write log entry (JSONL format)
    # -------------------------------------------------
    def write_log(self, entry):
        path = self.get_log_path()
        self.rotate_if_needed(path)

        with open(path, "a", encoding="utf-8") as f:
            json.dump(entry, f)
            f.write("\n")

        self.log_queue.put(entry)

    # -------------------------------------------------
    # Cleanup old logs
    # -------------------------------------------------
    def cleanup_old_logs(self):
        now = datetime.datetime.now()

        for file in os.listdir(self.data_dir):
            if file.endswith(".json"):
                full_path = os.path.join(self.data_dir, file)
                modified_time = datetime.datetime.fromtimestamp(
                    os.path.getmtime(full_path)
                )
                if (now - modified_time).days > self.retention_days:
                    os.remove(full_path)



class TCPMonitorApp:

    def __init__(self):
        self.root = tb.Window(themename="darkly")
        self.root.title("TCP/IP Monitor")
        self.root.state('zoomed')
        self.root.resizable(True, True)
        self.root.update_idletasks()
        self.root.geometry(f"{self.root.winfo_reqwidth()}x{self.root.winfo_reqheight()}")
        self.root.position_center()

        # Global Button Text details and mouse icon
        style = tb.Style()
        default_font = ("Segoe UI", 12, "bold")
        style.configure("TButton", font=default_font)
        self.root.option_add("*TButton.cursor", "hand2")
        
        # Determine portable data directory
        if getattr(sys, 'frozen', False):
            base_path = os.path.dirname(sys.executable)
        else:
            base_path = os.path.dirname(os.path.abspath(__file__))

        self.data_dir = os.path.join(base_path, ".tcp_monitor_data")
        self.config_path = os.path.join(self.data_dir, "config.json")

        # Create hidden data folder if it does not exist
        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)
            try:
                os.system(f'attrib +h "{self.data_dir}"')
            except:
                pass
        
        # Load or create default config
        self.default_config = self.load_config()

        self.logger = LogManager(self.data_dir)

        self.monitoring_running = False
        self.setup_tabs()
        self.auto_resize_window()
        self.center_window()
        self.root.mainloop()

    # Resize main window on tab change
    def auto_resize_window(self):
        self.root.update_idletasks()
        self.root.geometry("")

    # Center the window on screen
    def center_window(self):
        self.root.update_idletasks()
        width = self.root.winfo_width()
        height = self.root.winfo_height()
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f"{width}x{height}+{x}+{y}")

    # TABS SETUP
    def setup_tabs(self):
        self.notebook = tb.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True)

        self.tab_monitor = tb.Frame(self.notebook)
        self.tab_logs = tb.Frame(self.notebook)
        self.tab_trace = tb.Frame(self.notebook)
        self.tab_about = tb.Frame(self.notebook)

        self.notebook.add(self.tab_monitor, text="Monitor")
        self.notebook.add(self.tab_logs, text="Logs")
        self.notebook.add(self.tab_trace, text="Trace")
        self.notebook.add(self.tab_about, text="About / Options")

        self.build_monitor_start()
        self.build_logs_tab()
        self.build_trace_tab()
        self.build_about_tab()

    # ============================================================
    # MONITOR TAB SETUP
    # ============================================================

    def build_monitor_start(self):
        for widget in self.tab_monitor.winfo_children():
            widget.destroy()

        self.monitor_frame = tb.Frame(self.tab_monitor, padding=40)
        self.monitor_frame.pack(expand=True)

        tb.Label(
            self.monitor_frame,
            text="Start Monitoring",
            font=("Segoe UI", 22, "bold")
        ).pack(pady=30)

        self.btn_default = tb.Button(
            self.monitor_frame,
            text="Use Default Configuration",
            bootstyle=SUCCESS,
            width=35,
            command=self.start_default
        )
        self.btn_default.pack(pady=15, ipady=10)

        self.btn_manual = tb.Button(
            self.monitor_frame,
            text="Manual Configuration",
            bootstyle=INFO,
            width=35,
            command=self.show_manual_form
        )
        self.btn_manual.pack(pady=15, ipady=10)
        self.auto_resize_window()

    def show_manual_form(self):
        self.build_monitor_start()
        self.btn_default.pack_forget()
        self.btn_manual.pack_forget()

        self.manual_frame = tb.Frame(self.monitor_frame)
        self.manual_frame.pack(pady=20)

        self.create_input_field("Target (IP/Hostname):", "manual_target")
        self.create_input_field("Duration (0-60, 0=∞ minutes):", "manual_duration")
        self.create_input_field("Interval (1-60 seconds):", "manual_interval")

        tb.Button(
            self.manual_frame,
            text="Start Monitoring",
            bootstyle=PRIMARY,
            width=30,
            command=self.validate_manual
        ).pack(pady=10)

        tb.Button(
            self.manual_frame,
            text="Back",
            bootstyle=DANGER,
            width=30,
            command=self.cancel_manual
        ).pack(pady=10)
        self.auto_resize_window()

    def cancel_manual(self):
        if hasattr(self, 'manual_frame') and self.manual_frame:
            self.manual_frame.destroy()
        self.build_monitor_start()

    def create_input_field(self, label_text, attr_name):
        tb.Label(self.manual_frame, text=label_text, font=("Segoe UI", 13)).pack(pady=5)
        entry = tb.Entry(self.manual_frame, width=35)
        entry.pack()
        error_label = tb.Label(self.manual_frame, text="", foreground="red")
        error_label.pack()

        setattr(self, attr_name, entry)
        setattr(self, attr_name + "_error", error_label)

    def validate_manual(self):
        valid = True
        self.clear_manual_errors()

        target = self.manual_target.get()
        duration = self.manual_duration.get()
        interval = self.manual_interval.get()

        try:
            duration = int(duration)
            if duration < 0 or duration > 60:
                raise ValueError
        except:
            self.manual_duration.configure(bootstyle=DANGER)
            self.manual_duration_error.config(text="❗ Must be between 0 and 60")
            valid = False

        try:
            interval = int(interval)
            if interval < 1 or interval > 60:
                raise ValueError
        except:
            self.manual_interval.configure(bootstyle=DANGER)
            self.manual_interval_error.config(text="❗ Must be between 1 and 60")
            valid = False

        if not quick_ping(target):
            self.manual_target.configure(bootstyle=DANGER)
            self.manual_target_error.config(text="❗ Target unreachable")
            valid = False

        if valid:
            self.config_used = {
                "target": target,
                "duration": duration,
                "interval": interval
            }
            self.start_monitoring_ui()

    def clear_manual_errors(self):
        for field in ["manual_target", "manual_duration", "manual_interval"]:
            getattr(self, field).configure(bootstyle=DEFAULT)
            getattr(self, field + "_error").config(text="")

    def start_default(self):
        self.config_used = self.default_config.copy()
        self.start_monitoring_ui()

    def start_monitoring_ui(self):
        for widget in self.tab_monitor.winfo_children():
            widget.destroy()

        container = tb.Frame(self.tab_monitor, padding=40)
        container.pack(expand=True)

        tb.Label(
            container,
            text="Monitoring Running...",
            font=("Segoe UI", 22, "bold")
        ).pack(pady=15)

        config_text = (
            f"Target: {self.config_used['target']}\n"
            f"Duration: {'∞' if self.config_used['duration']==0 else str(self.config_used['duration'])+' min'}\n"
            f"Interval: {self.config_used['interval']} sec"
        )

        # Live Statistics
        tb.Label(
            container,
            text=config_text,
            font=("Segoe UI", 14),
            justify="center"
        ).pack(pady=10)

        stats_frame = tb.Frame(container)
        stats_frame.pack(pady=5)

        self.success_rate_label = tb.Label(
            stats_frame,
            text="Connection Success Rate: 0%",
            font=("Segoe UI", 13)
        )
        self.success_rate_label.pack(side=tk.LEFT, padx=40)

        self.elapsed_time_label = tb.Label(
            stats_frame,
            text="Elapsed Time: 00:00:00",
            font=("Segoe UI", 13)
        )
        self.elapsed_time_label.pack(side=tk.LEFT, padx=40)

        self.connection_type_label = tb.Label(
            stats_frame,
            text="Connection Type: N/A",
            font=("Segoe UI", 13)
        )
        self.connection_type_label.pack(side=tk.LEFT, padx=40)

        self.visual_frame = tb.Frame(container)
        self.visual_frame.pack(pady=20)

        self.visual_blocks = []
        for _ in range(10):
            lbl = tb.Label(self.visual_frame,
                           text=" ",
                           width=4,
                           font=("Segoe UI", 18),
                           relief="ridge")
            lbl.pack(side=tk.LEFT, padx=3)
            self.visual_blocks.append(lbl)

        tb.Button(
            container,
            text="Cancel Monitoring",
            bootstyle=DANGER,
            width=30,
            command=self.cancel_monitoring
        ).pack(pady=20)

        self.start_live_logging()
        self.monitoring_running = True
        threading.Thread(target=self.monitor_loop, daemon=True).start()
        threading.Thread(target=self.run_traceroute_once, daemon=True).start()
        self.monitor_start_time = time.time()
        self.update_elapsed_time()
        self.auto_resize_window()

    def update_elapsed_time(self):
        if not getattr(self, "monitoring_running", False):
            return

        elapsed = int(time.time() - self.monitor_start_time)

        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60

        self.elapsed_time_label.config(
            text=f"Elapsed Time: {hours:02}:{minutes:02}:{seconds:02}"
        )

        self.root.after(1000, self.update_elapsed_time)

    def cancel_monitoring(self):
        self.monitoring_running = False
        self.build_monitor_start()

    def monitor_loop(self):
        target = self.config_used["target"]
        duration = self.config_used["duration"]
        interval = self.config_used["interval"]

        history = deque(maxlen=10)
        total_checks = 0
        success_count = 0
        start_time = time.time()

        while self.monitoring_running:
            connection_type = "Failed"

            # First attempt ICMP
            if ping_host(target):
                status_symbol = "  ✓"
                connection_type = "ICMP"
                success_count += 1

            else:
                # Fallback to TCP
                if tcp_fallback_check(target):
                    status_symbol = "  ⁂"
                    connection_type = "TCP Fallback"
                    success_count += 1
                else:
                    status_symbol = "  ✕"

            total_checks += 1
            history.append(status_symbol)

            # Update visual blocks
            visual = list(history) + [" "] * (10 - len(history))

            for i in range(10):
                symbol = visual[i]

                if symbol == "  ✓":
                    color = "green"
                elif symbol == "  ✕":
                    color = "red"
                elif symbol == "  ⁂":
                    color = "orange"
                else:
                    color = "white"

                self.visual_blocks[i].config(text=symbol, foreground=color)

            # Update success rate
            success_rate = int((success_count / total_checks) * 100)
            self.success_rate_label.config(
                text=f"Connection Success Rate: {success_rate}%"
            )

            self.connection_type_label.config(
                text=f"Connection Type: {connection_type}"
            )

            if duration != 0 and (time.time() - start_time)/60 >= duration:
                break

            # Create structured log entry
            log_entry = {
                "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "target": target,
                "status_symbol": status_symbol,
                "connection_type": connection_type,
                "success": status_symbol != "  ✕",
                "success_rate": success_rate
            }

            self.logger.write_log(log_entry)

            time.sleep(interval)

    # ============================================================
    # ABOUT AND DEFAULT CONFIG TAB SETUP
    # ============================================================
    def build_about_tab(self):

        for widget in self.tab_about.winfo_children():
            widget.destroy()

        container = self.create_scrollable_frame(self.tab_about)

        center_frame = tb.Frame(container)
        center_frame.pack(expand=True)

        # General Info
        tb.Label(
            container,
            text="TCP/IP Connection Monitor®",
            font=("Segoe UI", 18, "bold"),
            justify="center"
        ).pack(pady=(10, 5))

        tb.Label(
            container,
            text="Developer: Roberto Pieterse - CCII Data Layer Engineer\n"
                 "Co-Developer: Musa T. Mukansi - CCII Instrumentation & Control Engineer\n"
                 "Description: Network monitoring program for the Analyzer\n"
                 "to measure connectivity and connection stability.\n\n"
                 "© iOCO - Digital Industries",
            font=("Segoe UI", 13),
            justify="center"
        ).pack(pady=(0, 30))

        # Config Frame
        config_frame = tb.Labelframe(
            container,
            text=" Default Configuration ",
            padding=40,
            bootstyle="secondary"
        )
        config_frame.pack(pady=10, fill="both", expand=True)

        style = tb.Style()
        style.configure("TLabelframe.Label", foreground="gray")

        self.create_about_field(config_frame, "Default Target:", "about_target")
        self.create_about_field(config_frame, "Default Duration (1-60, 0=∞) in minutes:", "about_duration")
        self.create_about_field(config_frame, "Default Interval (1-60) in seconds:", "about_interval")

        self.about_target.insert(0, self.default_config["target"])
        self.about_duration.insert(0, str(self.default_config["duration"]))
        self.about_interval.insert(0, str(self.default_config["interval"]))

        tb.Button(
            container,
            text="Save Default Configuration",
            bootstyle=SUCCESS,
            width=35,
            command=self.save_defaults
        ).pack(pady=30)
        self.auto_resize_window()

    def create_about_field(self, parent, text, attr):
        tb.Label(parent, text=text, font=("Segoe UI", 13), foreground="gray").pack(pady=5)
        entry = tb.Entry(parent, width=35)
        entry.pack()
        error = tb.Label(parent, text="", foreground="red")
        error.pack()
        setattr(self, attr, entry)
        setattr(self, attr+"_error", error)

    def save_defaults(self):

        valid = True

        target = self.about_target.get()
        duration = self.about_duration.get()
        interval = self.about_interval.get()

        # Reset styles first
        self.about_target.configure(bootstyle=DEFAULT)
        self.about_duration.configure(bootstyle=DEFAULT)
        self.about_interval.configure(bootstyle=DEFAULT)
        self.about_target_error.config(text="")
        self.about_duration_error.config(text="")
        self.about_interval_error.config(text="")

        # Validate duration
        try:
            duration = int(duration)
            if duration < 0 or duration > 60:
                raise ValueError
        except:
            self.about_duration.configure(bootstyle=DANGER)
            self.about_duration_error.config(text="❗ Must be between 0 and 60")
            valid = False

        # Validate interval
        try:
            interval = int(interval)
            if interval < 1 or interval > 60:
                raise ValueError
        except:
            self.about_interval.configure(bootstyle=DANGER)
            self.about_interval_error.config(text="❗ Must be between 1 and 60")
            valid = False

        # Validate target by ping
        if not quick_ping(target):
            self.about_target.configure(bootstyle=DANGER)
            self.about_target_error.config(text="❗ Target unreachable")
            valid = False

        if valid:
            self.default_config = {
                "target": target,
                "duration": duration,
                "interval": interval
            }
            messagebox.showinfo("Success", "Defaults Updated Successfully")
            self.save_config_to_file()

    # CONFIG PERSISTENCE
    def load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    return json.load(f)
            except:
                pass

        # Default fallback if no file exists
        return {
            "target": "8.8.8.8",
            "duration": 0,
            "interval": 5
        }

    def save_config_to_file(self):
        try:
            with open(self.config_path, "w") as f:
                json.dump(self.default_config, f, indent=4)
        except Exception as e:
            messagebox.showerror("Error", f"Could not save config:\n{e}")

    # ============================================================
    # LOG TAB SETUP
    # ============================================================
    def build_logs_tab(self):

        self.log_mode = "LIVE"

        top_frame = tb.Frame(self.tab_logs)
        top_frame.pack(fill="x", padx=10, pady=5)

        self.log_status_label = tb.Label(
            top_frame,
            text="Mode: LIVE",
            font=("Segoe UI", 10, "bold")
        )
        self.log_status_label.pack(side="left")

        button_frame = tb.Frame(top_frame)
        button_frame.pack(side="right")

        tb.Button(
            button_frame,
            text="Load Log File",
            command=self.load_log_file
        ).pack(side="left", padx=5)

        tb.Button(
            button_frame,
            text="Clear View",
            command=self.clear_log_view
        ).pack(side="left", padx=5)

        columns = (
            "timestamp",
            "target",
            "status",
            "connection",
            "success_rate"
        )

        self.log_table = tb.Treeview(
            self.tab_logs,
            columns=columns,
            show="headings",
            height=20
        )

        self.log_table.tag_configure("success", foreground="green")
        self.log_table.tag_configure("fail", foreground="red")
        self.log_table.tag_configure("fallback", foreground="orange")

        self.log_table.heading("timestamp", text="Timestamp")
        self.log_table.heading("target", text="Target")
        self.log_table.heading("status", text="Status")
        self.log_table.heading("connection", text="Connection Type")
        self.log_table.heading("success_rate", text="Success Rate")

        self.log_table.column("timestamp", width=160, anchor="center")
        self.log_table.column("target", width=140, anchor="center")
        self.log_table.column("status", width=80, anchor="center")
        self.log_table.column("connection", width=140, anchor="center")
        self.log_table.column("success_rate", width=120, anchor="center")

        scrollbar = tb.Scrollbar(
            self.tab_logs,
            orient="vertical",
            command=self.log_table.yview
        )

        self.log_table.configure(yscrollcommand=scrollbar.set)

        self.log_table.pack(side="left", fill="both", expand=True, padx=(10,0), pady=10)
        scrollbar.pack(side="right", fill="y", pady=10)

        self.update_log_ui()
        self.auto_resize_window()


    # Switch log page to LIVE mode when monitoring starts
    def start_live_logging(self):

        self.log_mode = "LIVE"
        self.log_status_label.config(text="Mode: LIVE")

        # Clear current log table
        for row in self.log_table.get_children():
            self.log_table.delete(row)

    # Update Log UI every few seconds
    def update_log_ui(self):

        if self.log_mode == "LIVE" and self.monitoring_running:

            try:
                while not self.logger.log_queue.empty():

                    entry = self.logger.log_queue.get_nowait()

                    symbol = entry["status_symbol"]

                    if symbol == "  ✓":
                        tag = "success"
                    elif symbol == "  ✕":
                        tag = "fail"
                    else:
                        tag = "fallback"

                    self.log_table.insert(
                        "",
                        "end",
                        values=(
                            entry["timestamp"],
                            entry["target"],
                            entry["status_symbol"],
                            entry["connection_type"],
                            f'{entry["success_rate"]}%'
                        ),
                        tags=(tag,)
                    )

                    self.log_table.yview_moveto(1)

            except:
                pass

        self.root.after(500, self.update_log_ui)

    #Clear log view
    def clear_log_view(self):
        for row in self.log_table.get_children():
            self.log_table.delete(row)

    # Load log file
    def load_log_file(self):

        file_path = filedialog.askopenfilename(
            title="Select Log File",
            filetypes=[("JSON Log Files", "*_monitoring_log.json"), ("All Files", "*.*")]
        )

        if not file_path:
            return

        self.log_mode = "STATIC"
        self.log_status_label.config(text="Mode: STATIC VIEW")
        self.clear_log_view()

        with open(file_path, "r") as f:

            for line in f:

                try:
                    entry = json.loads(line)

                    self.log_table.insert(
                        "",
                        "end",
                        values=(
                            entry["timestamp"],
                            entry["target"],
                            entry["status_symbol"],
                            entry["connection_type"],
                            f'{entry["success_rate"]}%'
                        )
                    )

                except:
                    continue

    # ============================================================
    # TRACE TAB SETUP
    # ============================================================
    def build_trace_tab(self):
        for widget in self.tab_trace.winfo_children():
            widget.destroy()

        container = tb.Frame(self.tab_trace, padding=10)
        container.pack(fill="both", expand=True)

        # Header and buttons
        top_frame = tb.Frame(container)
        top_frame.pack(fill="x", pady=5)

        self.trace_status_label = tb.Label(
            top_frame, text="Trace output will appear here.", font=("Segoe UI", 10, "bold")
        )
        self.trace_status_label.pack(side="left")

        # Buttons frame
        btn_frame = tb.Frame(top_frame)
        btn_frame.pack(side="right")

        # Store the button in an attribute so we can enable/disable it
        self.run_trace_button = tb.Button(
            btn_frame, text="Run Trace Again", bootstyle=PRIMARY, command=self.run_traceroute_once
        )
        self.run_trace_button.pack(side="left", padx=3)

        tb.Button(
            btn_frame, text="Clear View", bootstyle=SECONDARY, command=self.clear_trace_view
        ).pack(side="left", padx=3)

        tb.Button(
            btn_frame, text="Load Trace File", bootstyle=INFO, command=self.load_trace_file
        ).pack(side="left", padx=3)

        # Scrollable Text widget for output
        self.trace_text = tk.Text(container, font=("Consolas", 11), wrap="none")
        self.trace_text.pack(fill="both", expand=True, pady=10, padx=5)

        scrollbar_y = tb.Scrollbar(container, orient="vertical", command=self.trace_text.yview)
        scrollbar_y.pack(side="right", fill="y")
        self.trace_text.configure(yscrollcommand=scrollbar_y.set)

        scrollbar_x = tb.Scrollbar(container, orient="horizontal", command=self.trace_text.xview)
        scrollbar_x.pack(side="bottom", fill="x")
        self.trace_text.configure(xscrollcommand=scrollbar_x.set)

    # ------------------------------------------------------------
    # Clear Trace Text View
    # ------------------------------------------------------------
    def clear_trace_view(self):
        self.trace_text.delete("1.0", tk.END)

    # ------------------------------------------------------------
    # Load saved trace JSON file and display in Text
    # ------------------------------------------------------------
    def load_trace_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Trace File",
            filetypes=[("JSON Log Files", "*.json"), ("All Files", "*.*")]
        )
        if not file_path:
            return

        self.clear_trace_view()

        with open(file_path, "r", encoding="utf-8") as f:
            current_date = datetime.date.today().strftime("%Y-%m-%d")
            self.trace_text.insert(tk.END, f"{current_date}\nLoaded trace log from {os.path.basename(file_path)}\n\n")
            for line in f:
                try:
                    entry = json.loads(line)
                    rtt = entry.get("rtt", "")
                    hop = entry.get("hop", "")
                    ip = entry.get("ip", "")
                    self.trace_text.insert(tk.END, f"{hop:>2}    {rtt}    {ip}\n")
                except:
                    continue

        self.trace_text.insert(tk.END, "\nTrace load complete.\n")
        self.trace_text.see(tk.END)

    # ------------------------------------------------------------
    # Run traceroute once and append to log
    # ------------------------------------------------------------
    def run_traceroute_once(self):
        if not hasattr(self, "config_used"):
            messagebox.showwarning("Trace Error", "Start monitoring first.")
            return

        # Disable the button immediately
        self.run_trace_button.config(state="disabled")

        # Run the actual traceroute in a separate thread
        threading.Thread(target=self._traceroute_thread, daemon=True).start()


    def _traceroute_thread(self):
        target = self.config_used["target"]
        today_str = datetime.date.today().strftime("%Y-%m-%d")
        trace_file = os.path.join(self.data_dir, f"{today_str}_traceroot_log.json")

        # Header line for trace
        self.trace_text.insert(tk.END, f"Traceroute to {target} on {today_str}\n")
        self.trace_text.see(tk.END)

        startupinfo = no_window_subprocess()

        try:
            result = subprocess.run(
                ["tracert", "-d", target],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                startupinfo=startupinfo
            )

            hops_log = []

            for line in result.stdout.splitlines():
                self.trace_text.insert(tk.END, line + "\n")
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0].isdigit():
                    hop = int(parts[0])
                    rtt_ms = " ".join(parts[1:-1])
                    ip = parts[-1]
                    hops_log.append({
                        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "target": target,
                        "hop": hop,
                        "ip": ip,
                        "rtt": rtt_ms
                    })

            self.trace_text.see(tk.END)

            # Append hops to JSON log
            with open(trace_file, "a", encoding="utf-8") as f:
                for entry in hops_log:
                    json.dump(entry, f)
                    f.write("\n")

            self.trace_status_label.config(text=f"Trace completed for {target}.")

        except Exception as e:
            messagebox.showerror("Traceroute Error", str(e))
            self.trace_status_label.config(text=f"Trace failed for {target}.")

        finally:
            # Re-enable the button when done
            self.run_trace_button.config(state="normal")

    # ------------------------------------------------------------
    # Load saved trace JSON file and display in Text
    # ------------------------------------------------------------
    def load_trace_file(self):
        file_path = filedialog.askopenfilename(
            title="Select Trace File",
            filetypes=[("JSON Log Files", "*_traceroot_log.json"), ("All Files", "*.*")]
        )
        if not file_path:
            return

        self.clear_trace_view()

        # Read all entries
        entries = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue

        if not entries:
            return

        # Group entries by timestamp (assuming same timestamp = same trace run)
        from itertools import groupby
        entries.sort(key=lambda x: x["timestamp"])  # ensure chronological order
        for ts, group in groupby(entries, key=lambda x: x["timestamp"]):
            group_list = list(group)
            target = group_list[0].get("target", "Unknown")
            self.trace_text.insert(
                tk.END, f"{ts} Traceroute to {target}\nOver a maximum of 30 hops:\n\n"
            )

            for entry in group_list:
                hop = entry.get("hop", "")
                rtt = entry.get("rtt", "")
                ip = entry.get("ip", "")
                self.trace_text.insert(tk.END, f"{hop:>2}    {rtt}    {ip}\n")

            self.trace_text.insert(tk.END, "\n")  # extra line between trace runs

        self.trace_text.insert(tk.END, "Trace load complete.\n")
        self.trace_text.see(tk.END)

    def create_scrollable_frame(self, parent):

        container = tb.Frame(parent)
        container.pack(fill="both", expand=True)

        canvas = tk.Canvas(container, highlightthickness=0)
        canvas.pack(side="left", fill="both", expand=True)

        scrollbar = tb.Scrollbar(container, orient="vertical", command=canvas.yview)
        scrollbar.pack(side="right", fill="y")

        canvas.configure(yscrollcommand=scrollbar.set)

        scroll_frame = tb.Frame(canvas)

        window_id = canvas.create_window((0, 0), window=scroll_frame, anchor="n")

        # Update scroll region
        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        # Make frame match canvas width
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(window_id, width=e.width)
        )

        return scroll_frame

if __name__ == "__main__":
    TCPMonitorApp()