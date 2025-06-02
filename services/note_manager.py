#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
笔记管理器
负责管理笔记的读写，支持Obsidian和Google Docs
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Set
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
        self.note_backend = config.get('note_backend', 'obsidian')  # obsidian 或 google_docs
        
        # 初始化具体的后端
        if self.note_backend == 'obsidian':
            self._init_obsidian(config.get('obsidian', {}))
        elif self.note_backend == 'google_docs':
            self.google_docs_manager = GoogleDocsManager(config.get('google_docs', {}))
        else:
            raise ValueError(f"不支持的笔记后端: {self.note_backend}")
        
        logger.info(f"笔记管理器初始化成功，使用后端: {self.note_backend}")
    
    def _init_obsidian(self, obsidian_config: Dict[str, Any]):
        """初始化Obsidian配置"""
        self.vault_path = Path(obsidian_config['vault_path'])
        self.daily_notes_folder = self.vault_path / obsidian_config['daily_notes_folder']
        self.kb_folder = self.vault_path / obsidian_config['knowledge_base_folder']
        
        # 不再从配置读取分类，而是动态解析
        self._scan_categories()
        
        # 确保目录存在
        self._ensure_directories()
    
    def _scan_categories(self) -> Dict[str, str]:
        """
        扫描知识库文件夹，动态获取现有分类
        
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
        
        # 为每个分类创建目录
        for category_name in self.categories.values():
            category_path = self.kb_folder / category_name
            category_path.mkdir(exist_ok=True)
    
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
        保存内容到笔记
        
        Args:
            content_data: 内容数据，包含title、url、summary、category等
        """
        # 每次保存前重新扫描分类，以适应用户的手动修改
        self._scan_categories()
        
        if self.note_backend == 'obsidian':
            await self._save_to_obsidian(content_data)
        elif self.note_backend == 'google_docs':
            await self.google_docs_manager.save_content(content_data)
    
    async def _save_to_obsidian(self, content_data: Dict[str, Any]):
        """保存到Obsidian"""
        try:
            title = content_data.get('title', '未命名内容')
            url = content_data.get('url', '')
            summary = content_data.get('summary', '')
            category = content_data.get('category', 'others')
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
            
            # 构建笔记内容（使用新格式）
            note_content = self._build_formatted_note_content(
                title=title,
                url=url,
                summary=summary,
                context=context,
                extracted_at=extracted_at,
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
                await self._add_to_daily_note(title, kb_path, extracted_at, group_name)
            
            logger.info(f"内容已保存到Obsidian笔记: {kb_path}")
            
        except Exception as e:
            logger.error(f"保存内容到Obsidian时出错: {e}", exc_info=True)
            raise
    
    def _build_formatted_note_content(self, title: str, url: str, summary: str,
                                    context: str, extracted_at: datetime, 
                                    article_title: str = '', content_type: str = 'web_link',
                                    source_user: str = '', group_name: str = '', 
                                    is_history: bool = False) -> str:
        """构建格式化的笔记内容"""
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
        if title.endswith('...') and 'raw_content' in locals():
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
        获取知识库笔记路径
        
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
        保存笔记文件
        
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
    
    async def _add_to_daily_note(self, title: str, kb_path: Path, date: datetime, group_name: str = ''):
        """
        在日记中添加引用
        
        Args:
            title: 内容标题
            kb_path: 知识库笔记路径
            date: 日期
            group_name: 群组名称
        """
        daily_path = self._get_daily_note_path(date)
        
        # 计算相对路径
        try:
            relative_path = os.path.relpath(kb_path, self.vault_path)
            # 转换为Obsidian链接格式
            link = f"[[{relative_path.replace('.md', '')}|{title}]]"
        except:
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
            return await self.google_docs_manager.search_content(query)
        
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