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
from pathlib import Path
import json

from channel.channel import Context, Reply, ReplyType
from services.content_extractor import ContentExtractor
from utils.message_storage import MessageStorage
from bot.history_processor import HistoryProcessor
from services.llm_service import LLMService
from services.note_manager import NoteManager
from services.rag_service import RAGService
from bot.history_processor import HistoryProcessor


class MessageHandler:
    """消息处理器"""
    
    def __init__(self, config: Dict[str, Any], llm_service: LLMService,
                 note_manager: NoteManager, content_extractor: ContentExtractor, 
                 rag_service: Optional[RAGService] = None):
        self.config = config
        self.llm_service = llm_service
        self.note_manager = note_manager
        self.rag_service = rag_service
        self.content_extractor = content_extractor # 接收注入的实例
        self.channel = None  # 将在启动后通过set_channel注入

        # 通道特定配置
        channel_type = self.config.get('channel_type', 'js_wechaty')
        self.channel_config = self.config.get(channel_type, {})

        # 初始化白名单
        self.group_id_white_list = set(self.channel_config.get('group_id_white_list', []))
        self.group_name_white_list = set(self.channel_config.get('group_name_white_list', []))
        self.user_id_white_list = set(self.channel_config.get('user_id_white_list', []))
        self.admin_list = set(self.config.get('system', {}).get('admin_list', []))
        self.whitelist_file = Path(self.config.get('system', {}).get('whitelist_file', 'config/group_whitelist.json'))
        self._load_whitelist()

        # 注入对自身的引用到 content_extractor
        self.content_extractor.set_message_handler(self)

        # 历史处理器将在set_channel中初始化
        self.history_processor = None

        # 初始化消息存储
        db_path = self.config.get('system', {}).get('message_db_path', 'data/messages.db')
        self.message_storage = MessageStorage(db_path)

        # 首次启动时清理一次旧消息
        retention_days = self.config.get('system', {}).get('message_retention_days', 30)
        if retention_days > 0:
            self.message_storage.cleanup_old_messages(retention_days)

        # 记录已处理历史消息的群组，防止重复处理
        self.processed_history_groups = set()
    
    async def handle(self, context: Context) -> Optional[Reply]:
        """消息处理总入口"""
        if context.type == "TEXT":
            return await self.handle_text_message(context)
        elif context.type == "SHARING":
            return await self.handle_sharing_message(context)
        else:
            logger.debug(f"收到不支持的消息类型，已跳过: {context.type}")
            return None

    def set_channel(self, channel: Any):
        """设置消息通道实例，并完成依赖注入"""
        self.channel = channel
        # 此时channel可用，初始化历史处理器
        self.history_processor = HistoryProcessor(channel=self.channel, config=self.config)
        self.history_processor.set_message_handler(self)
    
    def _load_whitelist(self):
        """从文件加载白名单，优先使用ID"""
        try:
            if self.whitelist_file.exists():
                with self.whitelist_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 兼容新旧两种格式
                    if isinstance(data, list) and data and isinstance(data[0], str) and "@chatroom" in data[0]:
                        self.group_id_white_list = set(data)
                        logger.info(f"成功从白名单文件加载 {len(self.group_id_white_list)} 个群组ID。")
                    elif isinstance(data, list): # 旧的按名字的列表
                        self.group_name_white_list.update(data)
                        logger.warning("检测到旧版按群名配置的白名单，建议使用 #here 指令更新为ID格式。")
        except Exception as e:
            logger.error(f"加载白名单时出错: {e}", exc_info=True)
    
    def contains_link(self, text: str) -> bool:
        """
        检测文本中是否包含链接，能够解析微信消息中的XML内容。
        
        Args:
            text: 文本内容，可能为纯文本或XML格式字符串
            
        Returns:
            是否包含链接
        """
        if not text:
            return False

        # 1. 移除引用消息，避免重复处理或错误解析
        text_no_refer = re.sub(r'<refermsg>.*?</refermsg>', '', text, flags=re.DOTALL)
        
        # 2. 检查XML中的常见链接标签
        # 匹配 <url>...</url> 或 <title>...</title> 中包含的链接
        xml_link_pattern = r'<(?:url|title)>(?:<!\[CDATA\[)?(https?://\S+)(?:\]\]>)?</(?:url|title)>'
        if re.search(xml_link_pattern, text_no_refer):
            return True
            
        # 3. 检查纯文本中的链接
        plain_link_pattern = r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        if re.search(plain_link_pattern, text_no_refer):
            return True

        return False
    
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
        """处理文本消息的总入口"""
        try:
            # 0. 统一保存消息
            self.save_message_from_context(context)

            # 1. 优先处理管理员命令
            if context.content.startswith("#") and self._is_admin(context.user_id):
                reply_text = await self._handle_admin_command(context.content, context)
                if reply_text:
                    return Reply(ReplyType.TEXT, reply_text)
                return None # 管理员命令如果无回复，则直接结束

            # 2. 根据是群聊还是私聊，走不同逻辑
            if context.is_group:
                return await self._handle_group_message(context)
            else:
                return await self._handle_single_message(context)

        except Exception as e:
            logger.error(f"处理文本消息时出错: {e}", exc_info=True)
            return Reply(ReplyType.ERROR, "抱歉，处理您的消息时出现了错误。")

    async def _handle_text_link_message(self, context: Context):
        """专门处理白名单群聊中的纯文本链接"""
        if not context.is_group or not self._is_in_whitelist(context):
            return
        
        if self.contains_link(context.content):
            logger.debug(f"在群聊 '{context.group_name}' 中发现纯文本链接，触发内容提取。")
            # 历史消息在这里被处理，直接提取内容，无需保存
            if not context.kwargs.get('is_historical'):
                self.save_message_from_context(context)
            await self._extract_content(context)

    async def _handle_group_message(self, context: Context) -> Optional[Reply]:
        """处理群聊消息 - 仅负责聊天回复"""
        # 1. 检查白名单
        if not self._is_in_whitelist(context):
            return None

        # 2. 聊天回复逻辑 (需要@机器人)
        if self.config.get('bot_name') in context.content:
            logger.debug(f"在群聊 '{context.group_name}' 中被@，进入聊天回复逻辑。")
            reply_text = await self._generate_reply(context)
            if reply_text:
                return Reply(ReplyType.TEXT, reply_text)
        
        return None

    async def _handle_single_message(self, context: Context) -> Optional[Reply]:
        """处理私聊消息"""
        # 检查是否在私聊白名单中
        if self.user_id_white_list and context.user_id not in self.user_id_white_list:
             logger.info(f"用户 {context.nick_name} ({context.user_id}) 不在私聊白名单中，已忽略。")
             return None

        # 检查是否以指定前缀开头
        if not any(context.content.startswith(p) for p in self.channel_config.get('single_chat_prefix', [])):
            return None
        
        # 生成回复
        logger.info(f"收到来自 {context.nick_name} 的私聊消息: {context.content}")
        reply_text = await self._generate_reply(context)
        if reply_text:
            return Reply(ReplyType.TEXT, reply_text)
        return None

    async def handle_sharing_message(self, context: Context) -> Optional[Reply]:
        """
        处理分享消息
        
        Args:
            context: 消息上下文
            
        Returns:
            回复对象
        """
        # 兼容字典和对象两种形式
        if isinstance(context, dict):
            context = Context(**context)

        try:
            # 历史消息在此处被处理，在下游的 _extract_content 中再进行判断和保存
            # 此处不再重复保存，避免因上下文不完整导致错误
            if not context.kwargs.get('is_historical'):
                self.save_message_from_context(context)
            
            # 检查白名单
            if context.is_group and not self._is_in_whitelist(context):
                return None

            extraction_config = self.config.get('content_extraction', {})
            # 自动提取分享内容
            if extraction_config.get('auto_extract_enabled'):
                await self._extract_content(context, is_history=context.kwargs.get('is_historical', False))
                
                # 如果是静默模式，不回复
                if extraction_config.get('silent_mode', True):
                    return None
                else:
                    return Reply(ReplyType.TEXT, "正在为您提取内容，请稍候...")
            
            return None
            
        except Exception as e:
            logger.error(f"处理分享消息时出错: {e}", exc_info=True)
            return None
    
    async def handle_historical_message(self, current_msg: Dict[str, Any], batch_context: List[Dict[str, Any]], current_index: int, group_name: str):
        """
        专门处理历史消息，上下文从批次中构建。
        """
        logger.debug(f"正在处理来自 '{group_name}' 的历史消息，创建时间: {datetime.fromtimestamp(current_msg['create_time'])}")
        
        # 1. 在批次内构建上下文
        context_messages = self._get_context_from_batch(current_msg, batch_context, current_index)
        
        # 2. 构造一个临时的Context对象用于内容提取
        temp_context = Context(
            type="SHARING", # 历史消息统一视为分享类型
            is_group=True,
            content=current_msg.get('content', ''),
            user_id=current_msg.get('sender_id', 'unknown'),
            nick_name=current_msg.get('from_user_name', '未知'),
            room_id=current_msg.get('room_id', ''),
            group_name=group_name,
            msg=current_msg
        )

        # 3. 调用核心提取逻辑，并传入预处理好的上下文
        await self._extract_content(temp_context, is_history=True, predefined_context=context_messages)

    def _get_context_from_batch(self, current_msg: Dict[str, Any], batch_context: List[Dict[str, Any]], current_index: int) -> List[Dict[str, Any]]:
        """从一个消息批次中，为当前消息提取时间窗口内的上下文"""
        context_messages = []
        current_time = current_msg['create_time']
        
        # 针对历史消息使用更长的时间窗口
        extraction_config = self.config.get('content_extraction', {})
        window_seconds = extraction_config.get('history_context_time_window', 300)
        
        # 向前查找
        for i in range(current_index - 1, -1, -1):
            prev_msg = batch_context[i]
            time_diff = current_time - prev_msg['create_time']
            logger.debug(f"  [向前检查] 当前消息时间: {current_time}, 上一条消息时间: {prev_msg['create_time']}, 时间差: {time_diff}s (窗口: {window_seconds}s)")
            if time_diff <= window_seconds:
                context_messages.insert(0, prev_msg)
            else:
                break
        
        # 向后查找
        for i in range(current_index + 1, len(batch_context)):
            next_msg = batch_context[i]
            time_diff = next_msg['create_time'] - current_time
            logger.debug(f"  [向后检查] 当前消息时间: {current_time}, 下一条消息时间: {next_msg['create_time']}, 时间差: {time_diff}s (窗口: {window_seconds}s)")
            if time_diff <= window_seconds:
                context_messages.append(next_msg)
            else:
                break
        
        # 修正: 使用 'msg_id' (小写) 来兼容从数据库获取的历史消息
        msg_identifier = current_msg.get('msg_id', current_msg.get('MsgId', '未知ID'))
        logger.info(f"为历史消息 {msg_identifier} 构建了包含 {len(context_messages)} 条消息的批内上下文。")
        return context_messages

    async def _extract_content(self, context: Context, is_history: bool = False, predefined_context: Optional[List[Dict[str, Any]]] = None):
        """
        提取内容
        
        Args:
            context: 消息上下文
            is_history: 是否为历史消息
            predefined_context: 预定义的上下文消息
        """
        logger.info(f"--- 开始内容提取流程 (群聊: {context.group_name}, 历史消息: {is_history}) ---")
        try:
            context_messages = []
            # 如果是历史消息且有预定义上下文，则使用它
            if is_history and predefined_context is not None:
                context_messages = predefined_context
            # 否则，如果是实时消息，从数据库获取
            elif not is_history:
                extraction_config = self.config.get('content_extraction', {})
                context_window = extraction_config.get('context_time_window', 60)
                context_messages = self._get_context_messages(
                    int(time.time()),
                    context_window,
                    group_name=context.group_name if context.is_group else None
                )
            
            # 构造消息对象供提取器使用
            msg = {
                'Text': context.content,
                'Type': context.type,
                'CreateTime': context.msg.get('create_time') if is_history else int(time.time()),
                'User': {'NickName': context.nick_name}
            }
            
            # 提取内容
            extracted_content = await self.content_extractor.extract(
                msg,
                context_messages
            )
            
            if not extracted_content:
                logger.info("内容提取器未能从消息中提取到有效内容。")
                return # 提取失败，直接返回

            # 添加群组信息和历史标志
            extracted_content['group_name'] = context.group_name if context.is_group else ''
            extracted_content['is_history'] = is_history
            
            # 保存到笔记
            logger.info("内容提取成功，准备保存到笔记...")
            await self.note_manager.save_content(extracted_content)
            
            # 如果配置了RAG，更新向量数据库
            if self.rag_service:
                await self.rag_service.add_document(extracted_content)

            # 只有在所有步骤都成功后才记录成功日志
            log_title = extracted_content.get('structured_note', {}).get('title', '未知标题')
            logger.info(f"--- 内容提取与保存流程全部成功: {log_title} ---")
                    
        except Exception as e:
            logger.error(f"在 _extract_content 执行期间发生致命错误: {e}", exc_info=True)
    
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
        logger.info(f"从数据库获取 {group_name or '私聊'} 在时间戳 {target_time} 前后 {window_seconds} 秒的上下文。")
        results = self.message_storage.get_messages_in_time_window(
            target_time=target_time,
            window_seconds=window_seconds,
            group_name=group_name
        )
        logger.info(f"获取到 {len(results)} 条消息 (时间窗口: {window_seconds}秒)")
        return results
    
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
    
    async def check_and_process_history_on_startup(self):
        """启动时检查白名单并处理历史消息"""
        logger.info("启动时检查群组白名单，准备处理历史消息...")
        if not self.history_processor or self.config.get('channel_type') != 'mac_wechat':
            logger.info("历史消息自动处理功能仅在'mac_wechat'通道下可用。")
            return

        # 从配置中获取白名单群组名称
        group_names_to_process = self.group_name_white_list
        if not group_names_to_process:
            logger.info("群组白名单为空，无需处理历史消息。")
            return

        logger.info(f"配置的白名单群组: {list(group_names_to_process)}")
        
        # 获取所有可用的群聊信息
        all_groups = [c for c in self.channel.service.get_contacts() if c.get('type') == 'group']
        all_group_names = {g['nickname']: g['user_id'] for g in all_groups}
        
        for group_name in group_names_to_process:
            if group_name in all_group_names:
                group_id = all_group_names[group_name]
                logger.info(f"✅ 找到白名单群组: '{group_name}' (ID: {group_id})")
                
                # 动态地将解析出的ID添加到ID白名单中，以便后续检查
                self.group_id_white_list.add(group_id)
                
                # 获取待处理消息数量
                new_messages_count = await self.history_processor.get_new_history_count_by_id(group_id)
                logger.info(f"   -> 发现 {new_messages_count} 条新的历史消息待处理。")

                if new_messages_count > 0:
                    try:
                        await self.history_processor.process_group_history_by_id(group_id, group_name)
                    except Exception as e:
                        logger.error(f"处理群组 '{group_name}' 历史消息时失败: {e}", exc_info=True)
            else:
                logger.warning(f"❌ 未在您的微信联系人中找到名为 '{group_name}' 的白名单群组，请检查名称是否完全匹配。")

    def _save_whitelist(self):
        """保存白名单到文件"""
        try:
            with self.whitelist_file.open('w', encoding='utf-8') as f:
                json.dump(list(self.group_id_white_list), f, indent=4)
        except Exception as e:
            logger.error(f"保存白名单时出错: {e}", exc_info=True)

    def _is_in_whitelist(self, context: Context) -> bool:
        """检查消息是否来自白名单群组（ID优先）"""
        if context.room_id in self.group_id_white_list:
            return True
        if context.group_name in self.group_name_white_list:
            # 只有在ID列表为空，且名字匹配时才警告，避免历史消息处理时出现
            if not self.group_id_white_list:
                 logger.warning(f"群组 '{context.group_name}' 通过名称匹配，建议在群内使用 #here 指令更新为ID匹配，以提高可靠性。")
            return True
        return False

    def _is_admin(self, user_id: str) -> bool:
        """检查用户是否为管理员"""
        return user_id in self.admin_list

    async def _handle_admin_command(self, content: str, context: Context) -> Optional[str]:
        if not self._is_admin(context.user_id):
            return "您没有权限执行此操作。"

        parts = content.strip().split()
        command = parts[0].lower()

        if command == "#add_group" and len(parts) > 1:
            group_name = " ".join(parts[1:])
            if group_name not in self.group_name_white_list:
                self.group_name_white_list.add(group_name)
                self._save_whitelist()
                logger.info(f"管理员 '{context.nick_name}' 添加群组 '{group_name}' 到白名单")

                # 异步触发历史消息处理
                if self.history_processor and self.config.get('channel_type') == 'mac_wechat':
                    logger.info(f"即将为新群组 '{group_name}' 处理历史消息...")
                    asyncio.create_task(self.history_processor.process_group_history(group_name))

                return f"群组 '{group_name}' 已添加到白名单。"
            return f"群组 '{group_name}' 已在白名单中。"

        elif command == "#remove_group" and len(parts) > 1:
            group_name = " ".join(parts[1:])
            if group_name in self.group_name_white_list:
                self.group_name_white_list.remove(group_name)
                self._save_whitelist()
                logger.info(f"管理员 '{context.nick_name}' 移除群组 '{group_name}' 从白名单")
                return f"群组 '{group_name}' 已从白名单中移除。"
            return f"群组 '{group_name}' 不在白名单中。"

        return "无效的命令。请使用 #add_group <群组名> 或 #remove_group <群组名> 来管理群组白名单。" 