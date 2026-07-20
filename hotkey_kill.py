import json               # JSON 配置文件的读写
import os                  # 文件路径和环境变量操作
import sys                 # 运行时信息（打包判断、退出等）
import ctypes              # 调用 Windows API (user32/kernel32)
import ctypes.wintypes     # Windows 数据类型定义（RECT 等）
import threading           # 多线程执行耗时任务（坐标校准、自动登录等）
import time                # 延时等待
import tkinter as tk       # GUI 主框架
from tkinter import ttk, messagebox, simpledialog  # 主题控件、弹窗、输入对话框
from datetime import datetime  # 日志时间戳

import psutil              # 跨平台进程管理（遍历、终止进程）
import keyboard            # 全局热键监听与键盘模拟

# pyautogui：鼠标/键盘自动化，用于坐标点击和截图（可选依赖）
try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

# interception：驱动级键鼠输入，绕过部分游戏的输入拦截（可选依赖）
try:
    import interception
    from interception import KeyStroke
    HAS_INTERCEPTION = True
except ImportError:
    HAS_INTERCEPTION = False

# 检测 AutoHotkey 可执行文件路径（打包后优先使用内置的 ahk.exe）
if getattr(sys, 'frozen', False):
    _BUNDLE_DIR = sys._MEIPASS  # PyInstaller 解压的临时目录
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))  # 开发时取脚本所在目录

# 优先查找内置 ahk.exe，找不到则按常见安装路径逐个尝试
AHK_PATH = os.path.join(_BUNDLE_DIR, "ahk.exe")
if not os.path.exists(AHK_PATH):
    AHK_PATH = None
    for path in [
        r"C:\Program Files\AutoHotkey\v2\AutoHotkey.exe",  # v2 版本
        r"C:\Program Files\AutoHotkey\AutoHotkey.exe",      # v1 版本
    ]:
        if os.path.exists(path):
            AHK_PATH = path
            break
HAS_AHK = AHK_PATH is not None  # 标记是否可用

# 获取程序所在目录：打包后为 exe 所在目录，开发时为脚本所在目录
# 注意与 _BUNDLE_DIR 不同：APP_DIR 是用户可见的数据目录，_BUNDLE_DIR 是资源打包目录
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)       # 打包后的 exe 目录
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))  # 开发时的脚本目录

CONFIG_PATH = os.path.join(APP_DIR, "config.json")      # 主配置文件路径
ACCOUNTS_PATH = os.path.join(APP_DIR, "accounts.json")  # 账号数据文件路径
LOG_PATH = os.path.join(APP_DIR, "hotkey_kill.log")     # 日志文件路径

# 加载 Windows 系统 DLL，用于窗口操作和进程管理
user32 = ctypes.windll.user32    # 用户界面相关 API（窗口枚举、焦点、输入等）
kernel32 = ctypes.windll.kernel32  # 内核 API（当前未直接使用，保留备用）

def is_admin():
    """检查当前进程是否以管理员权限运行"""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False

def run_as_admin():
    """如果当前不是管理员，则以管理员身份重新启动程序并退出当前实例"""
    if not is_admin():
        ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, " ".join(sys.argv), None, 1
        )
        sys.exit(0)

def load_config():
    """加载配置文件，不存在则创建默认配置；返回完整配置字典"""
    default = {
        "hotkey": "ctrl+alt+k",                           # 默认触发热键
        "processes": ["notepad.exe"],                      # 默认要终止的进程列表
        "show_notification": True,                         # 是否显示桌面通知
        "log_to_file": True,                               # 是否记录到日志文件
        "wegame_path": r"C:\Program Files (x86)\WeGame\WeGame.exe",  # WeGame 默认安装路径
    }
    if not os.path.exists(CONFIG_PATH):
        save_config(default)
        return default
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return {**default, **cfg}  # 用默认值补齐缺失的字段
    except Exception:
        return default

def save_config(cfg):
    """将配置字典写入 JSON 文件"""
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4, ensure_ascii=False)

def load_accounts():
    """加载账号列表，不存在则创建空文件；返回账号字典列表"""
    if not os.path.exists(ACCOUNTS_PATH):
        save_accounts([])
        return []
    try:
        with open(ACCOUNTS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_accounts(accounts):
    """将账号列表写入 JSON 文件"""
    with open(ACCOUNTS_PATH, "w", encoding="utf-8") as f:
        json.dump(accounts, f, indent=4, ensure_ascii=False)

# ---- Win32 API 函数别名 ----
EnumWindows = user32.EnumWindows                # 枚举所有顶层窗口
GetWindowTextW = user32.GetWindowTextW          # 获取窗口标题文本（Unicode 版）
GetWindowTextLengthW = user32.GetWindowTextLengthW  # 获取窗口标题文本长度
IsWindowVisible = user32.IsWindowVisible        # 判断窗口是否可见
SetForegroundWindow = user32.SetForegroundWindow  # 将窗口设为前台焦点
ShowWindow = user32.ShowWindow                  # 显示/隐藏/最小化/最大化窗口
GetWindowRect = user32.GetWindowRect            # 获取窗口矩形坐标（左上右下）
GetClassNameW = user32.GetClassNameW            # 获取窗口类名
GetWindowLongW = user32.GetWindowLongW          # 获取窗口属性（样式、扩展样式等）
MapVirtualKeyW = user32.MapVirtualKeyW          # 虚拟键码与扫描码互转

SW_RESTORE = 9  # ShowWindow 参数：恢复窗口（非最小化/最大化）
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)  # 窗口枚举回调函数类型

def find_window_by_title(keyword):
    """根据标题关键字模糊搜索可见窗口，返回 [(hwnd, title), ...] 列表"""
    result = []
    def callback(hwnd, _):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                GetWindowTextW(hwnd, buf, length + 1)
                if keyword.lower() in buf.value.lower():
                    result.append((hwnd, buf.value))
        return True  # 返回 True 继续枚举下一个窗口
    EnumWindows(WNDENUMPROC(callback), 0)
    return result

def activate_window(hwnd):
    """将指定窗口恢复并设为前台焦点"""
    ShowWindow(hwnd, SW_RESTORE)  # 如果窗口最小化则恢复
    time.sleep(0.2)
    SetForegroundWindow(hwnd)      # 设为前台焦点
    time.sleep(0.3)


# Fluent Design 风格配色方案（参照 Windows 11 / macOS 设计语言）
FLUENT = {
    "bg":           "#fafafa",   # 页面背景色（浅灰白）
    "card":         "#ffffff",   # 卡片背景色（纯白）
    "card_border":  "#e8e8ec",   # 卡片边框色
    "accent":       "#2563eb",   # 主题强调色（蓝色，用于主要按钮）
    "accent_hover": "#1d4ed8",   # 强调色悬停态
    "accent_press": "#1e40af",   # 强调色按下态
    "text":         "#18181b",   # 主文字色（近黑）
    "text_sec":     "#71717a",   # 次要文字色（灰色）
    "text_inv":     "#ffffff",   # 反色文字（白底上用于深色按钮）
    "input_bg":     "#ffffff",   # 输入框背景色
    "input_border": "#d4d4d8",   # 输入框边框色
    "input_focus":  "#2563eb",   # 输入框聚焦边框色
    "log_bg":       "#18181b",   # 日志区域背景色（深色终端风格）
    "log_fg":       "#a1a1aa",   # 日志前景色（浅灰）
    "log_fg2":      "#d4d4d8",   # 日志前景色（稍亮，用于 WeGame 日志）
    "danger":       "#dc2626",   # 危险操作色（红色，用于停止/删除）
    "success":      "#16a34a",   # 成功状态色（绿色）
    "tree_sel":     "#eff6ff",   # Treeview 选中行背景色（浅蓝）
    "tree_head":    "#f4f4f5",   # Treeview 表头背景色
    "separator":    "#e4e4e7",   # 分隔线颜色
}


class FluentButton(tk.Button):
    """Fluent 风格按钮：支持 default / accent / danger 三种样式，自带悬停和按下变色效果"""

    def __init__(self, parent, text="", command=None, style="default", **kw):
        c = self._calc_colors(style)
        bg = kw.pop("bg", c["bg"])
        super().__init__(parent, text=text, command=command,
                         font=("Inter", 9), cursor="hand2",  # 手型光标
                         bg=bg, fg=c["fg"], activebackground=c["press"],
                         activeforeground=c["fg"], relief="flat", borderwidth=0,
                         padx=12, pady=6, highlightthickness=0, **kw)
        self._default_bg = bg
        self._hover_bg = c["hover"]
        self._press_bg = c["press"]
        # 绑定鼠标事件实现悬停/按下颜色变化
        self.bind("<Enter>", lambda e: self.configure(bg=self._hover_bg))
        self.bind("<Leave>", lambda e: self.configure(bg=self._default_bg))
        self.bind("<ButtonPress-1>", lambda e: self.configure(bg=self._press_bg))

    @staticmethod
    def _calc_colors(style):
        """根据样式名返回对应的颜色配置字典（bg, fg, hover, press）"""
        if style == "accent":
            return {"bg": FLUENT["accent"], "fg": FLUENT["text_inv"],
                    "hover": FLUENT["accent_hover"], "press": FLUENT["accent_press"]}
        if style == "danger":
            return {"bg": FLUENT["danger"], "fg": FLUENT["text_inv"],
                    "hover": "#b91c1c", "press": "#991b1b"}
        return {"bg": "#ffffff", "fg": FLUENT["text"],
                "hover": "#f4f4f5", "press": "#e4e4e7"}


class Card(ttk.Frame):
    """Fluent 风格卡片容器：带边框、可选标题和分隔线，内容放在 self.body 中"""

    def __init__(self, parent, title="", **kw):
        super().__init__(parent, style="Card.TFrame", **kw)
        # 外层边框（1px 阴影效果）
        outer = tk.Frame(self, bg=FLUENT["card_border"], padx=1, pady=1)
        outer.pack(fill="both", expand=True, padx=2, pady=2)
        inner = tk.Frame(outer, bg=FLUENT["card"])
        inner.pack(fill="both", expand=True)
        if title:
            # 标题标签
            tk.Label(inner, text=title, font=("Inter", 10, "bold"),
                     bg=FLUENT["card"], fg=FLUENT["text"]).pack(anchor="w", padx=16, pady=(12, 0))
            # 标题下方分隔线
            sep = tk.Frame(inner, bg=FLUENT["separator"], height=1)
            sep.pack(fill="x", padx=16, pady=(8, 0))
        # 内容区域（子控件应添加到 self.body）
        self.body = tk.Frame(inner, bg=FLUENT["card"])
        self.body.pack(fill="both", expand=True, padx=16, pady=12)


class HotkeyKillApp:
    """主应用程序类：集成一键退出游戏和 WeGame 自动登录两大功能"""

    def __init__(self):
        run_as_admin()  # 确保以管理员权限运行（终止进程需要）
        self.cfg = load_config()
        self.accounts = []           # 账号列表
        self.running = False         # 热键监听状态
        self.current_hotkey = None   # 当前注册的热键 ID（用于取消注册）
        self.lock = threading.Lock() # 防止热键触发时的并发冲突

        # 创建主窗口
        self.root = tk.Tk()
        self.root.title("尽量快乐LOL")
        self.root.geometry("1500x1200")
        self.root.minsize(900, 700)
        self.root.configure(bg=FLUENT["bg"])

        self._try_set_dpi()          # 设置高 DPI 感知
        self._configure_styles()     # 配置 ttk 样式
        self._build_ui()             # 构建界面
        self._load_ui_from_config()  # 从配置加载初始值到界面
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)  # 关闭窗口时保存配置

    def _try_set_dpi(self):
        """设置进程 DPI 感知，避免高分辨率屏幕下界面模糊"""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 1 = PROCESS_SYSTEM_DPI_AWARE
        except Exception:
            pass  # 旧版 Windows 不支持，忽略

    def _configure_styles(self):
        """配置 ttk 控件的全局样式，实现 Fluent 风格外观"""
        s = ttk.Style()
        s.theme_use("default")  # 使用默认主题作为基础

        # 卡片框架样式
        s.configure("Card.TFrame", background=FLUENT["card"])

        # 选项卡（Notebook）样式
        s.configure("TNotebook", background=FLUENT["bg"], borderwidth=0)
        s.configure("TNotebook.Tab", background=FLUENT["card"], foreground=FLUENT["text_sec"],
                     padding=[20, 8], font=("Inter", 10))
        s.map("TNotebook.Tab",
               background=[("selected", FLUENT["card"])],
               foreground=[("selected", FLUENT["accent"])])  # 选中时文字变蓝色

        # 框架样式
        s.configure("TFrame", background=FLUENT["bg"])
        s.configure("CardInner.TFrame", background=FLUENT["card"])

        # 标签样式（普通、次要、大标题、卡片标题）
        s.configure("TLabel", background=FLUENT["card"], foreground=FLUENT["text"],
                     font=("Inter", 10))
        s.configure("Sec.TLabel", background=FLUENT["card"], foreground=FLUENT["text_sec"],
                     font=("Inter", 9))
        s.configure("Title.TLabel", background=FLUENT["bg"], foreground=FLUENT["text"],
                     font=("Inter", 18, "bold"))
        s.configure("CardTitle.TLabel", background=FLUENT["card"], foreground=FLUENT["text"],
                     font=("Inter", 10, "bold"))

        # 输入框样式（聚焦时边框变蓝）
        s.configure("TEntry", fieldbackground=FLUENT["input_bg"], foreground=FLUENT["text"],
                     borderwidth=1, relief="solid", font=("Inter", 10))
        s.map("TEntry", fieldbackground=[("focus", FLUENT["input_bg"])],
               bordercolor=[("focus", FLUENT["input_focus"])])

        # 按钮样式
        s.configure("TButton", font=("Inter", 10), padding=(12, 6))
        s.configure("Accent.TButton", font=("Inter", 10, "bold"), padding=(14, 8))

        # 复选框样式
        s.configure("TCheckbutton", background=FLUENT["card"], foreground=FLUENT["text"],
                     font=("Inter", 10))

        # 表格（Treeview）样式
        s.configure("Treeview", background=FLUENT["card"], foreground=FLUENT["text"],
                     fieldbackground=FLUENT["card"], font=("Inter", 10), rowheight=32,
                     borderwidth=0)
        s.configure("Treeview.Heading", background=FLUENT["tree_head"], foreground=FLUENT["text_sec"],
                     font=("Inter", 10, "bold"), relief="flat")
        s.map("Treeview", background=[("selected", FLUENT["tree_sel"])],
               foreground=[("selected", FLUENT["accent"])])

        # 分隔线样式
        s.configure("Horizontal.TSeparator", background=FLUENT["separator"])

    def _build_ui(self):
        """构建主界面：标题栏 + 两个选项卡（一键退出游戏 / WeGame 自动登录）"""
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)  # 选项卡区域可伸缩

        # 顶部标题
        header = tk.Frame(self.root, bg=FLUENT["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=24, pady=(20, 12))
        tk.Label(header, text="尽量快乐LOL", font=("Inter", 20, "bold"),
                 bg=FLUENT["bg"], fg=FLUENT["text"]).pack(side="left")

        # 选项卡容器
        notebook = ttk.Notebook(self.root)
        notebook.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))

        tab1 = ttk.Frame(notebook)
        tab2 = ttk.Frame(notebook)
        notebook.add(tab1, text="  一键退出游戏  ")
        notebook.add(tab2, text="  WeGame 自动登录  ")

        self._build_tab_kill(tab1)      # 构建第一个选项卡
        self._build_tab_wegame(tab2)    # 构建第二个选项卡

    def _build_tab_kill(self, parent):
        """构建"一键退出游戏"选项卡：左侧设置+目标进程，右侧日志"""
        parent.columnconfigure(0, weight=2, minsize=400)  # 左侧占 2/3，最小400px
        parent.columnconfigure(1, weight=1, minsize=200)  # 右侧占 1/3，最小200px
        parent.rowconfigure(0, weight=1)

        # 左侧：设置区域
        left = tk.Frame(parent, bg=FLUENT["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        # 热键设置卡片：输入框 + 录制按钮
        card1 = Card(left, title="热键设置")
        card1.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        body = card1.body

        r = tk.Frame(body, bg=FLUENT["card"])
        r.pack(fill="x")
        tk.Label(r, text="触发热键", bg=FLUENT["card"], fg=FLUENT["text"],
                 font=("Inter", 10)).pack(side="left")
        self.hotkey_var = tk.StringVar()
        e = ttk.Entry(r, textvariable=self.hotkey_var, width=20)
        e.pack(side="left", padx=(16, 12))
        FluentButton(r, text="设置热键", command=self._record_hotkey).pack(side="left")
        tk.Label(body, text="格式: ctrl+alt+k / shift+f1 等", bg=FLUENT["card"],
                 fg=FLUENT["text_sec"], font=("Inter", 9)).pack(anchor="w", pady=(6, 0))

        # 目标进程卡片：列表 + 添加/删除/从运行中选择
        card2 = Card(left, title="目标进程")
        card2.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        body2 = card2.body
        body2.rowconfigure(0, weight=1)
        body2.columnconfigure(0, weight=1)

        # 目标进程列表（等宽字体方便对齐进程名）
        self.proc_listbox = tk.Listbox(body2, bg=FLUENT["card"], fg=FLUENT["text"],
            selectbackground=FLUENT["tree_sel"], selectforeground=FLUENT["accent"],
            font=("Consolas", 10), borderwidth=1, relief="solid",
            highlightthickness=0, activestyle="none", width=45)
        self.proc_listbox.grid(row=0, column=0, sticky="nsew", pady=(0, 10))

        # 操作按钮行
        abtn = tk.Frame(body2, bg=FLUENT["card"])
        abtn.grid(row=1, column=0, sticky="w")
        FluentButton(abtn, text="添加", command=self._add_process).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="删除", command=self._remove_process).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="从运行中选择", command=self._pick_running).pack(side="left")

        # 选项和控制按钮
        ctrl = tk.Frame(left, bg=FLUENT["bg"])
        ctrl.grid(row=2, column=0, sticky="ew", pady=(0, 0))

        # 选项卡片：通知和日志开关
        card3 = Card(ctrl, title="选项")
        card3.pack(fill="x", pady=(0, 8))
        body3 = card3.body
        self.notify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(body3, text="显示通知", variable=self.notify_var).pack(side="left")
        self.log_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(body3, text="记录日志", variable=self.log_var).pack(side="left", padx=(24, 0))

        # 启动/停止监听按钮（accent 蓝色样式）
        self.toggle_btn = FluentButton(ctrl, text="启动监听", command=self._toggle,
                                        style="accent")
        self.toggle_btn.pack(fill="x")

        # 右侧：日志区域（深色终端风格）
        right = tk.Frame(parent, bg=FLUENT["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        card4 = Card(right, title="运行日志")
        card4.grid(row=0, column=0, sticky="nsew")
        body4 = card4.body
        body4.rowconfigure(0, weight=1)
        body4.columnconfigure(0, weight=1)
        # 日志文本框（只读，深色背景，等宽字体；width=25 限制最小宽度，避免撑大右列）
        self.log_text = tk.Text(body4, bg=FLUENT["log_bg"], fg=FLUENT["log_fg"],
            font=("Cascadia Code", 10), borderwidth=0, state="disabled",
            highlightthickness=0, insertbackground=FLUENT["log_fg"], wrap="word", width=25)
        self.log_text.grid(row=0, column=0, sticky="nsew")

        self.log_visible = True

    def _build_tab_wegame(self, parent):
        """构建"WeGame 自动登录"选项卡：左侧设置+账号管理，右侧操作+日志"""
        parent.columnconfigure(0, weight=2, minsize=400)  # 左侧占 2/3，最小400px
        parent.columnconfigure(1, weight=1, minsize=200)  # 右侧占 1/3，最小200px
        parent.rowconfigure(0, weight=1)

        # 左侧：设置和账号管理
        left = tk.Frame(parent, bg=FLUENT["bg"])
        left.grid(row=0, column=0, sticky="nsew", padx=(12, 6), pady=12)
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        # WeGame 路径设置卡片
        c1 = Card(left, title="WeGame 路径")
        c1.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        prow = c1.body
        self.wegame_path_var = tk.StringVar()
        ttk.Entry(prow, textvariable=self.wegame_path_var).pack(side="left", fill="x", expand=True, padx=(0, 12))
        FluentButton(prow, text="浏览", command=self._browse_wegame).pack(side="right")

        # 登录设置卡片：窗口关键字、操作延迟等
        c2 = Card(left, title="登录设置")
        c2.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        sbody = c2.body

        r1 = tk.Frame(sbody, bg=FLUENT["card"])
        r1.pack(fill="x", pady=(0, 6))
        # 窗口关键字：用于模糊匹配 WeGame 窗口标题
        tk.Label(r1, text="窗口关键字", bg=FLUENT["card"], fg=FLUENT["text"],
                 font=("Inter", 10)).pack(side="left")
        self.win_keyword_var = tk.StringVar(value="WeGame")
        ttk.Entry(r1, textvariable=self.win_keyword_var, width=16).pack(side="left", padx=(16, 24))
        # 操作延迟：每次键盘输入之间的间隔（毫秒）
        tk.Label(r1, text="操作延迟(ms)", bg=FLUENT["card"], fg=FLUENT["text"],
                 font=("Inter", 10)).pack(side="left")
        self.action_delay_var = tk.StringVar(value="50")
        ttk.Entry(r1, textvariable=self.action_delay_var, width=8).pack(side="left", padx=(16, 0))

        # 定位模式（当前固定使用坐标模式）
        self.locate_mode = tk.StringVar(value="coords")

        # 账号管理卡片：表格形式管理 WeGame 账号
        c3 = Card(left, title="账号管理")
        c3.grid(row=2, column=0, sticky="nsew", pady=(0, 8))
        abody = c3.body
        abody.rowconfigure(0, weight=1)
        abody.columnconfigure(0, weight=1)

        # 三列：账号、密码、备注
        cols = ("account", "password", "name")
        self.acc_tree = ttk.Treeview(abody, columns=cols, show="headings", height=10)
        self.acc_tree.heading("account", text="账号")
        self.acc_tree.heading("password", text="密码")
        self.acc_tree.heading("name", text="备注")
        self.acc_tree.column("account", width=180, minwidth=150)
        self.acc_tree.column("password", width=180, minwidth=150)
        self.acc_tree.column("name", width=160, minwidth=120)
        self.acc_tree.grid(row=0, column=0, sticky="nsew", pady=(0, 10))

        # 账号操作按钮行
        abtn = tk.Frame(abody, bg=FLUENT["card"])
        abtn.grid(row=1, column=0, sticky="w")
        FluentButton(abtn, text="添加账号", command=self._add_account).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="编辑", command=self._edit_account).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="删除", command=self._del_account).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="校准坐标", command=self._calibrate).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="导入账号", command=self._import_accounts).pack(side="left")

        # 双击表格行可直接编辑单元格
        self.acc_tree.bind("<Double-1>", self._on_tree_double_click)

        # 一键登录按钮（放在左侧最下方）
        self.login_btn = FluentButton(left, text="一键登录 WeGame",
                                       command=self._do_wegame_login,
                                       style="accent")
        self.login_btn.grid(row=3, column=0, sticky="ew", pady=(8, 0))

        # 右侧：纯日志区域
        right = tk.Frame(parent, bg=FLUENT["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 12), pady=12)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        # 操作日志卡片
        c4 = Card(right, title="操作日志")
        c4.grid(row=0, column=0, sticky="nsew")
        lbody = c4.body
        lbody.rowconfigure(0, weight=1)
        lbody.columnconfigure(0, weight=1)

        # WeGame 操作日志文本框（只读，深色背景）
        # width=25 限制最小宽度，避免撑大右列
        self.wegame_log = tk.Text(lbody, bg=FLUENT["log_bg"], fg=FLUENT["log_fg2"],
            font=("Cascadia Code", 10), borderwidth=0, state="disabled",
            highlightthickness=0, wrap="word", width=25)
        self.wegame_log.grid(row=0, column=0, sticky="nsew")

    def _wlog(self, msg):
        """向 WeGame 日志区域追加一行带时间戳的日志"""
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {msg}\n"
            self.wegame_log.configure(state="normal")   # 临时启用编辑
            self.wegame_log.insert(tk.END, line)
            self.wegame_log.see(tk.END)                 # 自动滚动到底部
            self.wegame_log.configure(state="disabled")  # 恢复只读
        except tk.TclError:
            pass

    def _load_ui_from_config(self):
        """从配置文件和账号文件加载初始值填充到界面控件"""
        # 填充热键设置
        self.hotkey_var.set(self.cfg.get("hotkey", "ctrl+alt+k"))
        self.notify_var.set(self.cfg.get("show_notification", True))
        self.log_var.set(self.cfg.get("log_to_file", True))
        # 填充目标进程列表
        for p in self.cfg.get("processes", []):
            self.proc_listbox.insert(tk.END, p)
        # 填充 WeGame 设置
        self.wegame_path_var.set(self.cfg.get("wegame_path", ""))
        self.action_delay_var.set(str(self.cfg.get("action_delay", 50)))
        self.locate_mode.set("coords")
        # 填充账号表格
        self.accounts = load_accounts()
        for acc in self.accounts:
            self.acc_tree.insert("", tk.END, values=(acc.get("account", ""), acc.get("password", ""), acc.get("name", "")))
        # 补充空行使表格至少显示 10 行
        for _ in range(10 - len(self.accounts)):
            self.acc_tree.insert("", tk.END, values=("", "", ""))
        self._update_window_height()

    def _update_window_height(self):
        """根据账号数量动态调整窗口高度，最多不超过屏幕 85%"""
        count = len(self.acc_tree.get_children())
        row_h = 32  # Treeview 每行高度（像素）
        base_h = 800  # 基础窗口高度
        extra = max(0, count - 10) * row_h  # 超过 10 个账号后每多一个加一行高度
        new_h = min(base_h + extra, int(self.root.winfo_screenheight() * 0.85))
        self.root.geometry(f"1500x{new_h}")

    def _save_ui_to_config(self):
        """将界面当前状态保存到配置文件和账号文件"""
        processes = list(self.proc_listbox.get(0, tk.END))
        accounts = []
        for item in self.acc_tree.get_children():
            vals = self.acc_tree.item(item, "values")
            if vals[0]:  # 只保存有账号的行（跳过空行）
                accounts.append({"account": vals[0], "password": vals[1], "name": vals[2]})
        self.accounts = accounts
        save_accounts(accounts)
        self.cfg = {
            "hotkey": self.hotkey_var.get().strip(),
            "processes": processes,
            "show_notification": self.notify_var.get(),
            "log_to_file": self.log_var.get(),
            "wegame_path": self.wegame_path_var.get().strip(),
            "action_delay": int(self.action_delay_var.get() or 50),
            "locate_mode": "coords",
        }
        save_config(self.cfg)

    def _find_account(self, account_id):
        """按账号 ID 在账号列表中查找，返回账号字典或 None"""
        for acc in self.accounts:
            if acc.get("account") == account_id:
                return acc
        return None

    def _log(self, msg):
        """向一键退出游戏的日志区域追加一行带时间戳的日志"""
        try:
            ts = datetime.now().strftime("%H:%M:%S")
            line = f"[{ts}] {msg}\n"
            self.log_text.configure(state="normal")
            self.log_text.insert(tk.END, line)
            self.log_text.see(tk.END)
            self.log_text.configure(state="disabled")
        except tk.TclError:
            pass

    def _record_hotkey(self):
        """弹出热键录制对话框：用户按下组合键后自动识别并设置"""
        dlg = tk.Toplevel(self.root)
        dlg.title("录制热键")
        dlg.geometry("360x160")
        dlg.configure(bg=FLUENT["bg"])
        dlg.resizable(False, False)
        dlg.grab_set()          # 模态对话框
        dlg.transient(self.root)  # 依附主窗口
        tk.Label(dlg, text="按下想要的组合键...", font=("Inter", 12),
                 bg=FLUENT["bg"], fg=FLUENT["text"]).pack(pady=28)
        hint = tk.Label(dlg, text="", font=("Inter", 11, "bold"),
                        bg=FLUENT["bg"], fg=FLUENT["accent"])
        hint.pack()
        pressed = set()  # 记录当前按下的键
        def on_key(e):
            if e.event_type == "down":
                pressed.add(e.name)
                hint.configure(text=" + ".join(sorted(pressed)))  # 实时显示按键
            if e.event_type == "up" and pressed:
                combo = "+".join(sorted(pressed))  # 按字母排序拼接
                keyboard.unhook_all()  # 取消键盘钩子
                self.hotkey_var.set(combo)
                dlg.destroy()
        keyboard.hook(on_key)  # 注册全局键盘钩子

    def _add_process(self):
        """弹出输入对话框，手动添加一个进程名到目标列表"""
        name = simpledialog.askstring("添加进程", "输入进程名 (如 notepad.exe):", parent=self.root)
        if name and name.strip():
            self.proc_listbox.insert(tk.END, name.strip())
            self._save_ui_to_config()

    def _remove_process(self):
        """从目标列表中删除选中的进程"""
        sel = self.proc_listbox.curselection()
        if sel:
            self.proc_listbox.delete(sel[0])
            self._save_ui_to_config()

    def _pick_running(self):
        """弹出对话框列出当前运行的所有进程，双击即可添加到目标列表"""
        win = tk.Toplevel(self.root)
        win.title("选择运行中的进程")
        win.geometry("460x520")
        win.configure(bg=FLUENT["bg"])
        win.grab_set()
        win.transient(self.root)
        tk.Label(win, text="双击添加到目标列表", font=("Inter", 10),
                 bg=FLUENT["bg"], fg=FLUENT["text_sec"]).pack(pady=10)
        lb = tk.Listbox(win, bg=FLUENT["card"], fg=FLUENT["text"],
            selectbackground=FLUENT["tree_sel"], selectforeground=FLUENT["accent"],
            font=("Inter", 10), borderwidth=1, relief="solid", highlightthickness=0)
        lb.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        # 遍历所有运行中的进程，去重并排序
        procs = sorted(set(
            p.info["name"] for p in psutil.process_iter(["name"])
            if p.info["name"] and p.info["name"] != "System"
        ), key=str.lower)
        for p in procs:
            lb.insert(tk.END, p)
        def on_dbl(event):
            s = lb.curselection()
            if s:
                name = lb.get(s[0])
                existing = list(self.proc_listbox.get(0, tk.END))
                if name not in existing:  # 避免重复添加
                    self.proc_listbox.insert(tk.END, name)
                    self._save_ui_to_config()
                win.destroy()
        lb.bind("<Double-Button-1>", on_dbl)

    def _toggle(self):
        """切换监听状态（启动/停止）"""
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        """注册全局热键并开始监听，按钮变为红色停止监听"""
        hotkey = self.hotkey_var.get().strip()
        if not hotkey:
            messagebox.showwarning("提示", "请先设置热键")
            return
        processes = list(self.proc_listbox.get(0, tk.END))
        if not processes:
            messagebox.showwarning("提示", "请先添加目标进程")
            return
        self._save_ui_to_config()
        try:
            # 注册全局热键，触发时通过 after 在主线程执行 _do_kill
            self.current_hotkey = keyboard.add_hotkey(hotkey, lambda: self.root.after(0, self._do_kill))
        except ValueError as e:
            messagebox.showerror("热键错误", f"无效的热键格式: {e}")
            return
        self.running = True
        # 切换按钮为危险样式（红色）
        try:
            c = FluentButton._calc_colors("danger")
            self.toggle_btn.configure(text="停止监听", bg=c["bg"], fg=c["fg"],
                                       activebackground=c["press"])
            self.toggle_btn._default_bg = c["bg"]
            self.toggle_btn._hover_bg = c["hover"]
            self.toggle_btn._press_bg = c["press"]
        except tk.TclError:
            pass
        self._log(f"监听已启动 | 热键: {hotkey} | 目标: {', '.join(processes)}")

    def _stop(self):
        """取消热键注册并停止监听，按钮恢复为蓝色启动监听"""
        if self.current_hotkey is not None:
            try:
                keyboard.remove_hotkey(self.current_hotkey)
            except Exception:
                pass
            self.current_hotkey = None
        self.running = False
        # 切换按钮为主题样式（蓝色）
        try:
            c = FluentButton._calc_colors("accent")
            self.toggle_btn.configure(text="启动监听", bg=c["bg"], fg=c["fg"],
                                       activebackground=c["press"])
            self.toggle_btn._default_bg = c["bg"]
            self.toggle_btn._hover_bg = c["hover"]
            self.toggle_btn._press_bg = c["press"]
        except tk.TclError:
            pass
        self._log("监听已停止")

    def _do_kill(self):
        """热键触发时执行：遍历所有进程，终止匹配的目标进程"""
        with self.lock:  # 防止快速连按导致并发
            names = [n.lower() for n in self.cfg.get("processes", [])]
            killed, failed = [], []
            # 遍历所有运行中的进程
            for proc in psutil.process_iter(["pid", "name"]):
                pname = proc.info["name"]
                if pname and pname.lower() in names:
                    try:
                        psutil.Process(proc.info["pid"]).kill()  # 强制终止进程
                        killed.append(f"{pname}(PID:{proc.info['pid']})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                        failed.append(f"{pname}: {e}")
            # 记录结果
            if killed:
                self._log(f"✓ 已终止: {', '.join(killed)}")
            if failed:
                self._log(f"✗ 失败: {', '.join(failed)}")
            if not killed and not failed:
                self._log(f"? 未找到: {', '.join(self.cfg.get('processes', []))}")

    def _browse_wegame(self):
        """弹出文件选择对话框，让用户指定 WeGame.exe 路径"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择 WeGame.exe",
            filetypes=[("可执行文件", "*.exe")],
            initialdir=r"C:\Program Files (x86)\WeGame"
        )
        if path:
            self.wegame_path_var.set(path)
            self._save_ui_to_config()

    def _add_account(self):
        """在账号表格末尾添加一行空行供用户填写"""
        self.acc_tree.insert("", tk.END, values=("", "", ""))
        self._update_window_height()

    def _on_tree_double_click(self, event):
        """双击表格单元格时，在原位创建内联编辑框进行编辑"""
        region = self.acc_tree.identify_region(event.x, event.y)
        if region != "cell":
            return  # 只处理单元格区域的双击
        column = self.acc_tree.identify_column(event.x)
        item = self.acc_tree.identify_row(event.y)
        if not item or not column:
            return

        # 获取列索引（identify_column 返回 "#1", "#2", "#3" 格式）
        col_idx = int(column.replace("#", "")) - 1
        if col_idx < 0 or col_idx > 2:
            return

        # 获取当前单元格的值
        vals = self.acc_tree.item(item, "values")
        current_val = vals[col_idx]

        # 获取单元格在画布中的位置和尺寸
        bbox = self.acc_tree.bbox(item, column)
        if not bbox:
            return

        x, y, width, height = bbox

        # 在单元格位置创建内联编辑框
        entry = tk.Entry(self.acc_tree, font=("Inter", 10), relief="solid", borderwidth=1)
        entry.place(x=x, y=y, width=width, height=height)
        entry.insert(0, current_val)
        entry.select_range(0, tk.END)  # 全选
        entry.focus_set()

        def on_confirm(event=None):
            """确认编辑：更新表格值并保存到文件"""
            new_val = entry.get().strip()
            entry.destroy()
            new_vals = list(vals)
            new_vals[col_idx] = new_val
            self.acc_tree.item(item, values=new_vals)
            self._save_accounts_from_tree()

        def on_cancel(event=None):
            """取消编辑：销毁编辑框"""
            entry.destroy()

        entry.bind("<Return>", on_confirm)    # 回车确认
        entry.bind("<Escape>", on_cancel)     # Esc 取消
        entry.bind("<FocusOut>", on_confirm)  # 失去焦点也确认

    def _save_accounts_from_tree(self):
        """从 Treeview 表格中提取所有有效账号并保存到文件"""
        accounts = []
        for item in self.acc_tree.get_children():
            vals = self.acc_tree.item(item, "values")
            if vals[0]:  # 只保存有账号的行（跳过空行）
                accounts.append({"account": vals[0], "password": vals[1], "name": vals[2]})
        self.accounts = accounts
        save_accounts(accounts)

    def _edit_account(self):
        """弹出编辑对话框修改选中账号的信息"""
        sel = self.acc_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个账号")
            return
        item = sel[0]
        vals = self.acc_tree.item(item, "values")
        # 创建编辑对话框
        dlg = tk.Toplevel(self.root)
        dlg.title("编辑账号")
        dlg.geometry("400x200")
        dlg.configure(bg=FLUENT["bg"])
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)

        container = tk.Frame(dlg, bg=FLUENT["bg"])
        container.pack(fill="both", expand=True, padx=20, pady=20)

        tk.Label(container, text="编辑账号", font=("Inter", 14, "bold"),
                 bg=FLUENT["bg"], fg=FLUENT["text"]).pack(anchor="w", pady=(0, 16))

        fields = tk.Frame(container, bg=FLUENT["bg"])
        fields.pack(fill="x")

        tk.Label(fields, text="账号", bg=FLUENT["bg"], fg=FLUENT["text"],
                 font=("Inter", 10)).grid(row=0, column=0, sticky="w", pady=(0, 8))
        acc_var = tk.StringVar(value=vals[0])
        ttk.Entry(fields, textvariable=acc_var, width=30).grid(row=0, column=1, sticky="ew", pady=(0, 8))

        tk.Label(fields, text="密码", bg=FLUENT["bg"], fg=FLUENT["text"],
                 font=("Inter", 10)).grid(row=1, column=0, sticky="w", pady=(0, 8))
        pwd_var = tk.StringVar(value=vals[1])
        ttk.Entry(fields, textvariable=pwd_var, width=30).grid(row=1, column=1, sticky="ew", pady=(0, 8))

        tk.Label(fields, text="备注", bg=FLUENT["bg"], fg=FLUENT["text"],
                 font=("Inter", 10)).grid(row=2, column=0, sticky="w", pady=(0, 8))
        name_var = tk.StringVar(value=vals[2])
        ttk.Entry(fields, textvariable=name_var, width=30).grid(row=2, column=1, sticky="ew", pady=(0, 8))

        fields.columnconfigure(1, weight=1)

        btn_frame = tk.Frame(container, bg=FLUENT["bg"])
        btn_frame.pack(fill="x", pady=(16, 0))

        def on_ok():
            new_acc = acc_var.get().strip()
            new_pwd = pwd_var.get().strip()
            new_name = name_var.get().strip()
            if not new_acc:
                messagebox.showwarning("提示", "账号不能为空", parent=dlg)
                return
            self.acc_tree.item(item, values=(new_acc, new_pwd, new_name))
            # 更新 accounts 列表
            for a in self.accounts:
                if a.get("account") == vals[0]:
                    a["account"] = new_acc
                    a["password"] = new_pwd
                    a["name"] = new_name
                    break
            else:
                if new_acc:
                    self.accounts.append({"account": new_acc, "password": new_pwd, "name": new_name})
            save_accounts(self.accounts)
            dlg.destroy()

        FluentButton(btn_frame, text="取消", command=dlg.destroy).pack(side="right", padx=(8, 0))
        FluentButton(btn_frame, text="确定", command=on_ok, style="accent").pack(side="right")

    def _del_account(self):
        """删除选中的账号行，并补充空行保持至少 10 行"""
        sel = self.acc_tree.selection()
        if not sel:
            return
        vals = self.acc_tree.item(sel[0], "values")
        self.acc_tree.delete(sel[0])
        # 同步删除 accounts 列表中的对应项
        self.accounts = [a for a in self.accounts if a.get("account") != vals[0]]
        save_accounts(self.accounts)
        # 保持表格至少显示 10 行
        if len(self.acc_tree.get_children()) < 10:
            self.acc_tree.insert("", tk.END, values=("", "", ""))
        self._update_window_height()

    def _import_accounts(self):
        """从 JSON 文件导入账号列表（自动跳过重复项）"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择 accounts.json",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
            initialdir=os.path.dirname(os.path.abspath(__file__))
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                imported = json.load(f)
            if not isinstance(imported, list):
                messagebox.showerror("格式错误", "文件内容应为 JSON 数组")
                return
            existing = {a.get("account") for a in self.accounts}  # 已有账号集合
            added = 0
            for acc in imported:
                if not isinstance(acc, dict) or not acc.get("account"):
                    continue  # 跳过无效条目
                if acc["account"] in existing:
                    continue  # 跳过重复账号
                self.acc_tree.insert("", tk.END, values=(
                    acc["account"], acc.get("password", ""), acc.get("name", "")
                ))
                self.accounts.append(acc)
                existing.add(acc["account"])
                added += 1
            save_accounts(self.accounts)
            # 补充空行保持至少 10 行
            while len(self.acc_tree.get_children()) < 10:
                self.acc_tree.insert("", tk.END, values=("", "", ""))
            self._update_window_height()
            messagebox.showinfo("导入完成", f"成功导入 {added} 个账号")
        except Exception as e:
            messagebox.showerror("导入失败", str(e))

    def _calibrate(self):
        """坐标校准：让用户点击 WeGame 的账号输入框，3秒后自动采集鼠标位置"""
        keyword = self.win_keyword_var.get().strip() or "WeGame"
        windows = find_window_by_title(keyword)
        if not windows:
            messagebox.showwarning("提示", f"未找到包含 '{keyword}' 的窗口，请先打开 WeGame")
            return

        messagebox.showinfo("坐标校准",
            "即将开始校准，请点击：\n\n"
            "账号输入框\n\n"
            "等待3秒后自动采集鼠标位置")

        self._wlog("坐标校准开始...")

        def capture_points():
            """在后台线程中执行坐标采集（需要等待用户移动鼠标）"""
            if not HAS_PYAUTOGUI:
                self._wlog("错误: 未安装 pyautogui")
                return

            coords = {}

            # 采集账号输入框坐标：提示用户点击后等待3秒
            self.root.after(0, lambda: self._wlog("请点击: 账号输入框"))
            time.sleep(3)  # 等待用户将鼠标移到目标位置
            x, y = pyautogui.position()  # 读取当前鼠标坐标
            coords["username"] = {"x": x, "y": y}
            self.root.after(0, lambda px=x, py=y: self._wlog(f"  账号输入框: ({px}, {py})"))

            # 保存坐标到全局配置
            self.cfg["input_coords"] = coords
            save_config(self.cfg)
            self.root.after(0, lambda: self._wlog("✓ 坐标校准完成并已保存"))

        threading.Thread(target=capture_points, daemon=True).start()

    def _do_wegame_login(self):
        """一键登录入口：校验参数后隐藏主窗口，启动后台登录线程"""
        if not HAS_PYAUTOGUI:
            messagebox.showerror("错误", "未安装 pyautogui，请运行: pip install pyautogui")
            return
        sel = self.acc_tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先选择一个账号")
            return
        vals = self.acc_tree.item(sel[0], "values")
        account = vals[0]
        password = vals[1]
        if not account or not password:
            messagebox.showwarning("提示", "账号或密码为空，请编辑账号信息")
            return

        # 从全局配置读取校准坐标
        coords = self.cfg.get("input_coords", {})
        if not coords.get("username", {}).get("x"):
            messagebox.showwarning("提示", "坐标未校准，请先点击「校准坐标」")
            return

        # 隐藏主窗口，避免遮挡 WeGame 窗口
        self.root.withdraw()
        self.root.update()  # 立即刷新 UI 使隐藏生效

        # 在后台线程执行登录操作
        threading.Thread(target=self._wegame_login_worker, args=(account, password, coords), daemon=True).start()

    def _wegame_login_worker(self, account, password, coords):
        """后台登录工作线程：启动 WeGame（如未运行）→ 激活窗口 → 输入账号密码 → 回车登录"""
        self._wlog("=" * 40)
        self._wlog(f"开始自动登录: {account}")

        if not HAS_INTERCEPTION:
            self._wlog("✗ 未安装 interception-python，请运行: pip install interception-python")
            return

        keyword = self.win_keyword_var.get().strip() or "WeGame"
        delay = int(self.action_delay_var.get() or 50) / 1000.0  # 毫秒转秒

        wegame_path = self.wegame_path_var.get().strip()
        windows = find_window_by_title(keyword)

        # 如果 WeGame 未运行，尝试自动启动
        if not windows:
            if wegame_path and os.path.exists(wegame_path):
                self._wlog("WeGame 未运行，正在启动...")
                os.startfile(wegame_path)
                # 最多等待 20 秒
                for i in range(20):
                    time.sleep(1)
                    windows = find_window_by_title(keyword)
                    if windows:
                        break
                    self._wlog(f"  等待启动... ({i+1}s)")
                if not windows:
                    self._wlog("✗ 启动超时，未找到 WeGame 窗口")
                    return
            else:
                self._wlog("✗ 未找到 WeGame 窗口且路径无效")
                return

        hwnd, title = windows[0]
        self._wlog(f"找到窗口: {title}")

        # 激活窗口（恢复 + 设为前台）
        activate_window(hwnd)
        time.sleep(1)

        uc = coords.get("username", {})
        if not uc.get("x"):
            self._wlog("✗ 坐标未校准，请先点击「校准坐标」")
            return

        try:
            # 第一步：使用 Interception 驱动级点击账号输入框
            self._wlog(f"点击账号框: ({uc['x']}, {uc['y']})")
            SetForegroundWindow(hwnd)
            time.sleep(0.05)
            interception.click(uc["x"], uc["y"], delay=0.3)  # 驱动级点击，绕过游戏拦截
            time.sleep(0.3)

            # 第二步：Ctrl+A 全选并清除旧内容，然后输入账号
            with interception.hold_key("ctrl"):
                interception.press("a")
            time.sleep(0.05)
            interception.write(account, interval=delay)  # 逐字符输入
            self._wlog("✓ 账号已输入 (Interception驱动级)")

            # 第三步：Tab 跳转到密码输入框
            time.sleep(0.3)
            interception.press("tab")
            time.sleep(0.3)

            # 第四步：Ctrl+A 全选并清除旧内容，然后输入密码
            with interception.hold_key("ctrl"):
                interception.press("a")
            time.sleep(0.05)
            interception.write(password, interval=delay)
            self._wlog("✓ 密码已输入 (Interception驱动级)")

            # 第五步：回车提交登录
            time.sleep(0.3)
            interception.press("enter")
            self._wlog("✓ 已按回车登录，等待结果...")

            time.sleep(3)  # 等待登录响应
            self._wlog("✓ 自动登录流程完成")

        except Exception as e:
            self._wlog(f"✗ 登录出错: {e}")
        finally:
            time.sleep(1)
            self.root.after(0, lambda: self.root.deiconify())  # 恢复主窗口显示



    def _on_close(self):
        """窗口关闭事件处理：保存配置、停止监听、销毁窗口"""
        try:
            self._save_ui_to_config()  # 关闭前保存配置
            self._stop()               # 停止热键监听
            self.root.destroy()
        except tk.TclError:
            pass

    def run(self):
        """启动 Tkinter 主事件循环"""
        self.root.mainloop()


if __name__ == "__main__":
    app = HotkeyKillApp()
    app.run()
