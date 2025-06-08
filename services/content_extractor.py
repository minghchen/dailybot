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

from utils.link_parser import LinkParser
from utils.video_summarizer import BilibiliSummarizer


class ContentExtractor:
    """内容提取器"""
    
    def __init__(self, config: Dict[str, Any], llm_service):
        """
        初始化内容提取器
        
        Args:
            config: 配置信息
            llm_service: LLM服务实例
        """
        self.config = config
        self.extraction_config = self.config.get('content_extraction', {})
        self.llm_service = llm_service
        
        # 链接解析器
        self.link_parser = LinkParser()
        
        # B站视频总结器
        self.bilibili_summarizer = BilibiliSummarizer(config.get('bilibili', {}))
        
        # 提取类型映射
        self.extractors = {
            'wechat_article': self._extract_wechat_article,
            'bilibili_video': self._extract_bilibili_video,
            'arxiv_paper': self._extract_arxiv_paper,
            'web_link': self._extract_web_content
        }
        
        logger.info("内容提取器初始化成功")
    
    def set_message_handler(self, handler: Any):
        """注入消息处理器实例，以备回调使用"""
        self.message_handler = handler
    
    async def extract(self, msg: Dict[str, Any], context_messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        提取消息中的内容
        
        Args:
            msg: 消息对象
            context_messages: 上下文消息列表
            
        Returns:
            提取的内容数据
        """
        try:
            # 解析链接
            links = self.link_parser.parse_message(msg)
            if not links:
                return None
            
            # 获取第一个链接（后续可以支持多链接）
            link_info = links[0]
            link_type = link_info['type']
            url = link_info['url']
            
            # 检查是否支持该类型
            if link_type not in self.extraction_config['extract_types']:
                logger.info(f"跳过不支持的链接类型: {link_type}")
                return None
            
            # 提取内容
            if link_type in self.extractors:
                content_info = await self.extractors[link_type](url)
            else:
                content_info = await self._extract_web_content(url)
            
            if not content_info:
                return None
            
            # 构建上下文
            context = self._build_context(msg, context_messages)
            
            # 使用LLM总结内容，但要求精炼（1-5句话）
            summary_prompt = f"""请用1-5句话总结以下内容的核心要点，要求：
1. 提取最重要的观点或发现
2. 保持客观准确
3. 语言精炼，每句话都有信息量
4. 如果是技术内容，突出技术创新点

内容：
{content_info['content'][:3000]}"""
            
            summary = await self.llm_service.chat(summary_prompt)
            
            # 使用LLM进行智能分类
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
            
            # 构建返回数据
            result = {
                'title': content_info.get('title', link_info.get('title', '未知标题')),
                'article_title': content_info.get('article_title', ''),  # 公众号文章标题
                'url': url,
                'type': link_type,
                'summary': summary,
                'category': category,
                'context': context,
                'raw_content': content_info['content'],
                'extracted_at': datetime.now(),
                'source_user': msg['User']['NickName']
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
    
    async def _extract_wechat_article(self, url: str) -> Optional[Dict[str, Any]]:
        """提取微信公众号文章内容"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # 提取文章标题（这是公众号文章的标题）
            article_title = ''
            title_elem = soup.find('h1', class_='rich_media_title')
            if title_elem:
                article_title = title_elem.text.strip()
            
            # 提取内容标题（尝试从文章中提取论文或主题标题）
            content_title = article_title  # 默认使用文章标题
            
            # 提取作者
            author = ''
            author_elem = soup.find('span', class_='rich_media_meta_text')
            if author_elem:
                author = author_elem.text.strip()
            
            # 提取正文
            content_div = soup.find('div', id='js_content')
            content = ''
            if content_div:
                # 移除脚本和样式
                for script in content_div(['script', 'style']):
                    script.decompose()
                
                # 获取文本内容
                content = content_div.get_text(separator='\n', strip=True)
                
                # 尝试从正文中提取论文标题
                # 查找常见的论文标题模式
                paper_patterns = [
                    r'《([^》]+)》',  # 中文书名号
                    r'"([^"]+)"',     # 英文引号
                    r'「([^」]+)」',  # 日文引号
                    r'Title:\s*(.+)', # Title: 格式
                    r'论文.*?[：:]\s*(.+)', # 论文：格式
                ]
                
                for pattern in paper_patterns:
                    match = re.search(pattern, content[:1000])  # 只在前1000字符中查找
                    if match:
                        potential_title = match.group(1).strip()
                        # 验证是否像是论文标题（长度合适，包含关键词等）
                        if 10 < len(potential_title) < 200:
                            content_title = potential_title
                            break
            
            # 组合内容
            full_content = f"作者: {author}\n\n{content}" if author else content
            
            return {
                'title': content_title,  # 内容的主标题（论文名等）
                'article_title': article_title,  # 公众号文章标题
                'content': full_content,
                'author': author
            }
            
        except Exception as e:
            logger.error(f"提取微信公众号文章失败: {e}")
            return None
    
    async def _extract_bilibili_video(self, url: str) -> Optional[Dict[str, Any]]:
        """提取B站视频内容"""
        try:
            # 使用B站视频总结工具
            video_info = await self.bilibili_summarizer.get_video_info(url)
            
            if not video_info:
                return None
            
            # 构建内容
            content = f"""UP主: {video_info.get('author', '')}
时长: {video_info.get('duration', '')}
播放量: {video_info.get('views', '')}

简介:
{video_info.get('description', '')}

字幕/弹幕摘要:
{video_info.get('transcript', '(暂无字幕信息)')}
"""
            
            return {
                'title': video_info.get('title', ''),
                'article_title': '',  # 视频没有额外的文章标题
                'content': content
            }
            
        except Exception as e:
            logger.error(f"提取B站视频内容失败: {e}")
            return None
    
    async def _extract_arxiv_paper(self, url: str) -> Optional[Dict[str, Any]]:
        """提取arXiv论文内容"""
        try:
            # 从URL提取论文ID
            arxiv_id_match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d+\.\d+)', url)
            if not arxiv_id_match:
                return None
            
            arxiv_id = arxiv_id_match.group(1)
            
            # 获取论文元数据
            api_url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(api_url) as response:
                    xml_data = await response.text()
            
            # 解析XML
            soup = BeautifulSoup(xml_data, 'xml')
            entry = soup.find('entry')
            
            if not entry:
                return None
            
            # 提取信息
            title = entry.find('title').text.strip()
            authors = [author.find('name').text for author in entry.find_all('author')]
            summary = entry.find('summary').text.strip()
            published = entry.find('published').text[:10]  # 只取日期部分
            
            # 构建内容
            content = f"""作者: {', '.join(authors)}
发布日期: {published}

摘要:
{summary}
"""
            
            return {
                'title': title,  # 论文标题
                'article_title': '',  # arXiv没有额外的文章标题
                'content': content
            }
            
        except Exception as e:
            logger.error(f"提取arXiv论文失败: {e}")
            return None
    
    async def _extract_web_content(self, url: str) -> Optional[Dict[str, Any]]:
        """提取通用网页内容"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=30) as response:
                    html = await response.text()
            
            soup = BeautifulSoup(html, 'html.parser')
            
            # 移除脚本和样式
            for script in soup(['script', 'style']):
                script.decompose()
            
            # 尝试提取标题
            title = ''
            title_elem = soup.find('title')
            if title_elem:
                title = title_elem.text.strip()
            
            # 尝试提取主要内容
            # 优先查找article标签
            article = soup.find('article')
            if article:
                content = article.get_text(separator='\n', strip=True)
            else:
                # 查找main标签
                main = soup.find('main')
                if main:
                    content = main.get_text(separator='\n', strip=True)
                else:
                    # 获取body内容
                    body = soup.find('body')
                    content = body.get_text(separator='\n', strip=True) if body else ''
            
            # 限制内容长度
            if len(content) > 5000:
                content = content[:5000] + '\n...(内容过长，已截断)'
            
            return {
                'title': title,
                'article_title': '',
                'content': content
            }
            
        except Exception as e:
            logger.error(f"提取网页内容失败: {e}")
            return None 