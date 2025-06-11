#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
智能代理服务
负责分析内容，并决定是否需要通过工具（如搜索）来丰富内容，然后再进行总结。
"""

import asyncio
from typing import Dict, Any, Union, Optional, TYPE_CHECKING
from loguru import logger
from pydantic import Field, BaseModel
from duckduckgo_search import DDGS
import instructor

from services.llm_service import LLMService

# 仅在类型检查时导入，以避免循环导入
if TYPE_CHECKING:
    from services.content_extractor import ContentExtractor


# === Pydantic 模型定义 ===

class StructuredNote(BaseModel):
    """结构化的笔记内容模型"""
    date: str = Field(..., description="根据文章内容或当前日期，生成的年月格式，如 '2025.06'。")
    title: str = Field(..., description="文章的完整、准确的标题。")
    link_title: str = Field(..., description="适合用作超链接文本的简洁标题，通常与主标题相同或为其缩写。")
    summary: str = Field(..., description="对文章核心价值的深度、精炼的中文总结。目标是用2-3句话点明核心贡献/观点。只有在内容确实包含多个重要、独立的技术点时，才扩展到4-5句话。")

class SearchAndSummarize(BaseModel):
    """
    当文章内容明显引用了某个核心的、可搜索的实体（如论文、GitHub项目、特定事件）时，
    使用此工具。这个工具会先搜索该实体，获取更直接的信息，然后再进行总结。
    """
    query: str = Field(..., description="根据文章内容提取出的、最核心的搜索关键词。例如 'SELF-REFLECT: Learning to Refine Text-to-Image Generation' 或 'Llama 3'。")

class DirectSummarize(BaseModel):
    """
    当文章内容本身就是信息的主要来源，信息完整，或者没有明确的可搜索实体时，使用此工具直接对现有内容进行总结。
    """
    reason: str = Field(..., description="为什么选择直接总结的简要原因。例如'文章本身是观点性博客'或'内容是完整的新闻报道'。")


class AgentService:
    """智能代理服务类"""

    def __init__(self, config: Dict[str, Any], llm_service: LLMService, content_extractor: 'ContentExtractor'):
        """
        初始化Agent服务

        Args:
            config: 全局配置对象
            llm_service: LLM服务实例
            content_extractor: 内容提取器实例，用于获取搜索结果页面的内容
        """
        self.config = config
        self.llm_service = llm_service
        self.content_extractor = content_extractor
        logger.info("智能代理服务初始化成功。")

    async def process_content_to_note(self, original_content: str, conversation_context: str) -> StructuredNote:
        """
        处理原始内容，通过决策、丰富、总结的完整流程，生成结构化笔记。

        Args:
            original_content: 从链接中提取的原始内容。
            conversation_context: 围绕该链接的对话上下文。

        Returns:
            一个结构化的笔记Pydantic模型。
        """
        # 1. 决策并可能地丰富内容
        content_for_summary = await self._decide_and_enrich(original_content)
        
        # 2. 使用最终内容生成结构化笔记
        structured_note = await self.generate_structured_note(
            article_content=content_for_summary,
            conversation_context=conversation_context
        )
        return structured_note

    async def _decide_and_enrich(self, original_content: str) -> str:
        """
        分析原始内容，决定是直接总结还是先搜索再总结，并返回最终用于总结的文本。
        （原 decide_and_enrich 方法，现在是私有方法）
        """
        if not self.config.get("agent", {}).get("enabled", True):
             logger.info("智能代理未启用，直接返回原始内容。")
             return original_content

        logger.info("智能代理开始分析内容，决策中...")
        
        content_for_decision = original_content[:self.config.get("agent", {}).get("max_decision_content", 4000)]

        prompt = f"""
你是一个智能分析师。你的任务是阅读下面的文章内容，并决定如何最好地处理它。你有两个选择：

1.  **搜索并总结 (SearchAndSummarize)**: 如果文章内容主要是对另一个核心资源的介绍、评论或摘要（例如一篇论文、一个GitHub项目、一个特定的开源模型），你应该使用这个工具。你需要从文章中提取出那个核心资源的最准确的名称作为搜索词。
2.  **直接总结 (DirectSummarize)**: 如果文章本身就是信息的主要来源（例如一篇完整的博客文章、一篇新闻报道、一篇观点性文章），你应该使用这个工具。

请根据下面的文章内容，选择最合适的工具。

[文章内容]
{content_for_decision}
"""
        try:
            decision = await self.llm_service.aclient.chat.completions.create(
                model=self.llm_service.model,
                response_model=Union[SearchAndSummarize, DirectSummarize],
                messages=[
                    {"role": "user", "content": prompt},
                ],
                max_retries=1,
            )
            
            if isinstance(decision, SearchAndSummarize):
                logger.info(f"代理决策: [搜索并总结]，查询: '{decision.query}'")
                return await self._search_and_get_content(decision.query, original_content)
            
            elif isinstance(decision, DirectSummarize):
                logger.info(f"代理决策: [直接总结]，原因: '{decision.reason}'")
                return original_content

        except Exception as e:
            logger.error(f"代理决策过程出错: {e}，将回退到直接总结。", exc_info=True)
            return original_content
            
        return original_content

    async def _search_and_get_content(self, query: str, original_content: str) -> str:
        """
        执行搜索，获取新内容，并与原始内容合并。
        """
        logger.info(f"正在执行搜索: {query}")
        try:
            with DDGS() as ddgs:
                results = [r for r in ddgs.text(query, max_results=3)]

            if not results:
                logger.warning(f"未能找到关于 '{query}' 的任何搜索结果。")
                return original_content
            
            top_result = results[0]
            search_url = top_result['href']
            logger.info(f"找到最佳搜索结果链接: {search_url}")

            new_content_info = await self.content_extractor._fetch_content_with_reader(search_url)

            if new_content_info and new_content_info.get('content'):
                logger.info("成功从搜索结果中提取到新内容。")
                enriched_content = f"""
[原始介绍性内容]
{original_content}

---

[补充搜索到的核心内容]
来源URL: {search_url}
标题: {new_content_info.get('title')}
内容:
{new_content_info.get('content')}
"""
                return enriched_content
            else:
                logger.warning("从搜索结果链接中提取内容失败，将使用原始内容。")
                return original_content

        except Exception as e:
            logger.error(f"搜索或提取新内容时出错: {e}", exc_info=True)
            return original_content
    
    async def generate_structured_note(self, article_content: str, conversation_context: str) -> StructuredNote:
        """
        使用LLM和Instructor生成结构化的笔记内容。
        (从 LLMService 移入)
        """
        prompt = f"""
# Role: 你是一位资深的技术研究分析师。

# Background: 你正在整理一份研究笔记。你收到了三份信息：一份是文章/论文的主要内容，一份是围绕这篇文章的相关对话，一份是可能的补充材料。

# Primary Goal: 你的核心任务是**为未来的自己**提炼出文章最关键的价值点，生成一段高度浓缩、富有洞察力的总结。这份总结应该能让你在几个月后迅速回忆起这项研究的核心贡献。

# Input Data:
1.  **[文章内容]**: 这是分析的主要对象。它可能包含原始文章和补充搜索到的材料。
2.  **[对话上下文]**: 这份内容仅用作**理解的透镜**。它可以帮你：
    -   **聚焦重点**: 对话中反复讨论的部分，可能是文章的重点。
    -   **纠正偏差**: 如果对话指出了原文中可能被误解的地方，你的总结应体现出更正后的理解。
    -   **绝对不要**在最终总结中直接引用对话内容。

# Output Requirement (The `summary` field):
-   **必须使用中文**: 你的最终输出必须是流畅的中文。
-   **精炼为王 (2-3句话)**: 总结的核心是简洁。请用2-3句话精准概括。这需要你深入思考，回答诸如"这篇文章解决了什么核心问题？"和"它的关键思想/方法是什么？"这类问题。
-   **量化结果**: 如果文章提及其效果，请用关键实验数据来支撑。例如，"通过XXX方法，在YYY任务上将准确率从A%提升到B%"。
-   **杜绝套话**: 严禁使用"本文揭示了...的障碍"或"为未来研究提供了...路径"这类泛泛而谈的句子。你的总结必须具体、有料。
-   **按需扩展 (4-5句话)**: 仅当文章包含多个、同等重要的核心贡献，无法在3句话内概括时，才扩展至4-5句话。
-   **形成段落**: 将你的洞察编织成一段连贯、流畅的段落，而非要点列表。

---
[对话上下文]
{conversation_context}

---
[文章内容]
{article_content[:15000]} # 增加内容长度限制以处理更丰富的上下文
---

请基于以上要求，生成结构化的笔记。
"""
        try:
            note = await self.llm_service.aclient.chat.completions.create(
                model=self.llm_service.model,
                response_model=StructuredNote,
                messages=[
                    {"role": "user", "content": prompt},
                ],
                max_retries=2,
            )
            logger.info("LLM成功生成了高质量的结构化笔记。")
            return note
        except Exception as e:
            logger.error(f"使用Instructor生成结构化笔记失败: {e}", exc_info=True)
            raise 