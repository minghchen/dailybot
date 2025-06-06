"""
Mac WeChat Channel
基于数据库读取和Hook的Mac微信通道实现
支持两种模式：
1. 静默读取模式：定期读取数据库获取聊天记录（默认）
2. Hook模式：实时监听消息，支持自动回复
"""

import os
import time
import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from threading import Thread
from channel.channel import Channel
from services.mac_wechat_service import MacWeChatService

logger = logging.getLogger(__name__)


class MacWeChatChannel(Channel):
    """Mac微信通道，支持静默读取和Hook两种模式"""
    
    def __init__(self):
        super().__init__()
        self.service = MacWeChatService()
        self.is_running = False
        self.message_callback = None
        self.mode = "silent"  # 默认静默模式
        self.poll_interval = 60  # 静默模式下的轮询间隔（秒）
        self.last_check_time = None
        self.poll_thread = None
        
    def startup(self):
        """启动通道"""
        logger.info("Starting Mac WeChat Channel...")
        
        # 初始化服务
        if not self.service.initialize():
            raise Exception("Failed to initialize Mac WeChat service")
        
        # 检查运行模式
        use_hook = os.getenv("MAC_WECHAT_USE_HOOK", "false").lower() == "true"
        
        if use_hook:
            # Hook模式
            self.mode = "hook"
            logger.info("Running in Hook mode - real-time message monitoring with auto-reply")
            
            # 启用Hook功能
            if not self.service.enable_hook():
                logger.warning("Failed to enable hook, falling back to silent mode")
                self.mode = "silent"
            else:
                # 添加消息处理器
                self.service.add_message_handler(self._on_message_received)
        
        if self.mode == "silent":
            # 静默模式
            logger.info("Running in Silent mode - periodic database reading")
            
            # 获取数据库密钥
            if not self.service.get_db_key():
                raise Exception("Failed to get database key")
            
            # 记录启动时间
            self.last_check_time = datetime.now()
            
            # 启动轮询线程
            self.is_running = True
            self.poll_thread = Thread(target=self._poll_messages)
            self.poll_thread.daemon = True
            self.poll_thread.start()
        
        logger.info(f"Mac WeChat Channel started successfully in {self.mode} mode")
    
    def send(self, message: Dict, context: Dict = None):
        """发送消息（仅在Hook模式下有效）"""
        if self.mode != "hook":
            logger.warning("Send message is only available in Hook mode")
            return
            
        try:
            # 解析消息
            to_user = message.get("to_user_id")
            content = message.get("content")
            msg_type = message.get("type", "text")
            
            if msg_type == "text":
                # 发送文本消息
                success = self.service.send_message(to_user, content)
                if success:
                    logger.info(f"Message sent to {to_user}: {content}")
                else:
                    logger.error(f"Failed to send message to {to_user}")
            else:
                logger.warning(f"Unsupported message type: {msg_type}")
                
        except Exception as e:
            logger.error(f"Error sending message: {e}")
    
    def receive(self):
        """接收消息（通过回调实现）"""
        # 两种模式都使用回调方式，这里不需要主动轮询
        pass
    
    def set_message_callback(self, callback):
        """设置消息回调函数"""
        self.message_callback = callback
    
    def _poll_messages(self):
        """静默模式下的消息轮询"""
        while self.is_running:
            try:
                # 获取自上次检查以来的新消息
                messages = self._get_new_messages()
                
                if messages:
                    logger.info(f"Found {len(messages)} new messages")
                    
                    # 处理每条消息
                    for msg in messages:
                        self._process_silent_message(msg)
                
                # 更新检查时间
                self.last_check_time = datetime.now()
                
                # 等待下次轮询
                time.sleep(self.poll_interval)
                
            except Exception as e:
                logger.error(f"Error in message polling: {e}")
                time.sleep(self.poll_interval)
    
    def _get_new_messages(self) -> List[Dict]:
        """获取新消息"""
        try:
            # 获取最近的消息（比如最近1000条）
            all_messages = self.service.get_recent_messages(1000)
            
            # 过滤出新消息
            new_messages = []
            for msg in all_messages:
                # 解析时间戳
                msg_time = datetime.fromisoformat(msg['timestamp'])
                
                # 只处理上次检查之后的消息
                if msg_time > self.last_check_time:
                    new_messages.append(msg)
            
            return new_messages
            
        except Exception as e:
            logger.error(f"Error getting new messages: {e}")
            return []
    
    def _process_silent_message(self, raw_message: Dict):
        """处理静默模式下的消息"""
        try:
            # 转换消息格式
            message = {
                "msg_id": f"mac_silent_{raw_message.get('timestamp', '')}",
                "create_time": datetime.fromisoformat(raw_message['timestamp']).timestamp(),
                "from_user_id": raw_message.get('source', ''),  # 从source字段提取发送者
                "to_user_id": "self",
                "content": raw_message.get('content', ''),
                "type": self._convert_message_type(raw_message.get('type', 1)),
                "is_historical": True,  # 标记为历史消息
                "raw": raw_message
            }
            
            # 解析source字段以获取真实的发送者ID
            source = raw_message.get('source', '')
            if source and ':' in source:
                # 格式可能是 "wxid_xxx:xxx" 或类似格式
                parts = source.split(':')
                if parts[0].startswith('wxid_'):
                    message['from_user_id'] = parts[0]
            
            # 创建上下文
            context = {
                "channel": "mac_wechat",
                "mode": "silent",
                "msg": message,
                "session_id": message["from_user_id"]
            }
            
            # 调用回调（用于笔记更新等）
            if self.message_callback:
                self.message_callback(message, context)
                
        except Exception as e:
            logger.error(f"Error processing silent message: {e}")
    
    def _on_message_received(self, raw_message: Dict):
        """处理Hook模式下接收到的消息"""
        try:
            # 转换消息格式
            message = {
                "msg_id": f"mac_hook_{int(time.time() * 1000)}",
                "create_time": raw_message.get("timestamp", time.time()),
                "from_user_id": raw_message.get("from", ""),
                "to_user_id": "self",
                "content": raw_message.get("content", ""),
                "type": self._convert_message_type(raw_message.get("type", 1)),
                "is_historical": False,  # 标记为实时消息
                "raw": raw_message
            }
            
            # 创建上下文
            context = {
                "channel": "mac_wechat",
                "mode": "hook",
                "msg": message,
                "session_id": message["from_user_id"]
            }
            
            # 调用回调
            if self.message_callback:
                self.message_callback(message, context)
            
        except Exception as e:
            logger.error(f"Error processing hook message: {e}")
    
    def _convert_message_type(self, wechat_type: int) -> str:
        """转换微信消息类型到通用类型"""
        type_map = {
            1: "text",
            3: "image",
            34: "voice",
            43: "video",
            47: "emoji",
            49: "link"
        }
        return type_map.get(wechat_type, "unknown")
    
    def get_contacts(self) -> List[Dict]:
        """获取联系人列表"""
        return self.service.get_contacts()
    
    def get_chat_history(self, user_id: str = None, limit: int = 100) -> List[Dict]:
        """获取聊天历史"""
        messages = self.service.get_recent_messages(limit)
        
        # 如果指定了用户，进行过滤
        if user_id:
            messages = [m for m in messages if m.get("from") == user_id]
        
        return messages
    
    def search_messages(self, keyword: str, limit: int = 50) -> List[Dict]:
        """搜索消息"""
        return self.service.search_messages(keyword, limit)
    
    def add_auto_reply_rule(self, keyword: str, reply: str, exact_match: bool = False):
        """添加自动回复规则（仅Hook模式有效）"""
        if self.mode == "hook":
            self.service.add_auto_reply_rule(keyword, reply, exact_match)
        else:
            logger.warning("Auto-reply rules are only available in Hook mode")
    
    def set_poll_interval(self, seconds: int):
        """设置静默模式的轮询间隔"""
        self.poll_interval = seconds
        logger.info(f"Poll interval set to {seconds} seconds")
    
    def stop(self):
        """停止通道"""
        logger.info(f"Stopping Mac WeChat Channel ({self.mode} mode)...")
        
        self.is_running = False
        
        # 停止轮询线程
        if self.poll_thread:
            self.poll_thread.join(timeout=5)
        
        # 如果启用了Hook，清理
        if self.mode == "hook" and self.service._is_hook_installed():
            self.service.disable_hook()
        
        logger.info("Mac WeChat Channel stopped")


# 注册通道
def create_channel():
    """工厂函数，创建通道实例"""
    return MacWeChatChannel()


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    # 测试静默模式
    print("=== Testing Silent Mode ===")
    channel = MacWeChatChannel()
    
    # 设置消息回调
    def on_message(msg, ctx):
        print(f"[{ctx['mode']}] 收到消息: {msg['from_user_id']} -> {msg['content'][:50]}...")
        if msg.get('is_historical'):
            print("  (历史消息)")
    
    channel.set_message_callback(on_message)
    channel.set_poll_interval(10)  # 10秒轮询一次
    
    # 启动通道
    channel.startup()
    
    # 运行一段时间
    try:
        print("静默模式运行中，每10秒检查一次新消息...")
        time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        channel.stop()
    
    print("\n=== Testing Hook Mode ===")
    # 测试Hook模式
    os.environ["MAC_WECHAT_USE_HOOK"] = "true"
    channel2 = MacWeChatChannel()
    channel2.set_message_callback(on_message)
    channel2.add_auto_reply_rule("测试", "这是自动回复")
    
    try:
        channel2.startup()
        print("Hook模式运行中，支持实时消息和自动回复...")
        time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        channel2.stop() 