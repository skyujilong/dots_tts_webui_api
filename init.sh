#!/bin/bash
set -e

# 1. 终止正在运行的uv进程
echo ">>> 终止残留 uv 进程"
pkill -f "uv" || true

# 2. 更新软件源并安装 Python 3.11 + venv
echo ">>> 安装 Python 3.11"
apt update -y
apt install -y python3.11 python3.11-venv

# 3. 清理 uv 已下载的旧Python缓存
echo ">>> 清理 uv Python 缓存"
rm -rf /root/.local/share/uv/python
uv cache clean

# 4. 进入项目目录、锁定Python版本为3.11
echo ">>> 绑定项目 Python 3.11"
cd /root/dots_tts_webui_api-main
uv python pin 3.11

# 5. 并行执行 uv sync
echo ">>> 开始 uv sync"
uv sync --parallel 8

echo ">>> 执行完成！"