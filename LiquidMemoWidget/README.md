# LiquidMemoWidget

Windows 11 液态玻璃桌面待办小组件。

## 运行

依赖：

```powershell
python -m pip install PySide6-Fluent-Widgets
```

```powershell
pythonw ..\RunLiquidMemoWidget.pyw
```

也可以在开发时使用：

```powershell
python app.py
```

## 打包

在项目根目录运行：

```powershell
.\Build.ps1
```

## 交互

- 主窗口默认在右上角，小方形，自适应待办数量。
- `+` 添加待办。
- `-` 最小化，双击右下角图标恢复。
- `⋮⋮` 是唯一拖动区域。
- 勾选后默认归档消失，可在设置里改为淡化留存。
- `❗` 标记加急，文字变红并置顶。
- 右键托盘图标打开 Fluent 菜单：设置、历史记录、显示/隐藏、退出。
- 设置与历史记录使用 Windows 11 Fluent 风格居中面板。
- 设置中可选择字体颜色模式：手动颜色、自动颜色、自动颜色 + 高对比增强。

## 状态文件

```text
%AppData%\DesktopMemoWidget\liquid-state.json
```
