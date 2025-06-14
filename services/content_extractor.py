#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
内容提取服务
负责从各种链接中提取内容
"""

import re
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, TYPE_CHECKING
from loguru import logger
import requests
from bs4 import BeautifulSoup
import aiohttp
from playwright.async_api import async_playwright
import html

# from utils.video_summarizer import BilibiliSummarizer

# 仅在类型检查时导入，以避免循环导入
if TYPE_CHECKING:
    from services.agent_service import AgentService


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
        self.agent_service: Optional['AgentService'] = None
        logger.info("内容提取器初始化成功，将使用Jina AI Reader。")

    def set_message_handler(self, handler: Any):
        """注入消息处理器实例"""
        self.message_handler = handler

    def set_agent_service(self, agent_service: 'AgentService'):
        """注入Agent服务实例"""
        self.agent_service = agent_service
        logger.info("AgentService 已成功注入到 ContentExtractor。")

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
                    async with session.post(reader_post_url, json=payload, headers=headers, timeout=200) as response:
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
                    async with session.get(reader_get_url, headers=headers, timeout=200) as response:
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

    async def _fetch_bilibili_content_from_web(self, url: str) -> Optional[Dict[str, Any]]:
        """
        专门为Bilibili链接设计的内容提取器。
        它会处理b23.tv短链，跳转到实际视频页面，并抓取标题和描述。
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36'
        }
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                logger.debug(f"正在请求Bilibili URL: {url}")
                async with session.get(url, allow_redirects=True, timeout=200) as response:
                    if response.status != 200:
                        logger.error(f"请求Bilibili链接失败，状态码: {response.status}, 最终URL: {response.url}")
                        return None
                    
                    final_url = response.url
                    logger.info(f"Bilibili链接已跳转至: {final_url}")
                    html_content = await response.text()
                    soup = BeautifulSoup(html_content, 'html.parser')
                    
                    # 优先从h1标签获取标题，更准确
                    title_tag = soup.find('h1', class_='video-title')
                    if not title_tag:
                         title_tag = soup.find('title') # 备用方案
                    title = title_tag.text.strip() if title_tag else '未知标题'

                    # B站的视频简介通常在 <meta name="description" ...> 标签中
                    desc_tag = soup.find('meta', attrs={'name': 'description'})
                    description = desc_tag['content'] if desc_tag and desc_tag.get('content') else ''
                    
                    if description:
                        logger.info(f"成功从Bilibili页面meta标签提取到描述。")
                        return {'title': title, 'content': description}
                    
                    # 如果meta标签没有，尝试从特定的div中获取
                    logger.warning(f"在Bilibili页面 {final_url} 未找到description meta标签，尝试其他方式。")
                    desc_div = soup.find('div', class_='desc-info-content')
                    if desc_div:
                        description = desc_div.text.strip()
                        logger.info("通过查找class='desc-info-content'的div成功提取到描述。")
                        return {'title': title, 'content': description}

                    logger.warning(f"在Bilibili页面未能找到任何描述信息，将仅返回标题。")
                    return {'title': title, 'content': ''}

        except asyncio.TimeoutError:
            logger.error(f"请求Bilibili链接超时: {url}")
            return None
        except Exception as e:
            logger.error(f"提取Bilibili内容时发生未知错误: {e}", exc_info=True)
            return None

    async def extract(self, msg: Dict[str, Any], context_messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """统一提取消息中的链接内容，优先处理特定类型如视频号"""
        try:
            xml_string = msg.get('Text', '')
            content_info = None
            url = None

            # 1. 检查是否为微信视频号内容 (通过<finderFeed>标签判断)
            if '<finderFeed>' in xml_string:
                logger.info("检测到微信视频号分享，直接从XML中提取内容。")
                try:
                    soup = BeautifulSoup(xml_string, 'xml')
                    finder_feed = soup.find('finderFeed')
                    if finder_feed:
                        nickname = finder_feed.find('nickname').text if finder_feed.find('nickname') else '未知作者'
                        desc = finder_feed.find('desc').text.strip() if finder_feed.find('desc') else '无描述'
                        object_id = finder_feed.find('objectId').text if finder_feed.find('objectId') else ''
                        
                        title = f'来自"{nickname}"的视频号分享'
                        content_info = {'title': title, 'content': desc}
                        
                        url = f"wechat_channels_{object_id}" 
                        logger.info(f"成功从XML中提取视频号内容, 标题: '{title}', 内容: '{desc[:50]}...'")
                    else:
                        logger.warning("消息中发现 <finderFeed> 标签，但解析内部结构失败。")
                except Exception as e:
                    logger.error(f"从视频号XML中提取内容失败: {e}", exc_info=True)
                    content_info = None

            # 2. 如果不是视频号内容或提取失败，则走标准的链接提取逻辑
            if not content_info:
                links = self._parse_links_from_xml(xml_string)
                if not links:
                    logger.debug("在消息中未找到可处理的链接或视频号内容。")
                    return None
                
                url = links[0]

                is_bilibili = 'b23.tv' in url or 'bilibili.com' in url or '<appname>哔哩哔哩</appname>' in xml_string
                if is_bilibili:
                    logger.info(f"检测到Bilibili链接，使用专用抓取器: {url}")
                    content_info = await self._fetch_bilibili_content_from_web(url)
                    if not content_info:
                        logger.warning("Bilibili专用抓取器未能提取内容，将尝试通用提取器。")

                if not content_info:
                    logger.info(f"使用通用Jina Reader处理链接: {url}")
                    content_info = await self._fetch_content_with_reader(url)

            # 3. 后续处理
            if not content_info or not content_info.get('content'):
                logger.warning(f"未能从消息 {url or ''} 中提取到任何有效内容。")
                return None
            
            logger.info(f"成功从 {url} 提取到内容，标题: '{content_info.get('title', '')}'")

            # 使用LLM生成自然的对话上下文
            conversation_context = await self._build_context_with_llm(msg, context_messages)

            # <<<< 新的Agent调用逻辑 >>>>
            if self.agent_service:
                # 调用Agent Service处理从决策到生成结构化笔记的完整流程
                structured_note = await self.agent_service.process_content_to_note(
                    original_content=content_info['content'],
                    conversation_context=conversation_context
                )
                # 如果Agent判断内容不相关，则中止流程
                if structured_note is None:
                    logger.info(f"Agent服务判断内容不相关或无价值，中止提取流程。URL: {url}")
                    return None
            else:
                # 如果Agent不存在，提供一个错误或回退机制
                logger.error("AgentService未初始化，无法生成结构化笔记。")
                return None
            # <<<< Agent调用逻辑结束 >>>>
            
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
        # 1. 收集所有相关的原始消息文本，并附上时间戳
        raw_texts_with_ts = []
        all_msgs = surrounding_msgs + [main_msg]
        all_msgs.sort(key=lambda x: x.get('create_time', 0))

        for m in all_msgs:
            # 兼容不同来源的时间戳字段
            ts = m.get('CreateTime') or m.get('create_time', 0)
            formatted_time = datetime.fromtimestamp(ts).strftime('%H:%M:%S')
            raw_texts_with_ts.append(f"[{formatted_time}] {m.get('Text', '')}")
        
        full_raw_context = "\n---\n".join(raw_texts_with_ts)

        # 2. 构建prompt
        prompt = f"""你是一个对话摘要专家。下面是一些带有时间戳的原始聊天记录片段，其中可能包含复杂的XML格式。
你的任务是：
1. 阅读并理解这些聊天记录。
2. 将它们转换成一段格式化的文本摘要，格式为："[时间] A说: ...; [时间] B说: ...;"。
3. **必须保留每句话前面的时间戳**，这是重要的上下文。
4. 忽略无关的XML标签，只提取关键的人物和对话内容。
5. 如果内容含有引用，请表述为"A引用B的话说:..."。

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