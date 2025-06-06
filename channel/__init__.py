"""
Channel模块 - 消息通道抽象层
"""

from .channel import Channel
from .channel_factory import ChannelFactory
from .js_wechaty_channel import JSWechatyChannel
from .wcf_channel import WcfChannel

# Mac微信通道（仅macOS可用）
try:
    from .mac_wechat_channel import MacWeChatChannel
except ImportError:
    # 非macOS系统可能无法导入
    pass

__all__ = [
    'Channel',
    'ChannelFactory',
    'JSWechatyChannel',
    'WcfChannel',
    'MacWeChatChannel'
] 