"""
Channel模块 - 消息通道抽象层
"""
import sys

from .channel import Channel
from .js_wechaty_channel import JSWechatyChannel

# 根据操作系统平台，条件性地导入特定通道
if sys.platform == "win32":
    from .wcf_channel import WcfChannel
else:
    # 在非Windows系统上，定义一个假的WcfChannel以避免NameError
    WcfChannel = None 

# Mac微信通道（仅macOS可用）
if sys.platform == "darwin":
    from .mac_wechat_channel import MacWeChatChannel
else:
    MacWeChatChannel = None


__all__ = [
    'Channel',
    'JSWechatyChannel',
    'WcfChannel',
    'MacWeChatChannel'
] 