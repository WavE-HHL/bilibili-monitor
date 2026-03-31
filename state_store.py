"""
已推送评论 rpid 持久化存储（去重）
用 JSON 文件存储各视频已处理的最大 rpid
"""
import json
import os
import logging

logger = logging.getLogger(__name__)

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'state.json')


def load_state() -> dict:
    """
    加载已处理状态
    结构: { "BV1xxxxx": <max_rpid>, ... }
    """
    if not os.path.exists(STATE_PATH):
        return {}
    with open(STATE_PATH, 'r', encoding='utf-8') as f:
        try:
            return json.load(f)
        except Exception:
            return {}


def save_state(state: dict):
    """保存状态"""
    with open(STATE_PATH, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def get_last_rpid(bvid: str) -> int:
    """获取某视频最后处理的 rpid（0 表示从未处理）"""
    state = load_state()
    return state.get(bvid, 0)


def update_last_rpid(bvid: str, rpid: int):
    """更新某视频最后处理的 rpid"""
    state = load_state()
    old = state.get(bvid, 0)
    if rpid > old:
        state[bvid] = rpid
        save_state(state)
        logger.debug(f"[{bvid}] 更新 last_rpid: {old} -> {rpid}")


def reset_state():
    """
    重置所有监控记录
    删除 state.json 文件，让监控重新从 0 开始
    """
    if os.path.exists(STATE_PATH):
        try:
            os.remove(STATE_PATH)
            logger.info("监控记录已重置，state.json 已删除")
            return True
        except Exception as e:
            logger.error(f"重置监控记录失败: {e}")
            return False
    else:
        logger.info("监控记录文件不存在，无需重置")
        return True


def get_all_history() -> dict:
    """获取所有历史记录（用于显示）"""
    return load_state()
