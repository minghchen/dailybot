#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
RAG (Retrieval-Augmented Generation) 服务
负责根据用户问题，从笔记库中实时检索相关内容，并结合LLM生成回答。
"""
import re
from typing import Dict, Any, List, Optional
from loguru import logger

class RAGService:
    """
    RAG服务类。
    采用实时、双层检索的模式，而非静态索引。
    """
    
    def __init__(self, config: Dict[str, Any], llm_service: Any, note_manager: Any):
        """
        初始化RAG服务
        
        Args:
            config: RAG相关的配置
            llm_service: LLM服务实例
            note_manager: 笔记管理器实例
        """
        self.config = config.get('rag', {})
        self.enabled = self.config.get('enabled', False)
        if not self.enabled:
            logger.info("RAG服务未启用。")
            return
            
        self.llm_service = llm_service
        self.note_manager = note_manager
        self.top_k = self.config.get('top_k', 5)
        
        logger.info(f"RAG服务初始化成功 (双层实时检索模式)，将检索 Top {self.top_k} 个结果。")

    async def _select_relevant_files_with_llm(self, query: str) -> List[Dict[str, Any]]:
        """
        RAG第一层：使用LLM根据查询选择相关的笔记文件。
        """
        all_files = self.note_manager.get_note_files_config()
        if not all_files or len(all_files) <= 1:
            return all_files

        options_str = "\n".join([
            f"- 文件名: {f.get('name', '未命名')}\n  描述: {f.get('description', '无描述')}"
            for f in all_files
        ])

        prompt = f"""
你是一个信息检索专家。你的任务是根据一个用户问题，从下面的文件列表中，选出所有可能包含相关信息的文件。

[用户问题]
"{query}"

[文件列表]
{options_str}

[你的任务]
请分析问题和文件描述，列出所有相关的文件名。如果多个文件都可能相关，请全部列出。

[输出格式]
请严格按照以下格式回答，每行一个文件名，不要添加任何其他内容：
文件名1
文件名2
...
"""
        
        try:
            response = await self.llm_service.chat(prompt)
            relevant_file_names = [name.strip() for name in response.split('\n') if name.strip()]
            
            if not relevant_file_names:
                logger.warning("LLM未能确定任何相关文件，将搜索所有文件作为后备。")
                return all_files

            selected_configs = [f_config for f_config in all_files if f_config.get('name') in relevant_file_names]
            logger.info(f"RAG第一层：LLM选择了 {len(selected_configs)} 个相关文件进行搜索: {[f.get('name') for f in selected_configs]}")
            return selected_configs
        except Exception as e:
            logger.error(f"LLM选择相关文件失败: {e}，将搜索所有文件作为后备。")
            return all_files

    async def answer_question(self, query: str, group_filter: Optional[str] = None) -> str:
        """
        使用双层RAG流程回答问题：先选文件，再在文件内搜索。
        """
        if not self.enabled:
            return "抱歉，问答功能当前未启用。"
            
        try:
            # 1. RAG第一层：智能选择相关文件
            logger.info(f"RAG: 开始双层搜索，问题: '{query}'")
            relevant_files = await self._select_relevant_files_with_llm(query)

            # 2. RAG第二层：在选定的每个文件内进行搜索
            all_snippets = []
            for file_config in relevant_files:
                snippets = await self.note_manager.search_in_document(file_config, query, group_filter)
                for s in snippets:
                    s['document_name'] = file_config.get('name') # 确保来源信息
                all_snippets.extend(snippets)
            
            if not all_snippets:
                logger.warning("RAG: 未在任何相关文件中找到匹配片段，将直接由LLM回答。")
                return await self.llm_service.chat(f"请直接回答这个问题: {query}")

            # 3. 构建上下文
            # TODO: 在此可以加入更智能的跨文件结果排序和去重逻辑
            final_snippets = all_snippets[:self.top_k]
            context = "\n---\n".join([
                f"来源文件: {res.get('document_name')}\n标题: {res.get('title', '无标题')}\n内容片段: {res.get('text', '')}"
                for res in final_snippets
            ])
            logger.debug(f"RAG: 构建的最终上下文 (前200字符): {context[:200]}...")

            # 4. 构建提示并生成答案
            prompt = f"""
你是一个智能助理。请根据以下从多个笔记文件中检索到的、最相关的上下文信息，来回答用户的问题。

[上下文信息]
{context}

[用户问题]
{query}

请注意：
- 请只根据提供的上下文信息进行回答，不要编造信息。
- 如果上下文信息不足以回答问题，请明确告知用户"根据现有笔记，我无法回答这个问题"。
- 你的回答应该简洁、清晰、并直接针对用户的问题。
"""
            
            answer = await self.llm_service.chat(prompt)
            logger.info("RAG: 已成功生成回答。")
            return answer

        except Exception as e:
            logger.error(f"RAG处理过程中发生错误: {e}", exc_info=True)
            return "抱歉，我在回答问题时遇到了一个内部错误。"

# --- 以下为旧的、基于静态索引的逻辑，已被移除 ---
# import chromadb
# from langchain.vectorstores import Chroma
# from langchain.text_splitter import RecursiveCharacterTextSplitter
# from langchain.docstore.document import Document
# from langchain_openai import OpenAIEmbeddings
# from langchain.retrievers import ContextualCompressionRetriever
# from langchain.retrievers.document_compressors import LLMChainExtractor
# from langchain.chains import RetrievalQA 