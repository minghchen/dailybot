"""
Mac WeChat Channel
基于数据库读取和Hook的Mac微信通道实现
支持两种模式：
1. 静默读取模式：定期读取数据库获取聊天记录（默认）
2. Hook模式：依赖 WeChatTweak-macOS 实现实时消息收发
"""
import os
import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from threading import Thread, Lock
from pathlib import Path
import re

from channel.channel import Channel
from services.mac_wechat_service import MacWeChatService

logger = logging.getLogger(__name__)


class MacWeChatChannel(Channel):
    """Mac微信通道，支持静默读取和Hook两种模式"""

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.service: Optional[MacWeChatService] = None
        self.is_running = False
        self.message_callback = None
        
        mac_config = self.config.get('mac_wechat', {})
        
        # 根据配置决定运行模式
        self.mode = mac_config.get('mode', 'silent')
        self.use_hook_mode = self.mode == 'hook'
        if self.use_hook_mode:
            # For hook mode, we might need to ensure certain env vars are set
            os.environ["MAC_WECHAT_USE_HOOK"] = "true"
        
        # 静默模式相关
        self.poll_interval = mac_config.get('poll_interval', 60)
        self.last_check_timestamp = 0
        self.poll_thread = None
        self.lock = Lock()
        self.state_file = Path.home() / ".dailybot/mac_channel_state.json"
        # 从配置中分别获取群聊和用户的白名单
        self.group_name_white_list = mac_config.get('group_name_white_list', [])
        self.user_name_white_list = mac_config.get('user_name_white_list', [])

    def startup(self):
        """启动通道"""
        logger.info(f"正在启动 Mac WeChat Channel ({self.mode} Mode)...")
        
        try:
            self.service = MacWeChatService(self.config)
            if not self.service.initialize(use_hook_mode=self.use_hook_mode):
                raise Exception(f"初始化Mac微信服务 ({self.mode} mode) 失败。请检查日志和配置。")

            if self.mode == 'hook':
                # Hook模式下，设置实时消息回调
                self.service.add_message_handler(self._on_message_received)
                self.is_running = True
            else:
                # 静默模式下，加载状态并启动轮询
                self._load_state()
                self.is_running = True

                # 执行一次初始轮询，以便立即提供反馈
                self._poll_once()
                
                self.poll_thread = Thread(target=self._poll_loop)
                self.poll_thread.daemon = True
                self.poll_thread.start()

            # 如果是Hook模式，启动消息监控
            if self.use_hook_mode:
                # 检查Tweak是否安装
                if not self.service.is_tweak_installed():
                    logger.warning("Hook模式已启用，但未检测到WeChatTweak-macOS。实时消息功能将不可用。")
                    logger.warning("请访问 https://github.com/sunnyyoung/WeChatTweak-macOS 手动安装。")
                else:
                    logger.info("Hook模式已启用，并检测到WeChatTweak-macOS。")
                    self.service.start_monitoring(self._handle_hook_message)

            logger.info("Mac WeChat Channel 启动成功。")
        except Exception as e:
            logger.error(f"Mac WeChat Channel 启动失败: {e}")
            self.is_running = False

    def get_whitelisted_conversations(self) -> List[Dict[str, Any]]:
        """
        获取白名单中所有会话（群聊和个人）的详细信息。
        这使得上层应用（如HistoryProcessor）可以统一处理所有白名单会话。
        """
        if not self.service:
            logger.warning("服务未初始化，无法获取白名单会话。")
            return []
        
        whitelisted_items = []
        all_contacts = self.service.get_contacts()
        if not all_contacts:
            logger.warning("无法从服务中获取任何联系人信息。")
            return []

        # 1. 处理群聊白名单
        for name in self.group_name_white_list:
            found = False
            for contact in all_contacts:
                if contact.get('type') == 'group' and contact.get('nickname') == name:
                    whitelisted_items.append(contact)
                    logger.info(f"在群聊白名单中找到: '{name}' (ID: {contact.get('user_id')})")
                    found = True
                    break
            if not found:
                logger.warning(f"在联系人列表中未找到群聊白名单中的: '{name}'")
                
        # 2. 处理用户白名单
        for name in self.user_name_white_list:
            found = False
            for contact in all_contacts:
                # 只在好友类型中查找
                if contact.get('type') == 'friend' and (contact.get('nickname') == name or contact.get('remark') == name):
                    whitelisted_items.append(contact)
                    logger.info(f"在用户白名单中找到: '{name}' (ID: {contact.get('user_id')})")
                    found = True
                    break
            if not found:
                logger.warning(f"在联系人列表中未找到用户白名单中的: '{name}'")
        
        return whitelisted_items

    def send(self, reply: Any, context: Dict[str, Any]):
        """发送消息 (仅Hook模式支持)"""
        if self.mode != 'hook' or not self.service:
            logger.warning("发送消息功能仅在Hook模式下可用。")
            return

        try:
            target_id = reply.get("to_user_id")
            content = reply.get("content")
            if target_id and content:
                logger.info(f"[MacWeChat] 准备发送消息: To: {target_id}, Content: {content[:50]}...")
                success = self.service.send_message(target_id, content)
                if success:
                    logger.info(f"[MacWeChat] 消息发送成功。")
                else:
                    logger.error(f"[MacWeChat] 消息发送失败。")
        except Exception as e:
            logger.error(f"发送消息时出错: {e}", exc_info=True)

    def receive(self):
        """接收消息（通过回调实现，无需主动调用）"""
        pass

    def set_message_callback(self, callback):
        self.message_callback = callback

    def _load_state(self):
        """从文件加载上次的轮询状态"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    import json
                    state = json.load(f)
                    self.last_check_timestamp = state.get("last_check_timestamp", 0)
                logger.info(f"成功加载状态，上次检查时间: {datetime.fromtimestamp(self.last_check_timestamp)}")
            else:
                self.last_check_timestamp = int(datetime.now().timestamp())
                logger.info(f"未找到状态文件，将从当前时间开始处理: {datetime.fromtimestamp(self.last_check_timestamp)}")
        except Exception as e:
            logger.error(f"加载状态文件失败: {e}")
            self.last_check_timestamp = int(datetime.now().timestamp())

    def _save_state(self):
        """保存当前轮询状态到文件"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file, 'w') as f:
                import json
                state = {"last_check_timestamp": self.last_check_timestamp}
                json.dump(state, f)
        except Exception as e:
            logger.error(f"保存状态文件失败: {e}")

    def _poll_once(self):
        """执行单次消息轮询"""
        try:
            with self.lock:
                if not self.service:
                    logger.warning("MacWeChatService尚未初始化，跳过轮询。")
                    return

                # 记录轮询开始时的时间戳，作为下一次轮询的起点。
                # 这样可以确保时间窗口总是向前移动，避免卡在某个时间点。
                next_poll_timestamp = int(time.time())

                logger.info(f"正在检查自 {datetime.fromtimestamp(self.last_check_timestamp).strftime('%Y-%m-%d %H:%M:%S')} 以来的新消息...")
                new_messages = self.service.get_new_messages_since(self.last_check_timestamp)

                if new_messages:
                    logger.info(f"发现 {len(new_messages)} 条新消息。")
                    for msg in new_messages:
                        self._process_message(msg, is_historical=True)
                else:
                    logger.info("没有发现新消息。")

                # 无论是否找到消息，都将时间戳更新为本次轮询开始时记录的时间。
                self.last_check_timestamp = next_poll_timestamp
                logger.info(f"下次轮询将从 {datetime.fromtimestamp(self.last_check_timestamp).strftime('%Y-%m-%d %H:%M:%S')} 开始")
                self._save_state()

        except Exception as e:
            logger.error(f"轮询消息时出错: {e}", exc_info=True)

    def _poll_loop(self):
        """轮询循环 (静默模式)"""
        while self.is_running:
            try:
                logger.info(f"下一次轮询将在 {self.poll_interval} 秒后进行。")
                time.sleep(self.poll_interval)
                if self.is_running:
                    self._poll_once()
            except Exception as e:
                logger.error(f"轮询线程发生意外错误: {e}", exc_info=True)

    def _on_message_received(self, raw_message: Dict):
        """处理Hook模式下的实时消息"""
        self._process_message(raw_message, is_historical=False)

    def _process_message(self, raw_message: Dict, is_historical: bool):
        """处理消息，转换为通用格式并调用回调"""
        try:
            message = {
                "msg_id": raw_message.get('msg_id', f"mac_{self.mode}_{int(time.time() * 1000)}"),
                "create_time": raw_message.get('create_time'),
                "from_user_id": raw_message.get('sender_id') or raw_message.get('room_id') or raw_message.get('from_user_id'),
                "room_id": raw_message.get('room_id') if raw_message.get('is_group') else None,
                "content": raw_message.get('content', ''),
                "is_group": raw_message.get('is_group', False),
                "type": "text",
                "is_historical": is_historical,
                "raw": raw_message
            }
            
            # 在Hook模式的群聊中，如果能从原始日志中解析出具体发言人，则使用
            if self.mode == 'hook' and message['is_group']:
                 # 示例：'wxid_xxxx@chatroom(小明)'
                 match = re.search(r'\((.*?)\)', raw_message.get('from_user_id',''))
                 if match:
                     message['from_user_id'] = match.group(1) # 使用昵称作为发送者

            context = {
                "channel": "mac_wechat",
                "mode": self.mode,
                "msg": message,
                "session_id": message["room_id"] or message["from_user_id"]
            }

            if self.message_callback:
                self.message_callback(message, context)

        except Exception as e:
            logger.error(f"处理消息时出错: {e}", exc_info=True)

    def _handle_hook_message(self, msg: Dict[str, Any]):
        """处理来自Hook的消息"""
        try:
            # 简单的文本消息处理
            content = msg.get("content", "")
            from_user = msg.get("sender", "")
            room_id = msg.get("room_id", "")
            is_group = msg.get("is_group", False)

            if not content or not from_user:
                return

            context = self._create_context(content, from_user, room_id, is_group)
            if context:
                self.message_callback(context)

        except Exception as e:
            logger.error(f"处理Hook消息失败: {e}", exc_info=True)

    def _create_context(self, content: str, from_user: str, room_id: Optional[str] = None, is_group: bool = False) -> Optional[Dict]:
        """创建消息上下文，并检查是否需要触发机器人"""
        
        context = {
            "channel": "mac_wechat",
            "mode": self.mode,
            "msg": {
                "msg_id": f"mac_{self.mode}_{int(time.time() * 1000)}",
                "create_time": int(datetime.now().timestamp()),
                "from_user_id": from_user,
                "room_id": room_id,
                "content": content,
                "is_group": is_group,
                "type": "text",
                "is_historical": False,
                "raw": {
                    "msg_id": f"mac_{self.mode}_{int(time.time() * 1000)}",
                    "create_time": int(datetime.now().timestamp()),
                    "sender_id": from_user,
                    "room_id": room_id,
                    "content": content,
                    "is_group": is_group
                }
            },
            "session_id": room_id or from_user
        }

        return context

    def shutdown(self):
        """停止通道"""
        logger.info(f"正在停止 Mac WeChat Channel ({self.mode} mode)...")
        self.is_running = False
        if self.mode == 'hook' and self.service:
            if hasattr(self.service, 'stop_monitor'):
                self.service.stop_monitor()
        if self.poll_thread and self.poll_thread.is_alive():
            self.poll_thread.join(timeout=5)
        
        logger.info("Mac WeChat Channel 已停止。") 