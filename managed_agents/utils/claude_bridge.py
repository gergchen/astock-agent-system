"""飞书 ↔ Claude Code CLI 桥接器.

将飞书消息转发给 Claude Code CLI（非交互 -p 模式），
用 --session-id / --resume 维持对话记忆。

每个飞书群聊/用户有独立的 Claude 会话，互不干扰。
"""

import json
import logging
import os
import subprocess
import time
import uuid as _uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# Claude Code CLI 路径
CLAUDE_CLI = [
    "node",
    str(Path.home() / "AppData/Roaming/npm/node_modules/@anthropic-ai/claude-code/cli-wrapper.cjs"),
]

# 会话映射文件（持久化，重启 bot 后恢复）
_SESSION_MAP_FILE = Path(__file__).parent.parent / "managed_agents_data" / "claude_sessions.json"

# 消息计数（每个 session 独立计数，重启不丢失）
_MESSAGE_COUNT_FILE = Path(__file__).parent.parent / "managed_agents_data" / "claude_msg_count.json"

# 会话映射: chat_id -> session_uuid
_session_map: dict[str, str] = {}
_session_map_loaded = False

# 消息计数: session_uuid -> count
_msg_count: dict[str, int] = {}
_msg_count_loaded = False

# 每个 session 最大消息数，超过后自动重置
_MAX_MSGS_PER_SESSION = 50

# 压缩阈值：达到此数量后下次请求前先让 Claude 总结对话
_COMPRESS_THRESHOLD = 40

# 会话摘要文件
_SESSION_SUMMARY_FILE = Path(__file__).parent.parent / "managed_agents_data" / "claude_summaries.json"


def _load_session_map():
    global _session_map, _session_map_loaded
    if _session_map_loaded:
        return
    _session_map_loaded = True
    if _SESSION_MAP_FILE.exists():
        try:
            data = json.loads(_SESSION_MAP_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _session_map = data
                logger.info(f"加载了 {len(_session_map)} 个 Claude 会话映射")
        except Exception as e:
            logger.warning(f"加载会话映射失败: {e}")


def _save_session_map():
    _SESSION_MAP_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _SESSION_MAP_FILE.write_text(
            json.dumps(_session_map, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"保存会话映射失败: {e}")


def _load_msg_count():
    global _msg_count, _msg_count_loaded
    if _msg_count_loaded:
        return
    _msg_count_loaded = True
    if _MESSAGE_COUNT_FILE.exists():
        try:
            data = json.loads(_MESSAGE_COUNT_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _msg_count = {k: int(v) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"加载消息计数失败: {e}")


def _save_msg_count():
    _MESSAGE_COUNT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _MESSAGE_COUNT_FILE.write_text(
            json.dumps(_msg_count, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"保存消息计数失败: {e}")


# ── 会话摘要（压缩机制）──
_session_summaries: dict[str, str] = {}
_session_summaries_loaded = False


def _load_session_summaries():
    global _session_summaries, _session_summaries_loaded
    if _session_summaries_loaded:
        return
    _session_summaries_loaded = True
    if _SESSION_SUMMARY_FILE.exists():
        try:
            data = json.loads(_SESSION_SUMMARY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                _session_summaries = data
        except Exception as e:
            logger.warning(f"加载会话摘要失败: {e}")


def _save_session_summaries():
    _SESSION_SUMMARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        _SESSION_SUMMARY_FILE.write_text(
            json.dumps(_session_summaries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"保存会话摘要失败: {e}")


def _reset_session_for_chat(chat_id: str) -> str:
    """重置 chat_id 的会话，返回新 session_id。"""
    _load_session_map()
    old_sid = _session_map.pop(chat_id, "")
    _load_msg_count()
    if old_sid in _msg_count:
        del _msg_count[old_sid]
        _save_msg_count()

    # 删除会话文件
    if old_sid:
        session_file = _find_session_file(old_sid)
        if session_file:
            session_file.unlink(missing_ok=True)
            logger.info("会话文件已删除: %s (超限)", session_file.name)

    # 创建新会话
    new_sid = str(_uuid.uuid4())
    _session_map[chat_id] = new_sid
    _save_session_map()
    logger.info("会话已自动重置: chat=%s new=%s", chat_id, new_sid[:8])
    return new_sid


def _get_session_id(chat_id: str) -> str:
    """获取或创建 chat_id 对应的 Claude 会话 UUID."""
    _load_session_map()
    if chat_id not in _session_map:
        _session_map[chat_id] = str(_uuid.uuid4())
        _save_session_map()
        logger.info("为 %s 创建新 Claude 会话: %s", chat_id, _session_map[chat_id])
    return _session_map[chat_id]


def _find_session_file(session_id: str) -> Path | None:
    """在所有项目目录中查找指定 sessionId 的 .jsonl 文件。"""
    projects_dir = Path.home() / ".claude" / "projects"
    if not projects_dir.exists():
        return None
    target = str(session_id)
    for proj_dir in projects_dir.iterdir():
        if not proj_dir.is_dir():
            continue
        for f in proj_dir.iterdir():
            if f.suffix == ".jsonl" and f.stem == target:
                return f
    return None


def call_claude(
    prompt: str,
    chat_id: str = "default",
    timeout: int = 300,
) -> str:
    """调用 Claude Code CLI，返回回复文本。

    内置自动恢复：session 出错/超时时自动重置并重试一次。

    Args:
        prompt: 发送给 Claude 的消息文本。
        chat_id: 飞书群聊 ID，用于区分不同会话。
        timeout: 超时秒数（默认 300s）。

    Returns:
        Claude 的文本回复。
    """
    session_id = _get_session_id(chat_id)
    cwd = str(Path(__file__).parent.parent.parent)
    _load_msg_count()
    _load_session_summaries()
    current_count = _msg_count.get(session_id, 0)

    # ── 压缩阈值：会话过长时先让 Claude 总结，再重置 ──
    if current_count >= _COMPRESS_THRESHOLD and current_count < _MAX_MSGS_PER_SESSION:
        logger.info("Session %s 已达 %d 条，尝试压缩对话", session_id[:8], current_count)
        try:
            summary_cmd = CLAUDE_CLI + ["-p", "-", "--resume", session_id]
            summary_prompt = "请用中文简要总结我们对话的关键话题和结论（200字以内），只输出总结本身。"
            summary_result = subprocess.run(
                summary_cmd, input=summary_prompt, capture_output=True, text=True,
                timeout=60, encoding="utf-8", cwd=cwd,
            )
            if summary_result.returncode == 0:
                summary = _clean_output(summary_result.stdout or "")
                _session_summaries[session_id] = summary
                _save_session_summaries()
                logger.info("对话压缩完成: %.60s", summary)
        except Exception as e:
            logger.warning("对话压缩失败: %s", e)

    # ── 超限检查 ──
    if current_count >= _MAX_MSGS_PER_SESSION:
        logger.info("Session %s 已达上限，自动重置", session_id[:8])
        # 取出摘要后重置（摘要可能在上次压缩阈值时已保存）
        old_sid = session_id
        session_id = _reset_session_for_chat(chat_id)
        summary = _session_summaries.pop(old_sid, "")
        if summary:
            _save_session_summaries()
            prompt = f"[历史对话摘要]\n{summary}\n\n---\n新对话开始，请参考以上摘要，但优先响应当前问题。\n\n{prompt}"

    # 重试循环：最多 2 次（第一次失败则清理 session 重试）
    for attempt in range(2):
        is_retry = attempt > 0
        if is_retry:
            logger.warning("Claude 第 2 次尝试，已重置 session")
            session_id = _reset_session_for_chat(chat_id)

        # ── 第 1 步：--resume（续旧会话）──
        cmd = CLAUDE_CLI + ["-p", "-", "--resume", session_id]
        logger.info("Claude attempt=%d session=%s chat=%s prompt=%.50s",
                     attempt + 1, session_id[:8], chat_id, prompt)

        try:
            result = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True,
                timeout=timeout, encoding="utf-8", cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            if is_retry:
                raise TimeoutError(f"Claude 响应超时 ({timeout}s)，已重试仍失败")
            logger.warning("Claude 超时，清理 session 重试")
            continue  # 重置后重试
        except FileNotFoundError:
            raise RuntimeError(
                f"Claude CLI 未找到 ({CLAUDE_CLI[-1]})。请运行: "
                "npm install -g @anthropic-ai/claude-code"
            )

        # ── 第 2 步：session 不存在 → 用 --session-id 创建新会话 ──
        if result.returncode != 0 and any(
            kw in (result.stderr or "").lower() for kw in ["not found", "no conversation"]
        ):
            logger.info("Session %s 不存在，创建新会话", session_id[:8])
            cmd = CLAUDE_CLI + ["-p", "-", "--session-id", session_id]
            try:
                result = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True,
                    timeout=timeout, encoding="utf-8", cwd=cwd,
                )
            except subprocess.TimeoutExpired:
                if is_retry:
                    raise TimeoutError(f"Claude 响应超时 ({timeout}s)，已重试仍失败")
                logger.warning("Claude 超时，清理 session 重试")
                continue

        # ── 第 3 步：依然失败 → 看情况重试或放弃 ──
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            stdout = (result.stdout or "").strip()
            if stdout:
                logger.warning("Claude 返回码 %d, stderr=%.200s", result.returncode, stderr)
                if is_retry:
                    return f"[Claude 暂时不可用，重试仍失败] {_clean_output(stdout)[:500]}"
                logger.warning("清理 session 重试")
                continue
            if is_retry:
                error_msg = stderr or f"exit={result.returncode}"
                return f"[Claude 暂时不可用] {error_msg}"
            logger.warning("清理 session 重试")
            continue

        # ── 成功 ──
        output = (result.stdout or "").strip()
        if not output:
            output = (result.stderr or "").strip()

        # 计数 + 超限自动重置
        _load_msg_count()
        _msg_count[session_id] = _msg_count.get(session_id, 0) + 1
        _save_msg_count()
        if _msg_count[session_id] >= _MAX_MSGS_PER_SESSION:
            logger.info("Session %s 已达 %d 条消息，自动重置", session_id[:8], _MAX_MSGS_PER_SESSION)
            _reset_session_for_chat(chat_id)

        return _clean_output(output)

    # 理论上不会走到这里（循环内必 return/raise）
    return "[Claude 暂时不可用] 多次重试后放弃，请稍后再试"


def _clean_output(text: str) -> str:
    """清理 Claude 输出（去除非内容行）。"""
    lines = text.split("\n")
    # 去掉 ``` 围栏
    cleaned = []
    for line in lines:
        if line.strip().startswith("```"):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def _is_session_exists(session_id: str) -> bool:
    """检查 Claude 会话文件是否存在（读取 JSON 内容匹配 sessionId）。"""
    sessions_dir = Path.home() / ".claude" / "sessions"
    if not sessions_dir.exists():
        return False
    target = str(session_id)
    for f in sessions_dir.iterdir():
        if f.suffix != ".json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("sessionId") == target:
                return True
        except Exception:
            continue
    return False


def reset_session(chat_id: str) -> bool:
    """重置指定 chat_id 的 Claude 会话（删除会话文件 + 映射 + 计数）。"""
    _load_session_map()
    if chat_id not in _session_map:
        return False
    session_id = _session_map.pop(chat_id)
    _save_session_map()

    # 清除消息计数
    _load_msg_count()
    if session_id in _msg_count:
        del _msg_count[session_id]
        _save_msg_count()

    # 删除会话文件
    session_file = _find_session_file(session_id)
    if session_file:
        session_file.unlink(missing_ok=True)
        logger.info("已删除会话文件: %s", session_file.name)
    else:
        # 也尝试旧的 sessions 目录
        sessions_dir = Path.home() / ".claude" / "sessions"
        if sessions_dir.exists():
            for f in sessions_dir.iterdir():
                if f.is_file() and session_id in f.name:
                    f.unlink(missing_ok=True)
                    logger.info("已删除旧会话文件: %s", f.name)

    logger.info("已重置 %s 的 Claude 会话", chat_id)
    return True


def list_sessions() -> dict[str, str]:
    """列出所有活跃的 Claude 会话映射。"""
    _load_session_map()
    return dict(_session_map)
