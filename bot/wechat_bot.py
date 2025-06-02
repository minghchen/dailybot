#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微信机器人主类
负责处理微信消息的接收、分发和回复
"""

import time
import asyncio
import json
from typing import Dict, Any, Optional, List, Set
from loguru import logger
import itchat
from itchat.content import TEXT, SHARING, PICTURE, VIDEO, ATTACHMENT

from bot.message_handler import MessageHandler
from bot.history_processor import HistoryProcessor
from utils.message_queue import MessageQueue


class WeChatBot:
    """微信机器人主类"""
    
    def __init__(self, config: Dict[str, Any], llm_service, note_manager, rag_service):
        """
        初始化微信机器人
        
        Args:
            config: 配置信息
            llm_service: LLM服务实例
            note_manager: 笔记管理器实例
            rag_service: RAG服务实例
        """
        self.config = config
        self.wechat_config = config['wechat']
        self.llm_service = llm_service
        self.note_manager = note_manager
        self.rag_service = rag_service
        
        # 消息队列
        self.message_queue = MessageQueue(
            max_size=config['system']['message_queue_size']
        )
        
        # 消息处理器
        self.message_handler = MessageHandler(
            config=config,
            llm_service=llm_service,
            note_manager=note_manager,
            rag_service=rag_service,
            message_queue=self.message_queue
        )
        
        # 历史消息处理器
        self.history_processor = HistoryProcessor(
            message_handler=self.message_handler,
            config=config
        )
        
        # 运行状态
        self.running = False
        self.logged_in = False
        
        # 群组白名单（使用集合提高查询效率）
        self.group_white_list: Set[str] = set(self.wechat_config.get('group_name_white_list', []))
        self.processed_groups: Set[str] = set()  # 已处理历史消息的群组
        
        # 白名单配置文件路径
        self.whitelist_file = config.get('system', {}).get('whitelist_file', 'config/group_whitelist.json')
        self._load_whitelist()
        
    def _load_whitelist(self):
        """从文件加载群组白名单"""
        try:
            import os
            if os.path.exists(self.whitelist_file):
                with open(self.whitelist_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.group_white_list = set(data.get('groups', []))
                    self.processed_groups = set(data.get('processed', []))
                    logger.info(f"加载群组白名单: {len(self.group_white_list)} 个群组")
        except Exception as e:
            logger.warning(f"加载群组白名单失败: {e}")
    
    def _save_whitelist(self):
        """保存群组白名单到文件"""
        try:
            import os
            os.makedirs(os.path.dirname(self.whitelist_file), exist_ok=True)
            with open(self.whitelist_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'groups': list(self.group_white_list),
                    'processed': list(self.processed_groups)
                }, f, ensure_ascii=False, indent=2)
            logger.info("群组白名单已保存")
        except Exception as e:
            logger.error(f"保存群组白名单失败: {e}")
    
    async def add_group_to_whitelist(self, group_name: str):
        """
        添加群组到白名单并处理历史消息
        
        Args:
            group_name: 群组名称
        """
        if group_name not in self.group_white_list:
            self.group_white_list.add(group_name)
            self._save_whitelist()
            logger.info(f"群组 '{group_name}' 已添加到白名单")
            
            # 如果这个群组还没有处理过历史消息，开始处理
            if group_name not in self.processed_groups:
                await self._process_group_history(group_name)
    
    async def remove_group_from_whitelist(self, group_name: str):
        """
        从白名单移除群组
        
        Args:
            group_name: 群组名称
        """
        if group_name in self.group_white_list:
            self.group_white_list.remove(group_name)
            self._save_whitelist()
            logger.info(f"群组 '{group_name}' 已从白名单移除")
    
    async def _process_group_history(self, group_name: str):
        """
        处理群组的历史消息
        
        Args:
            group_name: 群组名称
        """
        try:
            logger.info(f"开始处理群组 '{group_name}' 的历史消息...")
            
            # 获取群组对象
            groups = itchat.search_chatrooms(name=group_name)
            if not groups:
                logger.warning(f"未找到群组: {group_name}")
                return
            
            group = groups[0]
            group_username = group['UserName']
            
            # 使用历史处理器处理历史消息
            processed_count = await self.history_processor.process_group_history(
                group_name=group_name,
                group_username=group_username
            )
            
            # 标记该群组已处理
            if processed_count > 0:
                self.processed_groups.add(group_name)
                self._save_whitelist()
            
        except Exception as e:
            logger.error(f"处理群组历史消息失败: {e}", exc_info=True)
        
    def _is_bot_triggered(self, msg: Dict[str, Any], is_group: bool) -> bool:
        """
        判断是否触发机器人
        
        Args:
            msg: 消息对象
            is_group: 是否是群聊消息
            
        Returns:
            是否触发机器人
        """
        text = msg.get('Text', '').strip()
        
        if is_group:
            # 群聊中被@
            if msg.get('IsAt', False):
                return True
            # 群聊前缀触发
            for prefix in self.wechat_config['group_chat_prefix']:
                if text.startswith(prefix):
                    return True
        else:
            # 私聊前缀触发
            for prefix in self.wechat_config['single_chat_prefix']:
                if text.startswith(prefix):
                    return True
                    
        return False
    
    def _check_white_list(self, msg: Dict[str, Any], is_group: bool) -> bool:
        """
        检查白名单
        
        Args:
            msg: 消息对象
            is_group: 是否是群聊
            
        Returns:
            是否在白名单中
        """
        if is_group:
            # 检查群白名单
            group_name = msg['User'].get('NickName', '')
            
            # 如果是ALL_GROUP，接受所有群
            if 'ALL_GROUP' in self.group_white_list:
                return True
            
            # 检查特定群名
            return group_name in self.group_white_list
        else:
            # 检查用户黑名单
            user_name = msg['User'].get('NickName', '')
            black_list = self.wechat_config.get('nick_name_black_list', [])
            return user_name not in black_list
    
    @itchat.msg_register([TEXT, SHARING])
    def handle_text_msg(self, msg: Dict[str, Any]):
        """处理文本和分享消息"""
        try:
            # 判断是否是群聊
            is_group = msg['FromUserName'].startswith('@@')
            
            # 检查是否是管理命令
            if self._handle_admin_command(msg, is_group):
                return
            
            # 检查白名单
            if not self._check_white_list(msg, is_group):
                return
            
            # 判断是否需要自动提取内容（有链接的消息）
            if self.config['content_extraction']['auto_extract_enabled']:
                # 检测消息中是否包含链接
                if self.message_handler.contains_link(msg['Text']) or msg['Type'] == 'Sharing':
                    # 加入消息队列等待处理
                    self.message_queue.put({
                        'msg': msg,
                        'is_group': is_group,
                        'type': 'extract',
                        'timestamp': time.time()
                    })
                    # 静默模式下不回复
                    if self.config['content_extraction']['silent_mode']:
                        return
            
            # 判断是否触发机器人回复
            if self._is_bot_triggered(msg, is_group):
                # 加入消息队列等待处理
                self.message_queue.put({
                    'msg': msg,
                    'is_group': is_group,
                    'type': 'reply',
                    'timestamp': time.time()
                })
                
        except Exception as e:
            logger.error(f"处理文本消息时出错: {e}", exc_info=True)
    
    def _handle_admin_command(self, msg: Dict[str, Any], is_group: bool) -> bool:
        """
        处理管理命令
        
        Args:
            msg: 消息对象
            is_group: 是否是群聊
            
        Returns:
            是否处理了管理命令
        """
        text = msg.get('Text', '').strip()
        
        # 只在私聊中处理管理命令
        if is_group:
            return False
        
        # 检查是否是管理员（可以通过配置文件设置管理员列表）
        admin_list = self.config.get('system', {}).get('admin_list', [])
        sender = msg['User'].get('NickName', '')
        
        if sender not in admin_list and admin_list:  # 如果配置了管理员列表但发送者不在其中
            return False
        
        # 添加群组到白名单
        if text.startswith('#add_group '):
            group_name = text[11:].strip()
            if group_name:
                asyncio.create_task(self.add_group_to_whitelist(group_name))
                itchat.send(f"群组 '{group_name}' 已添加到白名单，正在处理历史消息...", toUserName=msg['FromUserName'])
                return True
        
        # 从白名单移除群组
        elif text.startswith('#remove_group '):
            group_name = text[14:].strip()
            if group_name:
                asyncio.create_task(self.remove_group_from_whitelist(group_name))
                itchat.send(f"群组 '{group_name}' 已从白名单移除", toUserName=msg['FromUserName'])
                return True
        
        # 显示白名单
        elif text == '#list_groups':
            groups = list(self.group_white_list)
            if groups:
                response = "当前白名单群组：\n" + "\n".join(f"- {g}" for g in sorted(groups))
            else:
                response = "白名单为空"
            itchat.send(response, toUserName=msg['FromUserName'])
            return True
        
        # 导入聊天记录
        elif text.startswith('#import_history '):
            parts = text[16:].strip().split(' ', 1)
            if len(parts) == 2:
                file_path, group_name = parts
                asyncio.create_task(self._import_history(file_path, group_name, msg['FromUserName']))
                return True
        
        return False
    
    async def _import_history(self, file_path: str, group_name: str, reply_to: str):
        """导入聊天记录"""
        try:
            itchat.send(f"开始导入聊天记录: {file_path}", toUserName=reply_to)
            
            processed_count = await self.history_processor.process_exported_history(
                export_file=file_path,
                group_name=group_name
            )
            
            itchat.send(f"导入完成，共处理 {processed_count} 条包含链接的消息", toUserName=reply_to)
            
        except Exception as e:
            logger.error(f"导入聊天记录失败: {e}", exc_info=True)
            itchat.send(f"导入失败: {str(e)}", toUserName=reply_to)
    
    @itchat.msg_register([PICTURE, VIDEO, ATTACHMENT])
    def handle_media_msg(self, msg: Dict[str, Any]):
        """处理媒体消息"""
        try:
            # 判断是否是群聊
            is_group = msg['FromUserName'].startswith('@@')
            
            # 检查白名单
            if not self._check_white_list(msg, is_group):
                return
            
            # 媒体文件暂时只记录，不处理
            logger.info(f"收到媒体消息: {msg['Type']} from {msg['User']['NickName']}")
            
        except Exception as e:
            logger.error(f"处理媒体消息时出错: {e}", exc_info=True)
    
    def login_callback(self):
        """登录成功回调"""
        self.logged_in = True
        logger.info("微信登录成功")
        logger.info("="*50)
        logger.info("DailyBot 已启动，等待消息...")
        logger.info("="*50)
        
        # 登录成功后，检查是否有新的群组需要处理历史消息
        asyncio.create_task(self._check_pending_groups())
    
    async def _check_pending_groups(self):
        """检查是否有待处理的群组"""
        try:
            for group_name in self.group_white_list:
                if group_name not in self.processed_groups and group_name != 'ALL_GROUP':
                    await self._process_group_history(group_name)
        except Exception as e:
            logger.error(f"检查待处理群组时出错: {e}", exc_info=True)
    
    def logout_callback(self):
        """登出回调"""
        self.logged_in = False
        logger.info("微信已登出")
    
    async def start(self):
        """启动微信机器人"""
        try:
            # 启动消息处理线程
            asyncio.create_task(self.message_handler.start())
            
            # 配置itchat
            itchat.auto_login(
                hotReload=True,
                statusStorageDir='wechat.pkl',
                loginCallback=self.login_callback,
                exitCallback=self.logout_callback
            )
            
            # 启动itchat（阻塞运行）
            self.running = True
            itchat.run()
            
        except Exception as e:
            logger.error(f"微信机器人启动失败: {e}", exc_info=True)
            raise
        
    def stop(self):
        """停止微信机器人"""
        logger.info("正在停止微信机器人...")
        self.running = False
        self.message_handler.stop()
        itchat.logout()
        logger.info("微信机器人已停止") 