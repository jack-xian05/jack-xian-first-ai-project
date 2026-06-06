"""
进程守护脚本 —— 适用于没有 systemd 的环境（Windows 开发机、简单 VPS）。

功能：
  - 启动并持续监控被守护进程，进程崩溃后自动重启（指数退避，防止错误环境下狂刷）
  - 可同时守护 Streamlit 前端 + FastAPI 后端（--with-api），任一崩溃各自独立重启
  - 可选 HTTP 健康检测（--health-check）：进程活着但服务卡死/不响应时也触发重启
        · Streamlit 查 /_stcore/health   · FastAPI 查 /health  —— 各查各的端点
  - 连续稳定运行一段时间后崩溃计数清零；持续崩溃超上限则放弃并报错，避免假死循环
  - 收到 Ctrl-C / SIGTERM 时优雅停掉所有子进程
  - 日志同时写入 watchdog.log 和终端

用法：
    python watchdog.py                      # 只守护 Streamlit
    python watchdog.py --with-api           # 同时守护 Streamlit + FastAPI 后端
    python watchdog.py --health-check       # 启用 HTTP 健康检测（前后端各查各的端点）
    python watchdog.py --port 8502          # 指定 Streamlit 端口
    python watchdog.py --app law_app_v3.py  # 指定要守护的 Streamlit 应用文件

Linux 生产环境请优先用 deploy/law-app.service（systemd），不需要此脚本。
"""
import argparse
import logging
import signal
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ===== 参数 =====
CHECK_INTERVAL = 30        # 健康检查间隔（秒）
MAX_RESTARTS = 10          # 连续崩溃次数上限，超出后守护退出
BACKOFF_BASE = 5           # 重启退避基准秒数
BACKOFF_MAX = 120          # 退避上限秒数
STARTUP_GRACE = 8          # 进程启动后宽限时间（秒），期间不做健康检查，避免误判启动期
STABLE_RESET = 120         # 进程连续稳定运行满此秒数，崩溃计数清零（视为已恢复健康）
HEALTH_TIMEOUT = 5         # HTTP 健康检查超时（秒）

API_PORT = 8000
LOG_FILE = Path(__file__).parent / "watchdog.log"
HEALTH_URL_API = f"http://127.0.0.1:{API_PORT}/health"
# Streamlit 自带的健康端点，返回 200 + "ok"
HEALTH_URL_STREAMLIT = "http://127.0.0.1:{port}/_stcore/health"

# ===== 日志 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("watchdog")

# 被守护的服务列表（供信号处理器清理）
_services: "List[Service]" = []
_stop = False


# ===== 信号处理：Ctrl-C / kill 优雅退出 =====
def _signal_handler(sig, frame):
    global _stop
    log.info(f"收到信号 {sig}，正在退出守护...")
    _stop = True
    for svc in _services:
        if svc.proc and svc.proc.poll() is None:
            svc.proc.terminate()
            try:
                svc.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                svc.proc.kill()


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ===== 工具函数 =====
def _start(cmd: list) -> subprocess.Popen:
    log.info(f"启动: {' '.join(cmd)}")
    return subprocess.Popen(cmd)


def _check_http(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT) as r:
            return r.status == 200
    except Exception:
        return False


def _kill(proc: subprocess.Popen):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def _interruptible_sleep(seconds: float):
    """可被信号打断的 sleep：守护退出 / 退避等待期间收到 Ctrl-C 能秒退，不用等满。"""
    end = time.time() + seconds
    while not _stop and time.time() < end:
        time.sleep(min(1.0, end - time.time()))


@dataclass
class Service:
    """一个被守护的子进程及其运行状态。"""
    cmd: List[str]
    label: str
    health_url: Optional[str] = None
    proc: Optional[subprocess.Popen] = field(default=None, init=False)
    restarts: int = field(default=0, init=False)
    started_at: float = field(default=0.0, init=False)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def spawn(self):
        self.proc = _start(self.cmd)
        self.started_at = time.time()

    def uptime(self) -> float:
        return time.time() - self.started_at


def supervise(services: List[Service]) -> bool:
    """
    在单循环里统一守护多个进程：哪个挂了就重启哪个，各自独立退避与健康检查。
    返回 True 表示正常退出（收到停止信号），False 表示某进程连续崩溃超限。
    """
    while not _stop:
        for svc in services:
            # ── 启动 / 崩溃后重启 ──
            if not svc.alive():
                if svc.proc is not None:   # 不是首启，而是崩溃了
                    svc.restarts += 1
                    log.warning(f"[{svc.label}] 进程退出（exit={svc.proc.returncode}），"
                                f"第 {svc.restarts} 次重启")
                    if svc.restarts > MAX_RESTARTS:
                        log.error(f"[{svc.label}] 连续崩溃 {MAX_RESTARTS} 次，停止守护。"
                                  f"检查 {LOG_FILE} 排查根因。")
                        return False
                    wait = min(BACKOFF_BASE * (2 ** (svc.restarts - 1)), BACKOFF_MAX)
                    log.info(f"[{svc.label}] 等待 {wait}s 后重启...")
                    _interruptible_sleep(wait)
                    if _stop:
                        break
                svc.spawn()
                continue

            # ── 启动宽限期内不健康检查，避免误判 ──
            if svc.uptime() < STARTUP_GRACE:
                continue

            # ── HTTP 健康检查：进程活着但服务卡死也要重启 ──
            if svc.health_url and not _check_http(svc.health_url):
                log.warning(f"[{svc.label}] HTTP 健康检查失败（{svc.health_url}），重启进程...")
                _kill(svc.proc)   # 杀掉后下一轮 alive()=False，走重启分支并计数
                continue

            # ── 连续稳定运行足够久，崩溃计数清零（视为已恢复）──
            if svc.restarts and svc.uptime() > STABLE_RESET:
                log.info(f"[{svc.label}] 已稳定运行 {STABLE_RESET}s，重置崩溃计数")
                svc.restarts = 0

        if _stop:
            break
        _interruptible_sleep(CHECK_INTERVAL)

    # 收到停止信号，清理所有子进程
    for svc in services:
        if svc.alive():
            _kill(svc.proc)
    return True


def main():
    parser = argparse.ArgumentParser(description="劳动法助手进程守护")
    parser.add_argument("--port", type=int, default=8501, help="Streamlit 端口（默认 8501）")
    parser.add_argument("--app", default="law_app_v2.py", help="Streamlit 应用文件")
    parser.add_argument("--with-api", action="store_true",
                        help="同时启动并守护 FastAPI 后端（law_api.py）")
    parser.add_argument("--health-check", action="store_true",
                        help="启用 HTTP 健康检测：Streamlit 查 /_stcore/health，"
                             "FastAPI 查 /health（各查各的端点）")
    args = parser.parse_args()

    log.info("=" * 50)
    log.info("劳动法助手守护进程启动")
    log.info(f"  Streamlit 应用: {args.app}:{args.port}")
    if args.with_api:
        log.info(f"  FastAPI 后端: law_api.py:{API_PORT}")
    if args.health_check:
        log.info("  HTTP 健康检测: 已启用")
    log.info("=" * 50)

    # 先 API、后 Streamlit：保证后端先就绪（supervise 按列表顺序首启）
    if args.with_api:
        api_cmd = [
            sys.executable, "-m", "uvicorn", "law_api:app",
            "--port", str(API_PORT), "--host", "127.0.0.1",
        ]
        _services.append(Service(
            cmd=api_cmd,
            label="fastapi",
            health_url=HEALTH_URL_API if args.health_check else None,
        ))

    streamlit_cmd = [
        sys.executable, "-m", "streamlit", "run", args.app,
        "--server.port", str(args.port),
        "--server.headless", "true",
    ]
    _services.append(Service(
        cmd=streamlit_cmd,
        label="streamlit",
        health_url=HEALTH_URL_STREAMLIT.format(port=args.port) if args.health_check else None,
    ))

    ok = supervise(_services)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
