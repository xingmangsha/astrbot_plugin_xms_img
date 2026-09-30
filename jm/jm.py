import jmcomic
from jmcomic import *
from jmcomic import download_album, download_photo
from jmcomic import Feature
import os
from PIL import Image, ImageFile
import pyvips

def find_jpg_images_scandir(directory):
    """
    使用os.scandir查找目录下所有.jpg图片（性能更好）
    
    Args:
        directory (str): 要搜索的目录路径
        
    Returns:
        list: 包含所有.jpg图片完整路径的列表
    """
    if not os.path.isdir(directory):
        return []
    
    jpg_files = []
    
    # os.scandir() 比 os.listdir() 更高效
    with os.scandir(directory) as entries:
        for entry in entries:
            # 检查是否是文件且扩展名为.jpg
            if entry.is_file() and entry.name.lower().endswith('.jpg'):
                jpg_files.append(entry.path)  # entry.path 已经是完整路径
    
    jpg_files.sort()
    return jpg_files



def png_to_jpg(file_path: str, quality: int = 85, slice_height: int = 26000):
    """
    将 PNG（含超大长图）转换为 JPG。
    若高度超过 JPEG 格式限制（65500 像素），自动切成多段分别转换。

    :param file_path: 输入的 PNG 文件路径
    :param quality: JPG 画质 (1-100)，默认 85
    :param slice_height: 每段最大高度，默认 60000（低于 JPEG 的 65500 硬限制）
    :return: 转换后的 JPG 文件路径列表。单段时返回 [路径]，多段时返回多个路径
    """
    # 1. 检查文件是否存在
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    # 2. 检查后缀
    if not file_path.lower().endswith(".png"):
        raise ValueError(f"输入文件不是 PNG 格式: {file_path}")

    base = os.path.splitext(file_path)[0]

    # 3. 用 libvips 打开，流式访问降低内存占用
    image = pyvips.Image.new_from_file(file_path, access="sequential")

    # 4. 处理透明通道和色彩空间，确保输出是标准 RGB
    if image.hasalpha():
        image = image.flatten(background=[255, 255, 255])
    if image.bands != 3:
        image = image.colourspace("srgb")

    width, height = image.width, image.height

    # 5. 判断是否需要切片
    if height <= slice_height:
        # 高度没超限，直接单张输出
        out_path = base + ".jpg"
        image.write_to_file(out_path, Q=quality)
        return [out_path]

    # 6. 超过限制，切片处理
    out_paths = []
    y = 0
    idx = 0
    while y < height:
        h = min(slice_height, height - y)
        crop = image.crop(0, y, width, h)

        out_path = f"{base}_part{idx}.jpg"
        crop.write_to_file(out_path, Q=quality)
        out_paths.append(out_path)

        y += h
        idx += 1

    return out_paths



class jmcomic_xms:
    """
    jm有关的所有用方法
    """
    def download_jm_album(num: int, longimg: bool = True) -> list:
        """
        下载jm

        会返回一个列表，包含所有图片在本地的地址
        """
        script_dir = os.path.dirname(os.path.abspath(__file__)) #获取当前目录
        long_img_dir = script_dir + "\\longimg"  #长图保存位子
        os.environ['download'] = script_dir
        os.environ['download_long'] = long_img_dir
        script_dir_option = script_dir + "\\option.yml"

        option = jmcomic.create_option_by_file(f"{script_dir_option}")
        client = option.new_jm_client()
        page = client.search_site(search_query = num)
        album: JmAlbumDetail = page.single_album

        #download_album(num, option)
        result = option.download_album(num)

        #默认使用长图发送
        if longimg:
            long_img_num = long_img_dir + "\\" + str(num) + ".png"
            download_ip = png_to_jpg(long_img_num)
            return download_ip, f"{album.title}"

        #分页发送
        download_ip = script_dir + "\\" + str(num)
        download_list = find_jpg_images_scandir(download_ip)
        #print(f"\n{result}")
        out = [None] * len(download_list)
        
        for i, img_path in enumerate(download_list, 0):
            #print(f"{i}. {img_path}")
            out[i] = f"{img_path}"
        
        return out, f"{album.title}"



    def search_jm_albums(search_query: str | None = None, page_num: int = 1) -> str:
        """
        搜索JM漫画并返回格式化的结果文字

        Args:
            search_query: 搜索关键词，例如 '+MANA +无修正'
            page_num: 页码，默认为1

        Returns:
            格式化的搜索结果文字
        """

        if search_query is None:
            return
        client = JmOption.default().new_jm_client()
        page: JmSearchPage = client.search_site(search_query=search_query, page=page_num)

        # 构建结果文字
        lines = []
        lines.append(f'搜索关键词: {search_query}')
        lines.append(f'结果总数: {page.total}, 分页大小: {page.page_size}，总页数: {page.page_count}')
        lines.append('-' * 50)

        # 遍历结果
        #for album_id, title in page:
        #    lines.append(f'[{album_id}]: {title}')

        for album_id, title in page:
            # 关键修改：去掉方括号，改用更安全的格式
            # 原来: [104477]: [ro][おおかみと七匹の仔山羊Detail]
            # 改为: 104477 | ro | おおかみと七匹の仔山羊Detail
            # 或者保留ID用括号，标题不用括号
            #lines.append(f'{album_id} | {title}')
            # 如果还想保留ID的辨识度，可以用圆括号
            lines.append(f'({album_id}) {title}')

        return '\n'.join(lines)

    def dir():
        """
        获取当前运行目录
        """
        current_dir = os.getcwd()
        print(f"当前工作目录: {current_dir}")

        script_dir = os.path.dirname(os.path.abspath(__file__))
        print(f"脚本所在目录: {script_dir}")


        return f"{current_dir}"


