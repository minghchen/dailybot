#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Google Docs 管理器
负责管理Google在线文档的读写，支持智能内容插入
"""

import os
import re
import json
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple
from loguru import logger
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class GoogleDocsManager:
    """Google Docs管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化Google Docs管理器
        
        Args:
            config: Google Docs配置信息
        """
        self.config = config
        self.document_id = config.get('document_id')
        self.credentials_file = config.get('credentials_file')
        self.service = None
        
        # 分类配置
        self.categories = config.get('categories', {
            'theory': '理论研究',
            'application': '应用案例',
            'technology': '技术进展',
            'industry': '产业动态',
            'others': '其他'
        })
        
        # 初始化服务
        self._init_service()
        
        logger.info(f"Google Docs管理器初始化成功，文档ID: {self.document_id}")
    
    def _init_service(self):
        """初始化Google Docs API服务"""
        try:
            # 使用服务账号凭证
            credentials = service_account.Credentials.from_service_account_file(
                self.credentials_file,
                scopes=['https://www.googleapis.com/auth/documents']
            )
            
            self.service = build('docs', 'v1', credentials=credentials)
            
        except Exception as e:
            logger.error(f"初始化Google Docs服务失败: {e}")
            raise
    
    async def get_document_content(self) -> Dict[str, Any]:
        """
        获取文档内容
        
        Returns:
            文档内容
        """
        try:
            document = self.service.documents().get(documentId=self.document_id).execute()
            return document
        except HttpError as error:
            logger.error(f'获取文档失败: {error}')
            return None
    
    async def save_content(self, content_data: Dict[str, Any]):
        """
        保存内容到Google Docs，智能插入到合适位置
        
        Args:
            content_data: 内容数据
        """
        try:
            # 格式化内容
            formatted_content = self._format_content(content_data)
            
            # 获取文档结构
            document = await self.get_document_content()
            if not document:
                logger.error("无法获取文档内容")
                return
            
            # 分析文档结构，找到合适的插入位置
            insert_position, category_exists = await self._find_insert_position(
                document, 
                content_data.get('category', 'others'),
                content_data.get('title', '')
            )
            
            # 检查是否有重复内容
            if await self._check_duplicate(document, content_data):
                logger.info(f"内容已存在，跳过: {content_data.get('title')}")
                return
            
            # 构建请求
            requests = []
            
            # 如果类别不存在，先创建类别标题
            if not category_exists:
                category_name = self.categories.get(
                    content_data.get('category', 'others'), 
                    '其他'
                )
                requests.extend(self._create_category_section(insert_position, category_name))
                # 更新插入位置
                insert_position = insert_position + len(f"\n## {category_name}\n\n")
            
            # 插入内容
            requests.append({
                'insertText': {
                    'location': {
                        'index': insert_position
                    },
                    'text': formatted_content + '\n\n'
                }
            })
            
            # 应用格式
            requests.extend(self._format_content_requests(
                insert_position, 
                formatted_content,
                content_data
            ))
            
            # 执行批量更新
            result = self.service.documents().batchUpdate(
                documentId=self.document_id,
                body={'requests': requests}
            ).execute()
            
            logger.info(f"内容已保存到Google Docs: {content_data.get('title')}")
            
        except Exception as e:
            logger.error(f"保存内容到Google Docs失败: {e}", exc_info=True)
    
    def _format_content(self, content_data: Dict[str, Any]) -> str:
        """
        格式化内容为指定格式
        
        Args:
            content_data: 内容数据
            
        Returns:
            格式化后的文本
        """
        # 提取信息
        title = content_data.get('title', '未命名内容')
        url = content_data.get('url', '')
        summary = content_data.get('summary', '')
        article_title = content_data.get('article_title', '')
        content_type = content_data.get('type', 'web_link')
        
        # 提取日期
        if 'arxiv' in content_type or 'arxiv' in url.lower():
            # 尝试从URL或标题提取arxiv日期
            date_match = re.search(r'(\d{4})\.(\d{4,5})', url + ' ' + title)
            if date_match:
                year = date_match.group(1)
                date_str = f"{year}"
            else:
                date_str = datetime.now().strftime('%Y')
        else:
            # 使用提取日期
            extracted_at = content_data.get('extracted_at', datetime.now())
            if isinstance(extracted_at, str):
                extracted_at = datetime.fromisoformat(extracted_at)
            date_str = extracted_at.strftime('%Y-%m-%d')
        
        # 构建第一行（标题）
        if 'arxiv' in content_type or 'arxiv' in url.lower():
            first_line = f"**{date_str} {title}**"
        else:
            first_line = f"**{date_str} {title}**"
        
        # 构建第二行（文章链接）
        if article_title and article_title != title:
            second_line = f"[{article_title}]({url})"
        else:
            # 从URL中提取来源
            source = self._extract_source_from_url(url)
            second_line = f"[{source}]({url})"
        
        # 构建第三行（内容重点，限制为1-5句话）
        summary_sentences = self._extract_key_sentences(summary, max_sentences=5)
        third_line = summary_sentences
        
        # 组合内容
        formatted_content = f"{first_line}\n{second_line}\n{third_line}"
        
        return formatted_content
    
    def _extract_source_from_url(self, url: str) -> str:
        """从URL提取来源名称"""
        if 'mp.weixin.qq.com' in url:
            return '微信公众号文章'
        elif 'arxiv.org' in url:
            return 'arXiv论文'
        elif 'bilibili.com' in url or 'b23.tv' in url:
            return 'B站视频'
        elif 'github.com' in url:
            return 'GitHub项目'
        else:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            return parsed.netloc or '网页链接'
    
    def _extract_key_sentences(self, text: str, max_sentences: int = 5) -> str:
        """
        提取关键句子（1-5句话）
        
        Args:
            text: 原始文本
            max_sentences: 最大句子数
            
        Returns:
            关键句子
        """
        if not text:
            return "（无摘要）"
        
        # 分割句子
        sentences = re.split(r'[。！？.!?]+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        # 如果句子太少，直接返回
        if len(sentences) <= max_sentences:
            return '。'.join(sentences) + '。'
        
        # 提取前max_sentences句最重要的内容
        # 这里简单取前面的句子，实际可以用更复杂的算法
        key_sentences = sentences[:max_sentences]
        
        return '。'.join(key_sentences) + '。'
    
    async def _find_insert_position(self, document: Dict[str, Any], 
                                  category: str, title: str) -> Tuple[int, bool]:
        """
        找到合适的插入位置
        
        Args:
            document: 文档对象
            category: 内容类别
            title: 内容标题
            
        Returns:
            (插入位置索引, 类别是否存在)
        """
        content = document.get('body', {}).get('content', [])
        category_name = self.categories.get(category, '其他')
        
        # 查找类别标题
        category_start = None
        category_end = None
        next_category_start = None
        
        current_pos = 1  # 文档开始位置
        
        for element in content:
            if 'paragraph' in element:
                paragraph = element['paragraph']
                text_content = self._extract_text_from_paragraph(paragraph)
                
                # 检查是否是二级标题（类别）
                if text_content.startswith('## '):
                    section_title = text_content[3:].strip()
                    if section_title == category_name:
                        category_start = current_pos
                    elif category_start is not None and next_category_start is None:
                        next_category_start = current_pos
                
                # 更新位置
                current_pos = element.get('endIndex', current_pos)
        
        # 如果找到类别
        if category_start is not None:
            # 在该类别的末尾插入（下一个类别之前或文档末尾）
            if next_category_start is not None:
                return (next_category_start - 1, True)
            else:
                # 在文档末尾插入
                return (current_pos - 1, True)
        
        # 如果没找到类别，在文档末尾创建新类别
        return (current_pos - 1, False)
    
    def _extract_text_from_paragraph(self, paragraph: Dict[str, Any]) -> str:
        """从段落元素中提取文本"""
        text = ""
        for element in paragraph.get('elements', []):
            if 'textRun' in element:
                text += element['textRun'].get('content', '')
        return text.strip()
    
    async def _check_duplicate(self, document: Dict[str, Any], 
                             content_data: Dict[str, Any]) -> bool:
        """
        检查是否有重复内容
        
        Args:
            document: 文档对象
            content_data: 新内容数据
            
        Returns:
            是否重复
        """
        title = content_data.get('title', '')
        url = content_data.get('url', '')
        
        # 获取文档文本
        doc_text = self._get_document_text(document)
        
        # 检查标题是否已存在
        if title and title in doc_text:
            return True
        
        # 检查URL是否已存在
        if url and url in doc_text:
            return True
        
        # 检查arXiv ID
        arxiv_match = re.search(r'(\d{4}\.\d{4,5})', url + ' ' + title)
        if arxiv_match and arxiv_match.group(1) in doc_text:
            return True
        
        return False
    
    def _get_document_text(self, document: Dict[str, Any]) -> str:
        """获取文档的纯文本内容"""
        text = ""
        content = document.get('body', {}).get('content', [])
        
        for element in content:
            if 'paragraph' in element:
                text += self._extract_text_from_paragraph(element['paragraph']) + '\n'
        
        return text
    
    def _create_category_section(self, position: int, category_name: str) -> List[Dict[str, Any]]:
        """创建类别章节的请求"""
        return [
            {
                'insertText': {
                    'location': {'index': position},
                    'text': f"\n## {category_name}\n\n"
                }
            }
        ]
    
    def _format_content_requests(self, start_index: int, content: str, 
                               content_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        创建格式化请求
        
        Args:
            start_index: 开始位置
            content: 内容文本
            content_data: 内容数据
            
        Returns:
            格式化请求列表
        """
        requests = []
        lines = content.split('\n')
        
        current_index = start_index
        
        # 第一行加粗
        if lines:
            first_line = lines[0]
            if first_line.startswith('**') and first_line.endswith('**'):
                # 去掉Markdown标记
                actual_text = first_line[2:-2]
                bold_start = current_index + content.find(actual_text)
                bold_end = bold_start + len(actual_text)
                
                requests.append({
                    'updateTextStyle': {
                        'range': {
                            'startIndex': bold_start,
                            'endIndex': bold_end
                        },
                        'textStyle': {
                            'bold': True
                        },
                        'fields': 'bold'
                    }
                })
        
        return requests
    
    async def search_content(self, query: str) -> List[Dict[str, Any]]:
        """
        搜索文档内容
        
        Args:
            query: 搜索查询
            
        Returns:
            搜索结果
        """
        try:
            document = await self.get_document_content()
            if not document:
                return []
            
            doc_text = self._get_document_text(document)
            
            # 简单的文本搜索
            results = []
            paragraphs = doc_text.split('\n\n')
            
            for i, paragraph in enumerate(paragraphs):
                if query.lower() in paragraph.lower():
                    results.append({
                        'text': paragraph[:200] + '...' if len(paragraph) > 200 else paragraph,
                        'position': i
                    })
            
            return results[:10]  # 限制返回结果数量
            
        except Exception as e:
            logger.error(f"搜索文档失败: {e}")
            return [] 