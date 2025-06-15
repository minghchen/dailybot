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

from channel.channel import Context

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

    async def process_fetched_history(self, group_id: str, group_name: str, messages: List[Dict[str, Any]]) -> int:
        """
        处理已经预先获取好的历史消息列表
        
        Args:
            group_id: 群组ID
            group_name: 群组名称（用于日志)
            messages: 待处理的消息列表
            
        Returns:
            处理的消息数量
        """
        try:
            logger.info(f"开始为群组 '{group_name}' (ID: {group_id}) 处理 {len(messages)} 条已获取的历史消息...")
            
            if not messages:
                return 0
            
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

    def _map_msg_type_to_context(self, msg_type: int) -> str:
        """将Mac微信的消息类型码映射到统一的Context类型"""
        if msg_type == 1:
            return "TEXT"
        if msg_type == 49:
            return "SHARING"
        # 更多映射...
        return "UNKNOWN"

    async def _process_formatted_message_batch(self, batch: List[Dict[str, Any]], group_name: str) -> int:
        """
        处理已经格式化好的消息批次。
        与实时消息处理不同，这里会将整个批次作为上下文环境。
        """
        if not self.message_handler:
            logger.error("Message Handler 未注入，无法处理历史消息。")
            return 0
        
        processed_count = 0
        for i, msg in enumerate(batch):
            try:
                # 只处理包含链接的消息
                content = msg.get('content', '')
                if not self.message_handler.contains_link(content):
                    continue
                
                # 修正: 传递正确的批次和索引
                await self.message_handler.handle_historical_message(
                    current_msg=msg, 
                    batch_context=batch, # 上下文应该是当前批次
                    current_index=i,     # 索引也应该是批次内的索引
                    group_name=group_name
                )
                processed_count += 1

            except Exception as e:
                logger.error(f"处理来自 '{group_name}' 的历史消息时出错: {e}", exc_info=True)
                continue
        return processed_count 