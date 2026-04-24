#!/usr/bin/env python3
"""
NagaBusiness 自动签到脚本

用法:
    # 立即签到一次
    python naga_checkin.py --now

    # 每天定时签到（默认 08:00 CST / UTC+8）
    python naga_checkin.py

    # 自定义签到时间（24 小时制，CST 时区）
    python naga_checkin.py --time 09:30

    # 指定账户（也可通过环境变量 NAGA_USERNAME / NAGA_PASSWORD）
    python naga_checkin.py --username alice --password secret123

环境变量:
    NAGA_USERNAME   - 账户用户名
    NAGA_PASSWORD   - 账户密码
    NAGA_API_URL    - API 地址（默认 http://62.234.131.204:30031）
    NAGA_CHECKIN_TIME - 签到时间，格式 HH:MM（默认 08:00）
"""

from __future__ import annotations

import argparse
import json
import logging
import operator
import os
import re
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import httpx

# ── 配置 ──────────────────────────────────────────

CST = timezone(timedelta(hours=8))
DEFAULT_API_URL = "http://62.234.131.204:30031"
DEFAULT_CHECKIN_TIME = "08:00"
TOKEN_FILE = Path.home() / ".naga_checkin_session.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("naga_checkin")


# ── Token 持久化 ──────────────────────────────────

def save_tokens(access_token: str, refresh_token: str) -> None:
    """持久化 token 到文件"""
    TOKEN_FILE.write_text(
        json.dumps({"access_token": access_token, "refresh_token": refresh_token}),
        encoding="utf-8",
    )
    TOKEN_FILE.chmod(0o600)


def load_tokens() -> tuple[Optional[str], Optional[str]]:
    """从文件恢复 token"""
    if not TOKEN_FILE.exists():
        return None, None
    try:
        data = json.loads(TOKEN_FILE.read_text(encoding="utf-8"))
        return data.get("access_token"), data.get("refresh_token")
    except Exception:
        return None, None


def clear_tokens() -> None:
    """清除持久化 token"""
    if TOKEN_FILE.exists():
        TOKEN_FILE.unlink()


# ── API 客户端 ────────────────────────────────────

class NagaClient:
    """NagaBusiness API 客户端，管理登录态和自动刷新"""

    def __init__(self, api_url: str, username: str, password: str) -> None:
        self.api_url: str = api_url.rstrip("/")
        self.username: str = username
        self.password: str = password
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None

        # 尝试恢复已有 token
        self.access_token, self.refresh_token = load_tokens()
        if self.refresh_token:
            log.info("从缓存恢复 token")

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    def _extract_refresh_token(self, resp: httpx.Response) -> Optional[str]:
        """从 Set-Cookie 或响应 body 提取 refresh_token"""
        token = resp.cookies.get("refresh_token")
        if token:
            return token
        try:
            data = resp.json()
            return data.get("refresh_token") or data.get("refreshToken")
        except Exception:
            return None

    def _save(self) -> None:
        if self.access_token and self.refresh_token:
            save_tokens(self.access_token, self.refresh_token)

    @staticmethod
    def _solve_captcha(question: str) -> str:
        """自动解答数学验证码，如 '3 + 5 = ?' → '8'"""
        ops: dict[str, object] = {
            "+": operator.add, "-": operator.sub,
            "*": operator.mul, "×": operator.mul,
            "/": operator.truediv, "÷": operator.truediv,
        }
        # 匹配 "数字 运算符 数字" 模式
        m = re.search(r"(-?\d+)\s*([+\-*/×÷])\s*(-?\d+)", question)
        if m:
            a, op_str, b = int(m.group(1)), m.group(2), int(m.group(3))
            fn = ops.get(op_str)
            if fn:
                return str(int(fn(a, b)))  # type: ignore[operator]
        # 兜底：尝试 eval 纯数学表达式
        expr = re.sub(r"[=?？]", "", question).replace("×", "*").replace("÷", "/").strip()
        try:
            return str(int(eval(expr)))  # noqa: S307
        except Exception:
            log.warning(f"无法自动解答验证码: {question}")
            return ""

    def _get_captcha(self) -> tuple[str, str]:
        """获取验证码并自动解答，返回 (captcha_id, answer)"""
        with httpx.Client(timeout=15) as client:
            resp = client.get(f"{self.api_url}/api/auth/captcha")
            resp.raise_for_status()
            data = resp.json()

        captcha_id: str = data.get("captcha_id") or data.get("captchaId", "")
        question: str = data.get("question", "")
        log.info(f"验证码: {question}")

        answer = self._solve_captcha(question)
        if answer:
            log.info(f"验证码解答: {answer}")
        return captcha_id, answer

    def login(self) -> bool:
        """登录获取 token（自动处理验证码）"""
        log.info(f"正在登录: {self.username}")
        try:
            # 先获取并解答验证码
            captcha_id, captcha_answer = self._get_captcha()
            if not captcha_id or not captcha_answer:
                log.error("获取或解答验证码失败")
                return False

            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{self.api_url}/api/auth/login",
                    json={
                        "username": self.username,
                        "password": self.password,
                        "captcha_id": captcha_id,
                        "captcha_answer": captcha_answer,
                    },
                )
                if resp.status_code != 200:
                    log.error(f"登录失败 [{resp.status_code}]: {resp.text}")
                    return False

                data = resp.json()
                self.access_token = data.get("access_token") or data.get("accessToken")
                if not self.access_token:
                    log.error("登录响应中缺少 access_token")
                    return False

                rt = self._extract_refresh_token(resp)
                if rt:
                    self.refresh_token = rt
                self._save()
                log.info("登录成功")
                return True
        except Exception as e:
            log.error(f"登录异常: {e}")
            return False

    def refresh_access_token(self) -> bool:
        """用 refresh_token 刷新 access_token"""
        if not self.refresh_token:
            log.warning("无 refresh_token，需要重新登录")
            return False

        log.info("正在刷新 access_token ...")
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.post(
                    f"{self.api_url}/api/auth/refresh",
                    cookies={"refresh_token": self.refresh_token},
                )
                if resp.status_code != 200:
                    log.warning(f"刷新失败 [{resp.status_code}]: {resp.text}")
                    return False

                data = resp.json()
                self.access_token = data.get("access_token") or data.get("accessToken")

                new_rt = self._extract_refresh_token(resp)
                if new_rt:
                    self.refresh_token = new_rt
                self._save()
                log.info("token 刷新成功")
                return True
        except Exception as e:
            log.warning(f"刷新异常: {e}")
            return False

    def ensure_auth(self) -> bool:
        """确保有有效的认证状态，必要时自动刷新或重新登录"""
        # 先尝试刷新
        if self.refresh_token and self.refresh_access_token():
            return True
        # 刷新失败则重新登录
        return self.login()

    def check_in(self) -> dict | None:
        """执行签到，自动处理 401 重试"""
        for attempt in range(2):
            if not self.access_token and not self.ensure_auth():
                return None

            try:
                with httpx.Client(timeout=15) as client:
                    resp = client.post(
                        f"{self.api_url}/api/affinity/check-in",
                        headers=self._headers(),
                    )

                    if resp.status_code == 401 and attempt == 0:
                        log.info("access_token 过期，尝试刷新 ...")
                        if self.ensure_auth():
                            continue
                        return None

                    if resp.status_code != 200:
                        log.error(f"签到请求失败 [{resp.status_code}]: {resp.text}")
                        return None

                    return resp.json()
            except Exception as e:
                log.error(f"签到请求异常: {e}")
                return None
        return None

    def get_checkin_status(self) -> dict | None:
        """查询签到状态"""
        if not self.access_token and not self.ensure_auth():
            return None
        try:
            with httpx.Client(timeout=15) as client:
                resp = client.get(
                    f"{self.api_url}/api/affinity/check-in/status",
                    headers=self._headers(),
                )
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return None


# ── 签到逻辑 ──────────────────────────────────────

def do_checkin(naga: NagaClient) -> bool:
    """执行一次签到并打印结果，返回是否成功"""
    result = naga.check_in()
    if result is None:
        log.error("签到失败")
        return False

    already = result.get("already_checked_in") or result.get("alreadyCheckedIn", False)
    if already:
        log.info("今日已签到，无需重复签到")
        return True

    earned = result.get("affinity_earned") or result.get("affinityEarned", "0")
    credits = result.get("credits_earned") or result.get("creditsEarned", 0)
    streak = result.get("streak_days") or result.get("streakDays", 0)
    bonus = result.get("bonus_credits") or result.get("bonusCredits", 0)

    msg = f"签到成功! 熟悉度 +{earned}, 积分 +{credits}, 连签 {streak} 天"
    if bonus:
        msg += f" (连签奖励 +{bonus})"
    log.info(msg)
    return True


def seconds_until(hour: int, minute: int) -> float:
    """计算从现在到下一个 CST 指定时刻的秒数"""
    now = datetime.now(CST)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


def run_scheduler(naga: NagaClient, checkin_hour: int, checkin_minute: int) -> None:
    """定时签到主循环"""
    log.info(f"定时签到已启动，每天 {checkin_hour:02d}:{checkin_minute:02d} (CST) 自动签到")
    log.info("按 Ctrl+C 退出")

    # 优雅退出
    def handle_signal(sig: int, _frame: object) -> None:
        log.info("收到退出信号，正在停止 ...")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    while True:
        wait = seconds_until(checkin_hour, checkin_minute)
        next_time = datetime.now(CST) + timedelta(seconds=wait)
        log.info(f"下次签到: {next_time.strftime('%Y-%m-%d %H:%M:%S')} CST (等待 {wait:.0f} 秒)")
        time.sleep(wait)

        # 执行签到，失败重试最多 3 次，间隔 5 分钟
        for retry in range(3):
            if do_checkin(naga):
                break
            if retry < 2:
                log.warning(f"签到失败，{5} 分钟后重试 ({retry + 2}/3)")
                time.sleep(300)


# ── 入口 ──────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="NagaBusiness 自动签到脚本")
    parser.add_argument("--now", action="store_true", help="立即签到一次后退出")
    parser.add_argument("--username", "-u", default=os.environ.get("NAGA_USERNAME", ""), help="账户用户名（或设置 NAGA_USERNAME 环境变量）")
    parser.add_argument("--password", "-p", default=os.environ.get("NAGA_PASSWORD", ""), help="账户密码（或设置 NAGA_PASSWORD 环境变量）")
    parser.add_argument("--api-url", default=os.environ.get("NAGA_API_URL", DEFAULT_API_URL), help=f"API 地址（默认 {DEFAULT_API_URL}）")
    parser.add_argument("--time", "-t", default=os.environ.get("NAGA_CHECKIN_TIME", DEFAULT_CHECKIN_TIME), help="签到时间 HH:MM（CST, 默认 08:00）")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.username or not args.password:
        log.error("请通过 --username/--password 参数或 NAGA_USERNAME/NAGA_PASSWORD 环境变量提供账户信息")
        sys.exit(1)

    # 解析签到时间
    try:
        parts = args.time.split(":")
        checkin_hour, checkin_minute = int(parts[0]), int(parts[1])
        if not (0 <= checkin_hour <= 23 and 0 <= checkin_minute <= 59):
            raise ValueError
    except (ValueError, IndexError):
        log.error(f"无效的时间格式: {args.time}，请使用 HH:MM 格式")
        sys.exit(1)

    naga = NagaClient(api_url=args.api_url, username=args.username, password=args.password)

    if args.now:
        # 立即签到模式
        if not naga.ensure_auth():
            log.error("认证失败，请检查账户信息")
            sys.exit(1)
        success = do_checkin(naga)
        sys.exit(0 if success else 1)
    else:
        # 定时签到模式
        if not naga.ensure_auth():
            log.error("认证失败，请检查账户信息")
            sys.exit(1)
        run_scheduler(naga, checkin_hour, checkin_minute)


if __name__ == "__main__":
    main()
