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
from typing import Dict, Any, List, Optional, Tuple, Literal
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
        self.llm_service = None
        
        # 初始化服务
        self._init_service()
        
        logger.info(f"Google Docs管理器初始化成功")
    
    def set_llm_service(self, llm_service: Any):
        """注入LLM服务实例"""
        self.llm_service = llm_service

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
    
    async def execute_save(self, document_id: str, content_data: Dict[str, Any], 
                           insert_location: Dict[str, Any], document: Optional[Dict[str, Any]] = None):
        """
        将内容和格式化请求转换为Google Docs API调用。

        Args:
            document_id: 要保存到的文档ID
            content_data: 包含'structured_note'和'url'的内容数据
            insert_location: 包含插入位置和操作指令的字典
            document: (可选) 预加载的文档对象，避免重复请求
        """
        logger.info(f"开始执行Google Docs API调用, 目标文档ID: {document_id}")

        # 如果没有提供预加载的文档，需要先获取它以进行查重
        doc_to_check = document
        if not doc_to_check:
            doc_to_check = await self.get_document_content(document_id)
            if not doc_to_check:
                logger.error(f"无法获取文档 {document_id} 以检查重复项，取消保存。")
                return

        if await self.is_duplicate_in_document(self.config, content_data):
            log_title = content_data.get('structured_note', {}).get('title', '未知标题')
            logger.info(f"内容 '{log_title}' 已存在于文档中，跳过保存。")
            return

        try:
            requests = []
            insert_position = insert_location['position']
            action = insert_location['action']

            # 如果需要创建新标题
            if action == 'create_new_heading':
                heading_text = insert_location.get('new_heading_text', '新分类')
                heading_level = insert_location.get('new_heading_level', 2)
                heading_style = f'HEADING_{heading_level}'
                logger.info(f"将在索引 {insert_position} 创建新的 {heading_style} 标题: '{heading_text}'")

                # 确保标题在新行
                heading_text_formatted = f"{heading_text}\n"
                
                requests.append({
                    'insertText': {
                        'location': {'index': insert_position},
                        'text': heading_text_formatted
                    }
                })
                requests.append({
                    'updateParagraphStyle': {
                        'range': {
                            'startIndex': insert_position,
                            'endIndex': insert_position + len(heading_text_formatted) -1
                        },
                        'paragraphStyle': {'namedStyleType': heading_style},
                        'fields': 'namedStyleType'
                    }
                })
                # 更新插入位置到新标题之后
                insert_position += len(heading_text_formatted)

            # 在实际内容前插入一个换行符，确保与标题或之前的内容有间距
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

            # --- 关键修复：先设置段落为普通文本，再应用局部样式 ---
            
            # 1. 将新插入的所有内容段落设置为普通文本
            content_start_index = insert_position
            content_end_index = content_start_index + len(final_content)
            requests.append({
                'updateParagraphStyle': {
                    'range': {
                        'startIndex': content_start_index,
                        'endIndex': content_end_index
                    },
                    'paragraphStyle': { 'namedStyleType': 'NORMAL_TEXT' },
                    'fields': 'namedStyleType'
                }
            })
            
            # 2. 对第一行应用加粗
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

            # 3. 对第二行应用链接
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
            if requests:
                result = self.service.documents().batchUpdate(
                    documentId=document_id,
                    body={'requests': requests}
                ).execute()
                logger.info(f"Google Docs API调用成功，内容已保存: '{log_title_final}'")
            else:
                logger.warning("没有生成任何更新请求，不执行任何操作。")
            
        except Exception as e:
            logger.error(f"保存内容到Google Docs ({document_id})失败: {e}", exc_info=True)
    
    def _format_structured_content(self, note_data: Dict[str, Any], url: str) -> Tuple[str, Dict[str, Tuple[int, int]]]:
        """
        根据结构化的笔记数据生成格式化文本和需要特殊格式的范围。
        返回 (完整文本, {'bold': (start, end), 'link': (start, end)})
        """
        date = note_data.get('date', '')
        title = note_data.get('title', '（无标题）')
        link_title = note_data.get('link_title', '（无链接标题）')
        summary = note_data.get('summary', '（无摘要）')

        # 构建各个部分
        prefix_line = "[自动导入]"
        first_line = f"{date} {title}"
        second_line = f"{link_title}"
        
        # 组装最终文本，并为新前缀调整后续所有部分的偏移量
        final_text = f"{prefix_line}\n{first_line}\n{second_line}\n{summary}\n\n"
        
        prefix_len = len(prefix_line) + 1 # +1 for newline

        # 计算需要格式化的范围
        bold_start = prefix_len
        bold_end = bold_start + len(first_line)
        
        link_start = bold_end + 1
        link_end = link_start + len(second_line)

        format_ranges = {
            'bold': (bold_start, bold_end),
            'link': (link_start, link_end)
        }

        return final_text, format_ranges
    
    def _extract_text_from_paragraph(self, paragraph: Dict[str, Any]) -> str:
        """从段落元素中提取文本"""
        text = ""
        for element in paragraph.get('elements', []):
            if 'textRun' in element:
                text += element['textRun'].get('content', '')
        return text.strip()
    
    async def is_duplicate_in_document(self, doc_config: Dict[str, Any], content_data: Dict[str, Any]) -> bool:
        """
        在单个Google Doc文档中检查是否有重复内容。
        
        Args:
            doc_config: 包含 'document_id' 的文件配置。
            content_data: 新内容数据。
            
        Returns:
            是否重复。
        """
        document_id = doc_config.get('document_id')
        if not document_id:
            return False

        document = await self.get_document_content(document_id)
        if not document:
            return False # 获取文档失败，假定不重复

        note_data = content_data.get('structured_note', {})
        title_to_check = note_data.get('title', '')
        url_to_check = content_data.get('url', '')
        
        if not url_to_check and not title_to_check:
            return False

        content = document.get('body', {}).get('content', [])
        doc_text = self._get_document_text(document)
        
        if title_to_check and title_to_check in doc_text:
            logger.debug(f"在文档 '{doc_config.get('name')}' 中发现疑似重复内容（标题匹配）: '{title_to_check}'")
            return True
            
        if url_to_check:
            for element in content:
                if 'paragraph' in element:
                    for para_element in element.get('paragraph', {}).get('elements', []):
                        if 'textRun' in para_element:
                            text_style = para_element.get('textRun', {}).get('textStyle', {})
                            if 'link' in text_style and text_style['link'].get('url') == url_to_check:
                                logger.debug(f"在文档 '{doc_config.get('name')}' 中发现重复内容（URL匹配）: '{url_to_check}'")
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
    
    async def get_document_text(self, doc_config: Dict[str, Any]) -> Optional[str]:
        """
        获取单个Google Doc文档的纯文本内容。
        
        Args:
            doc_config: 包含'document_id'的笔记文件配置。
            
        Returns:
            文档的纯文本内容，如果失败则返回None。
        """
        document_id = doc_config.get('document_id')
        if not document_id:
            logger.warning(f"Google Docs配置缺少 'document_id': {doc_config}")
            return None

        try:
            document = await self.get_document_content(document_id)
            if not document:
                return None
            return self._get_document_text(document)
        except Exception as e:
            logger.error(f"获取文档 {document_id} 文本内容时失败: {e}")
            return None

    async def get_document_structure(self, document_id: str) -> Optional[Dict[str, Any]]:
        """
        从文档中提取标题层级结构和文档末尾位置。

        Returns:
            一个字典，包含:
            - 'headings': 标题列表 [{'text', 'level', 'startIndex', 'endIndex'}]
            - 'end_of_document': 文档末尾的索引。
            - 'raw_document': 原始文档对象，以备后用。
        """
        document = await self.get_document_content(document_id)
        if not document:
            return None

        headings = []
        content = document.get('body', {}).get('content', [])
        for element in content:
            if 'paragraph' in element:
                paragraph = element['paragraph']
                style = paragraph.get('paragraphStyle', {})
                named_style = style.get('namedStyleType')
                
                if named_style and named_style.startswith('HEADING_'):
                    try:
                        level = int(named_style.split('_')[1])
                        text = self._extract_text_from_paragraph(paragraph)
                        if text:
                            headings.append({
                                'text': text,
                                'level': level,
                                'startIndex': element.get('startIndex'),
                                'endIndex': element.get('endIndex')
                            })
                    except (ValueError, IndexError):
                        continue
        
        doc_end_index = content[-1].get('endIndex', 1) if content else 1
        
        structure = {
            'headings': headings,
            'end_of_document': doc_end_index,
            'raw_document': document
        }
        
        logger.debug(f"从文档 {document_id} 提取到 {len(headings)} 个标题，文档结构解析完毕。")
        return structure 