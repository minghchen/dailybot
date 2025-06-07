"""
Mac WeChat Service
Mac微信服务主接口，整合数据库的解密和读取功能，为上层提供统一的数据接口。
"""

import os
import logging
from typing import Dict, List, Optional
from pathlib import Path
from datetime import datetime, timedelta
import subprocess
import time
from threading import Thread, Lock
import json
import re

from .mac_wechat_hook import MacWeChatHook

logger = logging.getLogger(__name__)


class MacWeChatService:
    """
    Mac微信服务主类。
    负责协调底层hook，管理数据库解密，并向上层提供稳定的接口。
    """

    def __init__(self):
        self.hook: Optional[MacWeChatHook] = None
        # 为不同类型的数据库缓存解密后的路径
        self._decrypted_db_paths: Dict[str, Path] = {}
        # Hook模式相关
        self.is_hook_mode = False
        self.tweak_message_log_path: Optional[Path] = None
        self.message_monitor_thread: Optional[Thread] = None
        self.is_monitoring = False
        self.message_handlers = []
        self.last_log_size = 0
        self.lock = Lock()

    def initialize(self, use_hook_mode: bool = False) -> bool:
        """
        初始化服务。
        根据模式选择初始化静默模式或Hook模式。
        """
        self.is_hook_mode = use_hook_mode
        if self.is_hook_mode:
            return self._initialize_hook_mode()
        else:
            return self._initialize_silent_mode()

    def _initialize_silent_mode(self) -> bool:
        """初始化静默模式"""
        logger.info("正在初始化Mac微信服务 (Silent Mode)...")
        try:
            self.hook = MacWeChatHook()
            self._prepare_databases()
            logger.info("Mac微信服务 (Silent Mode) 初始化成功。")
            return True
        except (ValueError, FileNotFoundError) as e:
            logger.error(f"Mac微信服务 (Silent Mode) 初始化失败: {e}")
            self.hook = None
            return False

    def _initialize_hook_mode(self) -> bool:
        """
        初始化Hook模式。
        此模式依赖于用户已手动安装 WeChatTweak-macOS。
        """
        logger.info("正在初始化Mac微信服务 (Hook Mode)...")
        if not self._is_tweak_installed():
            logger.error("检测到未使用Hook模式或未安装WeChatTweak-macOS。")
            logger.error("请先访问 https://github.com/sunnyyoung/WeChatTweak-macOS 进行安装和配置。")
            return False

        # WeChatTweak 会将消息记录到特定日志文件
        # 通常路径为 ~/Library/Containers/com.tencent.xinWeChat/Data/Library/Caches/tweak_messages.log
        self.tweak_message_log_path = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data/Library/Caches/tweak_messages.log"
        if not self.tweak_message_log_path.exists():
             logger.warning(f"未找到Tweak消息日志: {self.tweak_message_log_path}")
             logger.warning("将无法实时接收消息。请确认Tweak版本和配置。")
             return False
        
        logger.info(f"检测到WeChatTweak已安装，将监控消息日志: {self.tweak_message_log_path}")
        self.start_message_monitor()
        return True

    def _is_tweak_installed(self) -> bool:
        """检查WeChatTweak-macOS是否已安装"""
        # 一个简单的检查方法是看微信二进制文件是否被修改过
        # 'wechattweak-cli' 会在注入后改变二进制文件
        try:
            wechat_binary_path = "/Applications/WeChat.app/Contents/MacOS/WeChat"
            result = subprocess.run(['otool', '-L', wechat_binary_path], capture_output=True, text=True)
            return 'WeChatTweak' in result.stdout
        except FileNotFoundError:
            logger.error("'otool' command not found. Unable to check for Tweak installation.")
            return False

    def _prepare_databases(self):
        """查找并解密所有需要的数据库文件。"""
        if not self.hook:
            return
            
        logger.info("正在准备数据库...")
        # 需要处理的数据库列表，可以根据需要扩展
        # 常见消息数据库命名为 msg_0.db, msg_1.db, ...
        db_to_prepare = [f"msg_{i}.db" for i in range(5)] + ["wccontact_new2.db"]

        for db_name in db_to_prepare:
            db_path = self.hook.find_main_db_path(db_name)
            if db_path:
                decrypted_path = self.hook.decrypt_database(db_path)
                if decrypted_path:
                    self._decrypted_db_paths[db_name] = decrypted_path
        
        if not self._decrypted_db_paths:
             logger.warning("未能找到或解密任何数据库文件。")
        else:
             logger.info(f"成功准备 {len(self._decrypted_db_paths)} 个数据库。")

    def get_new_messages_since(self, last_check_timestamp: int, limit_per_db: int = 100) -> List[Dict]:
        """
        从所有已知的消息数据库中，获取某个时间点之后的新消息。
        """
        if not self.hook:
            logger.error("服务未初始化。")
            return []

        all_new_messages = []
        msg_db_names = [name for name in self._decrypted_db_paths if name.startswith("msg_")]

        for db_name in msg_db_names:
            decrypted_path = self._decrypted_db_paths[db_name]
            messages = self.hook.get_chat_messages(
                decrypted_db_path=decrypted_path,
                last_check_time=last_check_timestamp,
                limit=limit_per_db
            )
            all_new_messages.extend(messages)
        
        # 按创建时间排序所有消息
        all_new_messages.sort(key=lambda x: x['create_time'])
        
        if all_new_messages:
            logger.info(f"从 {len(msg_db_names)} 个数据库中获取了 {len(all_new_messages)} 条新消息。")
            
        return all_new_messages

    def get_contacts(self) -> List[Dict]:
        """获取所有联系人列表（好友和群聊）。"""
        if not self.hook:
            logger.error("服务未初始化。")
            return []
            
        contact_db_name = "wccontact_new2.db"
        if contact_db_name not in self._decrypted_db_paths:
            logger.error("联系人数据库未准备好。")
            return []
            
        decrypted_path = self._decrypted_db_paths[contact_db_name]
        return self.hook.get_contacts(decrypted_path)

    # --- Hook模式相关功能 ---

    def send_message(self, to_user: str, content: str) -> bool:
        """
        发送消息（仅Hook模式）。通过AppleScript实现。
        """
        if not self.is_hook_mode:
            logger.warning("发送消息功能仅在Hook模式下可用。")
            return False

        script = f'''
        tell application "WeChat"
            activate
            tell session "{to_user}"
                send "{content}"
            end tell
        end tell
        '''
        try:
            subprocess.run(["osascript", "-e", script], check=True, capture_output=True)
            logger.info(f"通过AppleScript向 {to_user} 发送消息成功。")
            return True
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            logger.error(f"通过AppleScript发送消息失败: {e.stderr if isinstance(e, subprocess.CalledProcessError) else e}")
            return False

    def add_message_handler(self, handler):
        """
        添加实时消息处理器（仅Hook模式）。
        """
        if self.is_hook_mode:
            self.message_handlers.append(handler)
        else:
            logger.warning("实时消息处理仅在Hook模式下可用。")
    
    def start_message_monitor(self):
        """启动消息监控线程（仅Hook模式）"""
        if self.message_monitor_thread and self.message_monitor_thread.is_alive():
            logger.warning("消息监控已在运行。")
            return

        self.is_monitoring = True
        self.message_monitor_thread = Thread(target=self._monitor_tweak_log_file, daemon=True)
        self.message_monitor_thread.start()
        logger.info("Hook模式消息监控已启动。")
    
    def stop_monitor(self):
        if self.message_monitor_thread and self.message_monitor_thread.is_alive():
            self.is_monitoring = False
            self.message_monitor_thread.join()
            logger.info("消息监控已停止。")

    def _monitor_tweak_log_file(self):
        """监控Tweak日志文件以获取新消息"""
        if not self.tweak_message_log_path:
            return
            
        # 初始化文件大小
        self.last_log_size = self.tweak_message_log_path.stat().st_size

        while self.is_monitoring:
            try:
                with self.lock:
                    current_size = self.tweak_message_log_path.stat().st_size
                    if current_size > self.last_log_size:
                        with open(self.tweak_message_log_path, 'r', encoding='utf-8') as f:
                            f.seek(self.last_log_size)
                            new_lines = f.readlines()
                            for line in new_lines:
                                self._parse_and_handle_log_line(line)
                        self.last_log_size = current_size
                    elif current_size < self.last_log_size:
                        # 日志文件被滚动或清空
                        self.last_log_size = 0
            except FileNotFoundError:
                logger.warning(f"消息日志文件 {self.tweak_message_log_path} 不再存在。")
                time.sleep(10) # 等待文件重新创建
            except Exception as e:
                logger.error(f"监控Tweak日志文件时出错: {e}", exc_info=True)
            
            time.sleep(1) # 轮询间隔

    def _parse_and_handle_log_line(self, line: str):
        """解析单行日志并调用处理器"""
        # WeChatTweak 日志格式示例:
        # 2024-07-30 15:30:00.123 [WeChatTweak] [Message] wxid_xxxx@chatroom(小明): 大家好
        match = re.search(r'\[Message\]\s+(.*?)\((.*?)\):\s*(.*)', line)
        if match:
            full_user, nickname, content = match.groups()
            
            room_id = None
            sender_id = full_user
            if "@chatroom" in full_user:
                room_id = full_user
                # 这种情况无法直接从日志中获得发言人wxid，但通常tweak会提供
                # 我们先用昵称代替
                sender_id = nickname 
            
            message = {
                "msg_id": f"mac_hook_{int(time.time() * 1000)}",
                "create_time": int(datetime.now().timestamp()),
                "from_user_id": sender_id,
                "room_id": room_id,
                "content": content.strip(),
                "is_group": bool(room_id),
                "type": "text",
                "is_historical": False,
                "raw": line
            }
            
            # 调用所有消息处理器
            for handler in self.message_handlers:
                try:
                    handler(message)
                except Exception as e:
                    logger.error(f"消息处理器出错: {e}", exc_info=True)


# 使用示例
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # 需要先设置环境变量 WECHAT_DB_KEY
    if "WECHAT_DB_KEY" not in os.environ:
        print("错误: 请先设置 'WECHAT_DB_KEY' 环境变量才能运行测试。")
    else:
        # 测试静默模式
        print("--- 测试静默模式 ---")
        service = MacWeChatService()
        if service.initialize(use_hook_mode=False):
            print("\n--- 获取联系人 ---")
            contacts = service.get_contacts()
            if contacts:
                print(f"成功获取 {len(contacts)} 个联系人。")
                friend_count = sum(1 for c in contacts if c['type'] == 'friend')
                group_count = sum(1 for c in contacts if c['type'] == 'group')
                print(f"好友: {friend_count}, 群聊: {group_count}")
                print("前5个联系人:", contacts[:5])
            else:
                print("未能获取联系人。")

            print("\n--- 获取最近10分钟内的消息 ---")
            ten_minutes_ago = int((datetime.now() - timedelta(minutes=10)).timestamp())
            recent_messages = service.get_new_messages_since(ten_minutes_ago)
            if recent_messages:
                print(f"成功获取 {len(recent_messages)} 条最近消息。")
                print("最新一条消息:", recent_messages[-1])
            else:
                print("未发现最近10分钟内的消息。")
        
        # 测试Hook模式
        print("\n--- 测试Hook模式 ---")
        hook_service = MacWeChatService()
        def on_realtime_message(msg):
            print("\n>>> 实时消息收到:")
            print(f"    Content: {msg['content']}")
            print(f"    From: {msg['from_user_id']}")
        
        hook_service.add_message_handler(on_realtime_message)
        
        if hook_service.initialize(use_hook_mode=True):
            print("Hook模式初始化成功，正在监听实时消息... (按Ctrl+C停止)")
            # 模拟发送消息
            # hook_service.send_message("filehelper", "这是一条来自Python的测试消息")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                hook_service.stop_monitor()
                print("\n监控已停止。")
        else:
            print("Hook模式初始化失败，请确认已安装并配置好 WeChatTweak-macOS。") 