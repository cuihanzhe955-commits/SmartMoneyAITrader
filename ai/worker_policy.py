"""Bounded worker retry policy; never replays a transaction body."""
import logging


class BrainBusy(ValueError):
    pass


class WorkerUnavailable(ValueError):
    pass


def run_worker(tick, stop, report, interval=1):
    failures = 0
    while not stop.wait(min(30, interval * 2 ** min(failures, 5))):
        try:
            tick()
            failures = 0
        except WorkerUnavailable:
            failures += 1
            report('复盘模型未配置；任务保留，等待配置后重试')
        except BrainBusy:
            failures += 1
            logging.getLogger(__name__).warning('Worker database busy; durable state retained', exc_info=True)
            report('数据库暂忙；任务保留，退避重试')
        except Exception:
            logging.getLogger(__name__).exception('Worker stopped after unexpected failure')
            report('工作线程异常已停止；任务保留，请检查日志并重新启动服务')
            return
