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
import html

from utils.video_summarizer import BilibiliSummarizer


class ContentExtractor:
    """内容提取器，统一使用Jina AI Reader进行内容提取"""

    def __init__(self, config: Dict[str, Any], llm_service):
        """
        初始化内容提取器
        
        Args:
            config: 全局配置对象
            llm_service: LLM服务实例
        """
        self.config = config
        self.extraction_config = config.get('content_extraction', {})
        self.llm_service = llm_service
        self.reader_base_url = "https://r.jina.ai/"
        self.jina_api_key = config.get('jina', {}).get('api_key')
        logger.info("内容提取器初始化成功，将使用Jina AI Reader。")

    def set_message_handler(self, handler: Any):
        """注入消息处理器实例"""
        self.message_handler = handler

    def _parse_links_from_xml(self, xml_string: str) -> List[str]:
        """
        从消息的XML内容中健壮地提取所有链接。
        使用正则表达式，确保在复杂的XML结构中也能提取URL。
        """
        if not xml_string:
            return []

        # 1. 解码HTML实体，正确处理 &amp; 等
        decoded_string = html.unescape(xml_string)

        # 2. 使用更健壮的正则表达式查找所有链接
        link_pattern = re.compile(r'https?://[^\s<>"\'`]+')
        all_links = link_pattern.findall(decoded_string)
        
        # 3. 过滤掉常见的不需要处理的链接
        ignored_domains = ['wx.qlogo.cn', 'support.weixin.qq.com', 'wxapp.tc.qq.com']
        filtered_links = [
            link for link in all_links 
            if not any(domain in link for domain in ignored_domains)
        ]

        # 4. 去重并保持顺序
        unique_links = list(dict.fromkeys(filtered_links))
        
        if unique_links:
            logger.info(f"从消息内容中解析出 {len(unique_links)} 个有效链接: {unique_links}")
        else:
            logger.debug("在消息内容中未找到有效链接。")
            
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
        """
        使用Jina AI Reader提取任何URL的内容。
        根据Jina官方文档，对需要特殊处理的URL（如包含#的微信链接）使用POST方法。
        """
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        }
        if self.jina_api_key:
            headers['Authorization'] = f"Bearer {self.jina_api_key}"

        # 增加日志，用于调试API Key是否正确加载
        logger.debug(f"Jina Reader 请求头: {headers}")

        is_wechat_url = "mp.weixin.qq.com" in url
        
        # Jina Reader的POST接口
        reader_post_url = "https://r.jina.ai/"
        
        logger.info(f"正在通过Jina Reader提取内容: {url}")

        try:
            async with aiohttp.ClientSession() as session:
                if is_wechat_url:
                    # 对于微信链接，使用POST并指定引擎，以处理JS渲染和验证码
                    logger.info(f"检测到微信链接，使用POST方法及cf-browser-rendering引擎。")
                    payload = {
                        "url": url,
                        "engine": "cf-browser-rendering"
                    }
                    async with session.post(reader_post_url, json=payload, headers=headers, timeout=180) as response:
                        if response.status == 200:
                            json_response = await response.json()
                            logger.debug(f"Jina Reader (POST) 响应: {json_response}")
                            # 修正：从 'data' 字段中提取内容
                            data = json_response.get('data', {})
                            return {'title': data.get('title', url), 'content': data.get('content', '')}
                        else:
                            logger.error(f"Jina Reader POST请求失败，状态码: {response.status}, URL: {url}, 响应: {await response.text()}")
                            return None
                else:
                    # 对于其他链接，使用GET方法
                    reader_get_url = f"https://r.jina.ai/{url}"
                    async with session.get(reader_get_url, headers=headers, timeout=120) as response:
                        if response.status == 200:
                            json_response = await response.json()
                            logger.debug(f"Jina Reader (GET) 响应: {json_response}")
                            # 修正：从 'data' 字段中提取内容
                            data = json_response.get('data', {})
                            return {'title': data.get('title', url), 'content': data.get('content', '')}
                        else:
                            logger.error(f"Jina Reader GET请求失败，状态码: {response.status}, URL: {reader_get_url}")
                            return None

        except asyncio.TimeoutError:
            logger.error(f"Jina Reader请求超时: {url}")
            return None
        except Exception as e:
            logger.error(f"通过Jina Reader提取内容时发生未知错误: {e}", exc_info=True)
            return None

    async def extract(self, msg: Dict[str, Any], context_messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """统一提取消息中的链接内容"""
        try:
            # 使用新的解析函数
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

            # 使用LLM生成自然的对话上下文
            conversation_context = await self._build_context_with_llm(msg, context_messages)
            
            # 使用LLM生成结构化的笔记内容
            structured_note = await self.llm_service.generate_structured_note(
                article_content=content_info['content'],
                conversation_context=conversation_context
            )
            
            result = {
                'url': url,
                'structured_note': structured_note.dict(), # 将pydantic模型转为字典
                'context': conversation_context,
                'raw_content': content_info['content'],
                'extracted_at': datetime.now(),
                'source_user': msg.get('User', {}).get('NickName', '未知')
            }
            
            return result
            
        except Exception as e:
            logger.error(f"提取内容时出错: {e}", exc_info=True)
            return None

    async def _build_context_with_llm(self, main_msg: Dict[str, Any], surrounding_msgs: List[Dict[str, Any]]) -> str:
        """
        使用LLM将原始聊天记录生成为一段自然的、可读的对话摘要。
        """
        # 1. 收集所有相关的原始消息文本
        raw_texts = []
        all_msgs = surrounding_msgs + [main_msg]
        all_msgs.sort(key=lambda x: x.get('create_time', 0))

        for m in all_msgs:
            raw_texts.append(m.get('Text', ''))
        
        full_raw_context = "\n---\n".join(raw_texts)

        # 2. 构建prompt
        prompt = f"""你是一个对话摘要专家。下面是一些原始的聊天记录片段，其中可能包含复杂的XML格式。
你的任务是：
1. 阅读并理解这些聊天记录。
2. 将它们转换成一段流畅、自然的对话摘要，格式为："A说... B回复说... C评论道..."。
3. 忽略无关的XML标签，只提取关键的人物和对话内容。
4. 如果内容是引用，请表述为"A引用B的话说..."。
5. 保持摘要的简洁和中立。

[原始聊天记录]
{full_raw_context}

[生成的对话摘要]
"""

        try:
            # 3. 调用LLM
            formatted_context = await self.llm_service.chat(prompt)
            logger.info("LLM成功生成了格式化的上下文。")
            logger.debug(f"LLM生成的上下文: \n{formatted_context}")
            return formatted_context.strip()
        except Exception as e:
            logger.error(f"使用LLM生成上下文失败: {e}，将返回原始文本。")
            return full_raw_context # 失败时回退到原始文本 