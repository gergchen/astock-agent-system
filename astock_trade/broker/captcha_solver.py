"""验证码自动识别 — 打码平台集成.

目前支持:
  - 超级鹰 (chaojiying.com) : 最通用的中文验证码识别
"""

import base64
import logging
import time
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class CaptchaSolver(ABC):
    """验证码识别抽象接口。"""

    @abstractmethod
    def solve(self, image_path: str) -> Optional[str]:
        """识别验证码图片，返回文本。失败返回 None。"""
        ...


class SuperEagleSolver(CaptchaSolver):
    """超级鹰打码平台 (chaojiying.com)。

    API: https://www.chaojiying.com/api-1.html
    注册: https://www.chaojiying.com/ → 免费注册 → 充值（1元起）
    价格: ~1元/1000次识别
    codetype=1902 → 常见中英文验证码（同花顺适用）
    """

    API_URL = "http://upload.chaojiying.net/Upload/Processing.php"

    def __init__(self, username: str, password: str, soft_id: str = "956802",
                 code_type: int = 1902):
        """
        Args:
            username: 超级鹰账号
            password: 超级鹰密码（或识别密匙）
            soft_id: 软件ID，默认用公开的测试ID 956802
            code_type: 验证码类型，1902=常见中英文
        """
        self._username = username
        self._password = password
        self._soft_id = soft_id
        self._code_type = code_type

    def solve(self, image_path: str) -> Optional[str]:
        try:
            import requests
            with open(image_path, "rb") as f:
                img_data = f.read()
            img_b64 = base64.b64encode(img_data).decode()

            resp = requests.post(
                self.API_URL,
                data={
                    "user": self._username,
                    "pass": self._password,
                    "softid": self._soft_id,
                    "codetype": self._code_type,
                },
                files={"userfile": (f"captcha.png", img_data, "image/png")},
                timeout=15,
            )
            result = resp.json()
            if result.get("err_no") == 0:
                code = result.get("pic_str", "").strip()
                logger.info("超级鹰识别成功: %s", code)
                return code
            else:
                logger.warning("超级鹰识别失败: %s", result.get("err_str", "未知错误"))
                return None
        except Exception as e:
            logger.warning("超级鹰请求异常: %s", e)
            return None


class DummySolver(CaptchaSolver):
    """兜底 — 不识别，等待手动输入（或直接返回 None 走降级）。"""

    def solve(self, image_path: str) -> Optional[str]:
        logger.info("无打码平台配置，跳过验证码识别")
        return None


def create_solver(platform: str = "",
                  username: str = "", password: str = "",
                  soft_id: str = "") -> CaptchaSolver:
    """根据配置创建验证码识别器。"""
    if platform == "super_eagle" and username and password:
        return SuperEagleSolver(username=username, password=password,
                                soft_id=soft_id or "956802")
    return DummySolver()
