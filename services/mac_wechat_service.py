"""
Mac WeChat Service
Mac微信服务主接口，整合数据库的解密和读取功能，为上层提供统一的数据接口。
"""

import os
import logging
from typing import Dict, List, Optional, Any
from pathlib import Path
from datetime import datetime, timedelta
import subprocess
import time
from threading import Thread, Lock
import json
import re
import hashlib

from services.mac_wechat_hook import MacWeChatHook, DBManager

logger = logging.getLogger(__name__)


class MacWeChatService:
    """Mac微信服务，封装数据库解密、读取和Hook操作"""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.hook = MacWeChatHook()
        self.mode = 'silent'
        self.msg_db_managers: List[DBManager] = []
        self.contact_db_manager: DBManager = None
        # 为不同类型的数据库缓存解密后的路径
        self._decrypted_db_paths: Dict[str, Path] = {}
        # 缓存从数据库中解析出的完整联系人列表
        self._contacts_cache: List[Dict[str, Any]] = []
        # 缓存群聊ID到聊天表名的映射
        self._group_id_to_table_map: Dict[str, str] = {}
        # Hook模式相关
        self.is_hook_mode = False
        self.tweak_message_log_path: Optional[Path] = None
        self.message_monitor_thread: Optional[Thread] = None
        self.is_monitoring = False
        self.message_handlers = []
        self.last_log_size = 0
        self.lock = Lock()

    def initialize(self, use_hook_mode: bool = False) -> bool:
        """根据模式初始化服务"""
        self.mode = 'hook' if use_hook_mode else 'silent'
        if self.mode == 'silent':
            return self._initialize_silent_mode()
        return self._initialize_hook_mode()

    def _initialize_silent_mode(self) -> bool:
        logger.info("正在初始化Mac微信服务 (Silent Mode)...")
        try:
            user_path = self.hook.find_user_data_path()
            if not user_path: return False

            # 动态扫描并解密所有消息数据库
            message_dir = user_path / "Message"
            msg_db_files = sorted(message_dir.glob("msg_*.db"))
            logger.info(f"在 {message_dir} 中发现 {len(msg_db_files)} 个消息数据库文件，开始解密...")

            for db_path in msg_db_files:
                decrypted_path = self.hook.decrypt_database(db_path)
                if decrypted_path:
                    self.msg_db_managers.append(DBManager(decrypted_path))
            
            all_contacts = []
            # 解密并解析个人联系人
            contact_db_path = user_path / "Contact" / "wccontact_new2.db"
            if contact_db_path.exists():
                decrypted_path = self.hook.decrypt_database(contact_db_path)
                if decrypted_path:
                    personal_contacts = self.hook.get_contacts(decrypted_path)
                    all_contacts.extend(personal_contacts)
                    logger.info(f"成功解析了 {len(personal_contacts)} 个个人联系人。")
                    self.contact_db_manager = DBManager(decrypted_path)
            
            # 解密并解析群聊
            group_db_path = user_path / "Group" / "group_new.db"
            if group_db_path.exists():
                decrypted_path = self.hook.decrypt_database(group_db_path)
                if decrypted_path:
                    group_contacts = self.hook.get_groups(decrypted_path)
                    all_contacts.extend(group_contacts)
                    logger.info(f"成功解析了 {len(group_contacts)} 个群聊。")

            self._contacts_cache = all_contacts
            
            if not self.msg_db_managers:
                 logger.error("未能成功解密任何消息数据库。")
                 return False

            if not self._contacts_cache:
                 logger.warning("未能从任何联系人或群组数据库中解析出数据。")
            # else:
            #     # 构建群聊ID到聊天表的映射过程已被移除，因为它是不必要的。
            #     # 当前代码通过MD5哈希直接计算表名，不再需要此映射。
            #     # self._build_group_to_table_map()

            logger.info(f"成功加载 {len(self.msg_db_managers)} 个消息库和 {len(self._contacts_cache)} 个联系人/群组。")
            return True
        except Exception as e:
            logger.error(f"静默模式初始化失败: {e}", exc_info=True)
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

    def get_new_messages_since(self, last_check_time: int) -> List[Dict[str, Any]]:
        """从所有聊天记录中获取指定时间之后的新消息"""
        if not self.msg_db_managers:
            logger.error("消息数据库未初始化，无法获取新消息。")
            return []

        all_new_messages = []
        for db_manager in self.msg_db_managers:
            # 1. 找出该库中所有的聊天表，并排除删除表
            chat_tables = db_manager.execute_query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Chat_%' AND name NOT LIKE '%_dels'")
            
            for table_tuple in chat_tables:
                table_name = table_tuple[0]
                
                # 2. 从每个表中查询新消息
                rows = db_manager.execute_query(
                    f"SELECT mesLocalID, msgCreateTime, msgContent, mesDes, msgSource FROM {table_name} WHERE msgCreateTime > ?",
                    (last_check_time,)
                )
                if not rows: continue

                # 3. 格式化消息
                chatroom_id = table_name.replace("Chat_", "") + "@chatroom"
                for row in rows:
                    sender, content = None, row[2]
                    if row[3] == 0 and content and ":\n" in content:
                        parts = content.split(":\n", 1)
                        if len(parts) == 2 and parts[0].startswith("wxid_"):
                            sender, content = parts
                    
                    sender_name = self.get_contact_nickname(sender) if sender else ""
                    
                    all_new_messages.append({
                        "msg_id": row[0], "create_time": row[1], "content": content,
                        "sender_id": sender, "from_user_name": sender_name, 
                        "room_id": chatroom_id, "is_group": True,
                        "raw": {"MsgSource": row[4]}
                    })
        
        # 按时间排序所有找到的消息
        all_new_messages.sort(key=lambda x: x['create_time'])
        return all_new_messages

    def get_contacts(self) -> List[Dict[str, Any]]:
        """获取所有联系人（包括用户和群组）"""
        if not self._contacts_cache:
            logger.warning("联系人缓存为空，可能初始化未完成或失败。")
        return self._contacts_cache

    def get_contact_nickname(self, user_id: str) -> str:
        """根据用户ID获取联系人昵称"""
        if not user_id: return "未知"
        for contact in self._contacts_cache:
            if contact['user_id'] == user_id:
                return contact['nickname']
        return user_id

    def get_chatroom_name_by_id(self, chatroom_id: str) -> Optional[str]:
        """根据群聊ID获取群聊名称"""
        if not chatroom_id: return None
        for contact in self._contacts_cache:
            if contact['user_id'] == chatroom_id and contact['type'] == 'group':
                return contact['nickname']
        return None

    def get_messages_by_chatroom(self, chatroom_name: str, start_timestamp: int = 0) -> List[Dict[str, Any]]:
        if not self.msg_db_managers:
            logger.error("数据库未初始化。")
            return []
        
        chatroom_id = None
        for contact in self._contacts_cache:
            if contact['nickname'] == chatroom_name and contact['type'] == 'group':
                chatroom_id = contact['user_id']
                break
        
        if not chatroom_id:
             logger.warning(f"在缓存中未找到名为 '{chatroom_name}' 的群聊。")
             return []

        all_messages = []
        table_name = f"Chat_{hashlib.md5(chatroom_id.encode()).hexdigest()}"
        
        for db_manager in self.msg_db_managers:
             # 直接查询已知的表
            rows = db_manager.execute_query(
                f"SELECT mesLocalID, msgCreateTime, msgContent, mesDes, msgSource, messageType FROM {table_name} WHERE msgCreateTime > ?",
                (start_timestamp,)
            )
            if not rows: continue

            for row in rows:
                sender, content = None, row[2]
                if row[3] == 0 and content and ":\\n" in content:
                    parts = content.split(":\\n", 1)
                    if len(parts) == 2 and parts[0].startswith("wxid_"):
                        sender, content = parts
                
                sender_name = self.get_contact_nickname(sender) if sender else chatroom_name
                
                all_messages.append({
                    "msg_id": row[0], "create_time": row[1], "content": content,
                    "sender_id": sender, "from_user_name": sender_name, 
                    "room_id": chatroom_id, "is_group": True,
                    "type": row[5],
                    "raw": {"MsgSource": row[4]}
                })

        all_messages.sort(key=lambda x: x['create_time'])
        logger.info(f"为群组 '{chatroom_name}' 获取到 {len(all_messages)} 条历史消息。")
        return all_messages
    
    def get_messages_by_chatroom_id(self, chatroom_id: str, start_timestamp: int = 0) -> List[Dict[str, Any]]:
        if not self.msg_db_managers:
            logger.error("消息数据库未初始化。")
            return []
        
        all_messages = []
        table_name = f"Chat_{hashlib.md5(chatroom_id.encode()).hexdigest()}"
        
        for db_manager in self.msg_db_managers:
             # 直接查询已知的表
            rows = db_manager.execute_query(
                f"SELECT mesLocalID, msgCreateTime, msgContent, mesDes, msgSource, messageType FROM {table_name} WHERE msgCreateTime > ?",
                (start_timestamp,)
            )
            if not rows: continue

            for row in rows:
                sender, content = None, row[2]
                if row[3] == 0 and content and ":\\n" in content:
                    parts = content.split(":\\n", 1)
                    if len(parts) == 2 and parts[0].startswith("wxid_"):
                        sender, content = parts
                
                sender_name = self.get_contact_nickname(sender) if sender else ""
                
                all_messages.append({
                    "msg_id": row[0], "create_time": row[1], "content": content,
                    "sender_id": sender, "from_user_name": sender_name, 
                    "room_id": chatroom_id, "is_group": True,
                    "type": row[5],
                    "raw": {"MsgSource": row[4]}
                })

        all_messages.sort(key=lambda x: x['create_time'])
        return all_messages
    
    def get_new_message_count_by_chatroom_id(self, chatroom_id: str, start_timestamp: int = 0) -> int:
        if not self.msg_db_managers:
            return 0
            
        total_count = 0
        table_name = f"Chat_{hashlib.md5(chatroom_id.encode()).hexdigest()}"
        
        for db_manager in self.msg_db_managers:
            rows = db_manager.execute_query(
                f"SELECT COUNT(*) FROM {table_name} WHERE msgCreateTime > ?",
                (start_timestamp,)
            )
            if rows and rows[0]:
                total_count += rows[0][0]
                if total_count > 0:
                    break
        
        return total_count
    
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

    def debug_dump_all_groups(self):
        """Dumps all group chats based on the presence of a member list."""
        if not self.contact_db_manager:
            logger.error("Contact DB manager not available for dumping groups.")
            return
        
        logger.info("--- START DEBUG: DUMPING ACTUAL GROUPS (non-empty member list) ---")
        try:
            # A non-empty chatroom member list is the most reliable indicator of a group.
            rows = self.contact_db_manager.execute_query(
                "SELECT m_nsUsrName, nickname FROM WCContact WHERE m_nsChatRoomMemList IS NOT NULL AND m_nsChatRoomMemList != ''"
            )
            if not rows:
                logger.warning("No groups found in the contact database (based on non-empty m_nsChatRoomMemList).")
            else:
                logger.info(f"Found {len(rows)} actual groups:")
                for row in rows:
                    group_id, group_name = row
                    logger.info(f"  - ID: {group_id}, Name: '{group_name}'")
        except Exception as e:
            logger.error(f"Error while dumping groups: {e}", exc_info=True)
        logger.info("--- END DEBUG: DUMPING ACTUAL GROUPS ---")

    def _build_group_to_table_map(self):
        """
        通过扫描消息内容，建立群聊ID到聊天表名的映射。
        """
        group_ids = {c['user_id'] for c in self._contacts_cache if c.get('type') == 'group'}
        if not group_ids:
            logger.warning("缓存中没有群聊，无需建立映射。")
            return

        logger.info(f"开始为 {len(group_ids)} 个群聊构建ID->表名映射...")
        
        for db_manager in self.msg_db_managers:
            # 修正：排除掉记录已删除消息的 _dels 表
            chat_tables = db_manager.execute_query("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'Chat_%' AND name NOT LIKE '%_dels'")
            for table_tuple in chat_tables:
                table_name = table_tuple[0]
                if len(self._group_id_to_table_map) == len(group_ids): break
                
                try:
                    rows = db_manager.execute_query(f'SELECT msgContent FROM "{table_name}" WHERE msgContent LIKE "%@chatroom%" LIMIT 10')
                    for row in rows:
                        content = row[0]
                        match = re.search(r'([a-zA-Z0-9_-]+@chatroom)', content)
                        if match:
                            group_id = match.group(1)
                            if group_id in group_ids and group_id not in self._group_id_to_table_map:
                                logger.debug(f"配对成功: {group_id} -> {table_name}")
                                self._group_id_to_table_map[group_id] = table_name
                                break
                except Exception:
                    continue
            if len(self._group_id_to_table_map) == len(group_ids): break
        
        logger.info(f"映射构建完成，成功匹配 {len(self._group_id_to_table_map)} 个群聊。")


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