"""抖音监控技能 — 供 DouyinMonitor Agent 调用."""

import logging

from ..config import get_config
from ..douyin.api_client import DouyinAPI, DouyinAPIClientError
from ..douyin.analyzer import analyze_video_text
from ..douyin.crawler import DouyinCrawler
from ..douyin.models import DouyinVideo
from ..douyin.state_store import StateStore

logger = logging.getLogger(__name__)


class DouyinSkills:
    """抖音监控技能层."""

    def __init__(self):
        self.api = DouyinAPI()
        self.store = StateStore()
        self.crawler = DouyinCrawler(self.api, self.store)

    def scan_all_users(self) -> str:
        """扫描所有已配置用户, 检测新带货视频. 自动推送飞书."""
        results = self.crawler.scan_all()
        parts = [f"{uid}: {cnt}个新视频" for uid, cnt in results.items()]
        return self._sanitize("扫描完成\n" + "\n".join(parts)) if parts else "未发现新视频"

    def scan_user(self, sec_user_id: str, nickname: str = "") -> str:
        """扫描指定用户的最新视频."""
        count = self.crawler.scan_user(sec_user_id, nickname)
        return self._sanitize(f"用户 {nickname or sec_user_id}: 发现 {count} 个新视频")

    def analyze_video(self, url: str) -> str:
        """分析单个抖音视频的带货内容.

        Args:
            url: 抖音分享链接

        Returns:
            商品信息或"未检测到带货"
        """
        try:
            # 优先用 hybrid_parse, 如果失败则自行解析短链提取 aweme_id
            try:
                parsed = self.api.hybrid_parse(url, minimal=False)
            except DouyinAPIClientError:
                logger.info("hybrid_parse 失败, 尝试自行解析短链")
                parsed = None

            if parsed and parsed.get("code") in (0, 200):
                data = parsed.get("data", parsed)
            else:
                # 自行解析: 短链重定向 → 提取 aweme_id → fetch_one_video
                aweme_id = DouyinAPI.resolve_short_url(url)
                if not aweme_id:
                    return "无法解析视频链接"
                raw = self.api.get_video_data(aweme_id)
                if raw.get("code") not in (0, 200) or "aweme_detail" not in raw.get("data", {}):
                    return f"获取视频失败: {raw.get('message', 'unknown')}"
                data = raw["data"]["aweme_detail"]

            video = DouyinVideo(
                video_id=str(data.get("aweme_id", data.get("video_id", ""))),
                aweme_id=str(data.get("aweme_id", "")),
                desc=data.get("desc", ""),
                like_count=int(data.get("statistics", {}).get("digg_count", 0)),
                comment_count=int(data.get("statistics", {}).get("comment_count", 0)),
                share_count=int(data.get("statistics", {}).get("share_count", 0)),
            )

            result = analyze_video_text(video)
            if result.product and result.product.has_product:
                p = result.product
                return self._sanitize(
                    f"检测到带货:\n"
                    f"  品牌: {p.brand or '-'}\n"
                    f"  产品: {p.product_name or '-'}\n"
                    f"  品类: {p.category or '-'}\n"
                    f"  价格: {p.price or '-'}\n"
                    f"  置信度: {p.confidence:.0%}\n"
                    f"  依据: {p.raw_text}"
                )
            return "未检测到带货商品"

        except DouyinAPIClientError as e:
            return f"API 错误: {e}"
        except Exception as e:
            return f"分析失败: {e}"

    def list_users(self) -> str:
        """列出所有已配置的监控用户及其状态."""
        users = get_config().douyin_monitored_users
        if not users:
            return "未配置任何监控用户"

        lines = ["已配置的抖音监控用户:"]
        for u in users:
            status = "[V]" if u.get("enabled", True) else "[X]"
            nickname = u.get("nickname", u.get("sec_user_id", "")[:16])
            lines.append(f"  {status} {nickname}")

        stats = self.store.get_stats()
        lines.append(
            f"\n统计: 已分析 {stats.get('total_analyzed', 0)} 条视频, "
            f"触发 {stats.get('total_alerts', 0)} 次告警"
        )
        return self._sanitize("\n".join(lines))

    @staticmethod
    def _sanitize(text: str) -> str:
        """移除无法在 GBK 终端显示的字符."""
        return text.encode("gbk", errors="replace").decode("gbk")

    def get_user_info(self, sec_user_id: str) -> str:
        """获取抖音用户信息.

        Args:
            sec_user_id: 用户 sec_user_id
        """
        try:
            info = self.api.get_user_info(sec_user_id)
            data = info.get("data", info)
            user = data.get("user", data) if isinstance(data, dict) else data
            if isinstance(user, dict):
                return self._sanitize(
                    f"用户: {user.get('nickname', '')}\n"
                    f"抖音号: {user.get('unique_id', '')}\n"
                    f"简介: {user.get('signature', '')[:100]}\n"
                    f"粉丝: {user.get('follower_count', 0)}"
                )
            return f"用户信息: {info}"
        except DouyinAPIClientError as e:
            return f"获取用户信息失败: {e}"
