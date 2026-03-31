"""
配置管理模块
配置保存在 config.json，提供读写接口
"""
import json
import os
import logging

logger = logging.getLogger(__name__)

# 配置文件路径（与脚本同目录）
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

DEFAULT_CONFIG = {
    "videos": [
        {"bvid": "", "title": "视频1", "up_uid": "", "up_name": ""},
        {"bvid": "", "title": "视频2", "up_uid": "", "up_name": ""},
    ],
    "sendkey": "",
    "cookie": "",
    "interval_minutes": 30,
    "interval_seconds": 0,    # >0 时优先使用秒级间隔（用于高频游标模式）
    "use_cursor_mode": False,  # True = 游标高频模式，False = 原页码模式
    "max_pages_per_check": 5,
    "notify_on_start": True,
}


def load_config() -> dict:
    """读取配置，若不存在则创建默认配置"""
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()

    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        try:
            cfg = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"配置文件解析失败: {e}，使用默认配置")
            return DEFAULT_CONFIG.copy()

    # 补全缺失字段
    for k, v in DEFAULT_CONFIG.items():
        if k not in cfg:
            cfg[k] = v

    return cfg


def save_config(cfg: dict):
    """保存配置到文件"""
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    logger.info("配置已保存")


def validate_config(cfg: dict) -> list[str]:
    """
    验证配置有效性
    :return: 错误信息列表，为空表示通过
    """
    errors = []
    videos = cfg.get('videos', [])
    valid_videos = [v for v in videos if v.get('bvid', '').strip()]
    if not valid_videos:
        errors.append("至少需要配置 1 个有效的视频 BV 号")

    # 每个视频都需要配置对应的 UP 主 UID 和 UP 主名称
    for i, v in enumerate(videos, 1):
        if v.get('bvid', '').strip():
            if not str(v.get('up_uid', '')).strip():
                errors.append(f"视频{i}({v.get('bvid','')}) 未配置对应的 UP 主 UID")
            if not v.get('up_name', '').strip():
                errors.append(f"视频{i}({v.get('bvid','')}) 未配置对应的 UP 主名称")

    if not cfg.get('sendkey', '').strip():
        errors.append("Server酱 SendKey 不能为空")

    interval = cfg.get('interval_minutes', 0)
    interval_sec = cfg.get('interval_seconds', 0)
    use_cursor = cfg.get('use_cursor_mode', False)

    if use_cursor:
        # 游标模式：秒级间隔，最低 30 秒
        if interval_sec > 0 and interval_sec < 30:
            errors.append("游标模式下 interval_seconds 不能小于 30 秒")
        elif interval_sec == 0 and (not isinstance(interval, (int, float)) or interval < 1):
            errors.append("游标模式下 interval_minutes 不能小于 1 分钟")
    else:
        # 原页码模式：最低 5 分钟
        if not isinstance(interval, (int, float)) or interval < 5:
            errors.append("监测间隔不能小于 5 分钟")

    return errors


def save_config_json(config: dict) -> bool:
    """
    保存配置为JSON字符串（供GUI使用）
    :return: 是否保存成功
    """
    try:
        # 验证配置
        errors = validate_config(config)
        if errors:
            logger.warning(f"配置验证失败: {errors}")
            return False
        save_config(config)
        return True
    except Exception as e:
        logger.error(f"配置保存失败: {e}")
        return False
