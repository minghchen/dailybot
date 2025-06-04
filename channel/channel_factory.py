#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Channel工厂类 - 用于创建不同的消息通道实例
"""

from typing import Dict, Any, Optional
from loguru import logger

from channel.channel import Channel
from channel.wechat_channel import WechatChannel


class ChannelFactory:
    """Channel工厂类"""
    
    # 支持的通道类型
    CHANNEL_TYPES = {
        'wechat': WechatChannel,
        # 未来可以添加更多通道
        # 'wework': WeWorkChannel,
        # 'feishu': FeishuChannel,
        # 'dingtalk': DingTalkChannel,
    }
    
    @classmethod
    def create_channel(cls, channel_type: str, config: Dict[str, Any]) -> Optional[Channel]:
        """
        创建Channel实例
        
        Args:
            channel_type: 通道类型
            config: 配置信息
            
        Returns:
            Channel实例，如果类型不支持则返回None
        """
        if channel_type not in cls.CHANNEL_TYPES:
            logger.error(f"不支持的通道类型: {channel_type}")
            logger.info(f"支持的通道类型: {list(cls.CHANNEL_TYPES.keys())}")
            return None
        
        try:
            channel_class = cls.CHANNEL_TYPES[channel_type]
            channel = channel_class(config)
            logger.info(f"创建通道成功: {channel_type}")
            return channel
            
        except Exception as e:
            logger.error(f"创建通道失败: {e}", exc_info=True)
            return None
    
    @classmethod
    def get_supported_channels(cls) -> list:
        """获取支持的通道类型列表"""
        return list(cls.CHANNEL_TYPES.keys()) 