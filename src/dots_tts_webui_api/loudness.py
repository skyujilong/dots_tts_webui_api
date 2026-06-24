from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

# 响度归一化目标（行业旁白/广播标准），按需求写死、不做成可配置项。
TARGET_LUFS = -16.0  # 集成响度 I（LUFS）
TARGET_TRUE_PEAK = -1.5  # 真峰上限 TP（dBTP），留 headroom 防削顶爆音
TARGET_LRA = 11.0  # 响度范围 LRA

FFMPEG_BIN = "ffmpeg"


def ffmpeg_available() -> bool:
    """检测 ffmpeg 是否在 PATH 上。缺失时调用方须降级并记录，不静默忽略。"""
    return shutil.which(FFMPEG_BIN) is not None


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, check=False)


def _measure(src: Path) -> dict[str, str]:
    """第一遍扫描：返回 loudnorm 的输入测量值（input_i/tp/lra/thresh/target_offset）。

    测量值用于第二遍的精确线性归一化；缺 JSON 或 ffmpeg 失败时抛错，
    交由调用方降级，不返回伪造测量值掩盖问题。
    """
    args = [
        FFMPEG_BIN,
        "-hide_banner",
        "-nostats",
        "-i",
        str(src),
        "-af",
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK}:LRA={TARGET_LRA}:print_format=json",
        "-f",
        "null",
        "-",
    ]
    proc = _run(args)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg loudnorm measure failed (rc={proc.returncode}): {proc.stderr[-500:]}")
    # loudnorm 的 JSON 统计块打印在 stderr 末尾，取最后一对花括号解析
    text = proc.stderr
    start = text.rfind("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise RuntimeError("ffmpeg loudnorm measure produced no JSON block")
    return json.loads(text[start : end + 1])


def normalize_file(src: Path, dst: Path, *, sample_rate: int) -> None:
    """双次扫描 loudnorm 把 src 归一化到目标响度，写入 dst（16-bit PCM）。

    第二遍用 linear=true + 固定 -ar：只施加线性增益、不重采样、不改样本数，
    保证与 timeline.json / sentences.json 的时间轴一致（不漂移）。
    任一步失败抛异常，由调用方降级，不静默吞错。
    """
    measured = _measure(src)
    loudnorm = (
        f"loudnorm=I={TARGET_LUFS}:TP={TARGET_TRUE_PEAK}:LRA={TARGET_LRA}"
        f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}:linear=true:print_format=summary"
    )
    args = [
        FFMPEG_BIN,
        "-hide_banner",
        "-nostats",
        "-y",
        "-i",
        str(src),
        "-af",
        loudnorm,
        "-ar",
        str(sample_rate),
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    proc = _run(args)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg loudnorm apply failed (rc={proc.returncode}): {proc.stderr[-500:]}")
