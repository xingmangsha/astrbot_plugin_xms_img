import random
import time
import os
import json
import aiohttp
import requests
import urllib3
import sys
import io
from datetime import datetime
from astrbot.api.message_components import *
from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.core.star.filter.platform_adapter_type import PlatformAdapterType
from astrbot.api.star import Context, Star, register
from astrbot.api import logger # 使用 astrbot 提供的 logger 接口
from astrbot.core.utils.astrbot_path import get_astrbot_data_path
from astrbot.api.all import *
import astrbot.api.message_components as Comp
from botpy.errors import ServerError
from PIL import Image as PILImage
from .mcs.mc import MinecraftServerStatus
from .jm.jm import jmcomic_xms

#pixiv.re代理搜索pid图片
def find_pixiv_images(pid: str, base_url: str = "https://pixiv.re") -> list:
    """
    根据PID从Pixiv代理查找所有图片（含分页）。
    先探测分页，若无分页再尝试无页码格式。
    
    Args:
        pid: 作品ID
        base_url: 代理地址
    
    Returns:
        图片URL列表，失败返回空列表
    """
    extensions = ["png", "jpg"]
    found_urls = []
    seen = set()
    
    def add_url(url):
        if url not in seen:
            seen.add(url)
            found_urls.append(url)
    
    # ==================== 第一轮：先探测分页 ====================
    logger.info(f"[pixiv.re] 第一轮，分页探测: {pid}")
    max_pages = 200
    consecutive_fails = 0
    
    for page in range(1, max_pages + 1):
        page_found = False
        
        for ext in extensions:
            image_url = f"{base_url}/{pid}-{page}.{ext}"
            logger.info(f"[pixiv.re] 测试: {image_url}")
            
            try:
                response = requests.get(image_url, timeout=10)
                response.raise_for_status()
                #original_url = response.headers.get('x-origin-url')
                logger.info(f"[pixiv.re] 状态码: {response.status_code}")
                
                if response.status_code == 400:
                    continue
                    
                if response.status_code == 200:
                    content_type = response.headers.get('Content-Type', '')
                    if 'image' in content_type:
                        logger.info(f"[pixiv.re] 找到(分页{page}): {image_url}")
                        add_url(image_url)
                        page_found = True
                        break
                elif response.status_code in [301, 302]:
                    redirect_url = response.headers.get('Location', '')
                    if redirect_url:
                        logger.info(f"[pixiv.re] 重定向: {redirect_url}")
                        add_url(redirect_url)
                        page_found = True
                        break
                        
            except requests.exceptions.RequestException as e:
                logger.warning(f"[pixiv.re] 请求失败: {e}")
            
            time.sleep(0.5)
        
        if page_found:
            consecutive_fails = 0
        else:
            consecutive_fails += 1
            if consecutive_fails >= 1:
                logger.info(f"[pixiv.re] 连续{consecutive_fails}页未找到，停止分页探测")
                break
    
    # ==================== 第二轮：无分页才尝试无页码格式 ====================
    if len(found_urls) == 0:
        logger.info(f"[pixiv.re] 分页未找到，尝试无页码格式: {pid}")
        for ext in extensions:
            image_url = f"{base_url}/{pid}.{ext}"
            logger.info(f"[pixiv.re] 测试: {image_url}")
            
            try:
                response = requests.get(image_url, timeout=10)
                logger.info(f"[pixiv.re] 状态码: {response.status_code}")
                
                if response.status_code == 200:
                    content_type = response.headers.get('Content-Type', '')
                    if 'image' in content_type:
                        logger.info(f"[pixiv.re] 找到(无页码): {image_url}")
                        add_url(image_url)
                        break
                elif response.status_code in [301, 302]:
                    redirect_url = response.headers.get('Location', '')
                    if redirect_url:
                        logger.info(f"[pixiv.re] 重定向: {redirect_url}")
                        add_url(redirect_url)
                        break
                        
            except requests.exceptions.RequestException as e:
                logger.warning(f"[pixiv.re] 请求失败: {e}")
            
            time.sleep(0.5)
    
    if not found_urls:
        logger.error(f"[pixiv.re] 未找到任何图片, PID: {pid}")
    else:
        logger.info(f"[pixiv.re] 共找到 {len(found_urls)} 张图片")
    
    return found_urls

#yuki.sh的p站图片信息查询
def get_image_url_from_yuki( pid: str) -> tuple:
    """
    从API获取图片URL
    Args:
        api_url: API地址
    Returns:
        (状态码, 图片URL或错误信息)
        状态码: 1-成功, 0-失败
    """
    api = "https://pixiv.yuki.sh/api/illust?id="
    api_url = api + str(pid)
    try:
        response = requests.get(api_url, timeout=10)
        if response.status_code != 200:
            return (0, f"请求失败，状态码: {response.status_code}")
        data = response.json()
        # 检查返回结构
        if not data.get("success"):
            return (0, f"API返回失败: {data.get('message', '未知错误')}")
        if "data" not in data or not data["data"]:
            logger.info(data)
            return (0, "未获找到图片")
        image_list = data["data"]
        return (1, image_list)
    except requests.exceptions.Timeout:
        return (0, "请求超时")
    except requests.exceptions.RequestException as e:
        return (0, f"网络请求失败: {str(e)}")
    except Exception as e:
        return (0, f"解析失败: {str(e)}")

#图片转换（->jpg）
def convert_to_jpg( url: str) -> str:
    """
    如果不是JPG则下载转换，已经是JPG则直接返回URL
    Args:
        url: 图片URL
    Returns:
        JPG图片的本地路径或原URL
    """
    ## 提取扩展名
    #ext = url.split('.')[-1].split('?')[0].lower()
    #
    ## 已经是JPG，直接返回原URL
    #if ext in ['jpg', 'jpeg']:
    #    return url
    # 非JPG，下载并转换
    try:
        resp = requests.get(url, timeout=15)
        img = PILImage.open(io.BytesIO(resp.content))
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        jpg_path = os.path.join(os.path.dirname(__file__), "temp.jpg")
        img.save(jpg_path, 'JPEG', quality=85)
        return jpg_path
    except Exception as e:
        logger.error(f"转换JPG失败: {e}")
        return url  # 失败则返回原URL

#图片url提取
def extract_img_path(url: str) -> str:
    """
    从URL中提取 img/ 及之后的部分
    
    Args:
        url: 图片URL
    
    Returns:
        img/xxxxx.xxx 格式的路径
    """
    # 找到 "img" 的位置
    index = url.find("img")
    if index != -1:
        return url[index:]
    return ""

#MirlKoi的专用处理函数
def fetch_random_image(API: dict) -> tuple:
    """
    同步获取随机图片URL

    Returns:
        (状态码, 图片URL或错误信息)
        状态码: 0-成功, 1-失败
    """
    
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if not API:
        return (1, "请先在配置文件中设置API地址")

    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://weibo.com/',
            'Accept': 'application/json, text/json, */*'
        }
    
        response = requests.get(API, headers=headers, timeout=2, verify=False)
    
        if response.status_code != 200:
            return (1, f"API请求失败，状态码: {response.status_code}")
    
        try:
            data = response.json()
        except Exception as e:
            return (1, f"JSON解析失败: {str(e)}")
    
        if "pic" not in data:
            return (1, "API返回格式错误，缺少pic字段")
    
        pics = data["pic"]
        if not pics:
            return (1, "未获取到图片")
    
        random_pic = random.choice(pics)
        
        # 修复图片URL（内联处理）
        image_url = random_pic.replace("\\/", "/")
        image_url = image_url.replace("tva1.sina.cn", "tvax1.sina.cn")
        image_url = image_url.replace("tva2.sina.cn", "tvax2.sina.cn")
        image_url = image_url.replace("tva3.sina.cn", "tvax3.sina.cn")
        image_url = image_url.replace("tva4.sina.cn", "tvax4.sina.cn")
        if image_url.startswith('//'):
            image_url = 'https:' + image_url
    
        return (0, image_url)
    
    except Exception as e:
        return (1, f"请求失败: {str(e)}")


@register("astrbot_plugin_xms_img","xmsCCB", "查询器", "1.7.1")
class XMS_astrbot_plugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.config = context.get_config()
        self.mc = MinecraftServerStatus.mc_Information
        logger.info("xms的插件已加载")

    @filter.command("jm",alias={"JM"})
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def JM_command(self, event: AstrMessageEvent, num: dict | None = None, num1: dict | None = None, num2: dict | None = None):
        """禁漫天堂专用命令"""
        if num is None:
            yield event.plain_result(f"禁漫天堂专用命令\n使用方法/jm + （功能名称）\n例如：/jm 搜索 350234")
            result_message = [
                            Plain(f"以下为功能列表"),
                            Plain(f"\n搜索"),
                            Plain(f"\n下载"),
                            Plain(f"\n【后续功能还在开发中，敬请期待】"),

                        ]
            yield event.chain_result(result_message)
            return

        if num == "搜索":
            if num1 is None:
                yield event.plain_result(f"请输入需要搜索的内容\n例如：/jm 搜索 明日方舟")
            a = 1
            result = jmcomic_xms.search_jm_albums(num1,a)
            result_message = [
                        Plain(f"{result}"),
                    ]

        elif num == "下载":
            if type(num1) == int:
                yield event.plain_result(f"接收到车牌号{num1},开始下载\n预计需要3-5分钟，请勿再次发送消息")
                if num2 == "分页":
                    longimg = False
                    yield event.plain_result(f"当前发送方式：分页\n警告：当前模式下有几率出现图片无法发送的情况")
                    out, out_name = jmcomic_xms.download_jm_album(num1,longimg)
                else:
                    yield event.plain_result(f"当前发送方式：长图")
                    out, out_name = jmcomic_xms.download_jm_album(num1)
                out_num = 0
                out_num = len(out)
                yield event.plain_result(f"{out_name}\n漫画下载完成\n共{out_num}页，即将开始发送")
                for i, img_path in enumerate(out, 1):
                    yield event.plain_result(f"{i} | {out_num}")
                    yield event.image_result(f"{img_path}")
                    time.sleep(0.4)
                yield event.plain_result(f"发送完成")
                if num2 != "分页":
                    yield event.plain_result(f"如果需要分页发送，请在当前命令后添加参数<分页>二字\n例如/jm<空格>[下载]<空格>[车牌号]<空格>[分页]")
                return
            elif num1 is None:
                yield event.plain_result(f"请输入需要下载的车牌号\n例如：/jm 下载 350234")
                return
            else:
                yield event.plain_result(f"请输入正确的车牌号\n例如：/jm 下载 1156509")
                return

        else:
            yield event.plain_result(f"命令格式不正确\n/jm<空格>[命令]<空格>[参数]")
            return




        yield event.chain_result(result_message)
        return


    @filter.command("南风API",alias={"NF","nf","n","N"})
    async def NanFenAPI_command(self, event: AstrMessageEvent, num: int | None = None):
        """南风API专用命令"""
        if num is None:
            yield event.plain_result(f"南风API图库专用命令\n获取图片使用/NF + （数字）")
            result_message = [
                Plain(f"0--电脑端二次元动漫"),
                Plain(f"\n1--手机端二次元动漫"),
                Plain(f"\n2--头像"),
                Plain(f"\n3--电脑端二次元风景"),
                Plain(f"\n4--手机端二次元风景"),
            ]
            yield event.chain_result(result_message)
            return
        elif num > 4 or num < 0:
            yield event.plain_result(f"未知参数，请重新输入")
            result_message = [
                Plain(f"0--电脑端二次元动漫"),
                Plain(f"\n1--手机端二次元动漫"),
                Plain(f"\n2--头像"),
                Plain(f"\n3--电脑端二次元风景"),
                Plain(f"\n4--手机端二次元风景"),
            ]
            yield event.chain_result(result_message)
            return

        
        ip = [None] * 5
        name = [
            "电脑端二次元动漫",
            "手机端二次元动漫",
            "头像",
            "电脑端二次元风景",
            "手机端二次元风景",
        ]
        #电脑端二次元动漫
        ip[0] = "https://api.sretna.cn/api/anime/pc"
        #手机端二次元动漫
        ip[1] = "https://api.sretna.cn/api/anime/pe"
        #头像
        ip[2] = "https://api.sretna.cn/api/anime/tx"
        #电脑端二次元风景
        ip[3] = "https://api.sretna.cn/api/scenery/pc"
        #手机端二次元风景
        ip[4] = "https://api.sretna.cn/api/scenery/pe"

        tip = name[num]
        kand_out = convert_to_jpg(ip[num])
        yield event.image_result(kand_out)
        yield event.plain_result(f"{tip}  获取成功")
        return

    @filter.command("LoliAPI",alias={"loli","LOLI","萝莉","Loli"})
    async def LoliAPI_command(self, event: AstrMessageEvent, num: int | None = None):
        """LoliAPI专用命令"""
        if num is None:
            yield event.plain_result(f"LoliAPI图库专用命令\n获取图片使用/Loli + （数字）")
            result_message = [
                Plain(f"0--随机二次元图片"),
                Plain(f"\n1--随机二次元头像"),
            ]
            yield event.chain_result(result_message)
            return
        elif num > 2 or num < 0:
            yield event.plain_result(f"未知参数，请重新输入")
            result_message = [
                Plain(f"0--随机二次元图片"),
                Plain(f"\n1--随机二次元头像"),
            ]
            yield event.chain_result(result_message)
            return
        
        ip = [None] * 2
        name = [
            "随机二次元图片",
            "随机二次元头像"
        ]
        #随机二次元图片
        ip[0] = "https://www.loliapi.com/bg/"
        #随机二次元头像
        ip[1] = "https://www.loliapi.com/acg/pp/"

        tip = name[num]
        kand_out = convert_to_jpg(ip[num])
        yield event.image_result(kand_out)
        yield event.plain_result(f"{tip}  获取成功")
        return

    @filter.command("栗次元",alias={"LCY","lcy"})
    async def LCY_command(self, event: AstrMessageEvent, num: int | None = None):
        """栗次元图库专用命令"""
        if num is None:
            yield event.plain_result(f"栗次元图库专用命令\n获取图片使用/LCY + （数字）")
            result_message = [
                Plain(f"0--pc横图"),
                Plain(f"\n1--萌版横图"),
                Plain(f"\n2--风景横图"),
                Plain(f"\n3--白底横图"),
                Plain(f"\n4--原神横图"),
                Plain(f"\n5--移动竖图"),
                Plain(f"\n6--萌版竖图"),
                Plain(f"\n7--原神竖图"),
                Plain(f"\n8--ai竖图"),
                Plain(f"\n9--头像"),
                Plain(f"\n10--七濑胡桃"),
                Plain(f"\n11--小狐狸"),
                Plain(f"\n12--ai图"),
            ]
            yield event.chain_result(result_message)
            return
        elif num > 12 or num < 0:
            yield event.plain_result(f"未知参数，请重新输入")
            result_message = [
                Plain(f"0--pc横图"),
                Plain(f"\n1--萌版横图"),
                Plain(f"\n2--风景横图"),
                Plain(f"\n3--白底横图"),
                Plain(f"\n4--原神横图"),
                Plain(f"\n5--移动竖图"),
                Plain(f"\n6--萌版竖图"),
                Plain(f"\n7--原神竖图"),
                Plain(f"\n8--ai竖图"),
                Plain(f"\n9--头像"),
                Plain(f"\n10--七濑胡桃"),
                Plain(f"\n11--小狐狸"),
                Plain(f"\n12--ai图"),
            ]
            yield event.chain_result(result_message)
            return

        
        ip = [None] * 13
        name = [
            "pc横图",
            "萌版横图",
            "风景横图",
            "白底横图",
            "原神横图",
            "移动竖图",
            "萌版竖图",
            "原神竖图",
            "ai竖图",
            "头像",
            "七濑胡桃",
            "小狐狸",
            "ai图"
        ]
        #pc横图
        ip[0] = "https://t.alcy.cc/pc"
        #萌版横图
        ip[1] = "https://t.alcy.cc/moe"
        #风景横图
        ip[2] = "https://t.alcy.cc/fj"
        #白底横图
        ip[3] = "https://t.alcy.cc/bd"
        #原神横图
        ip[4] = "https://t.alcy.cc/ys"
        #移动竖图
        ip[5] = "https://t.alcy.cc/mp"
        #萌版竖图
        ip[6] = "https://t.alcy.cc/moemp"
        #原神竖图
        ip[7] = "https://t.alcy.cc/ysmp"
        #ai竖图
        ip[8] = "https://t.alcy.cc/aimp"
        #头像
        ip[9] = "https://t.alcy.cc/tx"
        #七濑胡桃
        ip[10] = "https://t.alcy.cc/lai"
        #小狐狸
        ip[11] = "https://t.alcy.cc/xhl"
        #ai图
        ip[12] = "https://t.alcy.cc/ai"


        tip = name[num]
        kand_out = convert_to_jpg(ip[num])
        yield event.image_result(kand_out)
        yield event.plain_result(f"{tip}  获取成功")
        return

    @filter.command("mcs")
    async def mcs_command(self, event: AstrMessageEvent, num: int | None = None):
        """mc服务器信息查询"""
        if num is None:
            yield event.plain_result(f"获取服务器信息使用/mcs + ip")
            return
        
        out = self.mc(num)
        result_message = [
            Plain(f"{out}")
        ]

        yield event.chain_result(result_message)
        return

    @filter.command("MirlKoi",alias={"M","Mir","m","mir","MK","mk"})
    async def MirlKoi_command(self, event: AstrMessageEvent, num: int | None = None):
        """MirlKoi图库专用命令"""
        if num is None:
            yield event.plain_result(f"MirlKoi图库专用命令\n获取图片使用/M + （数字）")
            result_message = [
                Plain(f"0--全部图"),
                Plain(f"\n1--无涩图"),
                Plain(f"\n2--精选"),
                Plain(f"\n3--横屏"),
                Plain(f"\n4--竖屏"),
                Plain(f"\n5--色图"),
                Plain(f"\n6--兽耳【已停更】"),
                Plain(f"\n7--银发【已停更】"),
                Plain(f"\n8--星空【已停更】"),
                Plain(f"\n9--Capoo【动图表情】"),
                Plain(f"\n10--月薪喵【动图表情】"),
                Plain(f"\n11--达妮娅【动图表情】"),
                Plain(f"\n12--呆猫八条【动图表情】")
            ]
            yield event.chain_result(result_message)
            return
        elif num > 12 or num < 0:
            yield event.plain_result(f"未知参数，请重新输入")
            result_message = [
                Plain(f"0--全部图"),
                Plain(f"\n1--无涩图"),
                Plain(f"\n2--精选"),
                Plain(f"\n3--横屏"),
                Plain(f"\n4--竖屏"),
                Plain(f"\n5--色图"),
                Plain(f"\n6--兽耳【已停更】"),
                Plain(f"\n7--银发【已停更】"),
                Plain(f"\n8--星空【已停更】"),
                Plain(f"\n9--Capoo【动图表情】"),
                Plain(f"\n10--月薪喵【动图表情】"),
                Plain(f"\n11--达妮娅【动图表情】"),
                Plain(f"\n12--呆猫八条【动图表情】")
            ]
            yield event.chain_result(result_message)
            return

        ip = [None] * 13
        name = [
            "全部图",
            "无涩图",
            "精选",
            "横屏",
            "竖屏",
            "色图",
            "兽耳【已停更】",
            "银发【已停更】",
            "星空【已停更】",
            "Capoo【动图表情】",
            "月薪喵【动图表情】",
            "达妮娅【动图表情】",
            "呆猫八条【动图表情】",
        ]
        #全部图
        ip[0] = "https://cnmiw.com/api.php?sort=random&type=json&num=2"
        #无涩图
        ip[1] = "https://cnmiw.com/api.php?sort=iw233&type=json&num=2"
        #精选
        ip[2] = "https://cnmiw.com/api.php?sort=top&type=json&num=2"
        #横屏
        ip[3] = "https://cnmiw.com/api.php?sort=pc&type=json&num=2"
        #竖屏
        ip[4] = "https://cnmiw.com/api.php?sort=mp&type=json&num=2"
        #色图
        ip[5] = "https://cnmiw.com/api.php?sort=setu&type=json&num=2"
        #兽耳
        ip[6] = "https://cnmiw.com/api.php?sort=cat&type=json&num=2"
        #银发
        ip[7] = "https://cnmiw.com/api.php?sort=yin&type=json&num=2"
        #星空
        ip[8] = "https://cnmiw.com/api.php?sort=xing&type=json&num=2"
        #Capoo
        ip[9] = "https://cnmiw.com/api.php?sort=Capoo&type=json&num=2"
        #月薪喵
        ip[10] = "https://cnmiw.com/api.php?sort=yuexinmiao&type=json&num=2"
        #达妮娅
        ip[11] = "https://cnmiw.com/api.php?sort=Denia&type=json&num=2"
        #呆猫八条
        ip[12] = "https://cnmiw.com/api.php?sort=daimao&type=json&num=2"

        status, kand_out = fetch_random_image(ip[num])

        if status:
            result_message = [
                Plain(f"出现错误！{kand_out}")
            ]
        else:
            tip = name[num]
            kand_out_1 = convert_to_jpg(kand_out)
            result_message = [
                Plain(f"{tip}  获取成功")
            ]
            yield event.image_result(kand_out_1)
        
        yield event.chain_result(result_message)
        return

    @filter.command("p", alias={"P"})
    @filter.event_message_type(filter.EventMessageType.PRIVATE_MESSAGE)
    async def p_command(self, event: AstrMessageEvent, num: int | None = None, num1: int | None = None, num2: int | None = None):
        """pid查询图片（私聊可用）"""
        if num is None:
                    result_message = [
                        Plain(f"命令使用方法教程"),
                        Plain(f"\n/p [pid] [特殊功能]"),
                    ]
                    yield event.chain_result(result_message)
                    return
        yield event.plain_result(f"开始查询")

        
        status,Information = get_image_url_from_yuki(num)
        if status == 0 :
            yield event.plain_result(f"图片信息查询失败❌\n将直接进行图片查询")
        else:
            urls = Information["urls"]
            urls_mini = urls["mini"]
            if urls_mini is None:
                yield event.plain_result(f"当前图片可能存在不雅内容")
            result_message =[
                 Plain(f"图源信息\npid：{Information["id"]}"),
                 Plain(f"\n作者：{Information["user"]["name"]}（ID:{Information["user"]["id"]}|账号:{Information["user"]["account"]}）"),
                 Plain(f"\n标题：{Information["title"]}"),
                 Plain(f"\n简介：{Information["description"] or "null"}"),
                 Plain(f"\ntag：{Information["tags"]}"),
                ]
            yield event.chain_result(result_message)

        
        result = find_pixiv_images(num)

        if len(result) == 1:
            result = convert_to_jpg(result[0])
            result_message = [
                Image.fromFileSystem(result),
            ]
            yield event.chain_result(result_message)
            return
        elif len(result) > 1 :
            yield event.plain_result(f"图片较多，请耐心等待，预计需要3-5分钟。")
            for i, url in enumerate(result, 1):
                result_path = convert_to_jpg(url)
                yield event.plain_result(f"P{i}/{len(result)}")
                yield event.image_result(result_path)
                await asyncio.sleep(0.3)
        else:
            yield event.plain_result(f"未找到图片")
            
            return


    async def terminate(self):
            """插件卸载时的清理工作"""
            logger.info("星茫沙的ccb_img插件已卸载")



        










