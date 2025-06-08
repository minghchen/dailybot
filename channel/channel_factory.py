#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Channel Factory - 创建不同类型的消息通道
"""

import sys
from typing import Dict, Any, Union
from loguru import logger

from .channel import Channel
from .js_wechaty_channel import JSWechatyChannel

# Conditionally import platform-specific channels
if sys.platform == 'darwin':
    from .mac_wechat_channel import MacWeChatChannel
else:
    MacWeChatChannel = None

if sys.platform == 'win32':
    from .wcf_channel import WcfChannel
else:
    WcfChannel = None


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
            channel_config = config.get(channel_type, {})
            
            if channel_type == 'js_wechaty':
                # 基于JavaScript wechaty的微信通道
                return JSWechatyChannel(channel_config)
                
            elif channel_type == 'wcf':
                # 基于WeChat-Ferry的微信通道（仅Windows）
                if WcfChannel is None:
                    raise ValueError(f"通道类型 'wcf' 仅在Windows上受支持，当前系统为 {sys.platform}。")
                return WcfChannel(channel_config)
                
            elif channel_type == 'mac_wechat':
                # 基于数据库读取和Hook的Mac微信通道（仅macOS）
                if MacWeChatChannel is None:
                    raise ValueError(f"通道类型 'mac_wechat' 仅在macOS上受支持，当前系统为 {sys.platform}。")
                return MacWeChatChannel(channel_config)
                
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


def create_channel(channel_type: Union[str, Dict[str, Any]]) -> Channel:
    """
    便捷函数：创建通道实例
    
    Args:
        channel_type: 通道类型字符串或完整配置字典
        
    Returns:
        Channel实例
    """
    if isinstance(channel_type, str):
        config = {'channel_type': channel_type}
    else:
        config = channel_type
    
    return ChannelFactory.create_channel(config) 