<div align="center">

# 🪟 Liquid Memo Widget · 液态玻璃桌面备忘

**Windows 11 上的半透明磨砂质感桌面待办小组件**

半透明磨砂玻璃（或自定义图片背景）悬浮于桌面，集待办、截止日期、日历订阅于一体。

中文 · [English](README.en.md)

![Platform](https://img.shields.io/badge/platform-Windows%2011-0078D6?logo=windows11&logoColor=white)
![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)
![Render](https://img.shields.io/badge/render-DWM%20Acrylic%20%2B%20Qt-5C2D91)
![License](https://img.shields.io/badge/license-MIT-green)

</div>

---

## ✨ 功能特性

### 🎨 视觉
- **磨砂玻璃皮肤（默认）**：基于 Windows 自带 DWM 亚克力（Acrylic）效果的半透明磨砂表面，省性能、文字清晰，无需 GPU 截屏。
- **图片背景皮肤**：上传并裁切一张图片作为静态背景皮肤，可在设置中随时切换。
- **可调窗口色调**：在设置中调节磨砂玻璃的低饱和背景染色，并自定义待办 / 加急文字颜色。

> 早期版本曾提供实时「液态玻璃」D3D11 折射皮肤（截取并折射桌面背景）。因 bug 较多且体积偏大，该皮肤已移除。

### ✅ 待办
- **待办为核心**：快速添加、勾选完成，完成项可归档或原地淡化（设置中可选）。
- **截止日期（DDL）**：每条待办带独立的截止时间列，支持 `6-15 23:59`、`2026/6/15`、`6月15日` 等多种写法；临近会变色提醒，逾期高亮。
- **加急置顶**：`❗` 标记加急，文字变红并自动置顶。
- **展开 / 折叠**：一键展开查看全部，折叠回紧凑方块。

### 📅 日历订阅
- **ICS / webcal 订阅**：在设置中填入订阅链接，自动同步未来若干天（默认 7 天、最多 30 天）的日程，单独显示在「日程」分组。
- **离线缓存**：上次同步结果会持久化，断网重启仍可查看；已勾选的日程跨次同步保持记忆（淡化 + 删除线）。

### 🖱️ 桌面交互
- **三种显示模式**：普通悬浮、贴边滑动隐藏，或动画悬浮图标；点击图标展开备忘录，移开后自动收回。
- **点击穿透**：半透明区域的点击会穿透到桌面，仅在复选框、按钮等控件上响应，不影响正常使用桌面。
- **原生拖动**：`⋮⋮` 移动窗口；悬浮图标可自由拖动并记忆位置。
- **全局滚轮滚动**：内容超出时可用滚轮浏览。
- **系统托盘**：托盘菜单提供设置、历史记录、显示/隐藏、退出。
- **开机自启**：设置中一键切换随 Windows 启动。

> ⚠️ Windows 专用（Win32 + DWM），无法在其他平台运行或构建。界面为中文，代码标识符为英文。

---

## 🚀 从源码运行

```powershell
python -m pip install -r .\LiquidMemoWidget\requirements.txt
pythonw .\RunLiquidMemoWidget.pyw    # pythonw 不弹出控制台窗口
```

---

## 🔨 构建

```powershell
.\Build.ps1
```

构建产物位于 `dist\LiquidMemoWidget`。

---

## 📦 本地打包

先安装 [Inno Setup 6](https://jrsoftware.org/isinfo.php)，然后运行（将版本号替换为要打包的版本）：

```powershell
.\Package.ps1 -Version <version>
```

会生成：

- `dist\LiquidMemoWidget-Portable-v<version>.zip`（便携版压缩包）
- `dist\installer\LiquidMemoWidget-Setup-v<version>.exe`（安装程序）

常用选项：

```powershell
.\Package.ps1 -Version <version> -SkipBuild        # 跳过构建
.\Package.ps1 -Version <version> -SkipInstaller    # 仅打包 zip
.\Package.ps1 -Version <version> -InnoSetupPath "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

若省略 `-Version`，脚本会依次回退到 `$env:RELEASE_VERSION`、当前提交上的 `v*` 标签、最后是 `0.0.1`。

---

## 🏷️ 发布

推送形如 `v0.0.2` 的版本标签会触发 GitHub Actions 发布流程：构建 PyInstaller 应用、用 Inno Setup 生成 Windows 安装程序、打包便携版 zip，并将两者发布到 GitHub Releases。

---

## 🗂️ 状态文件

应用状态（设置、窗口位置、待办、历史、日历缓存）保存在：

```text
%AppData%\Roaming\DesktopMemo_Pro\liquid-state.json
```

写入为原子操作（临时文件 + 替换）；文件损坏时会备份为 `liquid-state.bad-<时间戳>.json` 并重置为全新状态。

---

## 🙏 致谢

早期版本的实时液态玻璃皮肤改编自 [ai12989757/WindowsLiquidGlass](https://github.com/ai12989757/WindowsLiquidGlass)（MIT 许可）的 D3D11 渲染核心。该皮肤及其引擎现已移除，相关第三方代码不再随项目分发。

详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
