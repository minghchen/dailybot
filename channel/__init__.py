"""
Channel模块 - 消息通道抽象层
"""

from .channel import Channel
from .channel_factory import ChannelFactory
from .js_wechaty_channel import JSWechatyChannel
import platform
sys_type = platform.system().lower()
if sys_type == 'windows':
    from .wcf_channel import WcfChannel
elif sys_type == 'linux':
    from .wcf_channel import WcfChannel
elif sys_type == 'darwin':
    from .mac_wechat_channel import MacWeChatChannel
else:
    raise ImportError(f"Unsupported system: {sys_type}")

__all__ = [
    'Channel',
    'ChannelFactory',
    'JSWechatyChannel',
    'WcfChannel',
    'MacWeChatChannel'
] 