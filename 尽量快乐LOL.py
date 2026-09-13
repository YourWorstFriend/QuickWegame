import json               # JSON 配置文件的读写
import os                  # 文件路径和环境变量操作
os.environ.setdefault("PNG_WARNINGS", "0")  # 抑制 libpng iCCP 警告
import sys                 # 运行时信息（打包判断、退出等）
import ctypes              # 调用 Windows API (user32/kernel32)
import ctypes.wintypes     # Windows 数据类型定义（RECT 等）
import threading           # 多线程执行耗时任务（坐标校准、自动登录等）
import time                # 延时等待
import tkinter as tk       # GUI 主框架
from tkinter import ttk, messagebox, simpledialog  # 主题控件、弹窗、输入对话框
from datetime import datetime  # 日志时间戳
import csv                 # CSV 文件读写

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
    try:
        # 初始化interception，获取设备句柄
        interception.auto_capture_devices(keyboard=True, mouse=True, verbose=False)
    except Exception as e:
        print(f"Interception初始化失败: {e}")
        HAS_INTERCEPTION = False
except ImportError:
    HAS_INTERCEPTION = False

# 检测 AutoHotkey 可执行文件路径（打包后优先使用内置的 ahk.exe）
if getattr(sys, 'frozen', False):
    _BUNDLE_DIR = sys._MEIPASS  # PyInstaller 解压的临时目录
else:
    _BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))  # 开发时取脚本所在目录



# 获取程序所在目录：打包后为 exe 所在目录，开发时为脚本所在目录
# 注意与 _BUNDLE_DIR 不同：APP_DIR 是用户可见的数据目录，_BUNDLE_DIR 是资源打包目录
if getattr(sys, 'frozen', False):
    APP_DIR = os.path.dirname(sys.executable)       # 打包后的 exe 目录
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))  # 开发时的脚本目录

CONFIG_PATH = os.path.join(APP_DIR, "config.json")      # 主配置文件路径
ACCOUNTS_PATH = os.path.join(APP_DIR, "账号（accounts）.csv")   # 账号数据文件路径（CSV格式）
ACCOUNTS_JSON_PATH = os.path.join(APP_DIR, "accounts.json")  # 旧版JSON账号文件路径（用于迁移）
PROCS_PATH = os.path.join(APP_DIR, "进程（processes）.txt")     # 目标进程列表文件路径
LOG_PATH = os.path.join(APP_DIR, "hotkey_kill.log")     # 日志文件路径

# 加载 Windows 系统 DLL，用于窗口操作和进程管理
user32 = ctypes.windll.user32    # 用户界面相关 API（窗口枚举、焦点、输入等）

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

def migrate_json_to_csv():
    """迁移旧版JSON账号数据到CSV格式（如果CSV不存在且JSON存在）"""
    if os.path.exists(ACCOUNTS_PATH):
        # CSV文件已存在，无需迁移
        return False
    if not os.path.exists(ACCOUNTS_JSON_PATH):
        # JSON文件不存在，无需迁移
        return False
    try:
        with open(ACCOUNTS_JSON_PATH, "r", encoding="utf-8") as f:
            accounts = json.load(f)
        if not isinstance(accounts, list):
            return False
        # 保存为CSV格式
        save_accounts(accounts)
        # 重命名旧文件作为备份
        backup_path = ACCOUNTS_JSON_PATH + ".bak"
        if not os.path.exists(backup_path):
            os.rename(ACCOUNTS_JSON_PATH, backup_path)
        return True
    except Exception:
        return False

def load_accounts():
    """加载账号列表，支持CSV和JSON格式（向后兼容）；返回账号字典列表"""
    # 首次运行时尝试迁移
    migrate_json_to_csv()
    
    # 优先读取CSV
    if os.path.exists(ACCOUNTS_PATH):
        try:
            accounts = []
            with open(ACCOUNTS_PATH, "r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    accounts.append({
                        "account": row.get("账号", ""),
                        "password": row.get("密码", ""),
                        "name": row.get("备注", "")
                    })
            return accounts
        except Exception:
            pass
    
    # 回退读取JSON（兼容旧版）
    if os.path.exists(ACCOUNTS_JSON_PATH):
        try:
            with open(ACCOUNTS_JSON_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    
    # 都不存在，创建空CSV文件
    save_accounts([])
    return []

def save_accounts(accounts):
    """将账号列表写入CSV文件"""
    with open(ACCOUNTS_PATH, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["账号", "密码", "备注"])
        writer.writeheader()
        for acc in accounts:
            writer.writerow({
                "账号": acc.get("account", ""),
                "密码": acc.get("password", ""),
                "备注": acc.get("name", "")
            })

def load_processes():
    """从 processes.txt 读取目标进程列表（每行一个）"""
    if not os.path.exists(PROCS_PATH):
        return ["notepad.exe"]
    try:
        with open(PROCS_PATH, "r", encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except Exception:
        return ["notepad.exe"]

def save_processes(processes):
    """将目标进程列表写入 processes.txt"""
    with open(PROCS_PATH, "w", encoding="utf-8") as f:
        for p in processes:
            f.write(p + "\n")

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
    wegame_keywords = ["wegame", "腾讯游戏", "tgp", "tencent"]
    
    def callback(hwnd, _):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.lower()
                # 匹配策略：用户指定关键字 或 WeGame相关关键字
                if keyword.lower() in title or any(kw in title for kw in wegame_keywords):
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

# 小米开源字体 MiSans
FONT_FAMILY = "MiSans"
FONT_MONO = "MiSans"

# 小米 MiMo Desktop 现代简洁风格配色
# 核心思路：统一暖灰背景 + 纯白卡片 + 多层渐变阴影分割（无边框线）+ 橙色主强调
FLUENT = {
    "bg":           "#f0f0f0",   # 页面背景 & 标题栏同色
    "card":         "#ffffff",   # 卡片背景：纯白
    "shadow_1":     "#e0e0e0",   # 阴影层1（最外层，最深）
    "shadow_2":     "#e8e8e8",   # 阴影层2（中间层）
    "shadow_3":     "#eeeeee",   # 阴影层3（最内层，最浅）
    "accent":       "#ff6a00",   # 小米橙：主强调色
    "accent_hover": "#e55d00",   # 橙色悬停态
    "accent_press": "#cc5200",   # 橙色按下态
    "text":         "#1a1a1a",   # 主文字色：近黑
    "text_sec":     "#888888",   # 次要文字色：中灰
    "text_inv":     "#ffffff",   # 反色文字（深色按钮上）
    "input_bg":     "#ffffff",   # 输入框背景
    "input_border": "#e0e0e0",   # 输入框边框
    "input_focus":  "#ff6a00",   # 输入框聚焦边框色
    "log_bg":       "#2a2a2a",   # 日志区域深色背景
    "log_fg":       "#b0b0b0",   # 日志浅灰前景
    "log_fg2":      "#d4d4d4",   # 日志稍亮前景
    "danger":       "#e53935",   # 危险色：柔和红
    "success":      "#43a047",   # 成功色：柔和绿
    "tree_sel":     "#fff3e6",   # 表格选中行：极淡橙色
    "tree_head":    "#fafafa",   # 表头背景：极浅灰
    "separator":    "#f0f0f0",   # 分隔线：与背景同色（不可见）
    "tab_active":   "#1890ff",   # 选项卡选中态：蓝色
}


class FluentButton(tk.Button):
    """MiMo 风格按钮：支持 default / accent / danger 三种样式，圆润感 + 悬停变色"""

    def __init__(self, parent, text="", command=None, style="default", **kw):
        c = self._calc_colors(style)
        bg = kw.pop("bg", c["bg"])
        font = kw.pop("font", (FONT_FAMILY, 10))  # 【本轮修改】允许外部覆盖 font，修复重复参数崩溃
        super().__init__(parent, text=text, command=command,
                         font=font, cursor="hand2",
                         bg=bg, fg=c["fg"], activebackground=c["press"],
                         activeforeground=c["fg"], relief="flat", borderwidth=0,
                         padx=14, pady=7, highlightthickness=0,
                         highlightbackground=bg, **kw)
        self._default_bg = bg
        self._hover_bg = c["hover"]
        self._press_bg = c["press"]
        self.bind("<Enter>", lambda e: self.configure(bg=self._hover_bg))
        self.bind("<Leave>", lambda e: self.configure(bg=self._default_bg))
        self.bind("<ButtonPress-1>", lambda e: self.configure(bg=self._press_bg))

    @staticmethod
    def _calc_colors(style):
        if style == "accent":
            return {"bg": FLUENT["accent"], "fg": FLUENT["text_inv"],
                    "hover": FLUENT["accent_hover"], "press": FLUENT["accent_press"]}
        if style == "danger":
            return {"bg": FLUENT["danger"], "fg": FLUENT["text_inv"],
                    "hover": "#c62828", "press": "#b71c1c"}
        return {"bg": "#ffffff", "fg": FLUENT["text"],
                "hover": "#f0f0f0", "press": "#e0e0e0"}


class Card(ttk.Frame):
    """MiMo 风格卡片：无边框无阴影，纯白底直接与背景对比，内容放在 self.body"""

    def __init__(self, parent, title="", **kw):
        super().__init__(parent, style="Card.TFrame", **kw)
        inner = tk.Frame(self, bg=FLUENT["card"])
        inner.pack(fill="both", expand=True)
        if title:
            # 【本轮修改】模块标题：字号 11→13，加粗，深色，缩进 18→20
            tk.Label(inner, text=title, font=(FONT_FAMILY, 13),
                     bg=FLUENT["card"], fg=FLUENT["text"]).pack(anchor="w", padx=20, pady=(16, 0))
        self.body = tk.Frame(inner, bg=FLUENT["card"])
        self.body.pack(fill="both", expand=True, padx=20, pady=(10 if title else 14, 14))


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
        self._base_w = 1500
        self._base_h = 1200
        self._scale = 1.0

        self._try_set_dpi()          # 设置高 DPI 感知
        self._set_titlebar_color()   # 标题栏颜色与背景一致
        self._configure_styles()     # 配置 ttk 样式
        self._build_ui()             # 构建界面
        self._load_ui_from_config()  # 从配置加载初始值到界面
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Configure>", self._on_resize)

    def _on_resize(self, event):
        """窗口缩放时按 min(宽比, 高比) 等比放大字体"""
        if event.widget != self.root:
            return
        w, h = event.width, event.height
        scale = min(w / self._base_w, h / self._base_h)
        if abs(scale - self._scale) < 0.02:
            return
        self._scale = scale
        s = ttk.Style()
        fs = max(8, int(10 * scale))
        s.configure("TLabel", font=(FONT_FAMILY, fs))
        s.configure("TEntry", font=(FONT_FAMILY, fs))
        s.configure("TButton", font=(FONT_FAMILY, fs))
        s.configure("Treeview", font=(FONT_FAMILY, fs), rowheight=max(24, int(36 * scale)))
        s.configure("Treeview.Heading", font=(FONT_FAMILY, fs))
        s.configure("TCheckbutton", font=(FONT_FAMILY, fs))
        self._draw_tabs()

    def _try_set_dpi(self):
        """设置进程 DPI 感知，避免高分辨率屏幕下界面模糊"""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 1 = PROCESS_SYSTEM_DPI_AWARE
        except Exception:
            pass  # 旧版 Windows 不支持，忽略

    def _set_titlebar_color(self):
        """设置标题栏颜色与页面背景一致（需要 Windows 11 22H2+）"""
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            # DWMWA_CAPTION_COLOR = 35，Windows 11 22H2+ 支持
            # 颜色格式: COLORREF = 0x00BBGGRR
            bg = FLUENT["bg"].lstrip("#")
            r, g, b = int(bg[0:2], 16), int(bg[2:4], 16), int(bg[4:6], 16)
            colorref = r | (g << 8) | (b << 16)
            DWMWA_CAPTION_COLOR = 35
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(ctypes.c_int(colorref)), 4
            )
        except Exception:
            pass

    def _configure_styles(self):
        """配置 ttk 控件样式，实现 MiMo Desktop 现代简洁外观"""
        s = ttk.Style()
        s.theme_use("default")

        s.configure("Card.TFrame", background=FLUENT["bg"])

        s.configure("TFrame", background=FLUENT["bg"])

        s.configure("TLabel", background=FLUENT["card"], foreground=FLUENT["text"],
                     font=(FONT_FAMILY, 10))
        s.configure("Sec.TLabel", background=FLUENT["card"], foreground=FLUENT["text_sec"],
                     font=(FONT_FAMILY, 9))
        s.configure("Title.TLabel", background=FLUENT["bg"], foreground=FLUENT["text"],
                     font=(FONT_FAMILY, 20))
        s.configure("CardTitle.TLabel", background=FLUENT["card"], foreground=FLUENT["text"],
                     font=(FONT_FAMILY, 11))

        s.configure("TEntry", fieldbackground=FLUENT["input_bg"], foreground=FLUENT["text"],
                     borderwidth=1, relief="solid", font=(FONT_FAMILY, 10))
        s.map("TEntry", fieldbackground=[("focus", FLUENT["input_bg"])],
               bordercolor=[("focus", FLUENT["input_focus"])])

        s.configure("TButton", font=(FONT_FAMILY, 10), padding=(12, 7))
        s.configure("Accent.TButton", font=(FONT_FAMILY, 11, "bold"), padding=(16, 9))

        s.configure("TCheckbutton", background=FLUENT["card"], foreground=FLUENT["text"],
                     font=(FONT_FAMILY, 10))

        # 表格：行高 36px，选中行淡橙色
        s.configure("Treeview", background=FLUENT["card"], foreground=FLUENT["text"],
                     fieldbackground=FLUENT["card"], font=(FONT_FAMILY, 10), rowheight=36,
                     borderwidth=0)
        s.configure("Treeview.Heading", background=FLUENT["tree_head"], foreground=FLUENT["text_sec"],
                     font=(FONT_FAMILY, 10), relief="flat")
        s.map("Treeview", background=[("selected", FLUENT["tree_sel"])],
               foreground=[("selected", FLUENT["text"])])

        s.configure("Horizontal.TSeparator", background=FLUENT["separator"])

    def _build_ui(self):
        """构建主界面：标签栏 + 内容区"""
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # 顶部标题栏
        # 自定义标签栏
        self.tab_names = ["一键退出游戏", "WeGame 自动登录"]
        self.current_tab = 0
        self.tab_hover = -1
        self.tab_bar = tk.Canvas(self.root, bg=FLUENT["bg"], highlightthickness=0,
                                 height=80, bd=0)
        self.tab_bar.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 0))
        self.tab_bar.bind("<Button-1>", self._on_tab_click)
        self.tab_bar.bind("<Motion>", self._on_tab_hover)
        self.tab_bar.bind("<Leave>", lambda e: self._clear_hover())
        self.tab_bar.bind("<Configure>", lambda e: self._draw_tabs())

        # 内容容器：白色背景，与选中标签无缝连接
        self.content_frame = tk.Frame(self.root, bg=FLUENT["bg"])
        self.content_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 20))
        self.content_frame.columnconfigure(0, weight=1)
        self.content_frame.rowconfigure(0, weight=1)

        self.tab_frames = []
        for i in range(2):
            f = tk.Frame(self.content_frame, bg=FLUENT["bg"])
            f.grid(row=0, column=0, sticky="nsew")
            self.tab_frames.append(f)

        self._build_tab_kill(self.tab_frames[0])
        self._build_tab_wegame(self.tab_frames[1])

        self.tab_frames[1].grid_remove()
        self.root.after(50, self._draw_tabs)

    def _draw_tabs(self):
        """Folder Tab：选中白色，顶部外凸圆角，底部内凹圆角与内容区融合"""
        self.tab_bar.delete("all")
        bg = FLUENT["bg"]
        card = FLUENT["card"]
        text_color = FLUENT["text"]
        text_sec = FLUENT["text_sec"]

        bar_h = 80  # 等于画布高度，消除底部灰色空隙
        tab_top = 4
        tab_pad = 8
        r = 10
        font = (FONT_FAMILY, 11)
        font_bold = (FONT_FAMILY, 11)

        # 宽度：中文18px，英文10px，空格6px，padding 60px
        widths = []
        for name in self.tab_names:
            char_w = 0
            for c in name:
                if ord(c) > 127:
                    char_w += 18
                elif c == ' ':
                    char_w += 6
                else:
                    char_w += 10
            widths.append(char_w + 60)

        x = 14  # 与内容区 left 框架的 padx=(14,7) 对齐
        self._tab_rects = []
        for i, name in enumerate(self.tab_names):
            w = widths[i]
            is_selected = (i == self.current_tab)

            if is_selected:
                # 主体矩形
                self.tab_bar.create_rectangle(x + r, tab_top, x + w - r, bar_h, fill=card, outline="")
                self.tab_bar.create_rectangle(x, tab_top + r, x + w, bar_h, fill=card, outline="")
                # 左上外凸：圆心(x+r, tab_top+r)，北→西
                self.tab_bar.create_arc(x, tab_top, x + 2*r, tab_top + 2*r,
                                        start=90, extent=90, fill=card, outline="")
                # 右上外凸：圆心(x+w-r, tab_top+r)，东→北
                self.tab_bar.create_arc(x + w - 2*r, tab_top, x + w, tab_top + 2*r,
                                        start=0, extent=90, fill=card, outline="")
                # ── 右下内凹 ──
                # 白色正方形
                self.tab_bar.create_rectangle(x + w, bar_h - r, x + w + r, bar_h, fill=card, outline="")
                # 灰色弧：圆心与正方形右上角共用
                self.tab_bar.create_arc(x + w, bar_h - 2*r, x + w + 2*r, bar_h,
                                        start=180, extent=90, fill=bg, outline="")
                cx = x + w // 2
                cy = (tab_top + bar_h) // 2
                self.tab_bar.create_text(cx, cy, text=name, fill=text_color,
                                         font=font_bold, tags=f"tab_{i}")
            else:
                cx = x + w // 2
                cy = (tab_top + bar_h) // 2
                self.tab_bar.create_text(cx, cy, text=name, fill=text_sec,
                                         font=font, tags=f"tab_{i}")

            self._tab_rects.append((x, tab_top, x + w, bar_h, i))
            x += w + tab_pad

    def _on_tab_click(self, event):
        for x1, y1, x2, y2, idx in self._tab_rects:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                self._switch_tab(idx)
                break

    def _on_tab_hover(self, event):
        new_hover = -1
        for x1, y1, x2, y2, idx in self._tab_rects:
            if x1 <= event.x <= x2 and y1 <= event.y <= y2:
                if idx != self.current_tab:
                    new_hover = idx
                break
        if new_hover != self.tab_hover:
            self.tab_hover = new_hover
            self._draw_tabs()

    def _clear_hover(self):
        if self.tab_hover != -1:
            self.tab_hover = -1
            self._draw_tabs()

    def _switch_tab(self, idx):
        if idx == self.current_tab:
            return
        self.tab_frames[self.current_tab].grid_remove()
        self.current_tab = idx
        self.tab_frames[idx].grid()
        self._draw_tabs()

    def _build_tab_kill(self, parent):
        """构建"一键退出游戏"选项卡"""
        parent.columnconfigure(0, weight=2, minsize=420)
        parent.columnconfigure(1, weight=1, minsize=220)
        parent.rowconfigure(0, weight=1)

        left = tk.Frame(parent, bg=FLUENT["card"])
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=(0, 14))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        # ── 热键设置 ──
        card1 = Card(left, title="热键设置")
        card1.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        body = card1.body

        r = tk.Frame(body, bg=FLUENT["card"])
        r.pack(fill="x", padx=(32, 0))
        # 【本轮修改】字段标签：中灰 text_sec，固定 width=8 对齐，按钮字号 9px
        tk.Label(r, text="触发热键", bg=FLUENT["card"], fg=FLUENT["text_sec"],
                 font=(FONT_FAMILY, 10), width=8, anchor="w").pack(side="left")
        self.hotkey_var = tk.StringVar()
        e = ttk.Entry(r, textvariable=self.hotkey_var, width=20)
        e.pack(side="left", padx=(8, 12))
        FluentButton(r, text="录制", command=self._record_hotkey,
                     font=(FONT_FAMILY, 9)).pack(side="left")
        # 【本轮修改】说明文字：浅灰 #a0a0a0，字号 9px，左侧缩进 8px
        tk.Label(body, text="格式: ctrl+alt+k / shift+f1 等", bg=FLUENT["card"],
                 fg="#a0a0a0", font=(FONT_FAMILY, 9)).pack(anchor="w", padx=(32, 0), pady=(6, 0))

        # ── 目标进程 ──
        card2 = Card(left, title="目标进程")
        card2.grid(row=1, column=0, sticky="nsew", pady=(0, 10))
        body2 = card2.body
        body2.rowconfigure(0, weight=1)
        body2.columnconfigure(0, weight=1)

        self.proc_listbox = tk.Listbox(body2, bg=FLUENT["card"], fg=FLUENT["text"],
            selectbackground=FLUENT["tree_sel"], selectforeground=FLUENT["accent"],
            font=(FONT_FAMILY, 10), borderwidth=0, relief="flat",
            highlightthickness=0, highlightbackground=FLUENT["shadow_3"],
            activestyle="none", width=42)
        self.proc_listbox.grid(row=0, column=0, sticky="nsew", padx=(32, 0), pady=(0, 10))

        abtn = tk.Frame(body2, bg=FLUENT["card"])
        abtn.grid(row=1, column=0, sticky="w", padx=(18, 0))
        FluentButton(abtn, text="添加", command=self._add_process,
                     font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="删除", command=self._remove_process,
                     font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="从运行中选择", command=self._pick_running,
                     font=(FONT_FAMILY, 9)).pack(side="left")

        # ── 选项 ──
        ctrl = tk.Frame(left, bg=FLUENT["card"])
        ctrl.grid(row=2, column=0, sticky="ew")

        card3 = Card(ctrl, title="选项")
        card3.pack(fill="x", pady=(0, 10))
        body3 = card3.body
        body3_inner = tk.Frame(body3, bg=FLUENT["card"])
        body3_inner.pack(fill="x", padx=(32, 0))
        self.notify_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(body3_inner, text="显示通知", variable=self.notify_var).pack(side="left")
        self.log_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(body3_inner, text="记录日志", variable=self.log_var).pack(side="left", padx=(28, 0))

        self.toggle_btn = FluentButton(ctrl, text="▶  启动监听", command=self._toggle,
                                        style="accent")
        self.toggle_btn.pack(fill="x")

        right = tk.Frame(parent, bg=FLUENT["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=(0, 14))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        # 运行日志区域：与背景融合，无底框
        log_frame = tk.Frame(right, bg=FLUENT["bg"])
        log_frame.grid(row=0, column=0, sticky="nsew")
        log_frame.rowconfigure(1, weight=1)
        log_frame.columnconfigure(0, weight=1)
        tk.Label(log_frame, text="运行日志", font=(FONT_FAMILY, 13, "bold"),
                 bg=FLUENT["bg"], fg=FLUENT["text"]).grid(row=0, column=0, sticky="w", padx=(32, 0), pady=(0, 8))
        self.log_text = tk.Text(log_frame, bg=FLUENT["bg"], fg="#888888",
            font=(FONT_MONO, 10), borderwidth=0, state="disabled",
            highlightthickness=0, insertbackground="#888888", wrap="word", width=26)
        self.log_text.grid(row=1, column=0, sticky="nsew")

        self.log_visible = True

    def _build_tab_wegame(self, parent):
        """构建"WeGame 自动登录"选项卡"""
        parent.columnconfigure(0, weight=2, minsize=420)
        parent.columnconfigure(1, weight=1, minsize=220)
        parent.rowconfigure(0, weight=1)

        left = tk.Frame(parent, bg=FLUENT["card"])
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=(0, 14))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        # ── WeGame 路径 ──
        c1 = Card(left, title="WeGame 路径")
        c1.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        prow = c1.body
        self.wegame_path_var = tk.StringVar()
        ttk.Entry(prow, textvariable=self.wegame_path_var).pack(side="left", fill="x", expand=True, padx=(32, 10))
        # 【本轮修改】浏览按钮字号 9px
        FluentButton(prow, text="浏览", command=self._browse_wegame,
                     font=(FONT_FAMILY, 9)).pack(side="right")

        # ── 登录设置 ──
        c2 = Card(left, title="登录设置")
        c2.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        sbody = c2.body

        r1 = tk.Frame(sbody, bg=FLUENT["card"])
        r1.pack(fill="x", padx=(32, 0), pady=(0, 4))
        # 【本轮修改】字段标签：中灰 text_sec，固定 width=10 统一对齐线
        tk.Label(r1, text="窗口关键字", bg=FLUENT["card"], fg=FLUENT["text_sec"],
                 font=(FONT_FAMILY, 10), width=10, anchor="w").pack(side="left")
        self.win_keyword_var = tk.StringVar(value="WeGame")
        ttk.Entry(r1, textvariable=self.win_keyword_var, width=14).pack(side="left", padx=(8, 24))
        tk.Label(r1, text="操作延迟(ms)", bg=FLUENT["card"], fg=FLUENT["text_sec"],
                 font=(FONT_FAMILY, 10), width=10, anchor="w").pack(side="left")
        self.action_delay_var = tk.StringVar(value="50")
        ttk.Entry(r1, textvariable=self.action_delay_var, width=6).pack(side="left", padx=(8, 0))

        self.locate_mode = tk.StringVar(value="coords")

        c3 = Card(left, title="账号管理")
        c3.grid(row=2, column=0, sticky="nsew", pady=(0, 10))
        abody = c3.body
        abody.rowconfigure(0, weight=1)
        abody.columnconfigure(0, weight=1)

        cols = ("account", "password", "name")
        self.acc_tree = ttk.Treeview(abody, columns=cols, show="headings", height=10)
        self.acc_tree.heading("account", text="账号")
        self.acc_tree.heading("password", text="密码")
        self.acc_tree.heading("name", text="备注")
        self.acc_tree.column("account", width=180, minwidth=150)
        self.acc_tree.column("password", width=180, minwidth=150)
        self.acc_tree.column("name", width=160, minwidth=120)
        self.acc_tree.grid(row=0, column=0, sticky="nsew", padx=(32, 0), pady=(0, 12))

        abtn = tk.Frame(abody, bg=FLUENT["card"])
        abtn.grid(row=1, column=0, sticky="w", padx=(32, 0))
        FluentButton(abtn, text="添加", command=self._add_account,
                     font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="编辑", command=self._edit_account,
                     font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="删除", command=self._del_account,
                     font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="校准坐标", command=self._calibrate,
                     font=(FONT_FAMILY, 9)).pack(side="left", padx=(0, 6))
        FluentButton(abtn, text="导入", command=self._import_accounts,
                     font=(FONT_FAMILY, 9)).pack(side="left")

        self.acc_tree.bind("<Double-1>", self._on_tree_double_click)

        self.login_btn = FluentButton(left, text="🎮  一键登录 WeGame",
                                       command=self._do_wegame_login,
                                       style="accent")
        self.login_btn.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        right = tk.Frame(parent, bg=FLUENT["card"])
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=(0, 14))
        right = tk.Frame(parent, bg=FLUENT["bg"])
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=(0, 14))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        # 操作日志区域：与背景融合，无底框
        log_frame2 = tk.Frame(right, bg=FLUENT["bg"])
        log_frame2.grid(row=0, column=0, sticky="nsew")
        log_frame2.rowconfigure(1, weight=1)
        log_frame2.columnconfigure(0, weight=1)
        tk.Label(log_frame2, text="操作日志", font=(FONT_FAMILY, 13, "bold"),
                 bg=FLUENT["bg"], fg=FLUENT["text"]).grid(row=0, column=0, sticky="w", padx=(32, 0), pady=(0, 8))
        self.wegame_log = tk.Text(log_frame2, bg=FLUENT["bg"], fg="#888888",
            font=(FONT_MONO, 10), borderwidth=0, state="disabled",
            highlightthickness=0, wrap="word", width=26)
        self.wegame_log.grid(row=1, column=0, sticky="nsew")

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
        # 填充目标进程列表（从 processes.txt 读取）
        for p in load_processes():
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
        save_processes(processes)
        self.cfg = {
            "hotkey": self.hotkey_var.get().strip(),
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
        dlg.geometry("380x180")
        dlg.configure(bg=FLUENT["bg"])
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)
        tk.Label(dlg, text="按下想要的组合键…", font=(FONT_FAMILY, 12),
                 bg=FLUENT["bg"], fg=FLUENT["text_sec"]).pack(pady=32)
        hint = tk.Label(dlg, text="", font=(FONT_FAMILY, 14),
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
        win.geometry("480x540")
        win.configure(bg=FLUENT["bg"])
        win.grab_set()
        win.transient(self.root)
        tk.Label(win, text="双击添加到目标列表", font=(FONT_FAMILY, 10),
                 bg=FLUENT["bg"], fg=FLUENT["text_sec"]).pack(pady=12)
        lb = tk.Listbox(win, bg=FLUENT["card"], fg=FLUENT["text"],
            selectbackground=FLUENT["tree_sel"], selectforeground=FLUENT["accent"],
            font=(FONT_FAMILY, 10), borderwidth=0, relief="flat", highlightthickness=0)
        lb.pack(fill="both", expand=True, padx=18, pady=(0, 14))
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
            names = [n.lower() for n in load_processes()]
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
        entry = tk.Entry(self.acc_tree, font=(FONT_FAMILY, 10), relief="solid", borderwidth=1,
                         highlightthickness=1, highlightcolor=FLUENT["input_focus"],
                         highlightbackground=FLUENT["input_border"])
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
        dlg.geometry("420x220")
        dlg.configure(bg=FLUENT["bg"])
        dlg.resizable(False, False)
        dlg.grab_set()
        dlg.transient(self.root)

        container = tk.Frame(dlg, bg=FLUENT["bg"])
        container.pack(fill="both", expand=True, padx=22, pady=22)

        tk.Label(container, text="编辑账号", font=(FONT_FAMILY, 14),
                 bg=FLUENT["bg"], fg=FLUENT["text"]).pack(anchor="w", pady=(0, 18))

        fields = tk.Frame(container, bg=FLUENT["bg"])
        fields.pack(fill="x")

        tk.Label(fields, text="账号", bg=FLUENT["bg"], fg=FLUENT["text"],
                 font=(FONT_FAMILY, 10)).grid(row=0, column=0, sticky="w", pady=(0, 10))
        acc_var = tk.StringVar(value=vals[0])
        ttk.Entry(fields, textvariable=acc_var, width=30).grid(row=0, column=1, sticky="ew", pady=(0, 10))

        tk.Label(fields, text="密码", bg=FLUENT["bg"], fg=FLUENT["text"],
                 font=(FONT_FAMILY, 10)).grid(row=1, column=0, sticky="w", pady=(0, 10))
        pwd_var = tk.StringVar(value=vals[1])
        ttk.Entry(fields, textvariable=pwd_var, width=30).grid(row=1, column=1, sticky="ew", pady=(0, 10))

        tk.Label(fields, text="备注", bg=FLUENT["bg"], fg=FLUENT["text"],
                 font=(FONT_FAMILY, 10)).grid(row=2, column=0, sticky="w", pady=(0, 10))
        name_var = tk.StringVar(value=vals[2])
        ttk.Entry(fields, textvariable=name_var, width=30).grid(row=2, column=1, sticky="ew", pady=(0, 10))

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
        """从CSV或JSON文件导入账号列表（自动跳过重复项）"""
        from tkinter import filedialog
        path = filedialog.askopenfilename(
            title="选择账号文件",
            filetypes=[("CSV文件", "*.csv"), ("JSON文件", "*.json"), ("所有文件", "*.*")],
            initialdir=os.path.dirname(os.path.abspath(__file__))
        )
        if not path:
            return
        try:
            imported = []
            if path.lower().endswith('.csv'):
                # 读取CSV文件
                with open(path, "r", encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        imported.append({
                            "account": row.get("账号", ""),
                            "password": row.get("密码", ""),
                            "name": row.get("备注", "")
                        })
            else:
                # 读取JSON文件
                with open(path, "r", encoding="utf-8") as f:
                    imported = json.load(f)
            
            if not isinstance(imported, list):
                messagebox.showerror("格式错误", "文件内容格式不正确")
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
        pc = coords.get("password", {})
        if not uc.get("x"):
            self._wlog("✗ 坐标未校准，请先点击「校准坐标」")
            return

        try:
            # 第一步：使用 Interception 驱动级点击账号输入框
            self._wlog(f"点击账号框: ({uc['x']}, {uc['y']})")
            SetForegroundWindow(hwnd)
            time.sleep(0.1)  # 增加等待时间，确保窗口激活
            interception.click(uc["x"], uc["y"], delay=0.5)  # 驱动级点击，增加延迟
            time.sleep(0.5)  # 增加点击后等待时间

            # 第二步：Ctrl+A 全选并清除旧内容，然后输入账号
            with interception.hold_key("ctrl"):
                interception.press("a")
            time.sleep(0.1)  # 增加等待时间
            # 尝试删除可能残留的内容
            interception.press("delete")
            time.sleep(0.1)
            interception.write(account, interval=delay)  # 逐字符输入
            self._wlog("✓ 账号已输入 (Interception驱动级)")

            # 第三步：移动到密码输入框
            time.sleep(0.3)
            if pc.get("x"):
                # 优先使用校准的密码框坐标
                self._wlog(f"点击密码框: ({pc['x']}, {pc['y']})")
                interception.click(pc["x"], pc["y"], delay=0.3)
                time.sleep(0.3)
            else:
                # 回退到Tab跳转
                self._wlog("使用Tab跳转到密码框")
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
