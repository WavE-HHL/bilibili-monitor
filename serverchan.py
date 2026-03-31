"""
Server酱推送模块
支持 Server酱·Turbo (sctapi.ftqq.com) 和 Server酱³ (sc3.ft07.com)
"""
import logging
import requests

logger = logging.getLogger(__name__)


def send_serverchan(
    sendkey: str,
    title: str,
    desp: str = '',
    tags: str = '',
    short: str = '',
) -> bool:
    """
    通过 Server酱 推送消息
    自动识别版本：
      - SCT 开头  → Turbo版  POST https://sctapi.ftqq.com/{key}.send
      - sctp 开头 → ³版      GET  https://sc3.ft07.com/send/{key}
    :param sendkey: Server酱 SendKey
    :param title:   消息标题（最长64字符）
    :param desp:    消息内容（Markdown格式）
    :param tags:    标签，多个用竖线分隔
    :param short:   消息卡片内容摘要
    :return: 是否推送成功
    """
    if not sendkey or not sendkey.strip():
        logger.error("Server酱 SendKey 未配置")
        return False

    sendkey = sendkey.strip()

    try:
        key_lower = sendkey.lower()

        if key_lower.startswith('sct'):
            # ── Turbo 版：POST ──────────────────────────
            url = f'https://sctapi.ftqq.com/{sendkey}.send'
            payload = {'title': title[:64]}
            if desp:
                payload['desp'] = desp
            if tags:
                payload['tags'] = tags
            if short:
                payload['short'] = short
            resp = requests.post(url, data=payload, timeout=15)

        elif key_lower.startswith('sctp'):
            # ── ³ 版：GET，参数放 query string ──────────
            url = f'https://sc3.ft07.com/send/{sendkey}'
            params = {'title': title[:64]}
            if desp:
                params['desp'] = desp
            if tags:
                params['tags'] = tags
            if short:
                params['short'] = short
            resp = requests.get(url, params=params, timeout=15)

        else:
            # 未知格式，尝试 POST 到 sctapi（兜底）
            logger.warning(f"未识别的 SendKey 格式({sendkey[:8]}...)，尝试 Turbo 接口")
            url = f'https://sctapi.ftqq.com/{sendkey}.send'
            payload = {'title': title[:64]}
            if desp:
                payload['desp'] = desp
            resp = requests.post(url, data=payload, timeout=15)

        resp.raise_for_status()
        result = resp.json()

        # 两个版本成功时均返回 errno=0 或 code=0
        errno = result.get('errno', result.get('code', -1))
        if errno == 0:
            logger.info(f"Server酱推送成功: {title}")
            return True
        else:
            logger.warning(f"Server酱推送失败(errno={errno}): {result.get('message', '未知')}")
            return False

    except Exception as e:
        logger.error(f"Server酱推送异常: {e}")
        return False


def format_up_comment(comment: dict) -> str:
    """
    将单条 UP 主评论格式化为 Markdown 消息
    """
    import datetime
    t = datetime.datetime.fromtimestamp(comment['at_time']).strftime('%Y-%m-%d %H:%M')
    bvid = comment['bvid']
    up_name = comment.get('up_name', 'UP主')

    if comment['type'] == 'comment':
        return (
            f"📝 **{up_name} 发了一级评论**\n\n"
            f"> {comment['content']}\n\n"
            f"🕐 {t} | [视频链接](https://www.bilibili.com/video/{bvid})"
        )
    else:
        reply_to = comment.get('reply_to', '某用户')
        reply_content = comment.get('reply_to_content', '')
        short_reply = (reply_content[:40] + '…') if len(reply_content) > 40 else reply_content
        return (
            f"💬 **{up_name} 回复了 @{reply_to}**\n\n"
            f"> **{comment['content']}**\n\n"
            f"被回复内容：{short_reply}\n\n"
            f"🕐 {t} | [视频链接](https://www.bilibili.com/video/{bvid})"
        )


def push_new_comments(
    sendkey: str,
    comments: list[dict],
    video_title: str = '',
) -> bool:
    """
    批量推送 UP 主新评论
    当评论数 <= 3 时逐条推送；超过则合并推送
    :return: 是否全部推送成功
    """
    if not comments:
        return True

    tag = 'B站监控'
    count = len(comments)

    if count <= 3:
        # 逐条推送
        success = True
        for c in comments:
            body = format_up_comment(c)
            up_name = c.get('up_name', 'UP主')
            title = f"【B站】{up_name}新{'评论' if c['type']=='comment' else '回复'} | {c['bvid']}"
            ok = send_serverchan(sendkey, title, body, tags=tag)
            if not ok:
                success = False
        return success
    else:
        # 合并推送
        lines = [f"## 共发现 {count} 条 UP 主新动态\n"]
        if video_title:
            lines.append(f"**视频**：{video_title}\n\n---\n")
        for i, c in enumerate(comments, 1):
            lines.append(f"### {i}. {format_up_comment(c)}\n\n---\n")
        desp = '\n'.join(lines)
        # 取第一条评论的UP主名称作为标题
        up_name = comments[0].get('up_name', 'UP主')
        title = f"【B站监控】{up_name}发现 {count} 条新动态"
        return send_serverchan(sendkey, title, desp, tags=tag)
