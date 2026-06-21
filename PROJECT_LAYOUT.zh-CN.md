# 项目结构说明

语言: [English](PROJECT_LAYOUT.md) | 中文说明

这个 Demo 保留了私有项目的主要目录结构，但把私有运行状态替换成了适合公开展示的安全样例文件。

## 公开源码目录

```text
apps/desktop
```

PySide6 桌面工作台。可以从仓库根目录运行 `run_desktop.py` 或 `start_demo.bat` 启动。

```text
apps/db_viewer
```

只读 SQLite 数据库查看系统。可以运行 `run_db_viewer.py` 或 `open_database_viewer.bat` 打开。

```text
services/report_system
```

报告生成、邮件 dry-run、报告历史、体检和维护脚本。

```text
services/data_downloader
```

数据下载和导入模块。公开 Demo 中如需真实下载，需要使用者在本地提供自己的 Tushare Token。

```text
scripts/create_demo_data.py
```

用于生成公开 Demo 使用的小型模拟数据库 `data/futures.db`。

## 本地运行目录

下面这些目录会在本地运行时生成，默认由 Git 忽略，除非文档中特别说明，不应该提交：

```text
runtime/
backups/
services/report_system/logs/
services/report_system/reports/
services/data_downloader/logs/
services/data_downloader/futures_data/
```

## Git 提交规则

- 保持 `data/futures.db` 小体积、模拟数据、可公开展示。
- 不提交真实 `.env` 文件。
- 不提交真实收件人名单。
- 不提交生成的报告、日志、备份或下载的 CSV 行情导出。
- 根目录启动脚本要保持简单，方便非技术评审快速打开 Demo。
