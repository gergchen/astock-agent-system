"""抖音监控轮询引擎.

编排: 获取作品列表 → 去重 → 分析文案 → 推送带货 → 标记已处理
"""

import logging
import time
from datetime import datetime
from typing import Any

from ..config import get_config
from .api_client import DouyinAPI, DouyinAPIClientError
from .analyzer import analyze_video_text
from .models import DouyinVideo, DouyinConfig
from .state_store import StateStore

logger = logging.getLogger(__name__)


class DouyinCrawler:
    """抖音监控轮询引擎."""

    def __init__(
        self,
        api_client: DouyinAPI | None = None,
        state_store: StateStore | None = None,
    ):
        self.config = self._build_config()
        self.api = api_client or DouyinAPI()
        self.state = state_store or StateStore()

    @staticmethod
    def _build_config() -> DouyinConfig:
        cfg = get_config()
        return DouyinConfig(
            api_base_url=cfg.douyin_api_base_url,
            poll_interval_seconds=cfg.douyin_poll_interval,
            max_videos_per_scan=cfg.douyin_max_videos_per_scan,
            enable_vision=cfg.douyin_enable_vision,
            monitored_users=cfg.douyin_monitored_users,
            max_concurrent_analysis=cfg.douyin_max_concurrent,
            rate_limit_per_minute=cfg.douyin_rate_limit,
        )

    # ─── 核心扫描 ────────────────────────────────────────

    def scan_user(self, sec_user_id: str, nickname: str = "") -> int:
        """扫描单个用户的最新视频并分析.

        Returns:
            新发现的视频数量
        """
        try:
            raw = self.api.get_user_videos(
                sec_user_id, max_count=self.config.max_videos_per_scan,
            )
            video_list = DouyinAPI.extract_video_list(raw)
            if not video_list:
                logger.info(f"用户 {nickname} 暂无作品")
                return 0

            # 提取 aweme_id 列表
            video_ids = []
            for item in video_list:
                vid = DouyinAPI.extract_aweme_id(item)
                if vid:
                    video_ids.append(vid)

            if not video_ids:
                return 0

            # 过滤新视频
            new_ids = self.state.get_new_videos(sec_user_id, video_ids)
            if not new_ids:
                logger.info(f"用户 {nickname} 无新视频")
                self.state.update_user_state(
                    sec_user_id, last_check_time=datetime.now().isoformat(),
                    last_video_id=video_ids[0],
                )
                return 0

            logger.info(f"用户 {nickname}: {len(new_ids)} 个新视频待分析")

            # 分析每个新视频
            for vid in new_ids:
                video = self._build_video(vid, video_list, nickname)
                if video is None:
                    continue

                result = analyze_video_text(video)
                self.state.increment_analyzed()

                if result.product and result.product.has_product:
                    self.state.increment_alerts()
                    self._notify_product(result)
                    self.state.update_user_state(
                        sec_user_id, last_alert_time=datetime.now().isoformat(),
                    )

                self.state.mark_video_checked(sec_user_id, vid)

            # 更新用户状态
            self.state.update_user_state(
                sec_user_id,
                nickname=nickname or video_ids[0],
                last_video_id=video_ids[0],
                last_check_time=datetime.now().isoformat(),
            )

            return len(new_ids)

        except DouyinAPIClientError as e:
            logger.error(f"扫描用户 {nickname} 失败: {e}")
            return 0
        except Exception as e:
            logger.error(f"扫描用户 {nickname} 异常: {e}", exc_info=True)
            return 0

    def scan_all(self) -> dict[str, int]:
        """扫描所有已启用用户.

        Returns:
            {sec_user_id: new_video_count}
        """
        users = self.config.monitored_users
        if not users:
            logger.info("未配置任何监控用户")
            return {}

        results = {}
        for user in users:
            if not user.get("enabled", True):
                continue
            sec_user_id = user.get("sec_user_id", "")
            nickname = user.get("nickname", "")
            if not sec_user_id:
                continue
            results[sec_user_id] = self.scan_user(sec_user_id, nickname)

        self.state.set_last_run()
        return results

    def run_forever(self, interval: int | None = None) -> None:
        """轮询循环 (类似 Sentinel 模式)."""
        interval = interval or self.config.poll_interval_seconds
        logger.info(f"抖音监控轮询启动, 间隔 {interval}s")
        from ..utils.notifier import notify
        notify("抖音监控上线",
               f"轮询间隔 {interval}s, 监控 {len(self.config.monitored_users)} 个用户",
               "info", force=True)

        consecutive_errors = 0

        try:
            while True:
                if not self.api.health_check():
                    consecutive_errors += 1
                    wait = min(60 * consecutive_errors, 600)
                    logger.warning(f"Douyin API 不可达 ({consecutive_errors}次), {wait}s 后重试")
                    time.sleep(wait)
                    continue

                consecutive_errors = 0
                results = self.scan_all()
                total = sum(results.values())
                if total > 0:
                    logger.info(f"本轮发现 {total} 个新视频")

                time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("抖音监控轮询已停止")

    # ─── 内部方法 ─────────────────────────────────────────

    def _build_video(
        self, target_vid: str, video_list: list[dict], nickname: str
    ) -> DouyinVideo | None:
        """从作品列表中查找指定 vid 并构建 DouyinVideo."""
        for item in video_list:
            if DouyinAPI.extract_aweme_id(item) == target_vid:
                return self._item_to_video(item, nickname)
        return None

    def _item_to_video(self, item: dict, nickname: str) -> DouyinVideo:
        """将 API item dict 转换为 DouyinVideo."""
        video_info = item.get("video", {}) or {}
        statistics = item.get("statistics", item.get("stats", {})) or {}
        author = item.get("author", {}) or {}

        cover_url = ""
        cover = video_info.get("cover", {})
        if isinstance(cover, dict):
            url_list = cover.get("url_list", [])
            cover_url = url_list[0] if url_list else ""
        else:
            cover_url = item.get("cover_url", "")

        return DouyinVideo(
            video_id=str(item.get("aweme_id", item.get("id", ""))),
            aweme_id=str(item.get("aweme_id", "")),
            desc=item.get("desc", item.get("description", "")),
            create_time=int(item.get("create_time", 0)),
            cover_url=cover_url,
            author_sec_uid=author.get("sec_uid", ""),
            author_nickname=nickname or author.get("nickname", ""),
            play_count=int(statistics.get("play_count", 0)),
            like_count=int(statistics.get("like_count", 0)),
            comment_count=int(statistics.get("comment_count", 0)),
            share_count=int(statistics.get("share_count", 0)),
            video_url=self._extract_video_url(video_info),
            duration=int(video_info.get("duration", 0)),
        )

    @staticmethod
    def _extract_video_url(video_info: dict) -> str:
        play_addr = video_info.get("play_addr", {})
        if isinstance(play_addr, dict):
            url_list = play_addr.get("url_list", [])
            return url_list[0] if url_list else ""
        return ""

    def _notify_product(self, result) -> None:
        """检测到带货, 推送飞书 + 记录日志."""
        p = result.product
        v = result.video

        title = f"🛒 {v.author_nickname}: {p.product_name or '疑似带货'}"
        lines = [
            f"主播: {v.author_nickname}",
            f"视频: {v.desc[:100]}",
            f"链接: https://www.douyin.com/video/{v.aweme_id}",
            f"互动: 👍{v.like_count} 💬{v.comment_count} 🔄{v.share_count}",
            "---",
        ]
        if p.brand:
            lines.append(f"品牌: {p.brand}")
        if p.product_name:
            lines.append(f"产品: {p.product_name}")
        if p.category and p.category != "无":
            lines.append(f"品类: {p.category}")
        if p.price:
            lines.append(f"价格: {p.price}")
        if p.raw_text:
            lines.append(f"依据: {p.raw_text}")

        body = "\n".join(lines)

        now = datetime.now()
        is_quiet = now.hour >= 23 or now.hour < 8
        if is_quiet:
            logger.info(f"[静默] 检测到带货但暂不推送: {title}")
            return

        from ..utils.notifier import notify
        notify(title, body, level="warn", force=True)
