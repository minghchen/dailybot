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

from channel.channel import Context, Reply, ReplyType
from services.content_extractor import ContentExtractor
from utils.message_storage import MessageStorage


class MessageHandler:
    """消息处理器"""
    
    def __init__(self, config: Dict[str, Any], llm_service, note_manager, 
                 rag_service):
        """
        初始化消息处理器
        
        Args:
            config: 配置信息
            llm_service: LLM服务实例
            note_manager: 笔记管理器实例
            rag_service: RAG服务实例
        """
        self.config = config
        self.wechat_config = config['wechat']
        self.extraction_config = config['content_extraction']
        self.llm_service = llm_service
        self.note_manager = note_manager
        self.rag_service = rag_service
        
        # 内容提取器
        self.content_extractor = ContentExtractor(
            config=config,
            llm_service=llm_service
        )
        
        # 消息存储
        self.message_storage = MessageStorage(
            db_path=config.get('system', {}).get('message_db_path', 'data/messages.db')
        )
    
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
    
    def save_message_from_context(self, context: Context):
        """
        从Context保存消息到存储
        
        Args:
            context: 消息上下文
        """
        try:
            # 构造消息对象用于存储
            msg = {
                'MsgId': getattr(context.msg, 'msg_id', str(time.time())),
                'FromUserName': context.user_id,
                'ToUserName': '',
                'Content': context.content,
                'CreateTime': int(time.time()),
                'Type': context.type,
                'Text': context.content,
                'User': {
                    'NickName': context.nick_name,
                    'UserName': context.user_id
                }
            }
            
            # 如果是群消息，添加群信息
            if context.is_group:
                msg['User']['NickName'] = context.group_name
                msg['ActualNickName'] = context.nick_name
            
            self.message_storage.save_message(msg)
        except Exception as e:
            logger.error(f"保存消息失败: {e}")
    
    async def handle_text_message(self, context: Context) -> Optional[Reply]:
        """
        处理文本消息
        
        Args:
            context: 消息上下文
            
        Returns:
            回复对象
        """
        try:
            # 保存消息
            self.save_message_from_context(context)
            
            # 检查是否需要提取内容
            if self.extraction_config['auto_extract_enabled'] and self.contains_link(context.content):
                # 异步提取内容
                asyncio.create_task(self._extract_content(context))
                
                # 如果是静默模式，不回复
                if self.extraction_config.get('silent_mode', True):
                    return None
            
            # 获取回复内容
            reply_text = await self._generate_reply(context)
            
            if reply_text:
                # 添加回复前缀
                if context.is_group:
                    prefix = self.wechat_config.get('group_chat_reply_prefix', '')
                else:
                    prefix = self.wechat_config.get('single_chat_reply_prefix', '')
                
                reply_text = f"{prefix}{reply_text}"
                
                return Reply(ReplyType.TEXT, reply_text)
            
            return None
            
        except Exception as e:
            logger.error(f"处理文本消息时出错: {e}", exc_info=True)
            return Reply(ReplyType.ERROR, "抱歉，处理您的消息时出现了错误，请稍后再试。")
    
    async def handle_sharing_message(self, context: Context) -> Optional[Reply]:
        """
        处理分享消息
        
        Args:
            context: 消息上下文
            
        Returns:
            回复对象
        """
        try:
            # 保存消息
            self.save_message_from_context(context)
            
            # 自动提取分享内容
            if self.extraction_config['auto_extract_enabled']:
                asyncio.create_task(self._extract_content(context))
                
                # 如果是静默模式，不回复
                if self.extraction_config.get('silent_mode', True):
                    return None
                else:
                    return Reply(ReplyType.TEXT, "正在为您提取内容，请稍候...")
            
            return None
            
        except Exception as e:
            logger.error(f"处理分享消息时出错: {e}", exc_info=True)
            return None
    
    async def _extract_content(self, context: Context):
        """
        提取内容
        
        Args:
            context: 消息上下文
        """
        try:
            # 获取上下文消息
            context_window = self.extraction_config['context_time_window']
            context_messages = self._get_context_messages(
                int(time.time()),
                context_window,
                group_name=context.group_name if context.is_group else None
            )
            
            # 构造消息对象供提取器使用
            msg = {
                'Text': context.content,
                'Type': context.type,
                'CreateTime': int(time.time()),
                'User': {'NickName': context.nick_name}
            }
            
            # 提取内容
            extracted_content = await self.content_extractor.extract(
                msg,
                context_messages
            )
            
            if extracted_content:
                # 添加群组信息
                extracted_content['group_name'] = context.group_name if context.is_group else ''
                
                # 保存到笔记
                await self.note_manager.save_content(extracted_content)
                logger.info(f"内容已提取并保存: {extracted_content['title']}")
                
                # 如果配置了RAG，更新向量数据库
                if self.rag_service:
                    await self.rag_service.add_document(extracted_content)
                    
        except Exception as e:
            logger.error(f"提取内容时出错: {e}", exc_info=True)
    
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
    
    async def _generate_reply(self, context: Context) -> Optional[str]:
        """
        生成回复
        
        Args:
            context: 消息上下文
            
        Returns:
            回复内容
        """
        try:
            # 获取查询文本（去除前缀）
            query = context.content
            
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
            self.message_storage.save_message(msg)
            
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