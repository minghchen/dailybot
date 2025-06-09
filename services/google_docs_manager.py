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
        
        logger.info(f"Google Docs管理器初始化成功")
    
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
    
    async def get_document_content(self, document_id: str) -> Dict[str, Any]:
        """
        获取文档内容
        
        Returns:
            文档内容
        """
        try:
            document = self.service.documents().get(documentId=document_id).execute()
            return document
        except HttpError as error:
            logger.error(f'获取文档 {document_id} 失败: {error}')
            return None
    
    async def save_content(self, document_id: str, content_data: Dict[str, Any], document: Optional[Dict[str, Any]] = None):
        """
        保存内容到Google Docs，智能插入到合适位置
        
        Args:
            document_id: 要保存到的文档ID
            content_data: 内容数据
            document: (可选) 预加载的文档对象，避免重复请求
        """
        logger.info(f"GoogleDocsManager 开始处理保存任务，目标文档ID: {document_id}")
        try:
            # 如果没有传入文档对象，则获取
            if document is None:
                document = await self.get_document_content(document_id)
                if not document:
                    logger.error(f"无法获取文档内容: {document_id}，保存中断。")
                    return
            
            # 查重逻辑已移至NoteManager，此处不再执行
            
            # 分析文档结构，找到合适的插入位置
            # 注意: category现在由NoteManager的动态分类逻辑提供
            category_name = content_data.get('category', '未分类')
            insert_position, category_exists = await self._find_insert_position(document, category_name)
            logger.info(f"计算出的插入位置: {insert_position}, 类别 '{category_name}' 是否已存在: {category_exists}")
            
            # 构建请求
            requests = []
            
            # 如果类别不存在，先创建类别标题
            if not category_exists:
                logger.info(f"类别 '{category_name}' 不存在，将在文档末尾创建新的二级标题。")
                
                # 如果文档不是空的，先加一个换行，确保新标题在新的一行
                doc_end_index = document.get('body', {}).get('content', [])[-1].get('endIndex', 1) -1
                if doc_end_index > 1:
                    requests.append({
                        'insertText': {
                            'location': {'index': doc_end_index},
                            'text': '\n'
                        }
                    })
                    insert_position = doc_end_index + 1
                
                heading_text = f"{category_name}\n"
                requests.append({
                    'insertText': {
                        'location': {'index': insert_position},
                        'text': heading_text
                    }
                })
                requests.append({
                    'updateParagraphStyle': {
                        'range': {
                            'startIndex': insert_position,
                            'endIndex': insert_position + len(heading_text) - 1 # -1 to not include newline
                        },
                        'paragraphStyle': {'namedStyleType': 'HEADING_2'},
                        'fields': 'namedStyleType'
                    }
                })
                insert_position += len(heading_text)
            
            # 插入一个换行符，确保内容和标题（或之前的内容）分开
            requests.append({
                'insertText': {
                    'location': {'index': insert_position},
                    'text': '\n'
                }
            })
            insert_position += 1

            # --- 使用结构化数据构建内容和格式化请求 ---
            note_data = content_data['structured_note']
            url = content_data.get('url', '') # 从上层获取URL
            final_content, format_ranges = self._format_structured_content(note_data, url)
            
            # 插入格式化后的文本
            requests.append({
                'insertText': {
                    'location': {'index': insert_position},
                    'text': final_content
                }
            })
            
            # 对第一行应用加粗
            bold_range = format_ranges.get('bold')
            if bold_range:
                requests.append({
                    'updateTextStyle': {
                        'range': {
                            'startIndex': insert_position + bold_range[0],
                            'endIndex': insert_position + bold_range[1]
                        },
                        'textStyle': {'bold': True},
                        'fields': 'bold'
                    }
                })

            # 对第二行应用链接
            link_range = format_ranges.get('link')
            if link_range:
                requests.append({
                    'updateTextStyle': {
                        'range': {
                            'startIndex': insert_position + link_range[0],
                            'endIndex': insert_position + link_range[1]
                        },
                        'textStyle': {
                            'link': {'url': url}
                        },
                        'fields': 'link'
                    }
                })

            # 执行批量更新
            log_title_final = note_data.get('title', '未知标题')
            logger.info(f"准备执行 {len(requests)} 个API请求来更新文档...")
            result = self.service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()
            
            logger.info(f"Google Docs API调用成功，内容已保存: '{log_title_final}'")
            
        except Exception as e:
            logger.error(f"保存内容到Google Docs ({document_id})失败: {e}", exc_info=True)
    
    def _format_structured_content(self, note_data: Dict[str, Any], url: str) -> (str, Dict[str, Tuple[int, int]]):
        """
        根据结构化的笔记数据生成格式化文本和需要特殊格式的范围。
        返回 (完整文本, {'bold': (start, end), 'link': (start, end)})
        """
        date = note_data.get('date', '')
        title = note_data.get('title', '（无标题）')
        link_title = note_data.get('link_title', '（无链接标题）')
        summary = note_data.get('summary', '（无摘要）')

        # 构建各个部分
        first_line = f"{date} {title}"
        second_line = f"{link_title}" # 这里只保留纯文本
        
        # 组装最终文本
        final_text = f"{first_line}\n{second_line}\n{summary}\n\n"
        
        # 计算需要格式化的范围
        bold_start = 0
        bold_end = len(first_line)
        
        link_start = bold_end + 1 # +1 是因为换行符
        link_end = link_start + len(second_line)

        format_ranges = {
            'bold': (bold_start, bold_end),
            'link': (link_start, link_end)
        }

        return final_text, format_ranges
    
    def _format_content(self, content_data: Dict[str, Any]) -> str:
        """
        【已废弃】现在使用 _format_structured_content
        """
        return ""
    
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
                                  category: str) -> Tuple[int, bool]:
        """
        在文档中找到指定类别的插入位置。

        核心逻辑:
        1. 遍历所有段落，寻找样式为 HEADING_2 的标题。
        2. 使用不区分大小写和前后空格的方式进行稳健比较。
        3. 如果找到匹配的标题，返回该标题段落的 endIndex，新内容将在此之后插入。
        4. 如果未找到，返回文档末尾的位置，并标记为"类别不存在"。
        
        Args:
            document: 文档对象
            category: 要查找的类别名称
            
        Returns:
            (插入位置索引, 类别是否存在)
        """
        content = document.get('body', {}).get('content', [])
        
        for element in reversed(content): # 从后往前找，更快找到末尾的类别
            if 'paragraph' in element:
                paragraph = element['paragraph']
                style = paragraph.get('paragraphStyle', {})
                
                if style.get('namedStyleType') == 'HEADING_2':
                    text_content = self._extract_text_from_paragraph(paragraph)
                    
                    # 增加日志，暴露从文档中提取到的原始标题文本
                    logger.debug(f"正在检查文档标题: Raw='{text_content.encode('unicode_escape').decode()}', Cleaned='{text_content.strip()}'")

                    # 稳健比较：忽略首尾空格和大小写，并移除所有换行符
                    clean_doc_title = re.sub(r'\s+', ' ', text_content).strip().lower()
                    clean_category = re.sub(r'\s+', ' ', category).strip().lower()

                    if clean_doc_title == clean_category:
                        # 找到类别，返回该段落的结束位置作为插入点
                        insert_index = element.get('endIndex', 1)
                        logger.debug(f"找到已存在的类别 '{category}'，将在索引 {insert_index} 后插入。")
                        return (insert_index, True)

        # 如果未找到任何匹配的类别，返回文档末尾的位置
        doc_end_index = content[-1].get('endIndex', 1) if content else 1
        logger.debug(f"未找到类别 '{category}'，将在文档末尾（索引 {doc_end_index}）创建。")
        return (doc_end_index, False)
    
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
        # 修正：从结构化数据中获取标题和URL
        note_data = content_data.get('structured_note', {})
        title_to_check = note_data.get('title', '')
        # URL在顶层，因为它是链接本身，不属于LLM生成的内容
        url_to_check = content_data.get('url', '')
        
        if not url_to_check and not title_to_check:
            return False

        content = document.get('body', {}).get('content', [])
        doc_text = self._get_document_text(document)
        
        # 检查标题（效率较低，但作为备用）
        if title_to_check and title_to_check in doc_text:
            logger.info(f"发现疑似重复内容（标题匹配）: '{title_to_check}'")
            return True
            
        # 检查URL（更可靠）
        if url_to_check:
            for element in content:
                if 'paragraph' in element:
                    for para_element in element.get('paragraph', {}).get('elements', []):
                        if 'textRun' in para_element:
                            text_style = para_element.get('textRun', {}).get('textStyle', {})
                            if 'link' in text_style and text_style['link'].get('url') == url_to_check:
                                logger.info(f"发现重复内容（URL完全匹配）: '{url_to_check}'")
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
        """【已废弃】创建类别章节的请求"""
        # 此方法已废弃，逻辑已内联到 save_content 中并得到改进
        return []
    
    async def search_content(self, document_id: str, query: str) -> List[Dict[str, Any]]:
        """
        搜索文档内容
        
        Args:
            document_id: 要搜索的文档ID
            query: 搜索查询
            
        Returns:
            搜索结果
        """
        try:
            document = await self.get_document_content(document_id)
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
            logger.error(f"搜索文档 {document_id} 失败: {e}")
            return []
    
    async def get_document_headings(self, document_id: str) -> List[str]:
        """从文档中提取所有二级标题（HEADING_2）"""
        document = await self.get_document_content(document_id)
        if not document:
            return []

        headings = []
        content = document.get('body', {}).get('content', [])
        for element in content:
            if 'paragraph' in element:
                paragraph = element['paragraph']
                # Google Docs的标题有特定的段落样式
                if paragraph.get('paragraphStyle', {}).get('namedStyleType') == 'HEADING_2':
                    text_content = self._extract_text_from_paragraph(paragraph)
                    if text_content: # 确保标题不为空
                        headings.append(text_content)
        
        logger.debug(f"从文档 {document_id} 提取到以下标题: {headings}")
        return headings 