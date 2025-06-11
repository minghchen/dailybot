#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
LLM服务
负责与OpenAI API交互
"""

import asyncio
from typing import Dict, Any, List, Optional
from loguru import logger
from openai import AsyncOpenAI
import tiktoken
import instructor
from pydantic import Field, BaseModel


# 使用Instructor对OpenAI客户端进行增强
# 这使得 .chat.completions.create 方法可以返回Pydantic模型

class LLMService:
    """LLM服务类"""
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化LLM服务
        
        Args:
            config: OpenAI配置信息
        """
        self.config = config
        self.model = config.get('model', 'gpt-4o-mini')
        self.temperature = config.get('temperature', 0.7)
        self.max_tokens = config.get('max_tokens', 2000)
        
        # 初始化OpenAI客户端
        self.aclient = instructor.patch(AsyncOpenAI(
            api_key=config['api_key'],
            base_url=config.get('base_url'),
            http_client=self._get_http_client()
        ))
        
        # 初始化tokenizer
        try:
            self.encoding = tiktoken.encoding_for_model(self.model)
        except:
            self.encoding = tiktoken.get_encoding("cl100k_base")
            
        logger.info(f"LLM服务初始化成功，使用模型: {self.model}")
    
    def _get_http_client(self):
        """获取HTTP客户端（支持代理）"""
        proxy = self.config.get('proxy')
        if proxy:
            import httpx
            return httpx.AsyncClient(proxies={"http://": proxy, "https://": proxy})
        return None
    
    def count_tokens(self, text: str) -> int:
        """
        计算文本的token数量
        
        Args:
            text: 文本内容
            
        Returns:
            token数量
        """
        return len(self.encoding.encode(text))
    
    async def chat(self, 
                   message: str, 
                   system_prompt: Optional[str] = None,
                   history: Optional[List[Dict[str, str]]] = None) -> str:
        """
        发送聊天请求
        
        Args:
            message: 用户消息
            system_prompt: 系统提示
            history: 历史对话
            
        Returns:
            AI回复
        """
        try:
            messages = []
            
            # 添加系统提示
            if system_prompt:
                messages.append({
                    "role": "system",
                    "content": system_prompt
                })
            
            # 添加历史对话
            if history:
                messages.extend(history)
            
            # 添加当前消息
            messages.append({
                "role": "user",
                "content": message
            })
            
            # 调用API
            response = await self.aclient.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens
            )
            
            # 获取回复
            reply = response.choices[0].message.content
            
            logger.debug(f"LLM回复: {reply[:100]}...")
            
            return reply
            
        except Exception as e:
            logger.error(f"LLM请求失败: {e}", exc_info=True)
            raise
    
    async def generate_embedding(self, text: str) -> List[float]:
        """
        生成文本嵌入向量
        
        Args:
            text: 文本内容
            
        Returns:
            嵌入向量
        """
        try:
            response = await self.aclient.embeddings.create(
                model=self.config['rag']['embedding_model'],
                input=text
            )
            
            return response.data[0].embedding
            
        except Exception as e:
            logger.error(f"生成嵌入向量失败: {e}", exc_info=True)
            raise 