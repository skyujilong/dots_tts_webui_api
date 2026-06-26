#!/bin/bash
set -e

# 1. 终止正在运行的uv进程
echo ">>> 终止残留 uv 进程"
pkill -f "uv" || true

# 2. 进入项目目录
cd /root/dots_tts_webui_api-main

# 3. 检查现有 .venv 的 Python 版本，已是 3.11.9 则跳过重建
VENV_PY=""
if [ -x .venv/bin/python ]; then
    VENV_PY=$(.venv/bin/python --version 2>&1 | awk '{print $2}')
fi

if [ "$VENV_PY" = "3.11.9" ]; then
    echo ">>> .venv 已是 Python 3.11.9，跳过环境重建"
else
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
fi

# 6. 安装 ffmpeg（响度归一化 DOTS_ENABLE_LOUDNORM 依赖它的 loudnorm filter）
#    real 模式默认开启响度归一化，缺 ffmpeg 会降级并记 warning；这里直接装好。
echo ">>> 检查 / 安装 ffmpeg"
if command -v ffmpeg >/dev/null 2>&1; then
    echo "ffmpeg 已存在：$(ffmpeg -version | head -1)"
else
    echo ">>> 未检测到 ffmpeg，使用 apt 安装"
    apt-get update
    apt-get install -y ffmpeg
fi
# 校验 loudnorm filter 可用（响度归一化强依赖），不可用则明确报错而非静默继续
if ! ffmpeg -hide_banner -filters 2>/dev/null | grep -q loudnorm; then
    echo "!!! ffmpeg 缺少 loudnorm filter，响度归一化将无法工作" >&2
    exit 1
fi
echo "ffmpeg loudnorm filter 可用"

# 7. 并行执行 uv sync
echo ">>> 开始 uv sync"
uv sync --extra real --parallel 8

echo ">>> 执行完成！"
