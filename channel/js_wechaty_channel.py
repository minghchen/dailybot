#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
JavaScript Wechaty Channel - 基于JS版wechaty的实现
通过WebSocket与JavaScript wechaty服务通信
参考：https://github.com/wangrongding/wechat-bot
"""

import asyncio
import json
import os
import time
from typing import Dict, Any, Optional, List
from datetime import datetime
from loguru import logger
import websocket
import threading
from queue import Queue, Empty
import random

from channel.channel import Channel, Context, Reply, ReplyType


class JSWechatyChannel(Channel):
    """
    JavaScript Wechaty微信消息通道
    通过WebSocket与JS wechaty服务通信
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化JS Wechaty通道"""
        super().__init__(config)
        self.wechaty_config = config.get('js_wechaty', {})
        
        # WebSocket配置
        self.ws_url = self.wechaty_config.get('ws_url', 'ws://localhost:8788')
        self.token = self.wechaty_config.get('token', '')
        self.reconnect_interval = self.wechaty_config.get('reconnect_interval', 5)
        
        # 连接状态
        self.ws = None
        self.connected = False
        self.running = False
        self.user_info = None
        
        # 消息队列
        self.message_queue = Queue()
        
        # 群组白名单管理
        self.group_white_list = set(self.wechaty_config.get('group_name_white_list', []))
        
        # 消息频率控制
        self.message_limiter = {}  # {user_id: {'count': 0, 'reset_time': timestamp}}
        self.message_limit_window = 60  # 60秒窗口
        self.message_limit_count = self.wechaty_config.get('message_limit_per_minute', 20)
        
        # 防封号配置
        self.anti_ban_config = {
            'min_reply_delay': self.wechaty_config.get('min_reply_delay', 2),  # 最小回复延迟（秒）
            'max_reply_delay': self.wechaty_config.get('max_reply_delay', 5),  # 最大回复延迟（秒）
            'working_hours': self.wechaty_config.get('working_hours', {
                'enabled': False,
                'start': 9,
                'end': 22
            })
        }
        
        logger.info("JS Wechaty通道初始化完成")
        
        # 检查是否使用安全的puppet
        if not os.environ.get('WECHATY_PUPPET_SERVICE_TOKEN'):
            logger.warning("⚠️ 警告：未检测到PUPPET TOKEN，可能使用的是免费web协议")
            logger.warning("⚠️ 免费协议存在较高封号风险，建议使用PadLocal等付费协议")
            logger.warning("⚠️ 详情请查看: https://github.com/padlocal/puppet-padlocal-getting-started")
    
    def on_ws_message(self, ws, message):
        """处理WebSocket消息"""
        try:
            data = json.loads(message)
            msg_type = data.get('type')
            
            if msg_type == 'login':
                self.user_info = data.get('user')
                logger.info(f"登录成功: {self.user_info.get('name')}")
                logger.info("="*50)
                logger.info("DailyBot (JS Wechaty) 已启动，等待消息...")
                logger.info("="*50)
                
            elif msg_type == 'message':
                # 将消息放入队列
                self.message_queue.put(data.get('payload'))
                
            elif msg_type == 'error':
                logger.error(f"收到错误消息: {data.get('error')}")
                
        except Exception as e:
            logger.error(f"处理WebSocket消息失败: {e}")
    
    def on_ws_error(self, ws, error):
        """处理WebSocket错误"""
        logger.error(f"WebSocket错误: {error}")
    
    def on_ws_close(self, ws):
        """处理WebSocket关闭"""
        self.connected = False
        logger.warning("WebSocket连接已关闭")
        
        # 尝试重连
        if self.running:
            time.sleep(self.reconnect_interval)
            self.connect()
    
    def on_ws_open(self, ws):
        """处理WebSocket连接打开"""
        self.connected = True
        logger.info("WebSocket连接已建立")
        
        # 发送认证信息
        if self.token:
            auth_msg = {
                'type': 'auth',
                'token': self.token
            }
            ws.send(json.dumps(auth_msg))
    
    def connect(self):
        """连接到JS Wechaty服务"""
        try:
            logger.info(f"正在连接到JS Wechaty服务: {self.ws_url}")
            
            self.ws = websocket.WebSocketApp(
                self.ws_url,
                on_message=self.on_ws_message,
                on_error=self.on_ws_error,
                on_close=self.on_ws_close,
                on_open=self.on_ws_open
            )
            
            # 在新线程中运行WebSocket
            ws_thread = threading.Thread(
                target=self.ws.run_forever,
                daemon=True
            )
            ws_thread.start()
            
        except Exception as e:
            logger.error(f"连接JS Wechaty服务失败: {e}")
            raise
    
    def process_messages(self):
        """处理消息队列"""
        while self.running:
            try:
                # 从队列获取消息
                msg_data = self.message_queue.get(timeout=1)
                
                # 构建消息上下文
                context = self._build_context(msg_data)
                if not context:
                    continue
                
                # 检查白名单
                if not self.check_white_list(context):
                    continue
                
                # 检查是否触发机器人
                if not self._should_handle(context):
                    continue
                
                # 处理消息
                self.handle(context)
                
            except Empty:
                continue
            except Exception as e:
                logger.error(f"处理消息时出错: {e}", exc_info=True)
    
    def _build_context(self, msg_data: Dict[str, Any]) -> Optional[Context]:
        """构建消息上下文"""
        try:
            msg_type = msg_data.get('type', 'text')
            content = msg_data.get('text', '')
            sender = msg_data.get('from', {})
            room = msg_data.get('room')
            is_group = room is not None
            
            # 检查是否被@
            is_at = False
            if is_group:
                mentions = msg_data.get('mentionList', [])
                if self.user_info:
                    is_at = self.user_info.get('id') in mentions
            
            # 映射消息类型
            if msg_type == 'text':
                msg_type = 'TEXT'
            elif msg_type == 'image':
                msg_type = 'IMAGE'
            elif msg_type == 'voice':
                msg_type = 'VOICE'
            elif msg_type == 'video':
                msg_type = 'VIDEO'
            elif msg_type == 'file':
                msg_type = 'FILE'
            else:
                msg_type = 'UNKNOWN'
            
            context = Context(
                msg_type=msg_type,
                content=content,
                msg=msg_data,
                is_group=is_group,
                nick_name=sender.get('name', ''),
                user_id=sender.get('id', ''),
                group_name=room.get('topic', '') if room else '',
                group_id=room.get('id', '') if room else '',
                is_at=is_at
            )
            
            return context
            
        except Exception as e:
            logger.error(f"构建消息上下文失败: {e}", exc_info=True)
            return None
    
    def _should_handle(self, context: Context) -> bool:
        """判断是否应该处理该消息"""
        # 不处理自己发送的消息
        if self.user_info and context.user_id == self.user_info.get('id'):
            return False
        
        # 检查工作时间
        if self.anti_ban_config['working_hours']['enabled']:
            current_hour = datetime.datetime.now().hour
            start_hour = self.anti_ban_config['working_hours']['start']
            end_hour = self.anti_ban_config['working_hours']['end']
            
            if not (start_hour <= current_hour < end_hour):
                logger.debug(f"非工作时间({current_hour}点)，跳过处理消息")
                return False
        
        # 检查消息频率限制
        if not self._check_rate_limit(context.user_id):
            logger.warning(f"用户 {context.nick_name} 消息频率超限")
            return False
        
        if context.is_group:
            # 群聊消息
            if context.is_at:
                # 被@了
                return True
            # 检查群聊前缀
            prefix_list = self.wechaty_config.get('group_chat_prefix', [])
            matched, _ = self.check_prefix(context.content, prefix_list)
            return matched
        else:
            # 私聊消息
            prefix_list = self.wechaty_config.get('single_chat_prefix', [])
            matched, _ = self.check_prefix(context.content, prefix_list)
            return matched
    
    def _check_rate_limit(self, user_id: str) -> bool:
        """检查用户消息频率"""
        now = time.time()
        
        if user_id not in self.message_limiter:
            self.message_limiter[user_id] = {
                'count': 0,
                'reset_time': now + self.message_limit_window
            }
        
        user_limit = self.message_limiter[user_id]
        
        # 重置计数器
        if now > user_limit['reset_time']:
            user_limit['count'] = 0
            user_limit['reset_time'] = now + self.message_limit_window
        
        # 检查是否超限
        if user_limit['count'] >= self.message_limit_count:
            return False
        
        user_limit['count'] += 1
        return True
    
    def send(self, reply: Reply, context: Context):
        """发送回复消息"""
        # 添加随机延迟，模拟人工回复
        delay = random.uniform(
            self.anti_ban_config['min_reply_delay'],
            self.anti_ban_config['max_reply_delay']
        )
        time.sleep(delay)
        
        try:
            if not self.ws or not self.connected:
                logger.error("WebSocket未连接")
                return
            
            # 构建发送消息
            msg = {
                'type': 'send',
                'payload': {
                    'to': context.group_id if context.is_group else context.user_id,
                    'type': 'text',
                    'content': reply.content
                }
            }
            
            # 根据回复类型调整消息
            if reply.type == ReplyType.IMAGE:
                msg['payload']['type'] = 'image'
                msg['payload']['url'] = reply.content
            elif reply.type == ReplyType.FILE:
                msg['payload']['type'] = 'file'
                msg['payload']['path'] = reply.content
            
            # 发送消息
            self.ws.send(json.dumps(msg))
            
        except Exception as e:
            logger.error(f"发送消息失败: {e}", exc_info=True)
    
    def startup(self):
        """启动通道"""
        try:
            self.running = True
            
            # 连接WebSocket
            self.connect()
            
            # 启动消息处理线程
            msg_thread = threading.Thread(
                target=self.process_messages,
                daemon=True
            )
            msg_thread.start()
            
            logger.info("JS Wechaty通道已启动")
            
        except Exception as e:
            logger.error(f"启动JS Wechaty通道失败: {e}")
            raise
    
    def shutdown(self):
        """关闭通道"""
        self.running = False
        if self.ws:
            self.ws.close()
        logger.info("JS Wechaty通道已关闭") 