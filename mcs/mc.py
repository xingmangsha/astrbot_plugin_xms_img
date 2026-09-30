import requests
import json
from datetime import datetime
from urllib.parse import urlparse

class MinecraftServerStatus:
    """
    一个用于查询Minecraft服务器状态的类，基于 mcsrvstat.us API。
    支持自动判断 Java 版和基岩版。
    """
    BASE_URL = "https://api.mcsrvstat.us"
    API_VERSION = "3"

    def __init__(self, user_agent: str = "MyMinecraftBot/1.0"):
        """
        初始化查询器。
        :param user_agent: 请求头中的User-Agent，API要求必须设置且不能为空。
        """
        if not user_agent:
            raise ValueError("User-Agent cannot be empty. API requires a descriptive User-Agent.")
        self.headers = {
            "User-Agent": user_agent,
            "Accept": "application/json"
        }

    def _fetch_data(self, url: str) -> dict:
        """向API发送请求并返回JSON数据。"""
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            return {"error": f"网络请求失败: {e}"}
        except json.JSONDecodeError:
            return {"error": "解析JSON响应失败"}

    def _test_server_type(self, address: str) -> tuple:
        """
        测试服务器类型，返回 (服务器类型, 数据字典)。
        优先尝试 Java 版，如果失败则尝试基岩版。
        """
        # 先尝试 Java 版
        java_url = f"{self.BASE_URL}/{self.API_VERSION}/{address}"
        java_data = self._fetch_data(java_url)
        
        if java_data.get("online") and not java_data.get("error"):
            return "java", java_data
        
        # 如果 Java 版失败，尝试基岩版
        bedrock_url = f"{self.BASE_URL}/bedrock/{self.API_VERSION}/{address}"
        bedrock_data = self._fetch_data(bedrock_url)
        
        if bedrock_data.get("online") and not bedrock_data.get("error"):
            return "bedrock", bedrock_data
        
        # 两个都失败，返回错误信息
        if java_data.get("error"):
            return "unknown", java_data
        elif bedrock_data.get("error"):
            return "unknown", bedrock_data
        else:
            return "unknown", {"error": "服务器离线或无法访问"}

    def _format_text(self, text_data) -> str:
        """辅助函数，用于格式化可能为列表或字符串的文本字段。"""
        if isinstance(text_data, list):
            return " ".join(text_data)
        elif isinstance(text_data, str):
            return text_data
        return "N/A"

    def _format_player_list(self, players_data: dict) -> str:
        """格式化玩家列表。"""
        if not players_data:
            return "无玩家信息"
        
        online = players_data.get("online", 0)
        max_players = players_data.get("max", 0)
        player_list = players_data.get("list", [])
        
        if not player_list:
            return f"{online} / {max_players} "
        
        player_names = [p.get("name", "Unknown") for p in player_list]
        return f"{online} / {max_players}\n    玩家列表: {', '.join(player_names)}"

    def _format_plugins_mods(self, items: list, item_type: str = "插件") -> str:
        """格式化插件或Mods列表。"""
        if not items:
            return f"无{item_type}信息"
        
        formatted = []
        for item in items:
            name = item.get("name", "Unknown")
            version = item.get("version", "?")
            formatted.append(f"{name} v{version}")
        
        return f"{item_type}: {', '.join(formatted)}"

    def get_server_info(self, address: str) -> str:
        """
        查询服务器信息并返回可直接打印的完整文本。
        :param address: 服务器地址，例如 'play.hypixel.net' 或 '127.0.0.1:25565'
        :return: 格式化的服务器信息文本
        """
        # 自动检测服务器类型
        server_type, data = self._test_server_type(address)
        
        # 处理错误或离线情况
        if server_type == "unknown" or not data.get("online"):
            error_msg = data.get("error", "未知错误")
            return f" [{address}] 状态: 🔴\n错误信息: {error_msg}"
        
        # 解析在线服务器数据
        server_type_display = "Java版" if server_type == "java" else "基岩版"
        result_lines = [
            f" [{address}] 状态: 🟢",
            f"服务器类型: {server_type_display}",
            f"主机名: {data.get('hostname', 'N/A')}",
            f"游戏版本: {data.get('version', 'N/A')}",
        ]
        #f"IP 地址: {data.get('ip', 'N/A')}:{data.get('port', 'N/A')}",
        # 协议信息
        protocol = data.get("protocol", {})
        if protocol:
            protocol_name = protocol.get("name", "N/A")
            protocol_version = protocol.get("version", "N/A")
            result_lines.append(f"协议版本: {protocol_name} (v{protocol_version})")
        
        # MOTD
        motd = data.get("motd", {})
        if motd:
            motd_clean = self._format_text(motd.get("clean", "N/A"))
            result_lines.append(f"MOTD: {motd_clean}")
        
        # 软件信息
        if data.get("software"):
            result_lines.append(f"软件: {data.get('software')}")
        
        # 玩家信息
        
        players = data.get("players", {})
        if players:
            result_lines.append(f"在线玩家: {self._format_player_list(players)}")
        
        
        # 地图信息（Java版）
        map_data = data.get("map", {})
        if map_data:
            map_clean = map_data.get("clean", "N/A")
            if map_clean != "N/A":
                result_lines.append(f"地图: {map_clean}")
        
        # 游戏模式（基岩版）
        if data.get("gamemode"):
            result_lines.append(f"游戏模式: {data.get('gamemode')}")
        
        # 插件信息
        plugins = data.get("plugins", [])
        if plugins:
            result_lines.append(self._format_plugins_mods(plugins, "插件"))
        
        # Mods信息
        mods = data.get("mods", [])
        if mods:
            result_lines.append(self._format_plugins_mods(mods, "Mods"))
        
        # 缓存信息
        """
        debug = data.get("debug", {})
        if debug.get("cachehit"):
            cache_time = debug.get("cachetime")
            if cache_time:
                cache_time_readable = datetime.fromtimestamp(cache_time).strftime('%Y-%m-%d %H:%M:%S')
                result_lines.append(f"数据缓存时间: {cache_time_readable}")
            else:
                result_lines.append("数据缓存时间: N/A")
        else:
            result_lines.append("数据缓存: 未缓存")
        """
        
        # Debug信息（精简版）
        """
        if debug:
            debug_summary = {
                "ping": debug.get("ping", False),
                "query": debug.get("query", False),
                "srv": debug.get("srv", False),
                "cachehit": debug.get("cachehit", False)
            }
            result_lines.append(f"Debug概要: {debug_summary}")
        """
        
        return "\n".join(result_lines)

    def mc_Information(ip:str) -> str:
        """包含初始化的查询"""
        if ip is None:
            return
        api = MinecraftServerStatus(user_agent="XMS-mcbot/1.0 (contact: wjrwhat@qq.com)")
        server_info = api.get_server_info(ip)
        return server_info

# ============================================
# 使用示例（请删除或注释掉以下部分）
# ============================================
if __name__ == "__main__":
    # 创建查询器实例（请务必修改User-Agent）
    api = MinecraftServerStatus(user_agent="XMS-mcbot/1.0 (contact: wjrwhat@qq.com)")
    
    # 你只需要调用这一个函数，传入IP地址即可
    server_info = api.get_server_info("mod.tempestissimo.club")
    print(server_info)
    
    # 示例（你可以取消注释来测试）
    # print(api.get_server_info("mc.hypixel.net"))
    # print(api.get_server_info("play.example.com"))
    #print("请取消注释示例代码来测试，或直接使用 api.get_server_info('服务器地址')")
