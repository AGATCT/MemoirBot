"""
文件存储底层操作。

提供原子写入、JSON 读写、JSONL 追加、Markdown 读写等基础操作。
所有 I/O 通过 asyncio.to_thread 执行，不阻塞事件循环。
"""

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import frontmatter
import yaml


# =============================================================================
# 通用文件操作
# =============================================================================


async def read_text(filepath: Path) -> str:
    """异步读取文本文件。"""
    def _read():
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read()
    return await asyncio.to_thread(_read)


async def write_text(filepath: Path, content: str) -> None:
    """异步写入文本文件。"""
    def _write():
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
    await asyncio.to_thread(_write)


async def write_text_atomic(filepath: Path, content: str) -> None:
    """原子写入：先写临时文件，再 rename。"""
    def _write():
        filepath.parent.mkdir(parents=True, exist_ok=True)
        tmp = filepath.with_suffix(f".tmp.{os.getpid()}")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        tmp.replace(filepath)  # Windows Python 3.8+ 原子操作
    await asyncio.to_thread(_write)


async def file_exists(filepath: Path) -> bool:
    """异步检查文件是否存在。"""
    return await asyncio.to_thread(filepath.exists)


async def delete_file(filepath: Path) -> bool:
    """异步删除文件，返回是否成功。"""
    def _delete():
        try:
            filepath.unlink()
            return True
        except FileNotFoundError:
            return False
    return await asyncio.to_thread(_delete)


async def list_files(directory: Path, pattern: str = "*") -> list[Path]:
    """异步列出目录中的文件。"""
    def _list():
        if not directory.exists():
            return []
        return sorted(directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    return await asyncio.to_thread(_list)


async def get_mtime(filepath: Path) -> float:
    """异步获取文件修改时间。"""
    def _get():
        try:
            return filepath.stat().st_mtime
        except FileNotFoundError:
            return 0.0
    return await asyncio.to_thread(_get)


# =============================================================================
# JSON 操作
# =============================================================================


async def read_json(filepath: Path) -> dict | list | None:
    """异步读取 JSON 文件，不存在时返回 None。"""
    def _read():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return None
        except json.JSONDecodeError:
            return None
    return await asyncio.to_thread(_read)


async def write_json(filepath: Path, data: dict | list) -> None:
    """异步写入 JSON 文件（原子写入）。"""
    content = json.dumps(data, ensure_ascii=False, indent=2, default=str)
    await write_text_atomic(filepath, content)


# =============================================================================
# JSONL 操作
# =============================================================================


async def append_jsonl(filepath: Path, record: dict) -> None:
    """异步追加一条记录到 JSONL 文件。"""
    def _append():
        filepath.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, ensure_ascii=False, default=str)
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    await asyncio.to_thread(_append)


async def read_jsonl(filepath: Path, limit: int = 0) -> list[dict]:
    """异步读取 JSONL 文件中的所有记录。

    Args:
        filepath: JSONL 文件路径
        limit: 最多读取行数，0 表示全部读取
    """
    def _read():
        records = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                    if limit > 0 and len(records) >= limit:
                        break
        except FileNotFoundError:
            pass
        return records
    return await asyncio.to_thread(_read)


async def read_jsonl_range(
    filepath: Path, start: int = 0, limit: int = 0
) -> list[dict]:
    """异步读取 JSONL 文件中从 start 开始的记录。

    Args:
        filepath: JSONL 文件路径
        start: 起始行号（0-based）
        limit: 最多读取行数，0 表示全部读取
    """
    def _read():
        records = []
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i < start:
                        continue
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue
                    if limit > 0 and len(records) >= limit:
                        break
        except FileNotFoundError:
            pass
        return records
    return await asyncio.to_thread(_read)


async def count_jsonl_lines(filepath: Path) -> int:
    """异步统计 JSONL 文件行数。"""
    def _count():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return sum(1 for _ in f)
        except FileNotFoundError:
            return 0
    return await asyncio.to_thread(_count)


# =============================================================================
# Markdown + YAML Frontmatter 操作
# =============================================================================


async def read_markdown(filepath: Path) -> frontmatter.Post | None:
    """异步读取带 YAML frontmatter 的 Markdown 文件。"""
    def _read():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return frontmatter.load(f)
        except FileNotFoundError:
            return None
    return await asyncio.to_thread(_read)


async def write_markdown(
    filepath: Path, content: str, metadata: dict | None = None
) -> None:
    """异步写入带 YAML frontmatter 的 Markdown 文件（原子写入）。"""
    post = frontmatter.Post(content, **(metadata or {}))
    text = frontmatter.dumps(post)
    await write_text_atomic(filepath, text)


async def read_frontmatter_only(filepath: Path) -> dict:
    """仅读取 Markdown 文件的 frontmatter 元数据。"""
    def _read():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                post = frontmatter.load(f)
                return dict(post.metadata)
        except Exception:
            return {}
    return await asyncio.to_thread(_read)


# =============================================================================
# 会话专用操作
# =============================================================================


async def get_messages_since_offset(
    filepath: Path, offset: int
) -> list[dict]:
    """获取 JSONL 中从 offset 开始的消息。"""
    return await read_jsonl_range(filepath, start=offset)
