"""
Dream 调度器。

后台调度任务，定期检查是否需要运行 Dream 过程。
参考 coding-agent-main autoDream.ts 的三道门控设计。

门控（最便宜的检查优先）：
1. 时间门控: 距上次 dream >= dream_interval_hours
2. 会话门控: 自上次 dream 以来修改的会话数 >= min_sessions
3. 合并锁: 检查 .consolidate-lock 文件避免重复运行

锁机制（参考 consolidationLock.ts）：
- 锁文件: data/memories/.consolidate-lock
- mtime = 上次 dream 运行时间
- 内容 = 持有者的 PID
- 超时: 60 分钟（PID 重用保护）
"""

import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path

from app.config import settings
from app.storage import file_store
from app.storage.paths import (
    get_consolidation_lock_path,
    get_chats_dir,
    get_dream_state_path,
)

logger = logging.getLogger(__name__)

# 锁超时时间（毫秒）
LOCK_STALE_MS = 60 * 60 * 1000  # 60 分钟
# 会话扫描限流（毫秒）
SESSION_SCAN_INTERVAL_MS = 10 * 60 * 1000  # 10 分钟


class DreamScheduler:
    """Dream 后台调度器。

    作为 asyncio 后台任务运行，在 FastAPI lifespan 中启动。
    """

    def __init__(
        self,
        dream_agent,
        memory_engine=None,
        check_interval_minutes: int = 60,
    ):
        self.dream_agent = dream_agent
        self.memory_engine = memory_engine
        self.check_interval = check_interval_minutes * 60  # 秒
        self._task: asyncio.Task | None = None
        self._last_session_scan = 0.0
        self._is_running = False

    async def start(self) -> None:
        """启动调度器。"""
        if self._task is not None:
            logger.warning("DreamScheduler 已在运行")
            return
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"DreamScheduler 已启动（检查间隔: {self.check_interval}秒）"
        )

    async def stop(self) -> None:
        """停止调度器。"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("DreamScheduler 已停止")

    # ------------------------------------------------------------------
    # 主循环
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """主调度循环。"""
        # 启动后等待 30 秒再开始第一次检查
        await asyncio.sleep(30)

        while True:
            try:
                await self._check_and_run()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"DreamScheduler 错误: {e}", exc_info=True)

            await asyncio.sleep(self.check_interval)

    async def _check_and_run(self) -> None:
        """检查是否需要运行 Dream。"""
        # Gate 1: 时间门控
        last_at = await self._read_last_consolidated_at()
        hours_since = (datetime.now().timestamp() * 1000 - last_at) / 3_600_000
        min_hours = settings.dream_interval_hours

        if hours_since < min_hours:
            logger.debug(f"[dream] 时间门控未通过: {hours_since:.1f}h < {min_hours}h")
            return

        # 会话扫描限流
        since_scan = datetime.now().timestamp() * 1000 - self._last_session_scan
        if since_scan < SESSION_SCAN_INTERVAL_MS:
            logger.debug(f"[dream] 会话扫描限流: {since_scan/1000:.0f}s")
            return
        self._last_session_scan = datetime.now().timestamp() * 1000

        # Gate 2: 会话门控
        session_count = await self._count_sessions_since(last_at)
        min_sessions = settings.dream_min_sessions

        if session_count < min_sessions:
            logger.debug(
                f"[dream] 会话门控未通过: {session_count} < {min_sessions}"
            )
            return

        # Gate 3: 合并锁
        lock_acquired = await self._acquire_lock()
        if not lock_acquired:
            return

        logger.info(
            f"[dream] 🧠 触发 Dream — {hours_since:.1f}h 间隔, "
            f"{session_count} 个会话"
        )

        from app.agent.activity_log import get_activity_log
        act_id = get_activity_log().start(
            "dream", "Dream 记忆整理", detail=f"处理 {session_count} 个活跃会话",
        )

        self._is_running = True
        try:
            result = await self.dream_agent.dream(session_count)
            await self._record_dream_run(result)
            deleted = result.get("deleted", 0)
            merged = result.get("merged", 0)
            parts = []
            if deleted: parts.append(f"删除 {deleted} 条")
            if merged: parts.append(f"合并 {merged} 条")
            get_activity_log().finish(act_id, summary="，".join(parts) if parts else "完成")
            logger.info(f"[dream] ✅ Dream 完成: {result.get('status')}")
        except Exception as e:
            get_activity_log().finish(act_id, status="failed", summary=str(e)[:80])
            logger.error(f"[dream] ❌ Dream 失败: {e}", exc_info=True)
            # 失败时回滚锁 mtime（让下次能重试）
            await self._rollback_lock(last_at)
        finally:
            self._is_running = False

    # ------------------------------------------------------------------
    # 手动触发
    # ------------------------------------------------------------------

    async def trigger_manual(self) -> dict:
        """手动触发 Dream（不检查门控）。"""
        if self._is_running:
            return {"status": "error", "message": "Dream 正在运行中"}

        session_count = await self._count_sessions_since(
            await self._read_last_consolidated_at()
        )

        self._is_running = True
        try:
            logger.info("[dream] 📋 手动触发 Dream")
            # 不获取锁（手动触发不阻止自动触发）
            result = await self.dream_agent.dream(session_count)
            # 记录手动触发时间
            await self._update_lock_timestamp()
            await self._record_dream_run(result)
            return result
        except Exception as e:
            logger.error(f"[dream] 手动 Dream 失败: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            self._is_running = False

    def is_running(self) -> bool:
        return self._is_running

    # ------------------------------------------------------------------
    # 锁管理（参考 consolidationLock.ts）
    # ------------------------------------------------------------------

    async def _read_last_consolidated_at(self) -> float:
        """读取上次 Dream 的时间（毫秒时间戳）。

        锁文件不存在 → 返回 0（表示从未运行）。
        """
        mtime = await file_store.get_mtime(get_consolidation_lock_path())
        return mtime * 1000  # 转换为毫秒

    async def _acquire_lock(self) -> bool:
        """尝试获取合并锁。

        Returns:
            True = 获得锁，可以运行
            False = 锁被持有且未过期，跳过
        """
        lock_path = get_consolidation_lock_path()
        mtime = await file_store.get_mtime(lock_path)

        if mtime > 0:
            now_ms = datetime.now().timestamp() * 1000
            # 检查锁是否过期
            if now_ms - mtime * 1000 < LOCK_STALE_MS:
                # 锁未过期，检查 PID 是否存活
                try:
                    content = await file_store.read_text(lock_path)
                    pid = int(content.strip())
                    if self._is_pid_alive(pid):
                        logger.debug(f"[dream] 锁被 PID {pid} 持有，跳过")
                        return False
                except (ValueError, FileNotFoundError):
                    pass  # 无法读取或非法的 PID → 回收锁

        # 获取锁
        await self._update_lock_timestamp()
        return True

    async def _update_lock_timestamp(self) -> None:
        """更新锁文件时间和 PID。"""
        lock_path = get_consolidation_lock_path()
        await file_store.write_text_atomic(lock_path, str(os.getpid()))

    async def _rollback_lock(self, prior_mtime_ms: float) -> None:
        """回滚锁文件到之前的时间。"""
        lock_path = get_consolidation_lock_path()
        if prior_mtime_ms == 0:
            await file_store.delete_file(lock_path)
        else:
            # 恢复之前的时间戳
            await file_store.write_text_atomic(lock_path, "")

    @staticmethod
    def _is_pid_alive(pid: int) -> bool:
        """检查进程是否存活（Windows 兼容）。"""
        try:
            import ctypes
            import ctypes.wintypes

            SYNCHRONIZE = 0x100000
            handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
            if handle == 0:
                return False
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        except Exception:
            # 无法检测 → 假设存活
            return True

    # ------------------------------------------------------------------
    # 会话计数
    # ------------------------------------------------------------------

    async def _count_sessions_since(self, since_ms: float) -> int:
        """统计自 since_ms 以来修改过的会话数。

        参考 listSessionsTouchedSince。
        """
        chats_dir = get_chats_dir()
        if not chats_dir.exists():
            return 0

        count = 0
        dirs = await file_store.list_files(chats_dir, pattern="sess_*")
        for d in dirs:
            if not d.is_dir():
                continue
            mtime = await file_store.get_mtime(d / "metadata.json")
            if mtime * 1000 > since_ms:
                count += 1

        return count

    # ------------------------------------------------------------------
    # 状态持久化
    # ------------------------------------------------------------------

    async def _record_dream_run(self, result: dict) -> None:
        """记录 Dream 运行结果到状态文件。"""
        state = {
            "last_dream_run": datetime.now().isoformat(),
            "last_dream_result": result.get("status", "unknown"),
            "is_dream_running": False,
        }
        await file_store.write_json(get_dream_state_path(), state)


# =============================================================================
# 全局实例管理
# =============================================================================

_scheduler: DreamScheduler | None = None


def get_dream_scheduler() -> DreamScheduler | None:
    return _scheduler


async def init_dream_scheduler(dream_agent, memory_engine=None) -> DreamScheduler:
    """初始化并启动 DreamScheduler。"""
    global _scheduler
    _scheduler = DreamScheduler(
        dream_agent=dream_agent,
        memory_engine=memory_engine,
        check_interval_minutes=settings.dream_check_interval_minutes,
    )
    return _scheduler
