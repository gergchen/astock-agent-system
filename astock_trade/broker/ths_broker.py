"""同花顺模拟交易券商适配器 — THS virtual/simulated trading broker.

Supports 同花顺虚拟账号 for paper trading validation.
Phase 1: wraps easytrader. Phase 2: native THS API.
"""

import logging
import os
import threading
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from .base import (
    Account, BrokerBase, Order, OrderSide, OrderStatus, OrderType, Position,
)

if TYPE_CHECKING:
    from .captcha_solver import CaptchaSolver

logger = logging.getLogger(__name__)


class THSBroker(BrokerBase):
    """同花顺模拟交易券商 — wraps easytrader for THS paper trading.

    Setup:
      1. 下载安装同花顺网上股票交易系统
      2. 注册模拟交易账号（同花顺模拟炒股）
      3. pip install easytrader
      4. broker = THSBroker(prepare=True)  # 首次需准备

    Usage:
      broker = THSBroker()
      broker.connect()
      broker.place_order("600519", OrderSide.BUY, 1850.0, 100)
      broker.get_positions()
    """

    CAPTCHA_IMG_CTRL = 0x965   # 验证码图片 Static
    CAPTCHA_EDIT_CTRL = 0x964  # 验证码输入框 Edit

    def __init__(self, exe_path: Optional[str] = None, mock_fallback: bool = True,
                 captcha_solver: Optional["CaptchaSolver"] = None):
        """
        Args:
            exe_path: 同花顺下单程序路径 (xiadan.exe)，None 则自动查找
            mock_fallback: 若 easytrader 不可用，是否降级到 MockBroker
            captcha_solver: 验证码自动识别器（传入则自动打码）
        """
        self._exe_path = exe_path
        self._mock_fallback = mock_fallback
        self._user = None
        self._connected = False
        self._orders: dict[str, Order] = {}
        self._lock = threading.Lock()
        self._using_mock = False
        self._captcha_solver = captcha_solver
        # 账户数据缓存，避免频繁触发验证码弹窗
        self._cached_account: Optional[Account] = None
        self._cache_time: float = 0
        self._cache_ttl: float = 300.0  # 缓存5分钟，减少触发验证码频率

    # ── 连接管理 ───────────────────────────────────────────────

    def connect(self) -> bool:
        """连接到同花顺模拟交易客户端。"""
        import os as _os
        _tess_path = r"C:\Program Files\Tesseract-OCR"
        if _os.path.isdir(_tess_path) and _tess_path not in _os.environ["PATH"]:
            _os.environ["PATH"] += _os.pathsep + _tess_path
        import pytesseract as _pyt
        _pyt.pytesseract.tesseract_cmd = _os.path.join(_tess_path, "tesseract.exe")

        # 设置 TESSDATA_PREFIX 使 Tesseract 能找到中文语言包
        _chi_sim_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "..", "chi_sim.traineddata")
        _chi_sim_dir = _os.path.dirname(_os.path.abspath(_chi_sim_path))
        if _os.path.isfile(_os.path.join(_chi_sim_dir, "chi_sim.traineddata")):
            _os.environ.setdefault("TESSDATA_PREFIX", _chi_sim_dir)

        # Monkey-patch easytrader 验证码识别：使用中文语言包
        try:
            from easytrader.utils import captcha as _captcha_mod
            _orig_recognize = _captcha_mod.captcha_recognize

            def _patched_recognize(img_path):
                import pytesseract as _pt
                from PIL import Image as _PILImage
                _im = _PILImage.open(img_path).convert("L")
                _threshold = 200
                _table = [0 if i < _threshold else 1 for i in range(256)]
                _out = _im.point(_table, "1")
                return _pt.image_to_string(_out, lang="chi_sim")

            _captcha_mod.captcha_recognize = _patched_recognize
        except Exception as _e:
            logger.warning("易筋经验证码补丁失败: %s", _e)

        try:
            import easytrader
            user = easytrader.use("ths")

            exe_path = self._exe_path
            if not exe_path:
                # 从同花顺进程获取路径
                import psutil
                for proc in psutil.process_iter(["name", "exe"]):
                    if proc.info["name"] == "xiadan.exe":
                        exe_path = proc.info["exe"]
                        break

            if exe_path:
                user.connect(exe_path)
            else:
                # 自动查找
                user.connect()

            self._user = user
            self._connected = True
            return True
        except ImportError:
            if self._mock_fallback:
                from .mock_broker import MockBroker
                self._mock = MockBroker()
                self._mock.connect()
                self._connected = True
                self._using_mock = True
                return True
            raise
        except Exception as e:
            if self._mock_fallback:
                from .mock_broker import MockBroker
                self._mock = MockBroker()
                self._mock.connect()
                self._connected = True
                self._using_mock = True
                return True
            raise ConnectionError(f"无法连接同花顺客户端: {e}")

    def disconnect(self) -> None:
        if self._using_mock:
            self._mock.disconnect()
        self._connected = False

    # ── 验证码弹窗处理 ─────────────────────────────────────────

    _captcha_img_path: str = ""

    @classmethod
    def _get_captcha_img_path(cls) -> str:
        if not cls._captcha_img_path:
            import tempfile
            cls._captcha_img_path = os.path.join(tempfile.gettempdir(), "ths_captcha.png")
        return cls._captcha_img_path

    def _find_captcha_dialog(self):
        """查找验证码弹窗，返回 (dialog, exists) 。"""
        try:
            if not self._user or not self._user.app:
                return None, False
            for w in self._user.app.windows(class_name="#32770"):
                if w.is_visible():
                    for ctrl in w.descendants():
                        txt = ctrl.window_text() or ""
                        if "验证码" in txt:
                            return w, True
        except Exception:
            pass
        return None, False

    def _dismiss_captcha(self) -> bool:
        """检测并关闭验证码弹窗。"""
        w, found = self._find_captcha_dialog()
        if found:
            try:
                w.Button2.click()
                logger.info("已关闭验证码弹窗")
                time.sleep(0.3)
                return True
            except Exception:
                pass
        return False

    def _submit_captcha(self, code: str) -> bool:
        """向验证码弹窗填入识别结果。"""
        w, found = self._find_captcha_dialog()
        if not found:
            logger.warning("未找到验证码弹窗")
            return False
        try:
            edit = w.window(control_id=self.CAPTCHA_EDIT_CTRL, class_name="Edit")
            edit.set_text(code)
            w.set_focus()
            import pywinauto.keyboard
            pywinauto.keyboard.SendKeys("{ENTER}")
            logger.info("验证码已提交: %s", code)
            time.sleep(0.5)
            return True
        except Exception as e:
            logger.error("提交验证码失败: %s", e)
            return False

    def _auto_solve_captcha(self) -> bool:
        """自动识别并提交验证码（使用打码平台）。"""
        if not self._captcha_solver:
            return False
        w, found = self._find_captcha_dialog()
        if not found:
            return False
        try:
            img_path = self._get_captcha_img_path()
            ctrl = w.window(control_id=self.CAPTCHA_IMG_CTRL, class_name="Static")
            ctrl.capture_as_image().save(img_path)
            code = self._captcha_solver.solve(img_path)
            if code:
                return self._submit_captcha(code)
            return False
        except Exception as e:
            logger.warning("自动识别验证码失败: %s", e)
            return False

    def _get_from_cache(self) -> Optional[Account]:
        if self._cached_account and (time.time() - self._cache_time) < self._cache_ttl:
            return self._cached_account
        return None

    # ── 账户查询 ───────────────────────────────────────────────

    def get_account(self) -> Account:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.get_account()

        # 先查缓存（减少触发验证码频率）
        cached = self._get_from_cache()
        if cached is not None:
            return cached

        # 读取前主动关闭可能存在的旧验证码弹窗
        self._dismiss_captcha()

        # 重试读取，弹验证码则等手动输入或自动打码
        for _ in range(30):  # 最多等~90秒（30 × 3s）
            try:
                balance = self._user.balance
                pdata = self._user.position or []
                positions = []
                for p in pdata:
                    positions.append(Position(
                        symbol=p.get("证券代码", ""),
                        volume=int(p.get("股票余额", 0)),
                        avg_cost=float(p.get("成本价", 0)),
                        current_price=float(p.get("市价", 0)),
                        market_value=float(p.get("市值", 0)),
                        pnl=float(p.get("盈亏", 0)),
                        pnl_pct=float(p.get("盈亏比例(%)", 0)),
                    ))

                acct = Account(
                    cash=float(balance.get("可用金额", 0)),
                    frozen=float(balance.get("冻结金额", 0)),
                    total_assets=float(balance.get("总资产", 0)),
                    positions=positions,
                )
                self._cached_account = acct
                self._cache_time = time.time()
                return acct

            except Exception:
                # 有验证码弹窗 → 自动打码或等手动输入
                if self._auto_solve_captcha():
                    time.sleep(2)
                    continue
                _, captcha_active = self._find_captcha_dialog()
                if captcha_active:
                    if self._captcha_solver:
                        logger.info("验证码识别中...")
                    else:
                        logger.info("验证码弹窗中 → 你看屏幕手动输入后自动继续")
                    time.sleep(3)
                    continue

                # 非验证码错误 → 有缓存则用缓存，否则重试
                stale = self._cached_account
                if stale is not None and (time.time() - self._cache_time) < 600:
                    return stale
                time.sleep(2)

        # 全部重试耗尽 → 降级 MockBroker
        logger.warning("THS 持续失败（验证码未解决），降级 MockBroker")
        self._dismiss_captcha()
        from .mock_broker import MockBroker
        self._mock = MockBroker()
        self._mock.connect()
        self._using_mock = True
        return self._mock.get_account()

    def get_positions(self) -> list[Position]:
        acct = self.get_account()
        return acct.positions or []

    # ── 下单 ──────────────────────────────────────────────────

    def place_order(self, symbol: str, side: OrderSide, price: float,
                    volume: int, order_type: OrderType = OrderType.LIMIT) -> Order:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.place_order(symbol, side, price, volume, order_type)

        with self._lock:
            if side == OrderSide.BUY:
                result = self._user.buy(symbol, price=price, amount=volume)
            else:
                result = self._user.sell(symbol, price=price, amount=volume)

        entrust_no = str(result.get("委托编号", ""))
        contract_no = str(result.get("合同编号", ""))
        order_id = contract_no or entrust_no or str(datetime.now().timestamp())
        order = Order(
            symbol=symbol,
            side=side,
            price=price,
            volume=volume,
            order_type=order_type,
            order_id=order_id,
            status=OrderStatus.PENDING,
            filled_volume=0,
            filled_price=0.0,
            created_at=datetime.now(),
        )
        self._orders[order_id] = order
        return order

    def cancel_order(self, order_id: str) -> bool:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.cancel_order(order_id)

        with self._lock:
            result = self._user.cancel_entrust(order_id)
        if isinstance(result, dict) and result.get("message") == "已受理":
            if order_id in self._orders:
                self._orders[order_id].status = OrderStatus.CANCELLED
            return True
        return False

    # ── 订单查询 ───────────────────────────────────────────────

    def get_order(self, order_id: str) -> Optional[Order]:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.get_order(order_id)
        return self._orders.get(order_id)

    def get_orders(self, symbol: Optional[str] = None) -> list[Order]:
        self._ensure_connected()
        if self._using_mock:
            return self._mock.get_orders(symbol)

        # 同步实际订单状态
        try:
            entrusts = self._user.entrust
            for e in (entrusts or []):
                eid = str(e.get("委托编号", ""))
                status_text = e.get("状态", "")
                if eid in self._orders:
                    if "成交" in status_text:
                        self._orders[eid].status = OrderStatus.FILLED
                        self._orders[eid].filled_volume = int(e.get("成交数量", 0))
                        self._orders[eid].filled_price = float(e.get("成交价格", 0))
                    elif "撤" in status_text:
                        self._orders[eid].status = OrderStatus.CANCELLED
        except Exception:
            pass

        orders = list(self._orders.values())
        if symbol:
            orders = [o for o in orders if o.symbol == symbol]
        return orders

    # ── 模拟账户快捷入口 ──────────────────────────────────────

    @staticmethod
    def get_virtual_account_url() -> str:
        """获取同花顺模拟炒股注册地址。"""
        return "https://moni.10jqka.com.cn/"

    @property
    def using_mock(self) -> bool:
        """是否降级使用了 MockBroker。"""
        return self._using_mock

    def _ensure_connected(self):
        if not self._connected:
            raise RuntimeError("未连接同花顺客户端，请先调用 connect()")
