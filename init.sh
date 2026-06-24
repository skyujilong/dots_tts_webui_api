#!/bin/bash
set -e

# 1. 终止正在运行的uv进程
echo ">>> 终止残留 uv 进程"
pkill -f "uv" || true

# 2. 进入项目目录
cd /root/dots_tts_webui_api-main

# 3. 清理 uv 已下载的旧Python缓存
#    历史上系统 apt 源提供的 python3.11 是 3.11.0rc1（预发布版），
#    缺少 3.11 正式版才有的标准库函数（如 sys.get_int_max_str_digits），
#    会导致 torch._dynamo 导入崩溃。这里改为完全用 uv 管理 Python，
#    锁定到正式版 3.11.9，不再依赖系统 apt 的 python3.11。
echo ">>> 清理 uv Python 缓存"
rm -rf /root/.local/share/uv/python
uv cache clean

# 4. 用 uv 安装并固定 Python 3.11.9 正式版
#    通过镜像加速 python-build-standalone 的下载（解决 GitHub 超时）。
echo ">>> 安装并锁定 Python 3.11.9"
export UV_PYTHON_INSTALL_MIRROR="https://ghfast.top/https://github.com/astral-sh/python-build-standalone/releases/download"
uv python install 3.11.9
uv python pin 3.11.9

# 5. 重建虚拟环境，严格使用 3.11.9
echo ">>> 重建 .venv (Python 3.11.9)"
rm -rf .venv
uv venv --python 3.11.9 .venv

# 6. 并行执行 uv sync
echo ">>> 开始 uv sync"
uv sync --parallel 8

echo ">>> 执行完成！"
