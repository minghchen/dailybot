#!/usr/bin/env python3
"""
Mac微信通道测试脚本
演示静默读取模式（笔记整理）和Hook模式（自动回复）
"""

import os
import sys
import time
import logging
from pathlib import Path
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.mac_wechat_service import MacWeChatService
from channel.mac_wechat_channel import MacWeChatChannel
from channel.channel_factory import ChannelFactory

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_silent_mode():
    """测试静默模式：用于笔记整理"""
    logger.info("=== 测试静默模式（笔记整理） ===")
    
    # 使用配置文件创建通道
    config = {
        "channel_type": "mac_wechat",
        "mac_wechat": {
            "mode": "silent",
            "poll_interval": 10,  # 测试时设置为10秒
            "group_name_white_list": ["测试群", "AI研究群"]
        }
    }
    
    channel = ChannelFactory.create_channel(config)
    
    # 模拟消息处理器（实际使用时会是MessageHandler）
    def process_message(message, context):
        """模拟笔记整理功能"""
        content = message.get('content', '')
        
        # 检查是否包含链接
        if 'http' in content or 'arxiv' in content:
            logger.info(f"[笔记整理] 发现链接: {content[:100]}...")
            
            # 这里实际会：
            # 1. 提取链接
            # 2. 获取链接内容
            # 3. 使用LLM总结
            # 4. 保存到笔记系统
            logger.info("  -> 正在提取内容...")
            logger.info("  -> 正在生成总结...")
            logger.info("  -> 已保存到笔记系统")
        
        # 显示消息信息
        if message.get('is_historical'):
            logger.info(f"[历史消息] {message['from_user_id']}: {content[:50]}...")
        else:
            logger.info(f"[新消息] {message['from_user_id']}: {content[:50]}...")
    
    channel.set_message_callback(process_message)
    
    try:
        # 启动通道
        channel.startup()
        
        logger.info("静默模式运行中...")
        logger.info("- 每10秒检查一次新消息")
        logger.info("- 自动提取链接并整理笔记")
        logger.info("- 不会发送任何消息")
        logger.info("按Ctrl+C停止")
        
        # 运行30秒
        time.sleep(30)
        
    except KeyboardInterrupt:
        logger.info("正在停止...")
    finally:
        channel.stop()


def test_hook_mode():
    """测试Hook模式：自动回复功能"""
    logger.info("=== 测试Hook模式（自动回复） ===")
    
    # 设置环境变量启用Hook
    os.environ["MAC_WECHAT_USE_HOOK"] = "true"
    
    config = {
        "channel_type": "mac_wechat",
        "mac_wechat": {
            "mode": "hook",
            "auto_reply_rules": {
                "你好": "你好！有什么可以帮助你的吗？",
                "在吗": "在的，请说",
                "help": "可用命令：天气、时间、帮助"
            }
        }
    }
    
    channel = ChannelFactory.create_channel(config)
    
    # 定义消息处理器
    def handle_message(message, context):
        logger.info(f"[实时消息] {message['from_user_id']} -> {message['content']}")
        
        # 这里可以添加更复杂的处理逻辑
        content = message['content']
        
        # 特殊命令处理
        if "天气" in content:
            reply = {
                "to_user_id": message["from_user_id"],
                "content": "今天天气晴朗，温度适宜！",
                "type": "text"
            }
            channel.send(reply)
    
    channel.set_message_callback(handle_message)
    
    try:
        # 启动通道
        channel.startup()
        
        logger.info("Hook模式运行中...")
        logger.info("- 实时监听消息")
        logger.info("- 支持自动回复")
        logger.info("- 关键词: 你好、在吗、help、天气")
        logger.info("按Ctrl+C停止")
        
        # 保持运行
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("正在停止...")
    finally:
        channel.stop()


def test_with_bot_integration():
    """测试与Bot框架集成"""
    logger.info("=== 测试Bot集成（完整功能） ===")
    
    # 导入Bot相关模块
    try:
        from bot.message_handler import MessageHandler
        from services.note_manager import NoteManager
        
        # 创建通道
        config = {
            "channel_type": "mac_wechat",
            "mac_wechat": {
                "mode": "silent",
                "poll_interval": 30,
                "group_name_white_list": ["AI研究群", "机器人技术交流"]
            },
            "openai": {
                "model": "gpt-4o-mini"
            },
            "obsidian": {
                "vault_path": "./test_vault",
                "knowledge_base_folder": "Knowledge Base"
            }
        }
        
        channel = ChannelFactory.create_channel(config)
        
        # 创建消息处理器
        handler = MessageHandler(config)
        
        # 设置消息回调
        channel.set_message_callback(handler.handle_message)
        
        # 启动
        channel.startup()
        
        logger.info("完整Bot功能运行中...")
        logger.info("- 自动提取链接")
        logger.info("- 使用LLM总结内容")
        logger.info("- 保存到笔记系统")
        logger.info("- 支持问答功能")
        
        # 运行
        while True:
            time.sleep(1)
            
    except ImportError as e:
        logger.error(f"无法导入Bot模块: {e}")
        logger.info("请确保在项目根目录运行")
    except KeyboardInterrupt:
        logger.info("正在停止...")
        channel.stop()


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Mac微信通道测试")
    parser.add_argument(
        "--mode", 
        choices=["silent", "hook", "bot"], 
        default="silent",
        help="测试模式：silent(静默读取), hook(自动回复), bot(完整集成)"
    )
    
    args = parser.parse_args()
    
    logger.info(f"运行模式: {args.mode}")
    logger.info("=" * 50)
    
    if args.mode == "silent":
        test_silent_mode()
    elif args.mode == "hook":
        test_hook_mode()
    elif args.mode == "bot":
        test_with_bot_integration()


if __name__ == "__main__":
    main() 