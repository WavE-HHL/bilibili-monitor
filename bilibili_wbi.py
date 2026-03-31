"""
B站 WBI 签名模块
参考：https://github.com/SocialSisterYi/bilibili-API-collect/blob/master/docs/misc/sign/wbi.md
"""
import hashlib
import time
import urllib.parse
import requests

# WBI 混淆表
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52
]


def get_mixin_key(orig: str) -> str:
    """从原始 key 生成混淆 key"""
    return ''.join([orig[i] for i in MIXIN_KEY_ENC_TAB])[:32]


def encode_wbi(params: dict, img_key: str, sub_key: str) -> dict:
    """
    对请求参数进行 WBI 签名
    :param params: 原始请求参数
    :param img_key: 从 nav 接口获取的 img_key
    :param sub_key: 从 nav 接口获取的 sub_key
    :return: 带签名的参数字典
    """
    mixin_key = get_mixin_key(img_key + sub_key)
    curr_time = int(time.time())
    params['wts'] = curr_time

    # 按 key 排序
    params = dict(sorted(params.items()))

    # 过滤特殊字符
    filter_table = "!'()*"
    params_str = urllib.parse.urlencode(
        {k: ''.join(c for c in str(v) if c not in filter_table)
         for k, v in params.items()}
    )

    w_rid = hashlib.md5((params_str + mixin_key).encode()).hexdigest()
    params['w_rid'] = w_rid
    return params


def fetch_wbi_keys(session: requests.Session) -> tuple[str, str]:
    """
    从 B站 nav 接口获取 WBI 密钥对。
    注意：未登录时 code=-101，但 wbi_img 字段仍然存在且有效，可正常使用。
    :param session: requests.Session（有无 Cookie 均可）
    :return: (img_key, sub_key)
    """
    resp = session.get(
        'https://api.bilibili.com/x/web-interface/nav',
        timeout=10
    )
    resp.raise_for_status()
    data = resp.json()

    # wbi_img 在登录/未登录状态下均存在于 data 字段中
    nav_data = data.get('data') or {}
    wbi_img = nav_data.get('wbi_img')

    if not wbi_img:
        # 兜底：直接从 B站主页解析（极少情况下 data 为空）
        raise ValueError(
            f"无法获取 WBI 密钥（接口返回 code={data.get('code')}，"
            f"message={data.get('message')}）。请尝试填写 B站 Cookie 后重试。"
        )

    img_url = wbi_img.get('img_url', '')
    sub_url = wbi_img.get('sub_url', '')

    if not img_url or not sub_url:
        raise ValueError("WBI 密钥 URL 为空，请检查网络或填写 Cookie")

    # 提取文件名（去扩展名）作为 key
    img_key = img_url.rsplit('/', 1)[-1].split('.')[0]
    sub_key = sub_url.rsplit('/', 1)[-1].split('.')[0]

    return img_key, sub_key
