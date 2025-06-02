#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
视频总结工具
负责获取和总结B站等平台的视频内容
"""

import re
import json
import asyncio
from typing import Dict, Any, Optional
from loguru import logger
import aiohttp
from bilibili_api import video, Credential


class BilibiliSummarizer:
    """B站视频总结器"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化B站视频总结器
        
        Args:
            config: B站相关配置
        """
        self.config = config
        self.cookies = config.get('cookies', '')
        self.summarizer_api = config.get('summarizer_api', '')
        
        # 初始化凭证（如果有）
        self.credential = None
        if self.cookies:
            try:
                # 解析cookies
                sessdata = self._extract_sessdata(self.cookies)
                if sessdata:
                    self.credential = Credential(sessdata=sessdata)
            except Exception as e:
                logger.warning(f"解析B站cookies失败: {e}")
    
    def _extract_sessdata(self, cookies: str) -> Optional[str]:
        """从cookies字符串中提取SESSDATA"""
        match = re.search(r'SESSDATA=([^;]+)', cookies)
        return match.group(1) if match else None
    
    async def get_video_info(self, url: str) -> Optional[Dict[str, Any]]:
        """
        获取B站视频信息
        
        Args:
            url: B站视频链接
            
        Returns:
            视频信息字典
        """
        try:
            # 提取视频ID
            bvid = self._extract_bvid(url)
            if not bvid:
                logger.error(f"无法从URL提取BV号: {url}")
                return None
            
            # 创建视频对象
            v = video.Video(bvid=bvid, credential=self.credential)
            
            # 获取视频信息
            info = await v.get_info()
            
            # 获取视频字幕（如果有）
            transcript = await self._get_transcript(v)
            
            # 构建返回数据
            result = {
                'title': info.get('title', ''),
                'author': info.get('owner', {}).get('name', ''),
                'description': info.get('desc', ''),
                'duration': self._format_duration(info.get('duration', 0)),
                'views': info.get('stat', {}).get('view', 0),
                'likes': info.get('stat', {}).get('like', 0),
                'coins': info.get('stat', {}).get('coin', 0),
                'favorites': info.get('stat', {}).get('favorite', 0),
                'bvid': bvid,
                'url': url,
                'transcript': transcript
            }
            
            return result
            
        except Exception as e:
            logger.error(f"获取B站视频信息失败: {e}")
            return None
    
    def _extract_bvid(self, url: str) -> Optional[str]:
        """从URL中提取BV号"""
        # 支持多种URL格式
        patterns = [
            r'BV[\w]+',  # 直接的BV号
            r'bilibili\.com/video/(BV[\w]+)',  # 标准视频页
            r'b23\.tv/(BV[\w]+)',  # 短链接
        ]
        
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1) if '(' in pattern else match.group()
        
        return None
    
    def _format_duration(self, seconds: int) -> str:
        """格式化时长"""
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        secs = seconds % 60
        
        if hours > 0:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        else:
            return f"{minutes}:{secs:02d}"
    
    async def _get_transcript(self, v: video.Video) -> str:
        """
        获取视频字幕
        
        Args:
            v: 视频对象
            
        Returns:
            字幕文本
        """
        try:
            # 获取字幕列表
            subtitle_list = await v.get_subtitle_list()
            
            if not subtitle_list:
                return "(无字幕)"
            
            # 优先选择中文字幕
            chinese_subtitle = None
            for subtitle in subtitle_list:
                if 'zh' in subtitle.get('lan', ''):
                    chinese_subtitle = subtitle
                    break
            
            if not chinese_subtitle and subtitle_list:
                # 如果没有中文字幕，选择第一个
                chinese_subtitle = subtitle_list[0]
            
            if chinese_subtitle:
                # 获取字幕内容
                subtitle_url = chinese_subtitle.get('subtitle_url', '')
                if subtitle_url:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(subtitle_url) as response:
                            subtitle_data = await response.json()
                    
                    # 提取字幕文本
                    body = subtitle_data.get('body', [])
                    transcript_parts = []
                    for item in body[:100]:  # 限制长度
                        content = item.get('content', '')
                        transcript_parts.append(content)
                    
                    return ' '.join(transcript_parts)
            
            return "(无可用字幕)"
            
        except Exception as e:
            logger.warning(f"获取字幕失败: {e}")
            return "(获取字幕失败)"
    
    async def summarize_with_api(self, video_info: Dict[str, Any]) -> Optional[str]:
        """
        使用外部API总结视频（如果配置了）
        
        Args:
            video_info: 视频信息
            
        Returns:
            总结文本
        """
        if not self.summarizer_api:
            return None
        
        try:
            # 调用外部总结API
            async with aiohttp.ClientSession() as session:
                payload = {
                    'url': video_info['url'],
                    'title': video_info['title'],
                    'description': video_info['description'],
                    'transcript': video_info.get('transcript', '')
                }
                
                async with session.post(
                    self.summarizer_api,
                    json=payload,
                    timeout=30
                ) as response:
                    result = await response.json()
                    return result.get('summary')
                    
        except Exception as e:
            logger.error(f"调用视频总结API失败: {e}")
            return None 