#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
微信Channel - 基于wechaty的实现
使用wechaty替代itchat，提供更安全稳定的微信接入
支持 wechaty-puppet-service 远程连接
"""

import asyncio
import json
import os
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from loguru import logger

try:
    from wechaty import (
        Wechaty,
        Contact,
        Room,
        Message,
        FileBox,
        MessageType,
        ScanStatus,
        WechatyOptions
    )
    from wechaty_puppet import PuppetOptions
    WECHATY_AVAILABLE = True
except ImportError as e:
    logger.warning(f"Wechaty导入失败: {e}")
    logger.warning("请确保已安装wechaty: pip install wechaty wechaty-puppet-service")
    WECHATY_AVAILABLE = False
    # 定义占位类，避免代码报错
    class Wechaty: pass
    class Contact: pass
    class Room: pass
    class Message: pass
    class FileBox: pass
    class WechatyOptions: pass
    class PuppetOptions: pass
    class MessageType:
        MESSAGE_TYPE_TEXT = 1
        MESSAGE_TYPE_IMAGE = 2
        MESSAGE_TYPE_VOICE = 3
        MESSAGE_TYPE_VIDEO = 4
        MESSAGE_TYPE_ATTACHMENT = 5
        MESSAGE_TYPE_URL = 6
    class ScanStatus:
        Waiting = 0
        Scanned = 1
        Confirmed = 2

from channel.channel import Channel, Context, Reply, ReplyType


class WechatMessage:
    """微信消息包装类"""
    def __init__(self, msg: Message):
        self.msg = msg
        self.msg_id = getattr(msg, 'message_id', str(datetime.now().timestamp()))
        self.create_time = datetime.now()
        
    async def get_type(self) -> str:
        """获取消息类型"""
        if not WECHATY_AVAILABLE:
            return "TEXT"
            
        msg_type = self.msg.type()
        if msg_type == MessageType.MESSAGE_TYPE_TEXT:
            return "TEXT"
        elif msg_type == MessageType.MESSAGE_TYPE_IMAGE:
            return "IMAGE"
        elif msg_type == MessageType.MESSAGE_TYPE_VOICE:
            return "VOICE"
        elif msg_type == MessageType.MESSAGE_TYPE_VIDEO:
            return "VIDEO"
        elif msg_type == MessageType.MESSAGE_TYPE_ATTACHMENT:
            return "FILE"
        elif msg_type == MessageType.MESSAGE_TYPE_URL:
            return "SHARING"
        else:
            return "UNKNOWN"
    
    async def get_content(self) -> str:
        """获取消息内容"""
        if not WECHATY_AVAILABLE:
            return ""
        return self.msg.text()
    
    async def get_sender_info(self) -> Dict[str, str]:
        """获取发送者信息"""
        if not WECHATY_AVAILABLE:
            return {'id': '', 'name': '', 'alias': ''}
            
        talker = self.msg.talker()
        return {
            'id': talker.contact_id,
            'name': talker.name,
            'alias': await talker.alias() or talker.name
        }
    
    async def get_room_info(self) -> Optional[Dict[str, str]]:
        """获取群聊信息"""
        if not WECHATY_AVAILABLE:
            return None
            
        room = self.msg.room()
        if room:
            topic = await room.topic()
            return {
                'id': room.room_id,
                'name': topic
            }
        return None
    
    async def is_at(self, bot_contact: Contact) -> bool:
        """判断是否@机器人"""
        if not WECHATY_AVAILABLE:
            return False
            
        if self.msg.room():
            mention_list = await self.msg.mention_list()
            return bot_contact in mention_list
        return False


class WechatChannel(Channel):
    """
    微信消息通道
    基于wechaty实现，替代itchat
    支持 wechaty-puppet-service 远程连接
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化微信通道"""
        super().__init__(config)
        self.wechat_config = config.get('wechat', {})
        self.puppet_config = config.get('wechaty_puppet', {})
        self.bot: Optional[Wechaty] = None
        self.bot_contact: Optional[Contact] = None
        self.running = False
        
        # 群组白名单管理
        self.group_white_list = set(self.wechat_config.get('group_name_white_list', []))
        self.processed_groups = set()
        
        # 白名单配置文件
        self.whitelist_file = config.get('system', {}).get('whitelist_file', 'config/group_whitelist.json')
        self._load_whitelist()
        
        if not WECHATY_AVAILABLE:
            logger.error("Wechaty未正确安装，微信通道功能将受限")
    
    def _load_whitelist(self):
        """加载群组白名单"""
        try:
            if os.path.exists(self.whitelist_file):
                with open(self.whitelist_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.group_white_list = set(data.get('groups', []))
                    self.processed_groups = set(data.get('processed', []))
                    logger.info(f"加载群组白名单: {len(self.group_white_list)} 个群组")
        except Exception as e:
            logger.warning(f"加载群组白名单失败: {e}")
    
    def _save_whitelist(self):
        """保存群组白名单"""
        try:
            os.makedirs(os.path.dirname(self.whitelist_file), exist_ok=True)
            with open(self.whitelist_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'groups': list(self.group_white_list),
                    'processed': list(self.processed_groups)
                }, f, ensure_ascii=False, indent=2)
            logger.info("群组白名单已保存")
        except Exception as e:
            logger.error(f"保存群组白名单失败: {e}")
    
    def _get_puppet_options(self) -> Optional[PuppetOptions]:
        """获取 Puppet 配置选项"""
        if not WECHATY_AVAILABLE:
            return None
            
        # 优先从环境变量读取
        token = os.getenv('WECHATY_PUPPET_SERVICE_TOKEN') or self.puppet_config.get('token')
        endpoint = os.getenv('WECHATY_PUPPET_SERVICE_ENDPOINT') or self.puppet_config.get('endpoint')
        
        if token:
            logger.info("使用 wechaty-puppet-service 模式")
            logger.info(f"Token: {token[:10]}..." if token else "No token")
            logger.info(f"Endpoint: {endpoint}" if endpoint else "使用默认 endpoint")
            
            puppet_options = PuppetOptions()
            puppet_options.token = token
            if endpoint:
                puppet_options.endpoint = endpoint
            return puppet_options
        else:
            logger.info("使用本地 puppet 模式（可能不稳定）")
            return None
    
    async def on_message(self, msg: Message):
        """处理接收到的消息"""
        try:
            # 包装消息
            wechat_msg = WechatMessage(msg)
            
            # 构建消息上下文
            context = await self._build_context(wechat_msg)
            if not context:
                return
            
            # 检查白名单
            if not self.check_white_list(context):
                return
            
            # 检查是否触发机器人
            if not await self._should_handle(context):
                return
            
            # 处理消息
            self.handle(context)
            
        except Exception as e:
            logger.error(f"处理消息时出错: {e}", exc_info=True)
    
    async def _build_context(self, wechat_msg: WechatMessage) -> Optional[Context]:
        """构建消息上下文"""
        try:
            msg_type = await wechat_msg.get_type()
            content = await wechat_msg.get_content()
            sender_info = await wechat_msg.get_sender_info()
            room_info = await wechat_msg.get_room_info()
            is_group = room_info is not None
            
            # 检查是否被@
            is_at = False
            if is_group and self.bot_contact:
                is_at = await wechat_msg.is_at(self.bot_contact)
            
            context = Context(
                msg_type=msg_type,
                content=content,
                msg=wechat_msg,
                is_group=is_group,
                nick_name=sender_info['name'],
                user_id=sender_info['id'],
                group_name=room_info['name'] if room_info else '',
                group_id=room_info['id'] if room_info else '',
                is_at=is_at
            )
            
            return context
            
        except Exception as e:
            logger.error(f"构建消息上下文失败: {e}", exc_info=True)
            return None
    
    async def _should_handle(self, context: Context) -> bool:
        """判断是否应该处理该消息"""
        # 不处理自己发送的消息
        if self.bot_contact and context.user_id == self.bot_contact.contact_id:
            return False
        
        if context.is_group:
            # 群聊消息
            if context.is_at:
                # 被@了
                return True
            # 检查群聊前缀
            prefix_list = self.wechat_config.get('group_chat_prefix', [])
            matched, _ = self.check_prefix(context.content, prefix_list)
            return matched
        else:
            # 私聊消息
            prefix_list = self.wechat_config.get('single_chat_prefix', [])
            matched, _ = self.check_prefix(context.content, prefix_list)
            return matched
    
    async def on_scan(self, qr_code: str, status: ScanStatus):
        """处理扫码事件"""
        if status == ScanStatus.Waiting:
            logger.info(f"请扫描二维码登录")
            logger.info(f"二维码链接: {qr_code}")
            # 如果使用 puppet-service，可能不会显示二维码
            if self.puppet_config.get('token'):
                logger.info("提示：使用 puppet-service 时，请在对应的设备上查看二维码")
        elif status == ScanStatus.Scanned:
            logger.info("二维码已扫描，请在手机上确认登录")
        elif status == ScanStatus.Confirmed:
            logger.info("已确认登录")
    
    async def on_login(self, contact: Contact):
        """登录成功回调"""
        self.bot_contact = contact
        logger.info(f"登录成功: {contact.name}")
        logger.info("="*50)
        logger.info("DailyBot 已启动，等待消息...")
        logger.info("="*50)
    
    async def on_logout(self, contact: Contact):
        """登出回调"""
        logger.info(f"已登出: {contact.name}")
    
    def send(self, reply: Reply, context: Context):
        """发送回复消息"""
        asyncio.create_task(self._send_async(reply, context))
    
    async def _send_async(self, reply: Reply, context: Context):
        """异步发送消息"""
        try:
            if not self.bot or not WECHATY_AVAILABLE:
                logger.error("机器人未初始化或Wechaty不可用")
                return
            
            # 获取消息对象
            msg: Message = context.msg.msg
            
            # 根据回复类型发送不同内容
            if reply.type == ReplyType.TEXT:
                await msg.say(reply.content)
            elif reply.type == ReplyType.IMAGE:
                if isinstance(reply.content, str):
                    # 如果是文件路径
                    file_box = FileBox.from_file(reply.content)
                    await msg.say(file_box)
            elif reply.type == ReplyType.FILE:
                if isinstance(reply.content, str):
                    file_box = FileBox.from_file(reply.content)
                    await msg.say(file_box)
            else:
                logger.warning(f"不支持的回复类型: {reply.type}")
                
        except Exception as e:
            logger.error(f"发送消息失败: {e}", exc_info=True)
    
    async def startup_async(self):
        """异步启动"""
        try:
            if not WECHATY_AVAILABLE:
                logger.error("Wechaty未安装，无法启动微信通道")
                logger.info("请运行: pip install wechaty wechaty-puppet-service")
                return
            
            # 获取 puppet 配置
            puppet_options = self._get_puppet_options()
            
            # 创建 wechaty 选项
            options = WechatyOptions()
            options.name = 'DailyBot'
            if puppet_options:
                options.puppet_options = puppet_options
            
            # 创建wechaty实例
            self.bot = Wechaty(options)
            
            # 注册事件处理器
            self.bot.on('scan', self.on_scan)
            self.bot.on('login', self.on_login)
            self.bot.on('logout', self.on_logout)
            self.bot.on('message', self.on_message)
            
            # 启动机器人
            logger.info("正在启动 Wechaty...")
            await self.bot.start()
            self.running = True
            
        except Exception as e:
            logger.error(f"启动微信通道失败: {e}", exc_info=True)
            raise
    
    def startup(self):
        """启动通道"""
        # 在新的事件循环中启动
        asyncio.create_task(self.startup_async())
    
    def shutdown(self):
        """关闭通道"""
        self.running = False
        if self.bot and WECHATY_AVAILABLE:
            asyncio.create_task(self.bot.stop())
            logger.info("微信通道已关闭")
    
    async def add_group_to_whitelist(self, group_name: str):
        """添加群组到白名单"""
        if group_name not in self.group_white_list:
            self.group_white_list.add(group_name)
            self._save_whitelist()
            logger.info(f"群组 '{group_name}' 已添加到白名单")
    
    async def remove_group_from_whitelist(self, group_name: str):
        """从白名单移除群组"""
        if group_name in self.group_white_list:
            self.group_white_list.remove(group_name)
            self._save_whitelist()
            logger.info(f"群组 '{group_name}' 已从白名单移除") 