#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Mac微信通道实现
"""
import json
import time
import logging
import threading
import asyncio
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from pathlib import Path

from channel.channel import Channel, Context
from services.mac_wechat_service import MacWeChatService

logger = logging.getLogger(__name__)

class MacWeChatChannel(Channel):
    """
    通过本地数据库读取或Hook实现的macOS微信通道。
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        mac_config = config.get('mac_wechat', {})
        self.mode = mac_config.get('mode', 'silent')
        self.service: Optional[MacWeChatService] = None
        self.message_handler: Optional[Any] = None

        # 静默模式相关
        self.poll_interval = mac_config.get('poll_interval', 60)
        self.message_handlers: Dict[str, Callable] = {}
        self.last_check_timestamp = int(time.time())
        self.poll_thread = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.state_file_path = Path(config.get("system", {}).get("state_file_path", "data/mac_channel_state.json"))
        self.handler_is_set = threading.Event() # 用于确保handler被设置后再处理消息
        self.loop = None # 用于存储主事件循环

    def set_message_handler(self, handler: Any):
        """设置消息处理器实例"""
        self.message_handler = handler
        logger.info("MessageHandler 已成功注入到 MacWeChatChannel。")
        self.handler_is_set.set()

    def set_event_loop(self, loop: asyncio.AbstractEventLoop):
        """设置主事件循环，用于跨线程调用"""
        self.loop = loop

    def update_processed_timestamp(self, new_timestamp: int):
        """
        供外部模块（如HistoryProcessor）调用的方法，用于更新处理进度。
        这可以确保在不同模块处理完消息后，主轮询逻辑能从正确的时间点继续。
        """
        with self.lock:
            if new_timestamp > self.last_check_timestamp:
                logger.info(f"更新处理时间戳从 {datetime.fromtimestamp(self.last_check_timestamp)} 到 {datetime.fromtimestamp(new_timestamp)}")
                self.last_check_timestamp = new_timestamp
                self._save_state()
            else:
                logger.debug(f"尝试更新的时间戳 ({new_timestamp}) 不大于当前时间戳 ({self.last_check_timestamp})，不执行更新。")

    def send(self, reply: Any, context: Dict[str, Any]):
        """发送消息。仅在Hook模式下有效。"""
        if self.mode != 'hook' or not self.service:
            logger.warning("发送消息功能仅在Hook模式下可用，或服务未初始化。")
            return

        try:
            # 兼容不同地方调用时的数据结构
            to_user = reply.get("to_user") or reply.get("to_user_id")
            content = reply.get("content")
            
            if to_user and content:
                logger.info(f"准备通过Mac微信服务发送消息至: {to_user}")
                self.service.send_message(to_user, content)
            else:
                logger.warning(f"发送消息失败：缺少目标用户或内容。数据: {reply}")
        except Exception as e:
            logger.error(f"调用send方法时发生意外错误: {e}", exc_info=True)

    async def get_messages_by_chatroom_id(self, chatroom_id: str, start_timestamp: int = 0) -> List[Dict[str, Any]]:
        """
        从底层服务获取指定群聊的历史消息。
        """
        if self.service and hasattr(self.service, 'get_messages_by_chatroom_id'):
            return await asyncio.to_thread(self.service.get_messages_by_chatroom_id, chatroom_id, start_timestamp)
        logger.warning("当前通道的服务不支持按群聊ID获取消息。")
        return []

    def startup(self):
        """初始化通道服务，但不启动轮询。"""
        self.service = MacWeChatService(self.config)
        if self.mode == 'silent':
            logger.info("正在初始化 Mac WeChat Channel (silent Mode)...")
            if not self.service.initialize(use_hook_mode=False):
                logger.error("MacWeChatService 初始化失败。")
                return
            self._load_state()
            logger.info("Mac WeChat Channel 服务初始化完成。")

        else: # hook mode
            logger.info("正在启动 Mac WeChat Channel (Hook Mode)...")
            if not self.service.initialize(use_hook_mode=True):
                logger.error("MacWeChatService (Hook Mode) 初始化失败。")
                return
            self.service.add_message_handler(self._on_realtime_message)
            logger.info("Mac WeChat Channel (Hook Mode) 实时消息回调已设置。")
    
    def start_polling(self):
        """启动后台轮询线程（仅静默模式）。"""
        if self.mode == 'silent':
            logger.info("启动后台实时轮询线程...")
            self.poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
            self.poll_thread.start()

    def _init_hook_mode(self):
        """初始化Hook模式"""
        # 此方法的内容已合并到 startup，可被移除或保留为空
        pass

    def _on_realtime_message(self, msg: Dict[str, Any]):
        """实时消息回调"""
        self.handler_is_set.wait(timeout=10.0) # 等待handler设置，最多10秒
        if self.message_handler:
            self.message_handler.handle_message(msg)
        else:
            logger.warning("消息处理器未设置，无法处理实时消息。")

    def _load_state(self):
        """从文件加载上次的轮询状态"""
        try:
            if self.state_file_path.exists():
                with open(self.state_file_path, 'r') as f:
                    state = json.load(f)
                    self.last_check_timestamp = state.get('last_check_timestamp', int(time.time()))
                    logger.info(f"成功从状态文件加载进度，将从 {datetime.fromtimestamp(self.last_check_timestamp)} 开始处理。")
            else:
                logger.info(f"未找到状态文件，将从当前时间开始处理: {datetime.fromtimestamp(self.last_check_timestamp)}")
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"加载状态文件失败: {e}，将从当前时间开始。")
            self.last_check_timestamp = int(time.time())

    def _save_state(self):
        """保存当前轮询状态到文件"""
        try:
            self.state_file_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.state_file_path, 'w') as f:
                state = {"last_check_timestamp": self.last_check_timestamp}
                json.dump(state, f)
        except IOError as e:
            logger.error(f"保存状态文件失败: {e}")

    def _process_history(self):
        """检查并处理白名单中的历史消息"""
        if self.message_handler:
            # self.message_handler.trigger_history_processing()
            logger.debug("历史消息处理由app.py主流程触发。")
        else:
            logger.warning("Message Handler 未设置，无法处理历史消息。")

    def _poll_loop(self):
        """轮询循环，用于静默模式"""
        # self.initial_history_processed.wait() # 不再需要，因为轮询在历史处理后启动
        self.handler_is_set.wait() # 仍然等待handler设置
        
        while not self.stop_event.is_set():
            self._poll_once()
            self.stop_event.wait(self.poll_interval)

    def _poll_once(self):
        """执行一次轮询检查"""
        try:
            with self.lock:
                current_time = int(time.time())
                logger.info(f"正在检查自 {datetime.fromtimestamp(self.last_check_timestamp)} 以来的新消息...")
                
                new_messages = self.service.get_new_messages_since(self.last_check_timestamp)

                if new_messages:
                    logger.info(f"发现了 {len(new_messages)} 条新消息。")
                    for msg in new_messages:
                        if self.message_handler and self.loop:
                            # 构造Context对象
                            context = self._create_context_from_msg(msg)
                            # 通过run_coroutine_threadsafe安全地在主循环中执行异步的handle方法
                            asyncio.run_coroutine_threadsafe(self.message_handler.handle(context), self.loop)
                        else:
                            logger.warning("消息处理器或事件循环未设置，跳过消息处理。")
                    
                    # 使用新消息中的最新时间戳更新 internal state
                    latest_msg_time = new_messages[-1]['create_time']
                    if latest_msg_time > self.last_check_timestamp:
                         self.last_check_timestamp = latest_msg_time
                else:
                    logger.info("没有发现新消息。")
                    # 如果没有新消息，仍然更新时间戳到当前检查时间，避免重复扫描旧范围
                    if current_time > self.last_check_timestamp:
                        self.last_check_timestamp = current_time

                logger.info(f"下次轮询将从 {datetime.fromtimestamp(self.last_check_timestamp).strftime('%Y-%m-%d %H:%M:%S')} 开始")
                self._save_state()

        except Exception as e:
            logger.error(f"轮询时发生错误: {e}", exc_info=True)

    def _create_context_from_msg(self, msg: Dict[str, Any]) -> Context:
        """从原始消息字典创建Context对象"""
        is_group = msg.get('is_group', False)
        content = msg.get('content', '')

        # 简单的类型判断
        msg_type = "SHARING" if "http" in content or "<msg>" in content else "TEXT"

        return Context(
            type=msg_type,
            is_group=is_group,
            content=content,
            user_id=msg.get('sender_id'),
            nick_name=msg.get('from_user_name'),
            room_id=msg.get('room_id'),
            group_name=self.service.get_chatroom_name_by_id(msg.get('room_id')) if is_group else "",
            msg=msg, # 将原始消息体存入，方便下游使用
            kwargs={'is_historical': False} # 轮询到的消息都是实时的
        )

    def shutdown(self):
        """安全关闭通道"""
        logger.info(f"正在停止 Mac WeChat Channel ({self.mode} mode)...")
        if self.mode == 'silent' and self.poll_thread:
            self.stop_event.set()
            self.poll_thread.join(timeout=5)
        elif self.mode == 'hook':
            if self.service:
                self.service.stop_monitor()
        
        # 在关闭前最后保存一次状态
        if self.mode == 'silent':
            self._save_state()
        logger.info("Mac WeChat Channel 已停止。") 