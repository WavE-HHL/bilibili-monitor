"""
命令行入口 - 无 GUI 模式
用于服务器/无头环境运行
用法: python main.py [--once]
  --once   只执行一次检查，不启动定时任务
"""
import sys
import logging
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('monitor.log', encoding='utf-8'),
    ]
)

from config_manager import load_config, validate_config
from monitor import check_once, run_scheduler


def main():
    cfg = load_config()
    errors = validate_config(cfg)
    if errors:
        print("❌ 配置有误，请先编辑 config.json：")
        for e in errors:
            print(f"   - {e}")
        sys.exit(1)

    if '--once' in sys.argv:
        print("执行单次检查...")
        check_once()
    else:
        run_scheduler()


if __name__ == '__main__':
    main()
