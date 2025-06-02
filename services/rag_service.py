#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG服务
负责实现检索增强生成功能
"""

import os
import pickle
from typing import Dict, Any, List, Optional
from loguru import logger
import chromadb
from chromadb.config import Settings
import numpy as np
from langchain.text_splitter import RecursiveCharacterTextSplitter


class RAGService:
    """RAG服务类"""
    
    def __init__(self, config: Dict[str, Any], llm_service, note_manager):
        """
        初始化RAG服务
        
        Args:
            config: RAG配置信息
            llm_service: LLM服务实例
            note_manager: 笔记管理器实例
        """
        self.config = config
        self.llm_service = llm_service
        self.note_manager = note_manager
        
        # 文本分割器
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config['chunk_size'],
            chunk_overlap=config['chunk_overlap'],
            separators=["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
        )
        
        # 初始化向量数据库
        self._init_vector_db()
        
        # 初始化或加载索引
        self._init_index()
        
        logger.info("RAG服务初始化成功")
    
    def _init_vector_db(self):
        """初始化向量数据库"""
        # 使用ChromaDB作为向量数据库
        db_path = os.path.join(os.path.dirname(__file__), "..", "data", "chroma_db")
        
        self.chroma_client = chromadb.PersistentClient(
            path=db_path,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        
        # 创建或获取集合
        self.collection = self.chroma_client.get_or_create_collection(
            name="dailybot_knowledge",
            metadata={"hnsw:space": "cosine"}
        )
    
    def _init_index(self):
        """初始化或加载索引"""
        try:
            # 检查是否已有索引
            if self.collection.count() == 0:
                # 如果没有索引，从笔记构建
                logger.info("开始构建向量索引...")
                asyncio.create_task(self._build_index_from_notes())
            else:
                logger.info(f"加载现有向量索引，共 {self.collection.count()} 个文档")
        except Exception as e:
            logger.error(f"初始化索引失败: {e}", exc_info=True)
    
    async def _build_index_from_notes(self):
        """从笔记构建索引"""
        try:
            # 获取所有笔记
            notes = await self.note_manager.get_all_notes()
            
            for note in notes:
                await self.add_document({
                    'title': note['title'],
                    'url': note['metadata'].get('url', ''),
                    'content': note['content'],
                    'metadata': note['metadata']
                })
            
            logger.info(f"索引构建完成，共索引 {len(notes)} 篇笔记")
            
        except Exception as e:
            logger.error(f"构建索引失败: {e}", exc_info=True)
    
    async def add_document(self, document: Dict[str, Any]):
        """
        添加文档到向量数据库
        
        Args:
            document: 文档数据
        """
        try:
            title = document.get('title', '')
            url = document.get('url', '')
            content = document.get('content', '')
            metadata = document.get('metadata', {})
            
            # 分割文本
            if 'summary' in document:
                # 如果有总结，优先使用总结
                text_to_split = f"{title}\n\n{document['summary']}\n\n{content[:1000]}"
            else:
                text_to_split = f"{title}\n\n{content}"
            
            chunks = self.text_splitter.split_text(text_to_split)
            
            # 为每个chunk生成嵌入
            for i, chunk in enumerate(chunks):
                # 生成唯一ID
                doc_id = f"{url}_{i}" if url else f"{title}_{i}"
                
                # 生成嵌入向量
                embedding = await self.llm_service.generate_embedding(chunk)
                
                # 准备元数据
                chunk_metadata = {
                    'title': title,
                    'url': url,
                    'chunk_index': i,
                    'total_chunks': len(chunks),
                    **metadata
                }
                
                # 添加到向量数据库
                self.collection.add(
                    documents=[chunk],
                    embeddings=[embedding],
                    metadatas=[chunk_metadata],
                    ids=[doc_id]
                )
            
            logger.debug(f"文档已添加到向量数据库: {title} (分割为 {len(chunks)} 个chunk)")
            
        except Exception as e:
            logger.error(f"添加文档到向量数据库失败: {e}", exc_info=True)
    
    async def query(self, query: str) -> str:
        """
        使用RAG进行查询
        
        Args:
            query: 用户查询
            
        Returns:
            生成的回答
        """
        try:
            # 生成查询向量
            query_embedding = await self.llm_service.generate_embedding(query)
            
            # 检索相关文档
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=self.config['top_k']
            )
            
            if not results['documents'][0]:
                # 如果没有找到相关文档，直接使用LLM回答
                return await self.llm_service.chat(query)
            
            # 构建上下文
            context = self._build_context_from_results(results)
            
            # 构建增强提示
            enhanced_prompt = f"""基于以下参考资料回答用户的问题。如果参考资料中没有相关信息，请诚实地说不知道。

参考资料：
{context}

用户问题：{query}

请提供准确、有帮助的回答："""
            
            # 使用LLM生成回答
            answer = await self.llm_service.chat(enhanced_prompt)
            
            # 添加来源引用
            sources = self._extract_sources(results)
            if sources:
                answer += "\n\n参考来源：\n"
                for source in sources:
                    answer += f"- [{source['title']}]({source['url']})\n"
            
            return answer
            
        except Exception as e:
            logger.error(f"RAG查询失败: {e}", exc_info=True)
            # 降级到普通LLM回答
            return await self.llm_service.chat(query)
    
    def _build_context_from_results(self, results: Dict[str, Any]) -> str:
        """从检索结果构建上下文"""
        context_parts = []
        
        documents = results['documents'][0]
        metadatas = results['metadatas'][0]
        distances = results['distances'][0]
        
        for i, (doc, metadata, distance) in enumerate(zip(documents, metadatas, distances)):
            # 计算相似度分数（距离越小越相似）
            similarity = 1 - distance
            
            # 如果相似度太低，跳过
            if similarity < self.config['similarity_threshold']:
                continue
            
            title = metadata.get('title', '未知')
            context_parts.append(f"【{title}】\n{doc}\n")
        
        return "\n---\n".join(context_parts)
    
    def _extract_sources(self, results: Dict[str, Any]) -> List[Dict[str, str]]:
        """从检索结果中提取来源信息"""
        sources = []
        seen_urls = set()
        
        metadatas = results['metadatas'][0]
        distances = results['distances'][0]
        
        for metadata, distance in zip(metadatas, distances):
            similarity = 1 - distance
            
            # 如果相似度太低，跳过
            if similarity < self.config['similarity_threshold']:
                continue
            
            url = metadata.get('url', '')
            if url and url not in seen_urls:
                seen_urls.add(url)
                sources.append({
                    'title': metadata.get('title', '未知'),
                    'url': url
                })
        
        return sources
    
    async def update_index(self):
        """更新索引（全量重建）"""
        try:
            logger.info("开始更新向量索引...")
            
            # 清空现有索引
            self.collection.delete(where={})
            
            # 重新构建索引
            await self._build_index_from_notes()
            
            logger.info("向量索引更新完成")
            
        except Exception as e:
            logger.error(f"更新索引失败: {e}", exc_info=True)


# 需要在文件开头添加asyncio导入
import asyncio 