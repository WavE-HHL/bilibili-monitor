"""
B站评论爬取核心模块
支持：获取视频 aid、抓取评论（含二级回复）、过滤 UP 主评论
"""
import time
import random
import logging
import requests

from bilibili_wbi import encode_wbi, fetch_wbi_keys

logger = logging.getLogger(__name__)

# 默认请求头，模拟正常浏览器访问
DEFAULT_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                  'AppleWebKit/537.36 (KHTML, like Gecko) '
                  'Chrome/123.0.0.0 Safari/537.36',
    'Referer': 'https://www.bilibili.com/',
    'Origin': 'https://www.bilibili.com',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}


def create_session(cookie_str: str) -> requests.Session:
    """
    创建带 Cookie 的 Session
    :param cookie_str: Cookie 字符串，如 "SESSDATA=xxx; bili_jct=yyy"
    """
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)
    if cookie_str and cookie_str.strip():
        for item in cookie_str.split(';'):
            item = item.strip()
            if '=' in item:
                k, v = item.split('=', 1)
                session.cookies.set(k.strip(), v.strip(), domain='.bilibili.com')
    return session




def bv_to_aid(bvid: str, session: requests.Session) -> int:
    """
    将 BV 号转换为 aid（视频 oid）
    """
    url = 'https://api.bilibili.com/x/web-interface/view'
    resp = session.get(url, params={'bvid': bvid}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if data.get('code') != 0:
        raise ValueError(f"BV 号转换失败({bvid}): {data.get('message', '未知错误')}")
    return data['data']['aid']


def _random_sleep(min_s=1.0, max_s=3.0):
    """随机延迟，降低被封风险"""
    time.sleep(random.uniform(min_s, max_s))


def fetch_comments_page(
    oid: int,
    page: int,
    session: requests.Session,
    img_key: str,
    sub_key: str,
    page_size: int = 20,
) -> dict:
    """
    获取评论列表（一页，按页码）
    使用 WBI 签名接口 /x/v2/reply/wbi/main
    """
    params = {
        'oid': oid,
        'type': 1,          # 1 = 视频
        'mode': 3,          # 3 = 按时间排序（最新优先）
        'pn': page,
        'ps': page_size,
    }
    signed = encode_wbi(params, img_key, sub_key)

    url = 'https://api.bilibili.com/x/v2/reply/wbi/main'
    resp = session.get(url, params=signed, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get('code') != 0:
        raise ValueError(f"评论接口错误: {data.get('message', '未知')} (code={data.get('code')})")
    return data.get('data', {})


def fetch_comments_by_cursor(
    oid: int,
    session: requests.Session,
    img_key: str,
    sub_key: str,
    cursor_id: int = 0,
    page_size: int = 20,
) -> dict:
    """
    游标方式获取评论（高效增量拉取）
    使用 WBI 签名接口 /x/v2/reply/wbi/main，mode=2（按时间最新）
    cursor_id=0 表示拉取最新一页
    返回 data 字典，含 replies / top_replies / cursor 字段
    """
    params = {
        'oid': oid,
        'type': 1,
        'mode': 2,          # 2 = 时间正序，配合 cursor 做增量
        'ps': page_size,
    }
    if cursor_id > 0:
        params['pagination_str'] = '{"offset":"%d"}' % cursor_id

    signed = encode_wbi(params, img_key, sub_key)
    url = 'https://api.bilibili.com/x/v2/reply/wbi/main'
    resp = session.get(url, params=signed, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    if data.get('code') != 0:
        raise ValueError(f"评论接口错误(cursor): {data.get('message', '未知')} (code={data.get('code')})")
    return data.get('data', {})


def fetch_replies(
    oid: int,
    root_rpid: int,
    session: requests.Session,
    img_key: str,
    sub_key: str,
    max_pages: int = 5,
) -> list[dict]:
    """
    获取某条评论的所有二级回复
    """
    replies = []
    for pn in range(1, max_pages + 1):
        params = {
            'oid': oid,
            'type': 1,
            'root': root_rpid,
            'ps': 20,
            'pn': pn,
        }
        signed = encode_wbi(params, img_key, sub_key)
        url = 'https://api.bilibili.com/x/v2/reply/reply/cursor'
        try:
            resp = session.get(url, params=signed, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            if data.get('code') != 0:
                break
            page_replies = data.get('data', {}).get('replies') or []
            if not page_replies:
                break
            replies.extend(page_replies)
            _random_sleep(0.8, 1.8)
        except Exception as e:
            logger.warning(f"获取二级回复失败(root={root_rpid}, pn={pn}): {e}")
            break
    return replies


def get_up_comments(
    bvid: str,
    up_uid: int,
    session: requests.Session,
    img_key: str,
    sub_key: str,
    max_pages: int = 10,
    since_rpid: int = 0,
    up_name: str = '',
) -> list[dict]:
    """
    获取视频下 UP 主发布的评论及其回复他人的评论
    :param bvid:       视频 BV 号
    :param up_uid:     UP 主 UID
    :param session:    带 Cookie 的 Session
    :param img_key:    WBI img_key
    :param sub_key:    WBI sub_key
    :param max_pages:  最多扫描页数
    :param since_rpid: 只收集 rpid > 此值的评论（增量）
    :param up_name:    UP 主名称（不再自动获取）
    :return: UP 主评论列表，每项含 rpid/type/content/reply_to/at_time/up_name
    """
    oid = bv_to_aid(bvid, session)
    # 不再自动获取UP主名称，使用传入的参数
    if not up_name:
        up_name = f'UID:{up_uid}'
    logger.info(f"[{bvid}] aid={oid}，UP主={up_name}({up_uid})，开始扫描最多 {max_pages} 页评论")

    up_comments = []
    seen_rpid_set = set()  # 用于去重，避免重复添加
    _random_sleep(0.5, 1.5)

    for pn in range(1, max_pages + 1):
        try:
            page_data = fetch_comments_page(oid, pn, session, img_key, sub_key)
        except Exception as e:
            logger.warning(f"[{bvid}] 第{pn}页获取失败: {e}")
            _random_sleep(3, 6)
            break

        replies_list = page_data.get('replies') or []
        # 置顶评论在 top_replies 字段，需要单独处理（只在第1页追加一次）
        if pn == 1:
            top_replies = page_data.get('top_replies') or []
            if top_replies:
                logger.info(f"[{bvid}] 发现 {len(top_replies)} 条置顶评论，一并扫描")
                # 将置顶评论合并到列表头部（优先处理）
                replies_list = top_replies + replies_list
        if not replies_list:
            logger.info(f"[{bvid}] 第{pn}页无评论，停止")
            break

        found_new = False
        for comment in replies_list:
            rpid = comment.get('rpid', 0)
            if rpid <= since_rpid:
                continue  # 已处理过
            found_new = True

            mid = comment.get('member', {}).get('mid') or comment.get('mid')
            content = comment.get('content', {}).get('message', '')
            at_time = comment.get('ctime', 0)

            if str(mid) == str(up_uid):
                # UP 主发的一级评论
                logger.debug(f"[{bvid}] 发现UP主一级评论 rpid={rpid}")
                # 去重检查
                if rpid not in seen_rpid_set:
                    seen_rpid_set.add(rpid)
                    up_comments.append({
                        'rpid': rpid,
                        'type': 'comment',       # 一级评论
                        'content': content,
                        'reply_to': None,
                        'reply_to_content': None,
                        'at_time': at_time,
                        'bvid': bvid,
                        'up_name': up_name,      # 添加UP主名称
                    })
                else:
                    logger.warning(f"[{bvid}] 重复的一级评论 rpid={rpid}，跳过")

            # 检查该评论的二级回复中 UP 主的发言
            sub_replies = comment.get('replies') or []
            # 若二级回复不完整，进一步获取（直接替换，不合并）
            rcount = comment.get('rcount', 0)
            if rcount > len(sub_replies):
                more = fetch_replies(oid, rpid, session, img_key, sub_key)
                if more:
                    sub_replies = more  # 直接使用完整列表，不合并

            # 保存当前一级评论的信息，避免在二级回复循环中被覆盖
            root_content = content
            root_uname = comment.get('member', {}).get('uname', '未知用户')

            for reply in sub_replies:
                r_rpid = reply.get('rpid', 0)
                if r_rpid <= since_rpid:
                    continue
                r_mid = reply.get('member', {}).get('mid') or reply.get('mid')
                r_content = reply.get('content', {}).get('message', '')
                r_at_time = reply.get('ctime', 0)

                if str(r_mid) == str(up_uid):
                    # 找被回复方信息（使用一级评论的信息）
                    parent_content = root_content  # 一级评论内容
                    parent_uname = root_uname  # 一级评论作者
                    logger.debug(f"[{bvid}] 发现UP主二级回复 rpid={r_rpid}, 回复给: {parent_uname}")
                    # 去重检查
                    if r_rpid not in seen_rpid_set:
                        seen_rpid_set.add(r_rpid)
                        up_comments.append({
                            'rpid': r_rpid,
                            'type': 'reply',     # 二级回复
                            'content': r_content,
                            'reply_to': parent_uname,
                            'reply_to_content': parent_content,
                            'at_time': r_at_time,
                            'bvid': bvid,
                            'up_name': up_name,  # 添加UP主名称
                        })
                    else:
                        logger.warning(f"[{bvid}] 重复的二级回复 rpid={r_rpid}，跳过")

        if not found_new:
            logger.info(f"[{bvid}] 第{pn}页全是旧评论，停止扫描")
            break

        _random_sleep(1.5, 3.0)

    logger.info(f"[{bvid}] 共发现 UP 主新评论/回复 {len(up_comments)} 条")

    # 输出所有 rpid 用于调试
    if up_comments:
        logger.debug(f"[{bvid}] 所有评论的 rpid 列表: {[c['rpid'] for c in up_comments]}")

    # 最终去重检查（以防万一）
    rpid_count = {}
    for c in up_comments:
        r = c['rpid']
        rpid_count[r] = rpid_count.get(r, 0) + 1
    duplicates = {r: count for r, count in rpid_count.items() if count > 1}
    if duplicates:
        logger.warning(f"[{bvid}] 发现重复的 rpid: {duplicates}")
        # 去重
        seen = set()
        unique_comments = []
        for c in up_comments:
            if c['rpid'] not in seen:
                seen.add(c['rpid'])
                unique_comments.append(c)
        logger.warning(f"[{bvid}] 去重后剩余 {len(unique_comments)} 条评论")
        up_comments = unique_comments

    # 按时间从近到远排序（at_time 降序）
    if up_comments:
        up_comments.sort(key=lambda x: x['at_time'], reverse=True)
        logger.debug(f"[{bvid}] 已按时间从近到远排序")

    return up_comments


def get_up_comments_cursor(
    bvid: str,
    up_uid: int,
    session: requests.Session,
    img_key: str,
    sub_key: str,
    since_rpid: int = 0,
    up_name: str = '',
) -> tuple[list[dict], int]:
    """
    游标方式获取 UP 主新评论（高效增量，适合高频轮询）
    每次只发 1~2 个请求，可以安全地每 30 秒~1 分钟调用一次

    :return: (新评论列表, 最新评论的 rpid)
             新评论列表按时间从近到远排序
    """
    oid = bv_to_aid(bvid, session)
    if not up_name:
        up_name = f'UID:{up_uid}'
    logger.info(f"[{bvid}] 游标模式：aid={oid}，UP主={up_name}({up_uid})，since_rpid={since_rpid}")

    up_comments = []
    seen_rpid_set = set()
    max_rpid_found = since_rpid

    try:
        # 拉取最新一页（cursor=0 即第一页最新评论）
        page_data = fetch_comments_by_cursor(oid, session, img_key, sub_key, cursor_id=0)
    except Exception as e:
        logger.warning(f"[{bvid}] 游标接口失败，回退到页码模式: {e}")
        # 回退到原来的页码方式
        comments = get_up_comments(
            bvid=bvid, up_uid=up_uid, session=session,
            img_key=img_key, sub_key=sub_key,
            max_pages=3, since_rpid=since_rpid, up_name=up_name,
        )
        new_rpid = max((c['rpid'] for c in comments), default=since_rpid)
        return comments, new_rpid

    # 合并 top_replies + replies
    top_replies = page_data.get('top_replies') or []
    replies_list = (top_replies) + (page_data.get('replies') or [])

    if not replies_list:
        logger.info(f"[{bvid}] 游标模式：暂无评论")
        return [], since_rpid

    for comment in replies_list:
        rpid = comment.get('rpid', 0)
        if rpid <= since_rpid:
            continue  # 已处理过

        mid = comment.get('member', {}).get('mid') or comment.get('mid')
        content = comment.get('content', {}).get('message', '')
        at_time = comment.get('ctime', 0)
        max_rpid_found = max(max_rpid_found, rpid)

        if str(mid) == str(up_uid):
            if rpid not in seen_rpid_set:
                seen_rpid_set.add(rpid)
                up_comments.append({
                    'rpid': rpid,
                    'type': 'comment',
                    'content': content,
                    'reply_to': None,
                    'reply_to_content': None,
                    'at_time': at_time,
                    'bvid': bvid,
                    'up_name': up_name,
                })

        # 检查二级回复
        sub_replies = comment.get('replies') or []
        rcount = comment.get('rcount', 0)
        if rcount > len(sub_replies):
            more = fetch_replies(oid, rpid, session, img_key, sub_key)
            if more:
                sub_replies = more

        root_content = content
        root_uname = comment.get('member', {}).get('uname', '未知用户')

        for reply in sub_replies:
            r_rpid = reply.get('rpid', 0)
            if r_rpid <= since_rpid:
                continue
            r_mid = reply.get('member', {}).get('mid') or reply.get('mid')
            r_content = reply.get('content', {}).get('message', '')
            r_at_time = reply.get('ctime', 0)
            max_rpid_found = max(max_rpid_found, r_rpid)

            if str(r_mid) == str(up_uid):
                if r_rpid not in seen_rpid_set:
                    seen_rpid_set.add(r_rpid)
                    up_comments.append({
                        'rpid': r_rpid,
                        'type': 'reply',
                        'content': r_content,
                        'reply_to': root_uname,
                        'reply_to_content': root_content,
                        'at_time': r_at_time,
                        'bvid': bvid,
                        'up_name': up_name,
                    })

    logger.info(f"[{bvid}] 游标模式：发现 UP 主新评论/回复 {len(up_comments)} 条")

    if up_comments:
        up_comments.sort(key=lambda x: x['at_time'], reverse=True)

    return up_comments, max_rpid_found
