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
        self.client = AsyncOpenAI(
            api_key=config['api_key'],
            base_url=config.get('base_url'),
            http_client=self._get_http_client()
        )
        
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
            response = await self.client.chat.completions.create(
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
    
    async def summarize(self, content: str, prompt_template: Optional[str] = None) -> str:
        """
        总结内容
        
        Args:
            content: 待总结的内容
            prompt_template: 提示模板
            
        Returns:
            总结结果
        """
        if not prompt_template:
            prompt_template = """请总结以下内容的主要观点和关键信息：

{content}

总结要求：
1. 提取核心观点和重要信息
2. 保持客观准确
3. 结构清晰，使用要点形式
4. 控制在500字以内"""
        
        prompt = prompt_template.format(content=content)
        
        return await self.chat(prompt)
    
    async def classify(self, content: str, categories: List[str]) -> str:
        """
        对内容进行分类
        
        Args:
            content: 待分类的内容
            categories: 可选类别列表
            
        Returns:
            分类结果
        """
        categories_str = "、".join(categories)
        
        prompt = f"""请对以下内容进行分类，从这些类别中选择最合适的一个：{categories_str}

内容：
{content}

请直接返回类别名称，不要有其他内容。"""
        
        result = await self.chat(prompt)
        
        # 确保返回的是有效类别
        result = result.strip()
        if result not in categories:
            # 如果LLM返回的不是有效类别，使用默认类别
            result = categories[-1]  # 假设最后一个是"其他"类别
            
        return result
    
    async def extract_info(self, content: str, info_types: List[str]) -> Dict[str, Any]:
        """
        从内容中提取指定信息
        
        Args:
            content: 内容
            info_types: 需要提取的信息类型
            
        Returns:
            提取的信息字典
        """
        info_prompts = {
            "title": "文章或内容的标题",
            "author": "作者名称",
            "keywords": "关键词（用逗号分隔）",
            "summary": "简短摘要（100字以内）",
            "main_points": "主要观点（用编号列出）",
            "date": "发布日期",
            "source": "来源平台或网站"
        }
        
        prompt_parts = []
        for info_type in info_types:
            if info_type in info_prompts:
                prompt_parts.append(f"- {info_prompts[info_type]}")
        
        prompt = f"""请从以下内容中提取这些信息：
{chr(10).join(prompt_parts)}

内容：
{content}

请以JSON格式返回提取的信息，如果某个信息无法提取，请使用null值。"""
        
        result = await self.chat(prompt)
        
        # 解析JSON结果
        try:
            import json
            # 尝试提取JSON部分
            json_start = result.find('{')
            json_end = result.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                json_str = result[json_start:json_end]
                return json.loads(json_str)
        except:
            logger.warning("无法解析LLM返回的JSON")
            
        return {}
    
    async def generate_embedding(self, text: str) -> List[float]:
        """
        生成文本嵌入向量
        
        Args:
            text: 文本内容
            
        Returns:
            嵌入向量
        """
        try:
            response = await self.client.embeddings.create(
                model=self.config['rag']['embedding_model'],
                input=text
            )
            
            return response.data[0].embedding
            
        except Exception as e:
            logger.error(f"生成嵌入向量失败: {e}", exc_info=True)
            raise 