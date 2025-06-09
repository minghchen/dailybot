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

class StructuredNote(BaseModel):
    """结构化的笔记内容模型"""
    date: str = Field(..., description="根据文章内容或当前日期，生成的年月格式，如 '2025.06'。")
    title: str = Field(..., description="文章的完整、准确的标题。")
    link_title: str = Field(..., description="适合用作超链接文本的简洁标题，通常与主标题相同或为其缩写。")
    summary: str = Field(..., description="对文章核心内容的客观总结，最多5句话。**请务必使用中文进行总结**。对话上下文仅用于启发总结的侧重点，总结本身不应提及对话。")


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
    
    async def generate_structured_note(self, article_content: str, conversation_context: str) -> StructuredNote:
        """
        使用LLM和Instructor生成结构化的笔记内容。

        Args:
            article_content: 从链接中提取的文章或网页内容。
            conversation_context: 围绕该链接的对话上下文。

        Returns:
            一个包含日期、标题、链接标题和摘要的Pydantic模型实例。
        """
        prompt = f"""
你的任务是根据提供的文章内容和相关的对话上下文，生成一份结构化的笔记。

[对话上下文（仅供参考，用于理解文章的关注点）]
{conversation_context}

[文章内容]
{article_content[:10000]}

请严格按照要求的格式，提取或生成笔记的各个部分。
"""
        try:
            note = await self.aclient.chat.completions.create(
                model=self.model,
                response_model=StructuredNote,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                max_retries=2,
            )
            logger.info("LLM成功生成了结构化笔记。")
            return note
        except Exception as e:
            logger.error(f"使用Instructor生成结构化笔记失败: {e}", exc_info=True)
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