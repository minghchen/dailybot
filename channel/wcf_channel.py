#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
WeChat-Ferry Channel - 基于wcf的实现
仅支持Windows环境，需要特定版本的微信PC客户端
参考：https://github.com/lich0821/WeChatFerry
"""

import os
import sys
import time
import threading
from typing import Dict, Any, Optional, List
from datetime import datetime
from loguru import logger
from queue import Queue, Empty

# 检查操作系统
if sys.platform != 'win32':
    logger.error("WeChat-Ferry仅支持Windows系统")
    raise ImportError("WeChat-Ferry only supports Windows")

try:
    from wcferry import Wcf, WxMsg
    WCF_AVAILABLE = True
except ImportError as e:
    logger.warning(f"wcferry导入失败: {e}")
    logger.warning("请确保已安装wcferry: pip install wcferry")
    WCF_AVAILABLE = False
    # 定义占位类
    class Wcf: pass
    class WxMsg: pass

from channel.channel import Channel, Context, Reply, ReplyType


class WcfChannel(Channel):
    """
    WeChat-Ferry (wcf) 微信消息通道
    基于Windows Hook技术实现
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化wcf通道"""
        super().__init__(config)
        self.wcf_config = config.get('wcf', {})
        
        # wcf实例
        self.wcf: Optional[Wcf] = None
        self.running = False
        self.bot_wxid = None
        self.bot_info = None
        
        # 消息处理线程
        self.msg_thread = None
        
        # 群组白名单管理
        self.group_white_list = set(self.wcf_config.get('group_name_white_list', []))
        
        # 联系人缓存
        self.contacts_cache = {}
        self.last_cache_update = 0
        self.cache_ttl = 300  # 5分钟缓存
        
        if not WCF_AVAILABLE:
            logger.error("wcferry未正确安装，wcf通道功能将受限")
    
    def _update_contacts_cache(self):
        """更新联系人缓存"""
        try:
            current_time = time.time()
            if current_time - self.last_cache_update > self.cache_ttl:
                contacts = self.wcf.get_contacts()
                self.contacts_cache = {c['wxid']: c for c in contacts}
                self.last_cache_update = current_time
                logger.debug(f"更新联系人缓存，共 {len(self.contacts_cache)} 个联系人")
        except Exception as e:
            logger.error(f"更新联系人缓存失败: {e}")
    
    def _get_contact_name(self, wxid: str) -> str:
        """获取联系人名称"""
        self._update_contacts_cache()
        contact = self.contacts_cache.get(wxid, {})
        return contact.get('name', wxid)
    
    def _get_room_name(self, room_id: str) -> str:
        """获取群名称"""
        self._update_contacts_cache()
        room = self.contacts_cache.get(room_id, {})
        return room.get('name', room_id)
    
    def process_message(self, msg: WxMsg):
        """处理接收到的消息"""
        try:
            # 构建消息上下文
            context = self._build_context(msg)
            if not context:
                return
            
            # 检查白名单
            if not self.check_white_list(context):
                return
            
            # 检查是否触发机器人
            if not self._should_handle(context):
                return
            
            # 处理消息
            self.handle(context)
            
        except Exception as e:
            logger.error(f"处理消息时出错: {e}", exc_info=True)
    
    def _build_context(self, msg: WxMsg) -> Optional[Context]:
        """构建消息上下文"""
        try:
            # 获取消息类型
            msg_type = self._get_msg_type(msg.type)
            
            # 获取消息内容
            content = msg.content
            
            # 判断是否为群消息
            is_group = bool(msg.roomid)
            
            # 获取发送者信息
            sender_id = msg.sender
            sender_name = self._get_contact_name(sender_id)
            
            # 获取群信息
            group_id = msg.roomid if is_group else ''
            group_name = self._get_room_name(group_id) if is_group else ''
            
            # 检查是否被@
            is_at = False
            if is_group and self.bot_wxid:
                # 简单判断是否包含@机器人
                is_at = f"@{self.bot_info.get('name', '')}" in content if self.bot_info else False
            
            context = Context(
                msg_type=msg_type,
                content=content,
                msg=msg,
                is_group=is_group,
                nick_name=sender_name,
                user_id=sender_id,
                group_name=group_name,
                group_id=group_id,
                is_at=is_at
            )
            
            return context
            
        except Exception as e:
            logger.error(f"构建消息上下文失败: {e}", exc_info=True)
            return None
    
    def _get_msg_type(self, type_code: int) -> str:
        """转换消息类型"""
        type_map = {
            1: 'TEXT',      # 文本
            3: 'IMAGE',     # 图片
            34: 'VOICE',    # 语音
            43: 'VIDEO',    # 视频
            49: 'FILE',     # 文件
            47: 'EMOJI',    # 表情
            48: 'LOCATION', # 位置
        }
        return type_map.get(type_code, 'UNKNOWN')
    
    def _should_handle(self, context: Context) -> bool:
        """判断是否应该处理该消息"""
        # 不处理自己发送的消息
        if self.bot_wxid and context.user_id == self.bot_wxid:
            return False
        
        if context.is_group:
            # 群聊消息
            if context.is_at:
                # 被@了
                return True
            # 检查群聊前缀
            prefix_list = self.wcf_config.get('group_chat_prefix', [])
            matched, _ = self.check_prefix(context.content, prefix_list)
            return matched
        else:
            # 私聊消息
            prefix_list = self.wcf_config.get('single_chat_prefix', [])
            matched, _ = self.check_prefix(context.content, prefix_list)
            return matched
    
    def send(self, reply: Reply, context: Context):
        """发送回复消息"""
        try:
            if not self.wcf or not WCF_AVAILABLE:
                logger.error("wcf未初始化或不可用")
                return
            
            # 获取消息对象
            msg: WxMsg = context.msg
            receiver = msg.roomid if msg.roomid else msg.sender
            
            # 根据回复类型发送不同内容
            if reply.type == ReplyType.TEXT:
                # 如果是群消息且需要@发送者
                at_list = []
                if msg.roomid and self.wcf_config.get('group_at_sender', True):
                    at_list = [msg.sender]
                
                self.wcf.send_text(reply.content, receiver, at_list)
                
            elif reply.type == ReplyType.IMAGE:
                if isinstance(reply.content, str) and os.path.exists(reply.content):
                    self.wcf.send_image(reply.content, receiver)
                else:
                    logger.warning(f"图片文件不存在: {reply.content}")
                    
            elif reply.type == ReplyType.FILE:
                if isinstance(reply.content, str) and os.path.exists(reply.content):
                    self.wcf.send_file(reply.content, receiver)
                else:
                    logger.warning(f"文件不存在: {reply.content}")
                    
            else:
                logger.warning(f"不支持的回复类型: {reply.type}")
                
        except Exception as e:
            logger.error(f"发送消息失败: {e}", exc_info=True)
    
    def message_loop(self):
        """消息接收循环"""
        while self.running:
            try:
                msg = self.wcf.get_msg(timeout=1)
                if msg:
                    self.process_message(msg)
            except TimeoutError:
                continue
            except Exception as e:
                logger.error(f"消息循环出错: {e}", exc_info=True)
                time.sleep(1)
    
    def startup(self):
        """启动通道"""
        try:
            if not WCF_AVAILABLE:
                logger.error("wcferry未安装，无法启动wcf通道")
                logger.info("请运行: pip install wcferry")
                return
            
            logger.info("正在启动wcf...")
            
            # 创建wcf实例
            self.wcf = Wcf()
            
            # 检查登录状态
            if not self.wcf.is_login():
                logger.warning("微信未登录，请先登录微信PC客户端")
                # 获取二维码
                qrcode = self.wcf.get_qrcode()
                if qrcode:
                    logger.info(f"请扫描二维码登录: {qrcode}")
                # 等待登录
                while not self.wcf.is_login():
                    time.sleep(2)
            
            # 获取登录信息
            self.bot_info = self.wcf.get_user_info()
            self.bot_wxid = self.bot_info.get('wxid')
            logger.info(f"登录成功: {self.bot_info.get('name')} ({self.bot_wxid})")
            
            # 启用消息接收
            self.wcf.enable_receiving_msg()
            self.running = True
            
            # 启动消息处理线程
            self.msg_thread = threading.Thread(
                target=self.message_loop,
                daemon=True
            )
            self.msg_thread.start()
            
            logger.info("="*50)
            logger.info("DailyBot (wcf) 已启动，等待消息...")
            logger.info("="*50)
            
        except Exception as e:
            logger.error(f"启动wcf通道失败: {e}", exc_info=True)
            raise
    
    def shutdown(self):
        """关闭通道"""
        self.running = False
        if self.wcf and WCF_AVAILABLE:
            try:
                self.wcf.disable_recv_msg()
                self.wcf = None
            except:
                pass
        logger.info("wcf通道已关闭") 