#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
DailyBot - 微信信息整理AI助手
主程序入口
"""

import os
import sys
import json
import signal
import asyncio
from loguru import logger
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.wechat_bot import WeChatBot
from services.llm_service import LLMService
from services.note_manager import NoteManager
from services.rag_service import RAGService
from utils.config_loader import ConfigLoader


class DailyBot:
    """主应用类"""
    
    def __init__(self):
        """初始化应用"""
        self.config = None
        self.wechat_bot = None
        self.llm_service = None
        self.note_manager = None
        self.rag_service = None
        self.running = False
        
    def load_config(self):
        """加载配置文件"""
        config_path = Path(__file__).parent / "config" / "config.json"
        if not config_path.exists():
            logger.error(f"配置文件不存在: {config_path}")
            logger.info("请复制 config/config.example.json 为 config/config.json 并填写配置")
            sys.exit(1)
            
        try:
            self.config = ConfigLoader.load(config_path)
            logger.info("配置文件加载成功")
            
            # 验证笔记后端配置
            note_backend = self.config.get('note_backend', 'obsidian')
            if note_backend == 'google_docs':
                # 检查Google Docs配置
                google_config = self.config.get('google_docs', {})
                if not google_config.get('document_id') or google_config.get('document_id') == 'YOUR_GOOGLE_DOC_ID':
                    logger.error("请在配置文件中设置有效的 Google Docs document_id")
                    sys.exit(1)
                if not google_config.get('credentials_file') or not os.path.exists(google_config.get('credentials_file', '')):
                    logger.error("请配置有效的 Google 服务账号凭证文件")
                    sys.exit(1)
            
        except Exception as e:
            logger.error(f"配置文件加载失败: {e}")
            sys.exit(1)
    
    def init_services(self):
        """初始化各个服务"""
        try:
            # 初始化LLM服务
            self.llm_service = LLMService(self.config['openai'])
            logger.info("LLM服务初始化成功")
            
            # 初始化笔记管理器
            self.note_manager = NoteManager(self.config)
            logger.info("笔记管理器初始化成功")
            
            # 初始化RAG服务（根据笔记后端决定是否启用）
            if self.config['rag']['enabled']:
                # Google Docs暂不支持RAG
                if self.config.get('note_backend') == 'google_docs':
                    logger.warning("Google Docs后端暂不支持RAG功能")
                    self.rag_service = None
                else:
                    self.rag_service = RAGService(
                        self.config['rag'],
                        self.llm_service,
                        self.note_manager
                    )
                    logger.info("RAG服务初始化成功")
            
            # 初始化微信机器人
            self.wechat_bot = WeChatBot(
                config=self.config,
                llm_service=self.llm_service,
                note_manager=self.note_manager,
                rag_service=self.rag_service
            )
            logger.info("微信机器人初始化成功")
            
        except Exception as e:
            logger.error(f"服务初始化失败: {e}")
            sys.exit(1)
    
    def signal_handler(self, sig, frame):
        """处理退出信号"""
        logger.info("收到退出信号，正在关闭...")
        self.running = False
        if self.wechat_bot:
            self.wechat_bot.stop()
        sys.exit(0)
    
    async def run(self):
        """运行应用"""
        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # 加载配置
        self.load_config()
        
        # 设置日志级别
        logger.remove()
        logger.add(
            sys.stderr,
            level=self.config['system']['log_level'],
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
        )
        
        # 添加文件日志
        log_dir = Path(__file__).parent / "logs"
        log_dir.mkdir(exist_ok=True)
        logger.add(
            log_dir / "dailybot_{time}.log",
            rotation="1 day",
            retention="7 days",
            level=self.config['system']['log_level']
        )
        
        logger.info("="*50)
        logger.info("DailyBot - 微信信息整理AI助手")
        logger.info(f"笔记后端: {self.config.get('note_backend', 'obsidian')}")
        logger.info("="*50)
        
        # 初始化服务
        self.init_services()
        
        # 启动机器人
        logger.info("正在启动微信机器人...")
        self.running = True
        
        try:
            # 启动微信机器人（阻塞运行）
            await self.wechat_bot.start()
        except KeyboardInterrupt:
            logger.info("用户中断运行")
        except Exception as e:
            logger.error(f"运行时错误: {e}", exc_info=True)
        finally:
            logger.info("程序退出")


def main():
    """主函数"""
    bot = DailyBot()
    
    # 使用asyncio运行
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main() 