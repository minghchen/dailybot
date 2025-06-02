#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
链接解析器
负责从消息中解析各种类型的链接
"""

import re
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
from loguru import logger


class LinkParser:
    """链接解析器"""
    
    def __init__(self):
        """初始化链接解析器"""
        # 链接类型识别规则
        self.link_patterns = {
            'wechat_article': r'mp\.weixin\.qq\.com',
            'bilibili_video': r'(bilibili\.com|b23\.tv)',
            'arxiv_paper': r'arxiv\.org/(abs|pdf)',
            'pdf': r'\.pdf($|\?)',
            'youtube_video': r'(youtube\.com|youtu\.be)',
            'github': r'github\.com'
        }
        
        # URL正则表达式
        self.url_pattern = re.compile(
            r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+'
        )
    
    def parse_message(self, msg: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        从消息中解析链接
        
        Args:
            msg: 微信消息对象
            
        Returns:
            解析出的链接列表
        """
        links = []
        
        # 处理分享消息
        if msg.get('Type') == 'Sharing':
            url = msg.get('Url', '')
            title = msg.get('FileName', '分享内容')
            if url:
                link_type = self._identify_link_type(url)
                links.append({
                    'url': url,
                    'title': title,
                    'type': link_type
                })
        
        # 处理文本消息中的链接
        text = msg.get('Text', '')
        if text:
            # 查找所有URL
            urls = self.url_pattern.findall(text)
            for url in urls:
                link_type = self._identify_link_type(url)
                links.append({
                    'url': url,
                    'title': self._extract_title_from_url(url),
                    'type': link_type
                })
        
        return links
    
    def _identify_link_type(self, url: str) -> str:
        """
        识别链接类型
        
        Args:
            url: 链接地址
            
        Returns:
            链接类型
        """
        # 检查每种类型的模式
        for link_type, pattern in self.link_patterns.items():
            if re.search(pattern, url, re.IGNORECASE):
                return link_type
        
        # 默认为通用网页链接
        return 'web_link'
    
    def _extract_title_from_url(self, url: str) -> str:
        """
        从URL中提取标题（简单实现）
        
        Args:
            url: 链接地址
            
        Returns:
            标题
        """
        try:
            parsed = urlparse(url)
            
            # 特殊处理一些网站
            if 'arxiv.org' in parsed.netloc:
                # 提取arXiv ID作为标题
                match = re.search(r'/(\d+\.\d+)', url)
                if match:
                    return f"arXiv:{match.group(1)}"
            
            elif 'github.com' in parsed.netloc:
                # 提取仓库名
                parts = parsed.path.strip('/').split('/')
                if len(parts) >= 2:
                    return f"{parts[0]}/{parts[1]}"
            
            elif 'bilibili.com' in parsed.netloc:
                # 提取BV号
                match = re.search(r'BV[\w]+', url)
                if match:
                    return f"B站视频 {match.group()}"
            
            # 默认使用域名作为标题
            return parsed.netloc
            
        except Exception as e:
            logger.warning(f"从URL提取标题失败: {e}")
            return "未知链接"
    
    def is_supported_link(self, url: str) -> bool:
        """
        检查链接是否被支持
        
        Args:
            url: 链接地址
            
        Returns:
            是否支持
        """
        link_type = self._identify_link_type(url)
        return link_type != 'web_link' or self._is_valid_web_link(url)
    
    def _is_valid_web_link(self, url: str) -> bool:
        """
        检查是否是有效的网页链接
        
        Args:
            url: 链接地址
            
        Returns:
            是否有效
        """
        try:
            parsed = urlparse(url)
            # 检查是否有有效的scheme和netloc
            return bool(parsed.scheme and parsed.netloc)
        except:
            return False 