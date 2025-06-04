#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Channel基类 - 定义消息通道的抽象接口
参考chatgpt-on-wechat项目的设计
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, Callable
from loguru import logger


class ReplyType:
    """回复类型枚举"""
    TEXT = "TEXT"
    VOICE = "VOICE"
    IMAGE = "IMAGE"
    FILE = "FILE"
    VIDEO = "VIDEO"
    INFO = "INFO"
    ERROR = "ERROR"


class Reply:
    """回复消息类"""
    def __init__(self, type: str = ReplyType.TEXT, content: Any = None):
        self.type = type
        self.content = content


class Context:
    """消息上下文"""
    def __init__(self, msg_type: str = None, content: Any = None, **kwargs):
        self.type = msg_type  # 消息类型
        self.content = content  # 消息内容
        self.msg = kwargs.get('msg')  # 原始消息对象
        self.is_group = kwargs.get('is_group', False)  # 是否群聊
        self.nick_name = kwargs.get('nick_name', '')  # 发送者昵称
        self.user_id = kwargs.get('user_id', '')  # 发送者ID
        self.group_name = kwargs.get('group_name', '')  # 群名称
        self.group_id = kwargs.get('group_id', '')  # 群ID
        self.is_at = kwargs.get('is_at', False)  # 是否被@
        self.reply = None  # 回复内容
        self.kwargs = kwargs  # 其他参数


class Channel(ABC):
    """
    消息通道基类
    定义了消息接收、处理、发送的标准接口
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化通道
        
        Args:
            config: 配置信息
        """
        self.config = config
        self.name = self.__class__.__name__
        self.handlers = {}  # 消息处理器
        
    @abstractmethod
    def startup(self):
        """
        启动通道
        子类需要实现具体的启动逻辑
        """
        pass
        
    @abstractmethod
    def shutdown(self):
        """
        关闭通道
        子类需要实现具体的关闭逻辑
        """
        pass
    
    def register_handler(self, msg_type: str, handler: Callable):
        """
        注册消息处理器
        
        Args:
            msg_type: 消息类型
            handler: 处理函数
        """
        self.handlers[msg_type] = handler
        logger.info(f"注册消息处理器: {msg_type} -> {handler.__name__}")
    
    def handle(self, context: Context):
        """
        处理消息
        
        Args:
            context: 消息上下文
        """
        try:
            # 查找对应的处理器
            handler = self.handlers.get(context.type)
            if handler:
                # 调用处理器
                reply = handler(context)
                if reply:
                    context.reply = reply
                    self.send(reply, context)
            else:
                logger.warning(f"未找到消息类型 {context.type} 的处理器")
                
        except Exception as e:
            logger.error(f"处理消息时出错: {e}", exc_info=True)
            # 发送错误回复
            error_reply = Reply(ReplyType.ERROR, f"处理消息时出错: {str(e)}")
            self.send(error_reply, context)
    
    @abstractmethod
    def send(self, reply: Reply, context: Context):
        """
        发送回复消息
        
        Args:
            reply: 回复内容
            context: 消息上下文
        """
        pass
    
    def build_context(self, msg: Any) -> Optional[Context]:
        """
        构建消息上下文
        子类可以重写此方法以适配不同的消息格式
        
        Args:
            msg: 原始消息对象
            
        Returns:
            消息上下文
        """
        return Context(msg=msg)
    
    def check_prefix(self, content: str, prefix_list: list) -> tuple:
        """
        检查消息前缀
        
        Args:
            content: 消息内容
            prefix_list: 前缀列表
            
        Returns:
            (是否匹配, 去除前缀后的内容)
        """
        if not prefix_list:
            return True, content
            
        for prefix in prefix_list:
            if content.startswith(prefix):
                return True, content[len(prefix):].strip()
                
        return False, content
    
    def check_white_list(self, context: Context) -> bool:
        """
        检查白名单
        
        Args:
            context: 消息上下文
            
        Returns:
            是否在白名单中
        """
        if context.is_group:
            # 群聊白名单检查
            group_white_list = self.config.get('group_name_white_list', [])
            if 'ALL_GROUP' in group_white_list:
                return True
            return context.group_name in group_white_list
        else:
            # 私聊黑名单检查
            black_list = self.config.get('nick_name_black_list', [])
            return context.nick_name not in black_list 