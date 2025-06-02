#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
消息队列
用于管理消息的异步处理
"""

import queue
import threading
from typing import Any, Optional
from loguru import logger


class MessageQueue:
    """线程安全的消息队列"""
    
    def __init__(self, max_size: int = 100):
        """
        初始化消息队列
        
        Args:
            max_size: 队列最大容量
        """
        self.queue = queue.Queue(maxsize=max_size)
        self.lock = threading.Lock()
        
    def put(self, item: Any, block: bool = True, timeout: Optional[float] = None):
        """
        向队列添加项目
        
        Args:
            item: 要添加的项目
            block: 是否阻塞
            timeout: 超时时间
        """
        try:
            self.queue.put(item, block=block, timeout=timeout)
            logger.debug(f"消息已加入队列，当前队列大小: {self.queue.qsize()}")
        except queue.Full:
            logger.warning("消息队列已满，丢弃消息")
    
    def get(self, block: bool = True, timeout: Optional[float] = None) -> Optional[Any]:
        """
        从队列获取项目
        
        Args:
            block: 是否阻塞
            timeout: 超时时间
            
        Returns:
            队列中的项目，如果超时返回None
        """
        try:
            return self.queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None
    
    def qsize(self) -> int:
        """获取队列当前大小"""
        return self.queue.qsize()
    
    def empty(self) -> bool:
        """检查队列是否为空"""
        return self.queue.empty()
    
    def full(self) -> bool:
        """检查队列是否已满"""
        return self.queue.full()
    
    def clear(self):
        """清空队列"""
        with self.lock:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except queue.Empty:
                    break 