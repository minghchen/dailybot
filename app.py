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
import logging
from loguru import logger
from pathlib import Path

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from channel.channel_factory import ChannelFactory
from channel.channel import ReplyType, Context, Reply
from bot.message_handler import MessageHandler
from services.llm_service import LLMService
from services.note_manager import NoteManager
from services.rag_service import RAGService
from services.content_extractor import ContentExtractor
from services.agent_service import AgentService
from utils.config_loader import ConfigLoader


class InterceptHandler(logging.Handler):
    """
    将标准 logging 日志重定向到 Loguru。
    """
    def emit(self, record):
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


class DailyBot:
    """主应用类"""
    
    def __init__(self):
        """初始化应用"""
        self.config = None
        self.channel = None
        self.message_handler = None
        self.llm_service = None
        self.note_manager = None
        self.rag_service = None
        self.agent_service = None
        self.content_extractor = None
        self.running = False
        
    def load_config(self):
        """加载配置文件"""
        config_path = Path(__file__).parent / "config" / "config.json"
        if not config_path.exists():
            logger.error(f"配置文件不存在: {config_path}")
            logger.info("请复制 config/config.example.json 为 config/config.json 并填写配置")
            sys.exit(1)
            
        try:
            # ConfigLoader.load 现在返回一个完整的配置对象
            self.config = ConfigLoader.load(config_path)
            logger.info("配置文件加载成功")
            
            # 验证笔记后端配置
            note_backend = self.config.get('note_backend', 'obsidian')
            if note_backend == 'google_docs':
                # 检查Google Docs配置
                google_config = self.config.get('google_docs', {})
                note_files = google_config.get('note_files', [])
                if not note_files:
                    logger.error("使用Google Docs后端时，请在config.json的'google_docs'中配置'note_files'")
                    sys.exit(1)
                
                # 检查每个文档是否都有ID
                for doc in note_files:
                    if not doc.get('document_id') or doc.get('document_id') == 'YOUR_DOC_ID':
                        logger.error(f"Google Docs中的笔记 '{doc.get('name', '未命名')}' 未配置有效的 document_id")
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
            # 检查并初始化LLM服务
            if 'openai' not in self.config:
                logger.error("配置文件中缺少 'openai' 配置项。")
                sys.exit(1)
            self.llm_service = LLMService(self.config['openai'])
            logger.info("LLM服务初始化成功")
            
            # 初始化笔记管理器
            self.note_manager = NoteManager(self.config)
            self.note_manager.set_llm_service(self.llm_service)
            logger.info("笔记管理器初始化成功")
            
            # 检查并初始化RAG服务
            if self.config['openai'].get('rag', {}).get('enabled'):
                if 'rag' not in self.config:
                    logger.error("配置文件中缺少 'rag' 配置项。")
                    sys.exit(1)
                if self.config.get('note_backend') == 'google_docs':
                    logger.warning("Google Docs后端暂不支持RAG功能。")
                    self.rag_service = None
                else:
                    self.rag_service = RAGService(
                        self.config['rag'], self.llm_service, self.note_manager
                    )
                    logger.info("RAG服务初始化成功")
            else:
                self.rag_service = None

            # 新的服务初始化流程
            # 1. 初始化内容提取器
            self.content_extractor = ContentExtractor(
                config=self.config, llm_service=self.llm_service
            )
            logger.info("内容提取器初始化成功")

            # 2. 初始化Agent服务，并注入提取器
            self.agent_service = AgentService(
                config=self.config,
                llm_service=self.llm_service,
                content_extractor=self.content_extractor
            )
            logger.info("智能代理服务初始化成功")

            # 3. 将Agent服务注入回内容提取器，解决循环依赖
            self.content_extractor.set_agent_service(self.agent_service)

            # 4. 初始化消息处理器，并注入内容提取器
            if 'content_extraction' not in self.config:
                logger.error("配置文件中缺少 'content_extraction' 配置项。")
                sys.exit(1)
            self.message_handler = MessageHandler(
                config=self.config,
                llm_service=self.llm_service,
                note_manager=self.note_manager,
                content_extractor=self.content_extractor,
                rag_service=self.rag_service
            )
            logger.info("消息处理器初始化成功")
            
            # 检查并初始化Channel
            if 'channel_type' not in self.config:
                logger.error("配置文件中缺少 'channel_type' 配置项。")
                sys.exit(1)
            channel_type = self.config['channel_type']
            self.channel = ChannelFactory.create_channel(self.config)
            if not self.channel:
                logger.error(f"创建通道失败: {channel_type}")
                sys.exit(1)
            
            # 注册消息处理器
            self._register_handlers()
            logger.info("消息通道初始化成功")
            
        except Exception as e:
            logger.error(f"服务初始化失败: {e}", exc_info=True)
            sys.exit(1)
    
    def _register_handlers(self):
        """注册消息处理器到Channel"""
        # 处理文本消息
        async def handle_text(context: Context) -> Reply:
            return await self.message_handler.handle_text_message(context)
        
        # 处理分享消息
        async def handle_sharing(context: Context) -> Reply:
            return await self.message_handler.handle_sharing_message(context)
        
        # 注册处理器
        self.channel.register_handler("TEXT", handle_text)
        self.channel.register_handler("SHARING", handle_sharing)
    
    def signal_handler(self, sig, frame):
        """处理退出信号"""
        logger.info("收到退出信号，正在关闭...")
        self.running = False
        if self.channel:
            self.channel.shutdown()
        sys.exit(0)
    
    async def run(self):
        """运行应用"""
        # 设置信号处理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # 步骤 1: 首先，完整加载所有配置，包括环境变量
        self.load_config()
        
        # 步骤 2: 然后，使用加载好的配置来设置日志系统
        self._setup_logging()
        
        logger.info("="*50)
        logger.info("DailyBot - 微信信息整理AI助手")
        logger.info(f"笔记后端: {self.config.get('note_backend', 'obsidian')}")
        logger.info(f"消息通道: {self.config['channel_type']}")
        logger.info("="*50)
        
        # 步骤 3: 最后，用完整的配置初始化所有服务
        self.init_services()
        
        # 注入channel到message_handler
        self.message_handler.set_channel(self.channel)
        
        # 启动通道
        logger.info("正在启动消息通道...")
        self.running = True
        
        try:
            # 启动channel
            self.channel.startup()
            
            # 启动后处理已在白名单的群组的历史消息
            await self.message_handler.check_and_process_history_on_startup()
            
            # 保持运行
            while self.running:
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            logger.info("用户中断运行")
        except Exception as e:
            logger.error(f"运行时错误: {e}", exc_info=True)
        finally:
            if self.channel:
                self.channel.shutdown()
            logger.info("程序退出")

    def _setup_logging(self):
        """配置Loguru日志系统"""
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
        
        # 拦截标准logging，统一由loguru处理
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
        logger.info("标准日志已重定向到Loguru")


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