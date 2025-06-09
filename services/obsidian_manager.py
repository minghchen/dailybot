#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Obsidian 管理器
负责与Obsidian笔记库进行交互，包括读写、文件管理等。
"""

import os
import re
import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger
import frontmatter


class ObsidianManager:
    """Obsidian笔记管理器"""

    def __init__(self, config: Dict[str, Any]):
        """
        初始化Obsidian管理器
        
        Args:
            config: Obsidian相关的配置
        """
        self.config = config
        self.vault_path = Path(config['vault_path'])
        self.llm_service = None
        
        logger.info("Obsidian管理器初始化成功。")

    def set_llm_service(self, llm_service: Any):
        """注入LLM服务实例 (当前未使用，为未来功能保留)"""
        self.llm_service = llm_service

    def _sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符"""
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        if len(filename) > 200:
            filename = filename[:200]
        return filename.strip()

    def get_full_path(self, note_file_config: Dict[str, Any]) -> Path:
        """
        根据笔记文件配置获取在保险库内的完整绝对路径。
        支持在保险库根目录下的指定子文件夹。
        """
        filename = note_file_config.get('filename')
        if not filename:
            raise ValueError(f"Obsidian的note_files配置缺少 'filename' 键: {note_file_config}")
        
        sub_folder_name = note_file_config.get('folder', '')
        
        target_folder = self.vault_path / sub_folder_name
        
        target_folder.mkdir(parents=True, exist_ok=True)
        
        return target_folder / filename

    async def get_document_structure(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """
        从Markdown文件中提取标题层级结构。

        Returns:
            一个字典，包含:
            - 'headings': 标题列表 [{'text', 'level', 'startIndex', 'endIndex' (行号)}]
            - 'end_of_document': 文档末尾的行号。
            - 'raw_content': 文件的原始文本内容。
        """
        if not file_path.exists():
            return {
                'headings': [],
                'end_of_document': 1,
                'raw_content': f"# {file_path.stem}\n\n"
            }
        
        try:
            content = file_path.read_text(encoding='utf-8')
            lines = content.split('\n')
            headings = []
            
            heading_pattern = re.compile(r'^(#{1,6})\s+(.*)')
            
            for i, line in enumerate(lines):
                match = heading_pattern.match(line)
                if match:
                    level = len(match.group(1))
                    text = match.group(2).strip()
                    headings.append({
                        'text': text,
                        'level': level,
                        'startIndex': i + 1,
                        'endIndex': i + 1
                    })
            
            structure = {
                'headings': headings,
                'end_of_document': len(lines) + 1,
                'raw_document': content
            }
            logger.debug(f"从文件 {file_path.name} 提取到 {len(headings)} 个标题。")
            return structure
        except Exception as e:
            logger.error(f"读取或解析Obsidian笔记 {file_path} 失败: {e}")
            return None

    async def execute_save(self, file_path: Path, content_data: Dict[str, Any], insert_location: Dict[str, Any]):
        """
        根据精确指令，将内容保存到指定的Obsidian文件中。

        Args:
            file_path: 目标文件路径。
            content_data: 包含结构化笔记和元数据的内容。
            insert_location: 包含插入位置和操作的指令字典。
        """
        logger.info(f"开始执行Obsidian保存任务, 目标文件: {file_path}")
        
        doc_structure = await self.get_document_structure(file_path)
        if not doc_structure:
            logger.error(f"无法获取 {file_path} 的结构，取消保存。")
            return

        lines = doc_structure['raw_document'].split('\n')
        
        url = content_data.get('url', '')
        title = content_data.get('structured_note', {}).get('title', '')
        if await self.is_duplicate_in_document(file_path, content_data):
             logger.info(f"内容在Obsidian文件 {file_path.name} 中已存在，跳过保存。")
             return

        insert_pos = insert_location['position']
        action = insert_location['action']
        
        new_content_parts = []

        if action == 'create_new_heading':
            heading_level = insert_location.get('new_heading_level', 2)
            heading_text = insert_location.get('new_heading_text', '新分类')
            new_content_parts.append(f"\n{'#' * heading_level} {heading_text}\n")
        
        note_entry = self._build_note_entry(content_data['structured_note'], url, content_data)
        new_content_parts.append(note_entry + "\n")

        insert_index = max(0, insert_pos - 1)
        lines.insert(insert_index, "\n".join(new_content_parts))
        
        updated_content = "\n".join(lines)

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(updated_content)
            logger.info(f"内容 '{title}' 已成功保存到 {file_path.name}")
        except Exception as e:
            logger.error(f"写入文件 {file_path} 时失败: {e}", exc_info=True)

    def _build_note_entry(self, structured_note: Dict[str, str], url: str, content_data: Dict[str, Any]) -> str:
        """
        为单文件模式构建紧凑的笔记条目，并嵌入元数据。
        """
        date = structured_note['date']
        title = structured_note['title']
        link_title = structured_note['link_title']
        summary = structured_note['summary']
        
        metadata_to_embed = {
            "url": url,
            "source_user": content_data.get('source_user', ''),
            "group_name": content_data.get('group_name', ''),
            "is_history": content_data.get('is_history', False)
        }
        metadata_comment = f"<!-- metadata: {json.dumps(metadata_to_embed, ensure_ascii=False)} -->"
        
        return f"""
[自动导入]
**{date} {title}**
{metadata_comment}
[{link_title}]({url})
{summary}
""".strip()

    async def is_duplicate_in_document(self, doc_config: Dict[str, Any], content_data: Dict[str, Any]) -> bool:
        """
        在单个Obsidian笔记文件中检查是否有重复内容。
        """
        file_path = self.get_full_path(doc_config)
        if not file_path.exists():
            return False

        url = content_data.get('url', '')
        title = content_data.get('structured_note', {}).get('title', '')
        if not url and not title:
            return False

        try:
            content = file_path.read_text(encoding='utf-8')
            if url and url in content:
                logger.debug(f"在文件 '{doc_config.get('name')}' 中发现重复内容（URL匹配）: '{url}'")
                return True
            if title and title in content:
                logger.debug(f"在文件 '{doc_config.get('name')}' 中发现疑似重复内容（标题匹配）: '{title}'")
                return True
        except Exception as e:
            logger.error(f"检查Obsidian重复内容时出错: {e}")
        
        return False

    async def get_document_text(self, doc_config: Dict[str, Any]) -> Optional[str]:
        """
        获取单个Obsidian笔记文件的纯文本内容。
        
        Args:
            doc_config: 包含文件路径信息的文件配置。
            
        Returns:
            文件的纯文本内容，如果失败则返回None。
        """
        try:
            file_path = self.get_full_path(doc_config)
            if file_path.exists():
                return file_path.read_text(encoding='utf-8')
            else:
                logger.warning(f"请求的Obsidian笔记文件不存在: {file_path}")
                return None
        except Exception as e:
            logger.error(f"读取Obsidian笔记文件 {doc_config.get('filename')} 时失败: {e}", exc_info=True)
            return None 