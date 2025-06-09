#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
笔记管理器
负责管理笔记的读写，支持Obsidian和Google Docs
支持多文件管理和智能分类
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple
from loguru import logger
import frontmatter
import markdown
import hashlib

from services.google_docs_manager import GoogleDocsManager


class NoteManager:
    """笔记管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化笔记管理器
        
        Args:
            config: 配置信息
        """
        self.config = config
        self.note_backend = config.get('note_backend', 'obsidian')
        self.llm_service = None # Will be injected

        # 恢复到之前的初始化逻辑以修复导入错误
        if self.note_backend == 'obsidian':
            self._init_obsidian(config.get('obsidian', {}))
        elif self.note_backend == 'google_docs':
            self.google_docs_manager = GoogleDocsManager(config.get('google_docs', {}))
            self.note_files = config.get('google_docs', {}).get('note_documents', [])
        else:
            raise ValueError(f"不支持的笔记后端: {self.note_backend}")

        logger.info(f"笔记管理器初始化成功，使用后端: {self.note_backend}")
    
    def set_llm_service(self, llm_service):
        """设置LLM服务（用于智能分类）"""
        self.llm_service = llm_service
    
    def _init_obsidian(self, obsidian_config: Dict[str, Any]):
        """初始化Obsidian配置"""
        self.vault_path = Path(obsidian_config['vault_path'])
        self.daily_notes_folder = self.vault_path / obsidian_config['daily_notes_folder']
        self.kb_folder = self.vault_path / obsidian_config['knowledge_base_folder']
        
        # 笔记文件配置
        self.note_files = obsidian_config.get('note_files', [])
        
        # 确保目录存在
        self._ensure_directories()
        
        # 如果没有配置笔记文件，使用旧的文件夹扫描方式
        if not self.note_files:
            logger.warning("未配置note_files，将使用文件夹扫描模式")
            self._scan_categories()
    
    def _scan_categories(self) -> Dict[str, str]:
        """
        扫描知识库文件夹，动态获取现有分类（兼容旧版本）
        
        Returns:
            分类映射字典
        """
        self.categories = {}
        
        try:
            if self.kb_folder.exists():
                # 遍历知识库文件夹下的所有子文件夹
                for item in self.kb_folder.iterdir():
                    if item.is_dir() and not item.name.startswith('.'):
                        # 使用文件夹名作为分类
                        category_key = self._folder_name_to_key(item.name)
                        self.categories[category_key] = item.name
                        logger.debug(f"发现分类: {category_key} -> {item.name}")
            
            # 如果没有找到任何分类，创建默认分类
            if not self.categories:
                self.categories = {
                    'papers': '学术论文',
                    'articles': '文章资料',
                    'videos': '视频笔记',
                    'others': '其他资料'
                }
                logger.info("未找到现有分类，使用默认分类")
            else:
                # 确保至少有一个"其他"分类
                if 'others' not in self.categories and '其他' not in self.categories.values():
                    self.categories['others'] = '其他资料'
            
        except Exception as e:
            logger.error(f"扫描分类时出错: {e}")
            # 使用默认分类
            self.categories = {'others': '其他资料'}
        
        logger.info(f"当前分类: {self.categories}")
        return self.categories
    
    def _folder_name_to_key(self, folder_name: str) -> str:
        """
        将文件夹名转换为分类键
        
        Args:
            folder_name: 文件夹名
            
        Returns:
            分类键
        """
        # 简单的转换规则
        name_lower = folder_name.lower()
        
        # 常见映射
        mappings = {
            '学术论文': 'papers',
            '论文': 'papers',
            'papers': 'papers',
            '文章资料': 'articles',
            '文章': 'articles',
            'articles': 'articles',
            '视频笔记': 'videos',
            '视频': 'videos',
            'videos': 'videos',
            '技术': 'technology',
            'tech': 'technology',
            '应用': 'application',
            '理论': 'theory',
            '产业': 'industry',
            '其他': 'others',
            'others': 'others'
        }
        
        for key, value in mappings.items():
            if key in name_lower:
                return value
        
        # 如果没有匹配，使用文件夹名的简化版本作为键
        return re.sub(r'[^\w]', '_', folder_name.lower())
    
    def _ensure_directories(self):
        """确保必要的目录存在"""
        # 创建日记目录
        self.daily_notes_folder.mkdir(parents=True, exist_ok=True)
        
        # 创建知识库目录
        self.kb_folder.mkdir(parents=True, exist_ok=True)
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        清理文件名，移除非法字符
        
        Args:
            filename: 原始文件名
            
        Returns:
            清理后的文件名
        """
        # 移除或替换非法字符
        filename = re.sub(r'[<>:"/\\|?*]', '', filename)
        # 限制长度
        if len(filename) > 200:
            filename = filename[:200]
        return filename.strip()
    
    async def save_content(self, content_data: Dict[str, Any]):
        """
        保存提取的内容到指定的笔记后端
        
        Args:
            content_data: 提取的内容数据
        """
        logger.info(f"NoteManager 开始保存内容到 {self.note_backend}...")
        logger.debug(f"待保存数据: Title='{content_data.get('title', '')}', Type='{content_data.get('type', '')}', Category='{content_data.get('category', '')}'")
        try:
            if self.note_backend == 'obsidian':
                await self._save_to_obsidian(content_data)
            elif self.note_backend == 'google_docs':
                await self._save_to_google_docs(content_data)
            
            log_title = content_data.get('structured_note', {}).get('title', '未知标题')
            logger.info(f"NoteManager 确认内容 '{log_title}' 已成功交由 {self.note_backend} 处理。")
        except Exception as e:
            logger.error(f"NoteManager 在调用后端保存方法时发生异常: {e}", exc_info=True)
            raise # 重新抛出异常，让上层知道发生了错误
    
    async def _select_note_file_and_category(self, content_data: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str]:
        """
        使用LLM智能选择笔记文件和类别
        
        Args:
            content_data: 内容数据
            
        Returns:
            (选中的笔记文件配置, 类别名称)
        """
        if not self.llm_service:
            # 如果没有LLM服务，使用默认选择
            if self.note_files:
                return self.note_files[0], "其他"
            else:
                return None, "其他"
        
        # 构建选择提示
        title = content_data.get('title', '')
        summary = content_data.get('summary', '')
        url = content_data.get('url', '')
        
        # 获取可用的笔记文件
        if self.note_files:
            files_info = "\n".join([
                f"{i+1}. {f['name']}: {f['description']}"
                for i, f in enumerate(self.note_files)
            ])
            
            prompt = f"""请根据以下内容，选择最合适的笔记文件：

内容标题：{title}
内容摘要：{summary[:300]}
来源URL：{url}

可选的笔记文件：
{files_info}

请回答：
1. 选择的文件编号（如：1）
2. 在该文件中应该归类到哪个章节或标题下（如果是新类别，请给出建议的标题）

格式：
文件：[编号]
类别：[类别名称]"""
            
            try:
                response = await self.llm_service.chat(prompt)
                
                # 解析响应
                file_match = re.search(r'文件[：:]\s*(\d+)', response)
                category_match = re.search(r'类别[：:]\s*(.+)', response)
                
                if file_match and category_match:
                    file_idx = int(file_match.group(1)) - 1
                    category = category_match.group(1).strip()
                    
                    if 0 <= file_idx < len(self.note_files):
                        return self.note_files[file_idx], category
                
            except Exception as e:
                logger.error(f"LLM选择文件失败: {e}")
        
        # 默认选择
        if self.note_files:
            return self.note_files[0], "其他"
        else:
            return None, "其他"
    
    async def _save_to_google_docs(self, content_data: Dict[str, Any]):
        """
        保存内容到Google Docs
        """
        try:
            # 自动选择第一个文档作为目标
            if not self.note_files:
                raise ValueError("Google Docs配置中未找到任何note_documents，请检查config.json。")
            
            document_id = self.note_files[0].get('document_id')
            if not document_id:
                raise ValueError("在Google Docs配置的第一个note_document中未找到有效的'document_id'字段，请检查config.json。")

            # --- 优化流程：先获取文档，进行查重 ---
            document = await self.google_docs_manager.get_document_content(document_id)
            if not document:
                raise ConnectionError(f"无法获取文档 {document_id} 的内容。")

            if await self.google_docs_manager._check_duplicate(document, content_data):
                log_title = content_data.get('structured_note', {}).get('title', '未知标题')
                logger.info(f"内容 '{log_title}' 已存在于文档中，跳过保存。")
                return # 查重成功，直接返回

            # --- LLM动态分类逻辑 ---
            if self.llm_service:
                logger.info(f"开始为文档 '{document_id}' 进行LLM动态分类...")
                
                # 1. 获取文档的现有标题
                existing_headings = await self.google_docs_manager.get_document_headings(document_id)
                
                # 2. 构建智能分类的Prompt
                structured_note = content_data.get('structured_note', {})
                title = structured_note.get('title', '')
                summary = structured_note.get('summary', '')
                
                prompt = f"""你是一个智能笔记分类助手。请根据以下内容的标题和摘要，决定它应该属于哪个类别。

[内容信息]
标题: {title}
摘要: {summary}

[文档中已有的类别（请优先选择）]
{', '.join(existing_headings) if existing_headings else '（本文档尚无分类）'}

[如果以上类别都不合适，可以从以下通用分类中选择或创造一个更合适的新分类]
- AI方向的时讯和研究
- LLM
- LLM Agent
- Robotics
- 世界模型
- 应用案例
- 技术进展

你的任务：
1. 分析内容，理解其核心主题。
2. 对比内容和[文档中已有的类别]，如果匹配，请直接返回那个类别名称。
3. 如果不匹配，请从[通用分类]中选择一个最合适的，或者根据内容自己创建一个简洁、明确的新类别（例如"多模态学习"）。
4. **请只返回最终的类别名称，不要包含任何其他解释或前缀。**

类别名称："""
                
                # 3. 调用LLM获取分类
                try:
                    chosen_category = await self.llm_service.chat(prompt)
                    chosen_category = chosen_category.strip().replace('类别名称：', '').strip()
                    logger.info(f"LLM建议的分类是: '{chosen_category}'")
                    
                    # 4. 更新content_data中的分类
                    content_data['category'] = chosen_category
                except Exception as e:
                    logger.error(f"LLM动态分类失败，将使用默认分类: {e}")
                    content_data['category'] = '未分类'
            else:
                logger.warning("LLM服务未设置，将使用默认分类。")
                content_data['category'] = content_data.get('category', '未分类')

            # --- 最终保存，传入已获取的文档避免重复请求 ---
            await self.google_docs_manager.save_content(
                document_id, 
                content_data, 
                document=document
            )

        except Exception as e:
            # 只记录日志，然后将原始异常重新抛出
            logger.error(f"保存内容到Google Docs时出错: {e}", exc_info=True)
            raise
    
    async def _save_to_obsidian(self, content_data: Dict[str, Any]):
        """保存到Obsidian"""
        try:
            title = content_data.get('title', '未命名内容')
            url = content_data.get('url', '')
            summary = content_data.get('summary', '')
            context = content_data.get('context', '')
            extracted_at = content_data.get('extracted_at', datetime.now())
            raw_content = content_data.get('raw_content', '')
            source_user = content_data.get('source_user', '')
            group_name = content_data.get('group_name', '')
            is_history = content_data.get('is_history', False)
            article_title = content_data.get('article_title', '')
            content_type = content_data.get('type', 'web_link')
            
            # 检查是否是重复内容
            if await self._is_duplicate_content(url, title):
                logger.info(f"跳过重复内容: {title}")
                return
            
            # 智能选择笔记文件和类别
            selected_file, category = await self._select_note_file_and_category(content_data)
            
            # 如果有配置笔记文件，使用新的保存方式
            if selected_file:
                await self._save_to_note_file(
                    selected_file, category, content_data,
                    title, url, summary, context, extracted_at,
                    article_title, content_type, source_user, 
                    group_name, is_history
                )
            else:
                # 使用旧的文件夹方式
                # 构建笔记内容
                note_content = self._build_formatted_note_content(
                    title=title,
                    url=url,
                    summary=summary,
                    context=context,
                    extracted_at=extracted_at,
                    raw_content=raw_content,
                    article_title=article_title,
                    content_type=content_type,
                    source_user=source_user,
                    group_name=group_name,
                    is_history=is_history
                )
                
                # 保存到知识库
                kb_path = self._get_kb_note_path(title, category)
                await self._save_note(kb_path, note_content, content_data)
            
            # 在日记中添加引用（仅对非历史消息）
            if not is_history:
                await self._add_to_daily_note(title, None, extracted_at, group_name)
            
            logger.info(f"内容已保存到Obsidian笔记")
            
        except Exception as e:
            logger.error(f"保存内容到Obsidian时出错: {e}", exc_info=True)
            raise
    
    async def _save_to_note_file(self, note_file: Dict[str, Any], category: str, 
                                content_data: Dict[str, Any], title: str, url: str, 
                                summary: str, context: str, extracted_at: datetime,
                                article_title: str, content_type: str, source_user: str,
                                group_name: str, is_history: bool):
        """保存到指定的笔记文件"""
        # 构建笔记文件路径
        note_path = self.kb_folder / note_file['filename']
        
        # 读取现有内容
        existing_content = ""
        existing_categories = {}
        
        if note_path.exists():
            existing_content = note_path.read_text(encoding='utf-8')
            # 解析现有的类别结构
            existing_categories = self._parse_note_categories(existing_content)
        else:
            # 创建新文件，添加标题
            existing_content = f"# {note_file['name']}\n\n"
        
        # 构建新条目
        new_entry = self._build_note_entry(
            title=title,
            url=url,
            summary=summary,
            article_title=article_title,
            content_type=content_type,
            extracted_at=extracted_at
        )
        
        # 将新条目插入到合适的位置
        updated_content = self._insert_entry_to_category(
            existing_content, 
            category, 
            new_entry,
            existing_categories
        )
        
        # 保存更新后的内容
        with open(note_path, 'w', encoding='utf-8') as f:
            f.write(updated_content)
        
        logger.info(f"内容已添加到 {note_file['name']} 的 {category} 类别下")
    
    def _parse_note_categories(self, content: str) -> Dict[str, int]:
        """
        解析笔记中的类别结构
        
        Returns:
            类别名称到行号的映射
        """
        categories = {}
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            # 查找二级标题作为类别
            if line.startswith('## '):
                category_name = line[3:].strip()
                categories[category_name] = i
        
        return categories
    
    def _build_note_entry(self, title: str, url: str, summary: str,
                         article_title: str, content_type: str, 
                         extracted_at: datetime) -> str:
        """构建笔记条目"""
        # 提取日期（精确到月份）
        if 'arxiv' in content_type or 'arxiv' in url.lower():
            # 尝试从URL或标题提取arxiv日期
            date_match = re.search(r'(\d{2})(\d{2})\.(\d{4,5})', url + ' ' + title)
            if date_match:
                year = f"20{date_match.group(1)}"  # 假设是20xx年
                month = date_match.group(2)
                date_str = f"{year}-{month}"
            else:
                date_str = extracted_at.strftime('%Y-%m')
        else:
            date_str = extracted_at.strftime('%Y-%m-%d')
        
        # 构建链接行
        if article_title and article_title != title:
            link_line = f"[{article_title}]({url})"
        else:
            source = self._extract_source_from_url(url)
            link_line = f"[{source}]({url})"
        
        # 构建条目
        entry = f"""
**{date_str} {title}**  
{link_line}  
{summary}
"""
        
        return entry.strip()
    
    def _insert_entry_to_category(self, content: str, category: str, 
                                 new_entry: str, existing_categories: Dict[str, int]) -> str:
        """将新条目插入到指定类别"""
        lines = content.split('\n')
        
        if category in existing_categories:
            # 找到类别的位置
            category_line = existing_categories[category]
            
            # 找到下一个类别的位置或文件结尾
            next_category_line = len(lines)
            for cat, line_num in existing_categories.items():
                if line_num > category_line:
                    next_category_line = min(next_category_line, line_num)
            
            # 在类别后插入新条目
            # 查找类别下的第一个非空行
            insert_position = category_line + 1
            while insert_position < next_category_line and insert_position < len(lines):
                if lines[insert_position].strip():
                    break
                insert_position += 1
            
            # 插入新条目
            lines.insert(insert_position, '\n' + new_entry + '\n')
        else:
            # 创建新类别
            # 在文件末尾添加新类别
            if lines and lines[-1].strip():  # 如果最后一行不是空行
                lines.append('')
            
            lines.append(f'## {category}')
            lines.append('')
            lines.append(new_entry)
            lines.append('')
        
        return '\n'.join(lines)
    
    def _build_formatted_note_content(self, title: str, url: str, summary: str,
                                    context: str, extracted_at: datetime, 
                                    raw_content: str = '', article_title: str = '', 
                                    content_type: str = 'web_link', source_user: str = '', 
                                    group_name: str = '', is_history: bool = False) -> str:
        """构建格式化的笔记内容（用于旧的文件夹方式）"""
        # 提取日期（精确到月份）
        if 'arxiv' in content_type or 'arxiv' in url.lower():
            # 尝试从URL或标题提取arxiv日期
            date_match = re.search(r'(\d{2})(\d{2})\.(\d{4,5})', url + ' ' + title)
            if date_match:
                year = f"20{date_match.group(1)}"  # 假设是20xx年
                month = date_match.group(2)
                date_str = f"{year}-{month}"
            else:
                # 如果无法解析，使用当前日期
                date_str = extracted_at.strftime('%Y-%m')
        else:
            # 使用提取日期
            if isinstance(extracted_at, str):
                extracted_at = datetime.fromisoformat(extracted_at)
            date_str = extracted_at.strftime('%Y-%m-%d')
        
        # 构建标签
        tags = []
        if 'arxiv' in url.lower():
            tags.append('#论文')
        elif 'bilibili' in url.lower():
            tags.append('#视频')
        elif 'mp.weixin' in url.lower():
            tags.append('#公众号')
        else:
            tags.append('#网页')
        
        if group_name:
            tags.append(f'#群组/{self._sanitize_filename(group_name)}')
        
        if is_history:
            tags.append('#历史记录')
        
        # 构建第二行（文章链接）
        if article_title and article_title != title:
            link_line = f"[{article_title}]({url})"
        else:
            # 从URL中提取来源
            source = self._extract_source_from_url(url)
            link_line = f"[{source}]({url})"
        
        # 确保标题完整（特别是论文标题）
        # 如果标题被截断（以...结尾），尝试从原始内容中获取完整标题
        if title.endswith('...') and raw_content:
            # 尝试从原始内容中提取完整标题
            full_title = self._extract_full_title(raw_content, title)
            if full_title:
                title = full_title
        
        # 构建笔记
        content = f"""# {title}

{' '.join(tags)}

**{date_str} {title}**  
{link_line}  
{summary}

## 元信息

- **分享者**: {source_user}
- **来源群组**: {group_name}
- **提取时间**: {extracted_at.strftime('%Y-%m-%d %H:%M')}

## 上下文

{context}

---

*此笔记由 DailyBot 自动生成{' (从历史记录导入)' if is_history else ''}*
"""
        
        return content
    
    def _extract_full_title(self, content: str, partial_title: str) -> Optional[str]:
        """
        从内容中提取完整标题
        
        Args:
            content: 原始内容
            partial_title: 部分标题
            
        Returns:
            完整标题（如果找到）
        """
        # 移除...后缀
        partial = partial_title.rstrip('.')
        
        # 在内容中查找包含部分标题的完整行
        lines = content.split('\n')
        for line in lines[:20]:  # 只在前20行查找
            if partial in line and len(line) > len(partial_title):
                # 清理并返回
                full_title = line.strip()
                # 移除常见的标题前缀
                for prefix in ['Title:', 'title:', '标题：', '论文：']:
                    if full_title.startswith(prefix):
                        full_title = full_title[len(prefix):].strip()
                return full_title
        
        return None
    
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
    
    async def _is_duplicate_content(self, url: str, title: str) -> bool:
        """
        检查是否是重复内容
        
        Args:
            url: URL
            title: 标题
            
        Returns:
            是否重复
        """
        try:
            # 生成内容指纹
            content_hash = hashlib.md5(f"{url}:{title}".encode()).hexdigest()
            
            # 在知识库中搜索相同的URL或标题
            for md_file in self.kb_folder.rglob("*.md"):
                try:
                    with open(md_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        
                        # 检查URL
                        if url and url in content:
                            return True
                        
                        # 检查标题（忽略日期部分）
                        title_pattern = re.escape(title)
                        if re.search(title_pattern, content, re.IGNORECASE):
                            return True
                            
                except Exception as e:
                    logger.warning(f"检查重复内容时跳过文件 {md_file}: {e}")
            
            return False
            
        except Exception as e:
            logger.error(f"检查重复内容时出错: {e}")
            return False
    
    def _get_daily_note_path(self, date: Optional[datetime] = None) -> Path:
        """
        获取日记文件路径
        
        Args:
            date: 日期，默认为今天
            
        Returns:
            日记文件路径
        """
        if date is None:
            date = datetime.now()
        
        filename = date.strftime("%Y-%m-%d.md")
        return self.daily_notes_folder / filename
    
    def _get_kb_note_path(self, title: str, category: str) -> Path:
        """
        获取知识库笔记路径（用于旧的文件夹方式）
        
        Args:
            title: 笔记标题
            category: 分类
            
        Returns:
            笔记路径
        """
        # 重新扫描分类，确保使用最新的分类结构
        self._scan_categories()
        
        # 查找匹配的分类文件夹
        category_folder = None
        
        # 首先尝试直接匹配
        if category in self.categories:
            category_folder = self.categories[category]
        else:
            # 尝试通过值匹配
            for key, value in self.categories.items():
                if value.lower() == category.lower():
                    category_folder = value
                    break
        
        # 如果还是没找到，使用默认分类
        if not category_folder:
            # 查找"其他"分类
            for key, value in self.categories.items():
                if 'other' in key or '其他' in value:
                    category_folder = value
                    break
            
            # 如果连"其他"都没有，创建一个
            if not category_folder:
                category_folder = '其他资料'
                self.categories['others'] = category_folder
        
        category_path = self.kb_folder / category_folder
        category_path.mkdir(exist_ok=True)
        
        # 清理标题作为文件名
        filename = self._sanitize_filename(title) + ".md"
        
        return category_path / filename
    
    async def _save_note(self, path: Path, content: str, metadata: Dict[str, Any]):
        """
        保存笔记文件（用于旧的文件夹方式）
        
        Args:
            path: 文件路径
            content: 笔记内容
            metadata: 元数据
        """
        # 如果文件已存在，可能需要更新而不是追加
        if path.exists():
            # 读取现有内容，检查是否真的是相同内容的更新
            existing_content = path.read_text(encoding='utf-8')
            
            # 如果是完全相同的内容，跳过
            if content.strip() == existing_content.strip():
                logger.info(f"内容未变化，跳过更新: {path}")
                return
            
            # 否则，替换内容（而不是追加）
            logger.info(f"更新现有笔记: {path}")
        
        # 添加frontmatter
        post = frontmatter.Post(content)
        post.metadata.update({
            'title': metadata.get('title'),
            'url': metadata.get('url'),
            'category': metadata.get('category'),
            'created': metadata.get('extracted_at', datetime.now()).isoformat(),
            'tags': metadata.get('tags', []),
            'source_user': metadata.get('source_user', ''),
            'group_name': metadata.get('group_name', ''),
            'is_history': metadata.get('is_history', False)
        })
        
        # 保存文件
        with open(path, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))
    
    async def _add_to_daily_note(self, title: str, kb_path: Optional[Path], 
                               date: datetime, group_name: str = ''):
        """
        在日记中添加引用
        
        Args:
            title: 内容标题
            kb_path: 知识库笔记路径（如果有）
            date: 日期
            group_name: 群组名称
        """
        daily_path = self._get_daily_note_path(date)
        
        # 构建链接
        if kb_path:
            # 计算相对路径
            try:
                relative_path = os.path.relpath(kb_path, self.vault_path)
                # 转换为Obsidian链接格式
                link = f"[[{relative_path.replace('.md', '')}|{title}]]"
            except:
                link = f"[[{title}]]"
        else:
            # 如果没有路径，只用标题
            link = f"[[{title}]]"
        
        # 构建条目
        time_str = date.strftime('%H:%M')
        group_info = f" (来自群组: {group_name})" if group_name else ""
        entry = f"\n- {time_str} 提取内容: {link}{group_info}\n"
        
        # 读取或创建日记
        if daily_path.exists():
            content = daily_path.read_text(encoding='utf-8')
        else:
            content = f"# {date.strftime('%Y-%m-%d')} 日记\n\n## 提取的内容\n"
        
        # 添加条目
        content += entry
        
        # 保存日记
        with open(daily_path, 'w', encoding='utf-8') as f:
            f.write(content)
    
    async def search_notes(self, query: str, limit: int = 10, 
                          group_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        搜索笔记
        
        Args:
            query: 搜索查询
            limit: 返回结果数量限制
            group_filter: 群组过滤器
            
        Returns:
            搜索结果列表
        """
        if self.note_backend == 'google_docs':
            all_results = []
            # 注意: Google Docs后端目前不支持按群组过滤
            if group_filter:
                logger.warning("Google Docs后端搜索尚不支持按群组过滤。")

            for note_doc in self.note_files:
                doc_id = note_doc.get('document_id')
                if doc_id:
                    try:
                        results = await self.google_docs_manager.search_content(doc_id, query)
                        # 为结果添加文档信息
                        for res in results:
                            res['document_name'] = note_doc.get('name')
                            res['document_id'] = doc_id
                        all_results.extend(results)
                    except Exception as e:
                        logger.error(f"搜索文档 {note_doc.get('name')} ({doc_id}) 时出错: {e}")

            # 目前仅按找到的顺序返回，未来可以增加排序逻辑
            return all_results[:limit]
        
        # Obsidian搜索逻辑
        results = []
        query_lower = query.lower()
        
        # 搜索知识库中的所有笔记
        for md_file in self.kb_folder.rglob("*.md"):
            try:
                # 读取文件内容
                with open(md_file, 'r', encoding='utf-8') as f:
                    post = frontmatter.load(f)
                
                # 群组过滤
                if group_filter and post.metadata.get('group_name') != group_filter:
                    continue
                
                # 搜索标题和内容
                title = post.metadata.get('title', md_file.stem)
                content = post.content
                
                if query_lower in title.lower() or query_lower in content.lower():
                    results.append({
                        'title': title,
                        'path': str(md_file),
                        'content': content[:500],  # 只返回前500字符
                        'metadata': post.metadata,
                        'score': self._calculate_relevance_score(query_lower, title, content)
                    })
                    
            except Exception as e:
                logger.warning(f"搜索笔记时跳过文件 {md_file}: {e}")
        
        # 按相关性排序
        results.sort(key=lambda x: x['score'], reverse=True)
        
        return results[:limit]
    
    def _calculate_relevance_score(self, query: str, title: str, content: str) -> float:
        """计算相关性分数"""
        score = 0.0
        
        # 标题匹配权重更高
        if query in title.lower():
            score += 10.0
        
        # 内容匹配
        score += content.lower().count(query)
        
        return score
    
    async def get_all_notes(self, category: Optional[str] = None, 
                           group_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取所有笔记
        
        Args:
            category: 分类筛选
            group_filter: 群组筛选
            
        Returns:
            笔记列表
        """
        if self.note_backend == 'google_docs':
            # Google Docs不支持获取所有笔记
            return []
        
        notes = []
        
        # 重新扫描分类
        self._scan_categories()
        
        # 确定搜索路径
        if category and category in self.categories:
            search_path = self.kb_folder / self.categories[category]
        else:
            search_path = self.kb_folder
        
        # 遍历所有笔记
        for md_file in search_path.rglob("*.md"):
            try:
                with open(md_file, 'r', encoding='utf-8') as f:
                    post = frontmatter.load(f)
                
                # 群组过滤
                if group_filter and post.metadata.get('group_name') != group_filter:
                    continue
                
                notes.append({
                    'title': post.metadata.get('title', md_file.stem),
                    'path': str(md_file),
                    'metadata': post.metadata,
                    'content': post.content
                })
                
            except Exception as e:
                logger.warning(f"读取笔记时跳过文件 {md_file}: {e}")
        
        return notes 