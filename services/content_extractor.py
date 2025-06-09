#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
内容提取服务
负责从各种链接中提取内容
"""

import re
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional
from loguru import logger
import requests
from bs4 import BeautifulSoup
import aiohttp
from playwright.async_api import async_playwright

from utils.video_summarizer import BilibiliSummarizer


class ContentExtractor:
    """内容提取器，统一使用Jina AI Reader进行内容提取"""

    def __init__(self, config: Dict[str, Any], llm_service):
        """
        初始化内容提取器
        
        Args:
            config: 内容提取部分的配置
            llm_service: LLM服务实例
        """
        self.config = config
        self.extraction_config = config
        self.llm_service = llm_service
        self.reader_base_url = "https://r.jina.ai/"
        logger.info("内容提取器初始化成功，将使用Jina AI Reader。")

    def set_message_handler(self, handler: Any):
        """注入消息处理器实例"""
        self.message_handler = handler

    def _parse_links_from_xml(self, xml_string: str) -> List[str]:
        """
        从消息的XML内容中健壮地提取所有链接。
        """
        if not xml_string:
            return []

        # 1. 移除引用消息，避免重复处理
        text_no_refer = re.sub(r'<refermsg>.*?</refermsg>', '', xml_string, flags=re.DOTALL)

        # 2. 统一匹配所有 http/https 链接，无论是在标签内还是纯文本
        # 这个正则表达式会匹配:
        # - <url>https://...</url>
        # - <title>some text https://... some text</title>
        # - >https://...< (纯文本链接)
        # - CDATA中的链接
        link_pattern = re.compile(r'https?://[a-zA-Z0-9./?=&-_%~@#*+]+')
        
        links = link_pattern.findall(text_no_refer)
        
        # 去重并保持顺序
        unique_links = list(dict.fromkeys(links))
        
        logger.info(f"从消息内容中解析出 {len(unique_links)} 个链接: {unique_links}")
        return unique_links

    def _classify_link(self, url: str) -> str:
        """根据URL分类链接类型"""
        if "mp.weixin.qq.com" in url:
            return "wechat_article"
        if "bilibili.com" in url or "b23.tv" in url:
            return "bilibili_video"
        if "arxiv.org" in url:
            return "arxiv_paper"
        return "web_link"

    async def _fetch_content_with_reader(self, url: str) -> Optional[Dict[str, Any]]:
        """使用Jina AI Reader提取任何URL的内容"""
        reader_url = f"{self.reader_base_url}{url}"
        logger.info(f"正在通过Jina Reader提取内容: {reader_url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(reader_url, timeout=120) as response:
                    if response.status == 200:
                        content = await response.text()
                        # Jina Reader返回的内容是Markdown格式，标题通常是第一行
                        lines = content.split('\n')
                        title = lines[0].strip('# ').strip() if lines else url
                        return {'title': title, 'content': content}
                    else:
                        logger.error(f"Jina Reader请求失败，状态码: {response.status}, URL: {reader_url}")
                        return None
        except asyncio.TimeoutError:
            logger.error(f"Jina Reader请求超时: {reader_url}")
            return None
        except Exception as e:
            logger.error(f"通过Jina Reader提取内容时发生未知错误: {e}", exc_info=True)
            return None

    async def extract(self, msg: Dict[str, Any], context_messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """统一提取消息中的链接内容"""
        try:
            links = self._parse_links_from_xml(msg.get('Text', ''))
            if not links:
                return None
            
            url = links[0]
            logger.info(f"开始使用Jina Reader处理链接: {url}")

            content_info = await self._fetch_content_with_reader(url)
            if not content_info:
                logger.warning(f"未能从 {url} 提取到任何内容。")
                return None
            
            logger.info(f"成功从 {url} 提取到内容，标题: '{content_info.get('title', '')}'")

            context = self._build_context(msg, context_messages)
            
            # 由于Jina Reader已经对内容进行了很好的格式化，我们可以直接使用，或者进行更精简的总结
            summary_prompt = f"""请将以下已经由Jina Reader预处理过的内容，进一步总结为一段不超过200字的精炼摘要，保留最重要的信息和核心观点。

预处理后的内容：
{content_info['content'][:4000]}"""
            
            summary = await self.llm_service.chat(summary_prompt)
            
            categories = ['theory', 'application', 'technology', 'industry', 'others']
            category_prompt = f"""请对以下内容进行分类，选择最合适的一个类别：
- theory: 理论研究、学术论文、基础研究
- application: 应用案例、实践经验、项目实施
- technology: 技术进展、工具框架、技术实现
- industry: 产业动态、市场分析、行业趋势
- others: 其他难以归类的内容

内容标题：{content_info.get('title', '')}
内容摘要：{summary[:500]}

请直接返回类别名称（如：theory），不要有其他内容。"""
            
            category = await self.llm_service.chat(category_prompt)
            category = category.strip().lower()
            if category not in categories:
                category = 'others'
            
            result = {
                'title': content_info.get('title', url),
                'url': url,
                'summary': summary,
                'category': category,
                'context': context,
                'raw_content': content_info['content'],
                'extracted_at': datetime.now(),
                'source_user': msg.get('User', {}).get('NickName', '未知')
            }
            
            return result
            
        except Exception as e:
            logger.error(f"提取内容时出错: {e}", exc_info=True)
            return None

    def _build_context(self, msg: Dict[str, Any], context_messages: List[Dict[str, Any]]) -> str:
        """构建上下文信息"""
        context_parts = []
        
        # 添加发送者信息
        sender = msg['User']['NickName']
        context_parts.append(f"发送者: {sender}")
        
        # 添加时间信息
        send_time = datetime.fromtimestamp(msg['CreateTime'])
        context_parts.append(f"发送时间: {send_time.strftime('%Y-%m-%d %H:%M:%S')}")
        
        # 添加上下文消息
        if context_messages:
            context_parts.append("\n相关对话:")
            for ctx_msg in context_messages:
                ctx_sender = ctx_msg['User']['NickName']
                ctx_text = ctx_msg['Text']
                context_parts.append(f"- {ctx_sender}: {ctx_text}")
        
        return "\n".join(context_parts) 