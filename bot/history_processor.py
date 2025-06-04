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

from services.content_extractor import ContentExtractor


class HistoryProcessor:
    """历史消息处理器"""
    
    def __init__(self, message_handler, config: Dict[str, Any]):
        """
        初始化历史消息处理器
        
        Args:
            message_handler: 消息处理器实例
            config: 配置信息
        """
        self.message_handler = message_handler
        self.config = config
        self.content_extractor = message_handler.content_extractor
        
        # 处理配置
        self.batch_size = config.get('system', {}).get('history_batch_size', 50)
        self.process_delay = config.get('system', {}).get('history_process_delay', 0.5)
        self.max_history_days = config.get('system', {}).get('max_history_days', 30)
    
    async def process_group_history(self, group_name: str, group_username: str) -> int:
        """
        处理群组的历史消息
        
        Args:
            group_name: 群组名称
            group_username: 群组用户名
            
        Returns:
            处理的消息数量
        """
        try:
            logger.info(f"开始处理群组 '{group_name}' 的历史消息")
            
            # 获取历史消息
            messages = await self._get_group_history(group_username)
            
            if not messages:
                logger.info(f"群组 '{group_name}' 没有可处理的历史消息")
                return 0
            
            # 分批处理消息
            processed_count = 0
            total_messages = len(messages)
            
            for i in range(0, total_messages, self.batch_size):
                batch = messages[i:i + self.batch_size]
                batch_processed = await self._process_message_batch(batch, group_name)
                processed_count += batch_processed
                
                # 显示进度
                progress = (i + len(batch)) / total_messages * 100
                logger.info(f"处理进度: {progress:.1f}% ({i + len(batch)}/{total_messages})")
                
                # 避免处理过快
                await asyncio.sleep(self.process_delay)
            
            logger.info(f"群组 '{group_name}' 历史消息处理完成，共处理 {processed_count} 条包含链接的消息")
            return processed_count
            
        except Exception as e:
            logger.error(f"处理群组历史消息时出错: {e}", exc_info=True)
            return 0
    
    async def _get_group_history(self, group_username: str) -> List[Dict[str, Any]]:
        """
        获取群组历史消息
        
        注意：由于itchat的限制，这里提供一个接口定义
        实际实现可能需要使用其他方式获取历史消息
        
        Args:
            group_username: 群组用户名
            
        Returns:
            消息列表
        """
        # 这里是一个模拟实现
        # 实际使用时，可能需要：
        # 1. 使用其他微信API库
        # 2. 从导出的聊天记录中读取
        # 3. 使用微信PC端的数据库
        
        logger.warning("注意：当前使用模拟的历史消息获取，实际使用时需要实现真实的历史消息获取逻辑")
        
        # 返回空列表表示没有历史消息
        return []
    
    async def process_exported_history(self, export_file: str, group_name: str) -> int:
        """
        处理导出的聊天记录文件
        
        Args:
            export_file: 导出的聊天记录文件路径
            group_name: 群组名称
            
        Returns:
            处理的消息数量
        """
        try:
            logger.info(f"开始处理导出的聊天记录: {export_file}")
            
            # 解析导出文件
            messages = await self._parse_export_file(export_file)
            
            if not messages:
                logger.info("导出文件中没有可处理的消息")
                return 0
            
            # 处理消息
            processed_count = 0
            for i in range(0, len(messages), self.batch_size):
                batch = messages[i:i + self.batch_size]
                batch_processed = await self._process_message_batch(batch, group_name)
                processed_count += batch_processed
                await asyncio.sleep(self.process_delay)
            
            return processed_count
            
        except Exception as e:
            logger.error(f"处理导出文件时出错: {e}", exc_info=True)
            return 0
    
    async def _parse_export_file(self, export_file: str) -> List[Dict[str, Any]]:
        """
        解析导出的聊天记录文件
        支持多种格式：txt、html、json等
        
        Args:
            export_file: 文件路径
            
        Returns:
            解析后的消息列表
        """
        messages = []
        
        try:
            # 根据文件扩展名选择解析方式
            if export_file.endswith('.txt'):
                messages = await self._parse_txt_export(export_file)
            elif export_file.endswith('.html'):
                messages = await self._parse_html_export(export_file)
            elif export_file.endswith('.json'):
                messages = await self._parse_json_export(export_file)
            else:
                logger.warning(f"不支持的文件格式: {export_file}")
                
        except Exception as e:
            logger.error(f"解析导出文件失败: {e}", exc_info=True)
            
        return messages
    
    async def _parse_txt_export(self, file_path: str) -> List[Dict[str, Any]]:
        """解析TXT格式的导出文件"""
        messages = []
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # 简单的文本解析逻辑
            # 假设格式为: 时间 发送者: 内容
            lines = content.split('\n')
            
            for line in lines:
                if ':' in line and len(line) > 20:
                    # 尝试解析消息
                    parts = line.split(':', 2)
                    if len(parts) >= 3:
                        timestamp_str = parts[0].strip()
                        sender = parts[1].strip()
                        text = parts[2].strip()
                        
                        # 检查是否包含链接
                        if self.message_handler.contains_link(text):
                            messages.append({
                                'CreateTime': int(time.time()),  # 使用当前时间作为占位符
                                'User': {'NickName': sender},
                                'Text': text,
                                'Type': 'Text'
                            })
                            
        except Exception as e:
            logger.error(f"解析TXT文件失败: {e}", exc_info=True)
            
        return messages
    
    async def _parse_html_export(self, file_path: str) -> List[Dict[str, Any]]:
        """解析HTML格式的导出文件"""
        # TODO: 实现HTML格式解析
        return []
    
    async def _parse_json_export(self, file_path: str) -> List[Dict[str, Any]]:
        """解析JSON格式的导出文件"""
        import json
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            # 假设JSON格式包含messages数组
            if isinstance(data, list):
                messages = data
            elif isinstance(data, dict) and 'messages' in data:
                messages = data['messages']
            else:
                return []
                
            # 转换为标准格式
            formatted_messages = []
            for msg in messages:
                if self.message_handler.contains_link(msg.get('text', '')):
                    formatted_messages.append({
                        'CreateTime': msg.get('timestamp', int(time.time())),
                        'User': {'NickName': msg.get('sender', 'Unknown')},
                        'Text': msg.get('text', ''),
                        'Type': 'Text'
                    })
                    
            return formatted_messages
            
        except Exception as e:
            logger.error(f"解析JSON文件失败: {e}", exc_info=True)
            return []
    
    async def _process_message_batch(self, messages: List[Dict[str, Any]], group_name: str) -> int:
        """
        处理一批消息
        
        Args:
            messages: 消息列表
            group_name: 群组名称
            
        Returns:
            处理的消息数量
        """
        processed_count = 0
        
        for msg in messages:
            try:
                # 添加群组信息到消息
                msg['User'] = msg.get('User', {})
                msg['User']['NickName'] = msg['User'].get('NickName', group_name)
                
                # 使用消息处理器的统一方法处理历史消息
                extracted_content = await self.message_handler.process_message_for_history(msg, is_group=True)
                
                if extracted_content:
                    # 保存到笔记
                    await self.message_handler.note_manager.save_content(extracted_content)
                    
                    # 更新RAG
                    if self.message_handler.rag_service:
                        await self.message_handler.rag_service.add_document(extracted_content)
                    
                    processed_count += 1
                    
            except Exception as e:
                logger.error(f"处理历史消息时出错: {e}", exc_info=True)
                continue
                
        return processed_count
    
    def _get_context_from_batch(self, messages: List[Dict[str, Any]], target_msg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从批次中获取目标消息的上下文
        
        Args:
            messages: 消息列表
            target_msg: 目标消息
            
        Returns:
            上下文消息列表
        """
        context_messages = []
        target_time = target_msg.get('CreateTime', 0)
        context_window = self.config['content_extraction']['context_time_window']
        
        for msg in messages:
            msg_time = msg.get('CreateTime', 0)
            if abs(msg_time - target_time) <= context_window and msg != target_msg:
                context_messages.append(msg)
                
        return sorted(context_messages, key=lambda x: x.get('CreateTime', 0)) 