#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Channel Factory - 创建不同类型的消息通道
"""

from typing import Dict, Any
from loguru import logger

from channel.channel import Channel


class ChannelFactory:
    """通道工厂类"""
    
    @staticmethod
    def create_channel(config: Dict[str, Any]) -> Channel:
        """
        根据配置创建对应的通道实例
        
        Args:
            config: 配置字典
            
        Returns:
            Channel实例
        """
        channel_type = config.get('channel_type', 'js_wechaty')
        
        try:
            if channel_type == 'js_wechaty':
                # 基于JavaScript wechaty的微信通道
                from channel.js_wechaty_channel import JSWechatyChannel
                return JSWechatyChannel(config)
                
            elif channel_type == 'wcf':
                # 基于WeChat-Ferry的微信通道（仅Windows）
                from channel.wcf_channel import WcfChannel
                return WcfChannel(config)
                
            # 可以在这里添加更多通道类型
            # elif channel_type == 'telegram':
            #     from channel.telegram_channel import TelegramChannel
            #     return TelegramChannel(config)
            
            else:
                raise ValueError(f"不支持的通道类型: {channel_type}")
                
        except ImportError as e:
            logger.error(f"导入通道模块失败: {e}")
            raise
        except Exception as e:
            logger.error(f"创建通道失败: {e}")
            raise 