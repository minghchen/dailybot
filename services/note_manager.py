#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
笔记管理器
负责管理Obsidian笔记的读写
"""

import os
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from loguru import logger
import frontmatter
import markdown


class NoteManager:
    """笔记管理器"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化笔记管理器
        
        Args:
            config: Obsidian配置信息
        """
        self.config = config
        self.vault_path = Path(config['vault_path'])
        self.daily_notes_folder = self.vault_path / config['daily_notes_folder']
        self.kb_folder = self.vault_path / config['knowledge_base_folder']
        self.categories = config['categories']
        
        # 确保目录存在
        self._ensure_directories()
        
        logger.info(f"笔记管理器初始化成功，Vault路径: {self.vault_path}")
    
    def _ensure_directories(self):
        """确保必要的目录存在"""
        # 创建日记目录
        self.daily_notes_folder.mkdir(parents=True, exist_ok=True)
        
        # 创建知识库目录和分类子目录
        self.kb_folder.mkdir(parents=True, exist_ok=True)
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
        category_name = self.categories.get(category, self.categories['others'])
        category_path = self.kb_folder / category_name
        
        # 清理标题作为文件名
        filename = self._sanitize_filename(title) + ".md"
        
        return category_path / filename
    
    async def save_content(self, content_data: Dict[str, Any]):
        """
        保存内容到笔记
        
        Args:
            content_data: 内容数据，包含title、url、summary、category等
        """
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
            
            # 构建笔记内容
            note_content = self._build_note_content(
                title=title,
                url=url,
                summary=summary,
                context=context,
                extracted_at=extracted_at,
                raw_content=raw_content,
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
            
            logger.info(f"内容已保存到笔记: {kb_path}")
            
        except Exception as e:
            logger.error(f"保存内容到笔记时出错: {e}", exc_info=True)
            raise
    
    def _build_note_content(self, title: str, url: str, summary: str, 
                          context: str, extracted_at: datetime, raw_content: str,
                          source_user: str = '', group_name: str = '', 
                          is_history: bool = False) -> str:
        """构建笔记内容"""
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
        
        # 构建元信息
        metadata_parts = [
            f"**链接**: {url}",
            f"**提取时间**: {extracted_at.strftime('%Y-%m-%d %H:%M')}"
        ]
        
        if source_user:
            metadata_parts.append(f"**分享者**: {source_user}")
        
        if group_name:
            metadata_parts.append(f"**来源群组**: {group_name}")
        
        # 构建笔记
        content = f"""# {title}

{' '.join(tags)}

{chr(10).join(metadata_parts)}

## 摘要

{summary}

## 上下文

{context}

## 原始内容

{raw_content[:1000] if raw_content else '(内容过长，已截断)'}

---

*此笔记由 DailyBot 自动生成{' (从历史记录导入)' if is_history else ''}*
"""
        
        return content
    
    async def _save_note(self, path: Path, content: str, metadata: Dict[str, Any]):
        """
        保存笔记文件
        
        Args:
            path: 文件路径
            content: 笔记内容
            metadata: 元数据
        """
        # 如果文件已存在，追加内容
        if path.exists():
            existing_content = path.read_text(encoding='utf-8')
            # 在现有内容后追加新内容
            content = existing_content + "\n\n---\n\n## 更新内容\n\n" + content
        
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
        notes = []
        
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