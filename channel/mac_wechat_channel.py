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

        # Hook模式相关
        self.auto_reply_rules = mac_config.get('auto_reply_rules', {})

    def startup(self):
        """启动通道"""
        logger.info(f"正在启动 Mac WeChat Channel ({self.mode} Mode)...")
        
        try:
            self.service = MacWeChatService()
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
                self.poll_thread = Thread(target=self._poll_messages)
                self.poll_thread.daemon = True
                self.poll_thread.start()

            logger.info("Mac WeChat Channel 启动成功。")
        except Exception as e:
            logger.error(f"Mac WeChat Channel 启动失败: {e}")
            self.is_running = False

    def send(self, message: Dict, context: Dict = None):
        """发送消息（仅在Hook模式下有效）"""
        if self.mode != 'hook' or not self.service:
            logger.warning("发送消息功能仅在Hook模式下可用。")
            return

        try:
            to_user = message.get("to_user_id")
            content = message.get("content")
            if to_user and content:
                self.service.send_message(to_user, content)
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

    def _poll_messages(self):
        """消息轮询 (仅静默模式)"""
        while self.is_running:
            try:
                with self.lock:
                    if not self.service:
                        time.sleep(self.poll_interval)
                        continue
                    new_messages = self.service.get_new_messages_since(self.last_check_timestamp)
                    if new_messages:
                        logger.info(f"发现 {len(new_messages)} 条新消息。")
                        for msg in new_messages:
                            self._process_message(msg, is_historical=True)
                        self.last_check_timestamp = new_messages[-1]['create_time']
                        self._save_state()
                    else:
                        logger.debug("没有新消息。")
            except Exception as e:
                logger.error(f"轮询消息时出错: {e}", exc_info=True)
            time.sleep(self.poll_interval)

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