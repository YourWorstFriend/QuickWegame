# 尽量快乐LOL

WeGame 自动登录 + 一键退出游戏工具。

## 功能

- **一键退出游戏**：自定义热键快速终止英雄联盟进程
- **WeGame 自动登录**：驱动级键鼠模拟，自动输入账号密码并登录
- **多账号管理**：表格形式管理多个账号，支持双击直接编辑
- **坐标校准**：一键采集输入框坐标，适配不同分辨率

## 安装

```bash
pip install -r requirements.txt
```

### 依赖说明

| 依赖 | 用途 |
|------|------|
| `psutil` | 进程管理（遍历、终止） |
| `keyboard` | 全局热键监听 |
| `pyautogui` | 鼠标坐标采集 |
| `interception-python` | 驱动级键鼠输入（绕过游戏输入拦截） |

> **注意**：`interception-python` 需要安装 Interception 驱动。  
> 下载地址：https://github.com/oblitum/interception/releases

## 使用

```bash
python hotkey_kill.py
```

### 一键退出游戏

1. 添加目标进程名（如 `League of Legends.exe`）
2. 设置热键（如 `ctrl+alt+k`）
3. 点击「启动监听」
4. 按热键即可终止目标进程

### WeGame 自动登录

1. 设置 WeGame 路径
2. 点击「校准坐标」→ 将鼠标移到账号输入框 → 等待 3 秒
3. 在账号表格中添加账号（支持双击编辑）
4. 选中账号行 → 点击「一键登录 WeGame」

## 打包

```bash
pyinstaller --onefile --windowed --name "尽量快乐LOL" --add-data "ahk.exe;." --hidden-import interception hotkey_kill.py
```

## 开源许可

[MIT License](LICENSE)
