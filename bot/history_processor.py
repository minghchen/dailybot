#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
历史消息处理器
负责处理群组的历史聊天记录
"""

import time
import asyncio
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from loguru import logger
from pathlib import Path
import json

class HistoryProcessor:
    """历史消息处理器"""

    def __init__(self, channel: Any, config: Dict[str, Any]):
        """
        初始化历史消息处理器
        
        Args:
            channel: 消息通道实例
            config: 配置信息
        """
        self.channel = channel
        self.config = config
        self.message_handler = None # 通过 set_message_handler 注入
        
        # 处理配置
        self.batch_size = self.config.get('system', {}).get('history_batch_size', 50)
        self.process_delay = self.config.get('system', {}).get('history_process_delay', 0.5)
        self.max_history_days = self.config.get('system', {}).get('max_history_days', 30)

        # 状态管理
        self.state_file = Path.home() / ".dailybot/history_processor_state.json"
        self.group_process_state = self._load_state()

    def set_message_handler(self, handler: Any):
        """注入消息处理器实例"""
        self.message_handler = handler

    def _load_state(self) -> Dict[str, int]:
        """加载处理状态"""
        try:
            if self.state_file.exists():
                with self.state_file.open('r', encoding='utf-8') as f:
                    logger.info(f"从 {self.state_file} 加载历史消息处理状态。")
                    return json.load(f)
        except Exception as e:
            logger.error(f"加载历史处理状态文件失败: {e}", exc_info=True)
        return {}

    def _save_state(self):
        """保存处理状态"""
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            with self.state_file.open('w', encoding='utf-8') as f:
                json.dump(self.group_process_state, f, indent=4)
        except Exception as e:
            logger.error(f"保存历史处理状态文件失败: {e}", exc_info=True)

    async def get_new_history_count_by_id(self, group_id: str) -> int:
        """根据群组ID获取待处理的历史消息数量"""
        if self.config.get('channel_type') != 'mac_wechat' or not hasattr(self.channel, 'service'):
            return 0
            
        mac_service = self.channel.service
        if not mac_service:
            return 0

        last_timestamp = self.group_process_state.get(group_id)
        if last_timestamp:
            start_timestamp = last_timestamp
        else:
            start_time = datetime.now() - timedelta(days=self.max_history_days)
            start_timestamp = int(start_time.timestamp())
        
        return mac_service.get_new_message_count_by_chatroom_id(group_id, start_timestamp)

    async def process_group_history_by_id(self, group_id: str, group_name: str) -> int:
        """
        处理群组的历史消息
        
        Args:
            group_id: 群组ID
            group_name: 群组名称（用于日志)
            
        Returns:
            处理的消息数量
        """
        try:
            logger.info(f"开始为群组 '{group_name}' (ID: {group_id}) 处理历史消息...")
            
            # 获取历史消息
            messages = await self._get_group_history(group_id)
            
            if not messages:
                logger.info(f"群组 '{group_name}' 没有新的历史消息需要处理。")
                return 0
            
            logger.info(f"找到 {len(messages)} 条新的历史消息，开始分批处理...")
            # 分批处理消息
            processed_count = 0
            total_messages = len(messages)
            
            for i in range(0, total_messages, self.batch_size):
                batch = messages[i:i + self.batch_size]
                batch_processed = await self._process_formatted_message_batch(batch, group_name)
                
                if batch_processed > 0:
                    processed_count += batch_processed
                    # 更新状态到当前批次的最后一条消息
                    last_msg_time = batch[-1].get('create_time')
                    if last_msg_time:
                        self.group_process_state[group_id] = last_msg_time
                        self._save_state()

                # 显示进度
                progress = (i + len(batch)) / total_messages * 100
                logger.info(f"处理进度: {progress:.1f}% ({i + len(batch)}/{total_messages}) - 本批处理了 {batch_processed} 条含链接的消息。")
                
                await asyncio.sleep(self.process_delay)
            
            logger.info(f"群组 '{group_name}' 历史消息处理完成，共找到并处理了 {processed_count} 条包含链接的新消息。")
            return processed_count
            
        except Exception as e:
            logger.error(f"处理群组 '{group_name}' 历史消息时出错: {e}", exc_info=True)
            return 0

    async def _get_group_history(self, group_id: str) -> List[Dict[str, Any]]:
        """
        从Mac微信数据库获取群组历史消息
        
        Args:
            group_id: 群组ID
            
        Returns:
            消息列表
        """
        if self.config.get('channel_type') != 'mac_wechat' or not hasattr(self.channel, 'service'):
            logger.warning("历史消息获取仅在Mac微信通道下可用。")
            return []

        try:
            mac_service = self.channel.service
            if not mac_service:
                logger.error("MacWeChatService 不可用。")
                return []
            
            # 确定起始时间戳
            last_timestamp = self.group_process_state.get(group_id)
            if last_timestamp:
                start_timestamp = last_timestamp
                logger.info(f"群组 '{group_id}' 存在处理记录，将从 {datetime.fromtimestamp(start_timestamp).strftime('%Y-%m-%d %H:%M:%S')} 开始增量处理。")
            else:
                start_time = datetime.now() - timedelta(days=self.max_history_days)
                start_timestamp = int(start_time.timestamp())
                logger.info(f"群组 '{group_id}' 为首次处理，将获取过去 {self.max_history_days} 天的消息。")

            # 调用服务层方法获取消息
            messages = mac_service.get_messages_by_chatroom_id(group_id, start_timestamp)

            return messages
        except Exception as e:
            logger.error(f"从数据库获取群组 '{group_id}' 历史消息失败: {e}", exc_info=True)
            return []

    async def _process_formatted_message_batch(self, messages: List[Dict[str, Any]], group_name: str) -> int:
        """
        处理已经格式化好的消息批次 (主要用于Mac微信历史记录)
        """
        if not self.message_handler:
            logger.error("Message Handler 未注入，无法处理历史消息。")
            return 0
        
        processed_count = 0
        for msg in messages:
            try:
                # 检查消息内容是否包含链接
                content = msg.get('content', '')
                if not self.message_handler.contains_link(content):
                    continue

                # 构造Context对象
                context = {
                    "channel": "mac_wechat_history",
                    "msg": msg,
                    "session_id": msg.get("room_id", group_name)
                }

                # 使用消息处理器的统一方法处理
                reply = await self.message_handler.handle_sharing_message(context)
                
                if reply:
                    processed_count += 1
            except Exception as e:
                logger.error(f"处理来自 '{group_name}' 的历史消息时出错: {e}", exc_info=True)
                continue
        return processed_count 