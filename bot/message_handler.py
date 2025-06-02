#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
消息处理器
负责处理具体的消息逻辑
"""

import re
import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from loguru import logger
import itchat

from services.content_extractor import ContentExtractor
from utils.message_storage import MessageStorage


class MessageHandler:
    """消息处理器"""
    
    def __init__(self, config: Dict[str, Any], llm_service, note_manager, 
                 rag_service, message_queue):
        """
        初始化消息处理器
        
        Args:
            config: 配置信息
            llm_service: LLM服务实例
            note_manager: 笔记管理器实例
            rag_service: RAG服务实例
            message_queue: 消息队列实例
        """
        self.config = config
        self.wechat_config = config['wechat']
        self.extraction_config = config['content_extraction']
        self.llm_service = llm_service
        self.note_manager = note_manager
        self.rag_service = rag_service
        self.message_queue = message_queue
        
        # 内容提取器
        self.content_extractor = ContentExtractor(
            config=config,
            llm_service=llm_service
        )
        
        # 消息存储
        self.message_storage = MessageStorage(
            db_path=config.get('system', {}).get('message_db_path', 'data/messages.db')
        )
        
        # 运行状态
        self.running = False
    
    def contains_link(self, text: str) -> bool:
        """
        检测文本中是否包含链接
        
        Args:
            text: 文本内容
            
        Returns:
            是否包含链接
        """
        # URL正则表达式
        url_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        # 微信公众号链接
        mp_pattern = r'mp\.weixin\.qq\.com'
        # B站链接
        bilibili_pattern = r'bilibili\.com|b23\.tv'
        
        return bool(re.search(url_pattern, text) or 
                   re.search(mp_pattern, text) or
                   re.search(bilibili_pattern, text))
    
    def save_message(self, msg: Dict[str, Any]):
        """
        保存消息到存储
        
        Args:
            msg: 微信消息对象
        """
        try:
            self.message_storage.save_message(msg)
        except Exception as e:
            logger.error(f"保存消息失败: {e}")
    
    def _get_context_messages(self, target_time: int, window_seconds: int = 60,
                            group_name: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取指定时间窗口内的上下文消息
        
        Args:
            target_time: 目标时间戳
            window_seconds: 时间窗口（秒）
            group_name: 群组名称
            
        Returns:
            上下文消息列表
        """
        # 从存储中获取消息
        return self.message_storage.get_messages_in_time_window(
            target_time=target_time,
            window_seconds=window_seconds,
            group_name=group_name
        )
    
    def _remove_prefix(self, text: str, prefixes: List[str]) -> str:
        """移除触发前缀"""
        for prefix in prefixes:
            if text.startswith(prefix):
                return text[len(prefix):].strip()
        return text.strip()
    
    async def _handle_extract_message(self, message_data: Dict[str, Any]):
        """
        处理内容提取消息
        
        Args:
            message_data: 消息数据
        """
        msg = message_data['msg']
        
        try:
            # 保存消息到存储
            self.save_message(msg)
            
            # 获取群组名称（如果是群消息）
            group_name = None
            if message_data.get('is_group'):
                group_name = msg.get('User', {}).get('NickName', '')
            
            # 获取上下文消息（从持久化存储）
            context_window = self.extraction_config['context_time_window']
            context_messages = self._get_context_messages(
                msg['CreateTime'],
                context_window,
                group_name=group_name
            )
            
            # 提取内容
            extracted_content = await self.content_extractor.extract(
                msg,
                context_messages
            )
            
            if extracted_content:
                # 添加群组信息
                extracted_content['group_name'] = group_name or ''
                
                # 保存到笔记
                await self.note_manager.save_content(extracted_content)
                logger.info(f"内容已提取并保存: {extracted_content['title']}")
                
                # 如果配置了RAG，更新向量数据库
                if self.rag_service:
                    await self.rag_service.add_document(extracted_content)
                    
        except Exception as e:
            logger.error(f"处理内容提取消息时出错: {e}", exc_info=True)
    
    async def _handle_reply_message(self, message_data: Dict[str, Any]):
        """
        处理回复消息
        
        Args:
            message_data: 消息数据
        """
        msg = message_data['msg']
        is_group = message_data['is_group']
        
        try:
            # 保存消息到存储
            self.save_message(msg)
            
            # 获取消息文本并移除前缀
            text = msg['Text']
            if is_group:
                text = self._remove_prefix(text, self.wechat_config['group_chat_prefix'])
            else:
                text = self._remove_prefix(text, self.wechat_config['single_chat_prefix'])
            
            # 生成回复
            reply = await self._generate_reply(text, msg)
            
            if reply:
                # 添加回复前缀
                if is_group:
                    prefix = self.wechat_config.get('group_chat_reply_prefix', '')
                else:
                    prefix = self.wechat_config.get('single_chat_reply_prefix', '')
                
                reply = f"{prefix}{reply}"
                
                # 发送回复
                itchat.send(reply, toUserName=msg['FromUserName'])
                logger.info(f"已回复消息: {reply[:50]}...")
                
        except Exception as e:
            logger.error(f"处理回复消息时出错: {e}", exc_info=True)
            # 发送错误提示
            error_msg = "抱歉，处理您的消息时出现了错误，请稍后再试。"
            itchat.send(error_msg, toUserName=msg['FromUserName'])
    
    async def _generate_reply(self, query: str, msg: Dict[str, Any]) -> Optional[str]:
        """
        生成回复
        
        Args:
            query: 用户查询
            msg: 原始消息对象
            
        Returns:
            回复内容
        """
        try:
            # 如果启用了RAG
            if self.rag_service and self.config['rag']['enabled']:
                # 使用RAG生成回复
                reply = await self.rag_service.query(query)
            else:
                # 直接使用LLM生成回复
                reply = await self.llm_service.chat(query)
            
            return reply
            
        except Exception as e:
            logger.error(f"生成回复时出错: {e}", exc_info=True)
            return None
    
    async def process_message_for_history(self, msg: Dict[str, Any], 
                                        is_group: bool = False) -> Optional[Dict[str, Any]]:
        """
        处理历史消息（供历史处理器使用）
        
        Args:
            msg: 消息对象
            is_group: 是否是群消息
            
        Returns:
            提取的内容（如果有）
        """
        try:
            # 保存消息到存储
            self.save_message(msg)
            
            # 检查是否包含链接
            if not self.contains_link(msg.get('Text', '')):
                return None
            
            # 获取群组名称
            group_name = None
            if is_group:
                group_name = msg.get('User', {}).get('NickName', '')
            
            # 获取上下文消息
            context_window = self.extraction_config['context_time_window']
            context_messages = self._get_context_messages(
                msg['CreateTime'],
                context_window,
                group_name=group_name
            )
            
            # 提取内容
            extracted_content = await self.content_extractor.extract(
                msg,
                context_messages
            )
            
            if extracted_content:
                extracted_content['group_name'] = group_name or ''
                extracted_content['is_history'] = True
                return extracted_content
            
            return None
            
        except Exception as e:
            logger.error(f"处理历史消息时出错: {e}", exc_info=True)
            return None
    
    async def start(self):
        """启动消息处理循环"""
        self.running = True
        logger.info("消息处理器已启动")
        
        # 启动定期清理任务
        asyncio.create_task(self._periodic_cleanup())
        
        while self.running:
            try:
                # 从队列获取消息（非阻塞）
                message_data = self.message_queue.get(timeout=1)
                
                if message_data:
                    msg_type = message_data['type']
                    
                    if msg_type == 'extract':
                        # 处理内容提取
                        await self._handle_extract_message(message_data)
                    elif msg_type == 'reply':
                        # 处理回复生成
                        await self._handle_reply_message(message_data)
                        
            except asyncio.TimeoutError:
                # 队列为空，继续循环
                continue
            except Exception as e:
                logger.error(f"消息处理循环出错: {e}", exc_info=True)
                await asyncio.sleep(1)
        
        logger.info("消息处理器已停止")
    
    async def _periodic_cleanup(self):
        """定期清理旧消息"""
        while self.running:
            try:
                # 每天清理一次
                await asyncio.sleep(24 * 3600)
                
                # 清理超过配置天数的消息
                retention_days = self.config.get('system', {}).get('message_retention_days', 30)
                self.message_storage.cleanup_old_messages(retention_days)
                
            except Exception as e:
                logger.error(f"定期清理任务出错: {e}")
    
    def stop(self):
        """停止消息处理器"""
        self.running = False 