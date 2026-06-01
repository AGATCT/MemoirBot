"""
日记引擎。

负责日记的创建、读取、更新、删除。
日记以 Markdown + YAML frontmatter 格式存储在 data/diaries/YYYY/MM/DD.md。
"""

import logging
from datetime import date, datetime
from pathlib import Path

from app.diary.schemas import DiaryEntry, DiaryEntryCreate, DiaryEntrySummary
from app.storage import file_store
from app.storage.paths import get_diary_path

logger = logging.getLogger(__name__)


class DiaryEngine:
    """日记引擎。"""

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def get_entry(self, year: int, month: int, day: int) -> DiaryEntry | None:
        """获取指定日期的日记。"""
        filepath = get_diary_path(year, month, day)
        post = await file_store.read_markdown(filepath)
        if post is None:
            return None

        metadata = dict(post.metadata) if post.metadata else {}
        return DiaryEntry(
            id=metadata.get("id", f"diary_{year}{month:02d}{day:02d}"),
            date=f"{year}-{month:02d}-{day:02d}",
            content=post.content or "",
            mood=metadata.get("mood"),
            tags=metadata.get("tags", []),
            created_at=metadata.get("created_at", datetime.now().isoformat()),
            updated_at=metadata.get("updated_at", datetime.now().isoformat()),
        )

    async def save_entry(self, entry_data: DiaryEntryCreate) -> DiaryEntry:
        """保存（创建或更新）日记。"""
        # 解析日期
        parts = entry_data.date.split("-")
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])

        # 检查是否已存在
        existing = await self.get_entry(year, month, day)
        now = datetime.now().isoformat()

        metadata = {
            "id": f"diary_{year}{month:02d}{day:02d}",
            "created_at": existing.created_at if existing else now,
            "updated_at": now,
            "mood": entry_data.mood,
            "tags": entry_data.tags,
        }

        filepath = get_diary_path(year, month, day)
        await file_store.write_markdown(filepath, entry_data.content, metadata)
        logger.info(f"日记已保存: {entry_data.date}")

        return DiaryEntry(
            id=metadata["id"],
            date=entry_data.date,
            content=entry_data.content,
            mood=entry_data.mood,
            tags=entry_data.tags,
            created_at=metadata["created_at"],
            updated_at=now,
        )

    async def delete_entry(self, year: int, month: int, day: int) -> bool:
        """删除指定日期的日记。"""
        filepath = get_diary_path(year, month, day)
        deleted = await file_store.delete_file(filepath)
        if deleted:
            logger.info(f"日记已删除: {year}-{month:02d}-{day:02d}")
        return deleted

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    async def get_month_view(self, year: int, month: int) -> dict[int, DiaryEntrySummary]:
        """获取某月所有有日记的日期摘要。"""
        month_dir = get_diary_path(year, month, 1).parent
        files = await file_store.list_files(month_dir, pattern="*.md")

        result: dict[int, DiaryEntrySummary] = {}
        for f in files:
            try:
                day_str = f.stem  # "DD"
                day = int(day_str)
                post = await file_store.read_markdown(f)
                if post is None:
                    continue
                metadata = dict(post.metadata) if post.metadata else {}
                content = post.content or ""
                result[day] = DiaryEntrySummary(
                    id=metadata.get("id", f"diary_{year}{month:02d}{day:02d}"),
                    date=f"{year}-{month:02d}-{day:02d}",
                    mood=metadata.get("mood"),
                    tags=metadata.get("tags", []),
                    preview=content[:100],
                )
            except (ValueError, Exception):
                continue

        return result

    async def list_entries(
        self, year: int | None = None, month: int | None = None
    ) -> list[DiaryEntrySummary]:
        """列出日记条目。

        Args:
            year: 筛选年份
            month: 筛选月份
        """
        from app.storage.paths import get_diaries_dir

        result: list[DiaryEntrySummary] = []
        base_dir = get_diaries_dir()

        # 构建搜索路径
        if year and month:
            search_dir = base_dir / str(year) / f"{month:02d}"
        elif year:
            search_dir = base_dir / str(year)
        else:
            search_dir = base_dir

        # 递归查找 .md 文件
        all_files = await file_store.list_files(search_dir, pattern="**/*.md")
        # list_files 不递归，需要手动处理
        if year and month:
            raw_files = await file_store.list_files(search_dir, pattern="*.md")
        else:
            raw_files = await self._find_all_md_files(search_dir)

        for f in raw_files:
            try:
                post = await file_store.read_markdown(f)
                if post is None:
                    continue
                metadata = dict(post.metadata) if post.metadata else {}
                content = post.content or ""

                # 从路径解析日期
                parts = f.relative_to(base_dir).parts
                if len(parts) >= 3:
                    fy, fm, fd = parts[-3], parts[-2], f.stem
                    date_str = f"{fy}-{fm}-{fd}"
                else:
                    continue

                result.append(DiaryEntrySummary(
                    id=metadata.get("id", ""),
                    date=date_str,
                    mood=metadata.get("mood"),
                    tags=metadata.get("tags", []),
                    preview=content[:100],
                ))
            except Exception:
                continue

        result.sort(key=lambda e: e.date, reverse=True)
        return result

    async def _find_all_md_files(self, directory: Path) -> list[Path]:
        """递归查找所有 .md 文件。"""
        import asyncio

        def _find():
            if not directory.exists():
                return []
            return sorted(directory.rglob("*.md"), reverse=True)

        return await asyncio.to_thread(_find)

    async def get_recent_entries(self, count: int = 10) -> list[DiaryEntrySummary]:
        """获取最近的日记条目。"""
        all_entries = await self.list_entries()
        return all_entries[:count]
