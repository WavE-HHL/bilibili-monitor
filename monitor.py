"""
监测调度核心
支持两种模式：
  1. 原页码模式（use_cursor_mode=false）：每 interval_minutes 分钟检查一次，最低 5 分钟
  2. 游标高频模式（use_cursor_mode=true）：每 interval_seconds 秒检查一次，最低 30 秒
     每次只发 1 个请求，适合接近实时的监控场景
"""
import logging
import time

from config_manager import load_config, validate_config
from bilibili_wbi import fetch_wbi_keys
from bilibili_crawler import create_session, get_up_comments, get_up_comments_cursor
from serverchan import push_new_comments, send_serverchan
from state_store import get_last_rpid, update_last_rpid

logger = logging.getLogger(__name__)


def check_once():
    """执行一次完整的检查循环（页码模式）"""
    cfg = load_config()
    errors = validate_config(cfg)
    if errors:
        logger.error("配置不完整，跳过本次检查：" + " | ".join(errors))
        return

    sendkey = cfg['sendkey']
    max_pages = cfg.get('max_pages_per_check', 5)
    videos = [v for v in cfg['videos'] if v.get('bvid', '').strip()]

    session = create_session(cfg.get('cookie', ''))

    try:
        img_key, sub_key = fetch_wbi_keys(session)
        logger.info(f"WBI 密钥获取成功: img_key={img_key[:8]}...")
    except Exception as e:
        logger.error(f"WBI 密钥获取失败: {e}")
        send_serverchan(
            sendkey,
            "【B站监控】WBI 密钥获取失败",
            f"错误：{e}\n\n请检查 Cookie 是否有效，或 B站接口是否变更。",
        )
        return

    for video in videos:
        bvid = video['bvid'].strip()
        up_uid = str(video.get('up_uid', '')).strip()
        up_name = video.get('up_name', '').strip() or f'UID:{up_uid}'
        vtitle = video.get('title', bvid)
        since_rpid = get_last_rpid(bvid)

        logger.info(f"开始检查视频 [{vtitle}]({bvid})，监控UP主={up_name}({up_uid})，since_rpid={since_rpid}")

        try:
            new_comments = get_up_comments(
                bvid=bvid,
                up_uid=up_uid,
                session=session,
                img_key=img_key,
                sub_key=sub_key,
                max_pages=max_pages,
                since_rpid=since_rpid,
                up_name=up_name,
            )
            logger.info(f"[{bvid}] 获取到 {len(new_comments)} 条新评论/回复")
        except Exception as e:
            logger.error(f"[{bvid}] 抓取失败: {e}")
            send_serverchan(
                sendkey,
                f"【B站监控】抓取失败 {bvid}",
                f"视频：{vtitle}\n\n错误：{e}",
            )
            continue

        if new_comments:
            ok = push_new_comments(sendkey, new_comments, vtitle)
            if ok:
                max_rpid = max(c['rpid'] for c in new_comments)
                update_last_rpid(bvid, max_rpid)
                logger.info(f"[{bvid}] 推送成功，更新 last_rpid={max_rpid}")
            else:
                logger.warning(f"[{bvid}] 推送失败，本次结果未标记为已处理")
        else:
            logger.info(f"[{bvid}] 暂无新的 UP 主评论/回复")

        time.sleep(2)


def check_once_cursor():
    """执行一次完整的检查循环（游标高频模式）"""
    cfg = load_config()
    # 游标模式跳过间隔校验（单独处理）
    sendkey = cfg['sendkey']
    videos = [v for v in cfg['videos'] if v.get('bvid', '').strip()]

    session = create_session(cfg.get('cookie', ''))

    try:
        img_key, sub_key = fetch_wbi_keys(session)
        logger.debug(f"WBI 密钥获取成功")
    except Exception as e:
        logger.error(f"WBI 密钥获取失败: {e}")
        return

    for video in videos:
        bvid = video['bvid'].strip()
        up_uid = str(video.get('up_uid', '')).strip()
        up_name = video.get('up_name', '').strip() or f'UID:{up_uid}'
        vtitle = video.get('title', bvid)
        since_rpid = get_last_rpid(bvid)

        try:
            new_comments, max_rpid = get_up_comments_cursor(
                bvid=bvid,
                up_uid=up_uid,
                session=session,
                img_key=img_key,
                sub_key=sub_key,
                since_rpid=since_rpid,
                up_name=up_name,
            )
        except Exception as e:
            logger.error(f"[{bvid}] 游标抓取失败: {e}")
            continue

        if new_comments:
            ok = push_new_comments(sendkey, new_comments, vtitle)
            if ok:
                update_last_rpid(bvid, max_rpid)
                logger.info(f"[{bvid}] 游标模式推送 {len(new_comments)} 条，更新 last_rpid={max_rpid}")
            else:
                logger.warning(f"[{bvid}] 推送失败")
        else:
            logger.debug(f"[{bvid}] 暂无新评论")


def run_scheduler(interval_minutes: int = None):
    """
    启动定时任务
    自动根据配置选择游标模式或页码模式
    """
    cfg = load_config()
    use_cursor = cfg.get('use_cursor_mode', False)

    if use_cursor:
        # 游标高频模式：秒级循环
        interval_sec = cfg.get('interval_seconds', 0)
        if interval_sec <= 0:
            interval_sec = int(cfg.get('interval_minutes', 1) * 60)
        interval_sec = max(interval_sec, 30)  # 最低 30 秒

        logger.info(f"🚀 游标高频模式启动，每 {interval_sec} 秒检查一次")

        # 启动推送通知
        if cfg.get('notify_on_start', True):
            try:
                send_serverchan(
                    cfg['sendkey'],
                    "【B站监控】已启动（高频游标模式）",
                    f"监控间隔：{interval_sec} 秒\n监控视频数：{len([v for v in cfg['videos'] if v.get('bvid')])} 个",
                )
            except Exception:
                pass

        # 立即执行一次
        check_once_cursor()

        while True:
            time.sleep(interval_sec)
            check_once_cursor()

    else:
        # 原页码模式：分钟级，用 schedule 库
        import schedule

        errors = validate_config(cfg)
        if errors:
            logger.error("配置验证失败: " + " | ".join(errors))
            return

        minutes = interval_minutes or cfg.get('interval_minutes', 30)
        logger.info(f"📋 页码模式启动，每 {minutes} 分钟检查一次")

        check_once()

        schedule.every(minutes).minutes.do(check_once)

        while True:
            schedule.run_pending()
            time.sleep(30)
