# AGENTS.md

This file is for Codex and other coding agents working in this repository.

**Single source of truth:** all project guidance — commands, architecture, the
module layout, the PyInstaller hidden-import pitfall, the test suite, and the
release process — lives in [CLAUDE.md](CLAUDE.md). Read it before making changes.
It is kept current, and this file intentionally does not duplicate it so the two
cannot drift apart.

## What this is (at a glance)

A Windows 11 desktop memo/todo widget rendered as a translucent "Liquid Glass"
surface: a real-time GPU screen-capture widget that continuously captures the
desktop region behind itself and refracts it through D3D11 effects, with a Qt
content layer (todo rows, buttons) floating on top. Windows-only (Win32 + D3D11);
it will not run or build on other platforms.

UI strings are Chinese. Code/identifiers are English.

See **CLAUDE.md** for commands, architecture, and everything else.
