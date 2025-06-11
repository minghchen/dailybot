#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
笔记管理器 (高级协调器)
负责根据配置初始化并协调不同的笔记后端服务（如Obsidian或Google Docs）。
"""

import re
import json
from typing import Dict, Any, List, Optional, Literal
from loguru import logger
from pydantic import BaseModel, Field

from services.google_docs_manager import GoogleDocsManager
from services.obsidian_manager import ObsidianManager


class InsertionDecision(BaseModel):
    """
    一个Pydantic模型，用于规范LLM关于内容插入位置的决策。
    """
    thought: str = Field(..., description="对为何做出此决策的简要中文解释。")
    decision: Literal["insert_under_leaf", "insert_into_miscellaneous", "create_new_subheading"] = Field(..., description="最终决策。")
    target_heading: Optional[str] = Field(None, description="当决策为 'insert_under_leaf' 时，目标叶子节点的完整文本。")
    parent_heading: Optional[str] = Field(None, description="当决策为 'insert_into_miscellaneous' 或 'create_new_subheading' 时，父级现有标题的完整文本。")
    new_heading_text: Optional[str] = Field(None, description="当决策是 'create_new_subheading' 时，新子标题的文本（不应是文章标题）。")


class NoteManager:
    """
    笔记管理器。
    作为一个外观（Facade），将请求路由到具体的后端笔记管理器。
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化笔记管理器
        
        Args:
            config: 全局应用配置
        """
        self.config = config
        self.note_backend_name = config.get('note_backend', 'obsidian')
        self.backend_manager = None
        self.llm_service = None

        if self.note_backend_name == 'obsidian':
            obsidian_config = config.get('obsidian', {})
            self.backend_manager = ObsidianManager(obsidian_config)
            self.note_files_config = obsidian_config.get('note_files', [])
        elif self.note_backend_name == 'google_docs':
            gdocs_config = config.get('google_docs', {})
            self.backend_manager = GoogleDocsManager(gdocs_config)
            self.note_files_config = gdocs_config.get('note_files', [])
        else:
            raise ValueError(f"不支持的笔记后端: {self.note_backend_name}")

        logger.info(f"笔记管理器初始化成功，使用后端: {self.note_backend_name}")
    
    def set_llm_service(self, llm_service: Any):
        """
        设置LLM服务，并将其注入到具体的后端管理器中。
        """
        self.llm_service = llm_service
        if self.backend_manager and hasattr(self.backend_manager, 'set_llm_service'):
            self.backend_manager.set_llm_service(llm_service)
            logger.info(f"LLM服务已成功注入到 {self.note_backend_name} 管理器。")
    
    async def save_content(self, content_data: Dict[str, Any]):
        """
        将提取的内容路由到相应的后端管理器进行保存。
        这是一个包含两步LLM决策的完整流程。
        
        Args:
            content_data: 从ContentExtractor提取并处理过的内容数据。
        """
        if not self.backend_manager:
            logger.error("没有可用的笔记后端管理器，无法保存内容。")
            return
        
        # 步骤 1: 全局查重
        if await self._check_for_duplicates(content_data):
            log_title = content_data.get('structured_note', {}).get('title', '未知标题')
            logger.info(f"内容 '{log_title}' 已在笔记库中存在，跳过保存。")
            return

        if not self.llm_service:
            logger.error("LLM服务未设置，无法执行智能分类和保存。")
            # TODO: 在此可以实现一个不依赖LLM的简单保存逻辑作为后备
            return

        logger.info(f"NoteManager开始处理内容 '{content_data.get('structured_note', {}).get('title', '')}'，后端: {self.note_backend_name}")
        
        try:
            # --- 步骤 2: 使用LLM选择目标笔记文件 ---
            target_doc_config = await self._select_target_document_with_llm(content_data)
            if not target_doc_config:
                logger.error("未能确定目标笔记文件，取消保存。")
                return

            # --- 步骤 3: 获取文档结构 ---
            doc_id_or_path = target_doc_config.get('document_id') if self.note_backend_name == 'google_docs' else self.backend_manager.get_full_path(target_doc_config)
            
            doc_structure = await self.backend_manager.get_document_structure(doc_id_or_path)
            if not doc_structure:
                logger.error(f"无法获取文档 {doc_id_or_path} 的结构，取消保存。")
                return

            # --- 步骤 4: 使用LLM决定在文件内的插入位置 ---
            logger.info("正在调用LLM以决定内容的最佳插入位置...")
            decision = await self._decide_insertion_location_with_llm(content_data, doc_structure)
            logger.info(f"LLM决策: {decision.decision} | 目标: '{decision.target_heading or decision.parent_heading}' | 新标题: '{decision.new_heading_text}' | 理由: {decision.thought}")

            # --- 步骤 5: 根据决策计算具体的插入指令 ---
            insert_location = self._calculate_insert_location(decision, doc_structure)
            
            # --- 步骤 6: 指示后端管理器执行保存操作 ---
            await self.backend_manager.execute_save(
                doc_id_or_path, 
                content_data, 
                insert_location,
                document=doc_structure.get('raw_document') # 传递预加载的文档以优化
            )

        except Exception as e:
            logger.error(f"NoteManager 在处理保存流程时发生异常: {e}", exc_info=True)
            raise
    
    async def _select_target_document_with_llm(self, content_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """第一步决策：使用LLM根据内容和文件描述，选择最合适的笔记文件。"""
        if not self.note_files_config:
            raise ValueError(f"后端 '{self.note_backend_name}' 没有在config.json中配置任何 'note_files'。")
        
        if len(self.note_files_config) == 1:
            logger.info("只有一个可用的笔记文件，将直接选择它。")
            return self.note_files_config[0]

        title = content_data.get('structured_note', {}).get('title', '')
        summary = content_data.get('structured_note', {}).get('gist', '')

        options_str = "\n".join([
            f"{i+1}. 文件名: {f.get('name', '未命名')}\n   描述: {f.get('description', '无描述')}"
            for i, f in enumerate(self.note_files_config)
        ])

        prompt = f"""
你是一位笔记管理员，需要决定一篇新笔记应该归入哪个笔记文件。

[笔记内容]
- 标题: {title}
- 摘要: {summary}

[可选的笔记文件]
{options_str}

[你的任务]
请分析笔记内容和每个文件的描述，选择最匹配的 **文件编号**。

[输出格式]
请严格按照以下格式回答，只返回一个数字，不要添加任何其他解释：
文件编号: [一个数字]
"""
        
        try:
            response = await self.llm_service.chat(prompt)
            match = re.search(r'\d+', response)
            if match:
                file_idx = int(match.group(0)) - 1
                if 0 <= file_idx < len(self.note_files_config):
                    selected_doc = self.note_files_config[file_idx]
                    logger.info(f"LLM选择了文件: '{selected_doc.get('name')}'")
                    return selected_doc
        except Exception as e:
            logger.error(f"LLM选择文件失败: {e}", exc_info=True)
        
        logger.warning("LLM选择文件失败，将回退到第一个文件。")
        return self.note_files_config[0]
    
    async def _decide_insertion_location_with_llm(self, content_data: Dict[str, Any], doc_structure: Dict[str, Any]) -> InsertionDecision:
        """第二步决策：调用LLM来决定新内容在文件内的最佳插入位置。"""
        # --- 根据配置选择分类策略 ---
        strategy_key = self.config.get('note_management', {}).get('classification_strategy', 'balanced')
        
        strategy_instructions = {
            "cautious_filer": """
# Role: 你是一位极其谨慎的档案管理员，首要任务是避免错误分类。

1.  **第一优先级 (insert_into_miscellaneous)**: 这是你的默认和首选操作。除非满足下一条的**严格**条件，否则总是将内容放入最相关父标题下的"其他"分类中。
2.  **第二优先级 (insert_under_leaf)**: 只有当新内容的主题与某个"叶子节点"的标题**完全一致或主题高度重合**时，才允许你将内容放入该叶子节点下。如果你有任何一丝犹豫，就退回使用第一优先级。
3.  **第三优先级 (create_new_subheading)**: **（严格禁止）** 绝对不要创建新的子标题。
""",
            "diligent_categorizer": """
# Role: 你是一位勤奋的图书管理员，目标是尽可能地将每一份资料都精准归档到现有的分类中。

1.  **第一优先级 (insert_under_leaf)**: 请尽你最大的努力，在"叶子节点列表"中寻找一个**最相关**的现有标题，即使主题不是100%完全匹配，只要它是最合理的归宿即可。这是你的首要目标。
2.  **第二优先级 (insert_into_miscellaneous)**: 仅当你在所有叶子节点中都**找不到任何一个**合适的归宿时，才允许将内容放入相关父标题的"其他"分类中。
3.  **第三优先级 (create_new_subheading)**: **（几乎不用）** 只有在内容与所有现有分类都完全无关，且确实需要一个全新分类时，才考虑此选项。
""",
            "balanced": """
# Role: 你是一位经验丰富的图书管理员，追求效率和结构之间的平衡。

1.  **第一优先级 (insert_under_leaf)**: 检查新内容是否与"叶子节点列表"中的某个标题主题**高度匹配**。如果是，这是最优先的选择。
2.  **第二优先级 (insert_into_miscellaneous)**: 如果找不到高度匹配的叶子，将内容放入最相关父标题的"其他"分类中，这是一个安全的选择。
3.  **第三优先级 (create_new_subheading)**: 如果内容确实代表了一个在父标题下非常重要且**缺失**的子分类，可以创建一个新的子标题来优化结构。请不要轻易使用此选项。
""",
            "aggressive": """
# Role: 你是一位富有远见的架构师，目标是主动构建和优化知识库的结构。

1.  **第一优先级 (create_new_subheading)**: 新内容是否可以作为一个现有标题下的、逻辑清晰的**新子分类**？如果是，请大胆地创建新子标题，这是丰富文档结构的最佳方式。
2.  **第二优先级 (insert_under_leaf)**: 如果无法创建有意义的新子标题，再检查内容是否与某个已有的"叶子节点"**高度匹配**。
3.  **第三优先级 (insert_into_miscellaneous)**: 仅当内容与整个文档结构都无关时，才使用此选项。
"""
        }
        
        selected_instructions = strategy_instructions.get(strategy_key, strategy_instructions['balanced'])
        logger.info(f"正在使用 '{strategy_key}' 分类策略。")

        tree_str = self._format_headings_as_tree(doc_structure['headings'])
        title = content_data.get('structured_note', {}).get('title', '')
        summary = content_data.get('structured_note', {}).get('gist', '')

        # 预处理，找出所有的叶子节点
        headings = doc_structure['headings']
        leaf_nodes = self._get_leaf_nodes(headings)
        leaf_nodes_str = "\n".join([f"- {node['text']}" for node in leaf_nodes]) or "无"

        prompt = f"""
你是一位图书管理员，你的任务是根据一份现有文档的目录结构，将一份新内容精准地归类。
你的行为模式由你的角色决定，请严格遵循。

{selected_instructions}

[文档现有目录结构]
```
{tree_str if tree_str else "此文档为空。"}
```

[可供直接归类的叶子节点列表]
{leaf_nodes_str}

[待插入的新内容]
- 标题: {title}
- 摘要: {summary}

[注意]
- **禁止创建新的一级标题**，除非文档完全为空。
- 你的目标是维护一个整洁、有序的笔记结构，而不是随意扩张。

请仔细思考并用中文解释你的决策过程，然后做出最终决策。
"""
        
        # 如果文档为空，则强制创建新的一级标题
        if not headings:
            return InsertionDecision(
                thought="文档为空，必须创建一个新的一级标题来存放内容。",
                decision="create_new_subheading", # 在_calculate_insert_location中会处理成一级标题
                parent_heading=None,
                new_heading_text=(content_data.get('structured_note', {}).get('title', '未命名内容'))
            )

        return await self.llm_service.aclient.chat.completions.create(
            model=self.llm_service.model,
            response_model=InsertionDecision,
            messages=[{"role": "user", "content": prompt}],
            max_retries=2,
        )

    def _get_leaf_nodes(self, headings: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """从标题列表中识别出所有的叶子节点（没有子标题的标题）。"""
        leaf_nodes = []
        for i, heading in enumerate(headings):
            is_leaf = True
            # 检查后续的标题
            for j in range(i + 1, len(headings)):
                next_heading = headings[j]
                # 如果下一个标题的层级更高，说明当前标题不是叶子
                if next_heading['level'] > heading['level']:
                    is_leaf = False
                    break
                # 如果遇到同级或更低级别的标题，说明已经超出了当前子树
                if next_heading['level'] <= heading['level']:
                    break
            if is_leaf:
                leaf_nodes.append(heading)
        return leaf_nodes

    def _format_headings_as_tree(self, headings: List[Dict[str, Any]]) -> str:
        """将标题列表格式化为缩进的树状结构字符串。"""
        tree_lines = []
        for heading in headings:
            indent = "  " * (heading['level'] - 1)
            tree_lines.append(f"{indent}- {heading['text']} (层级 {heading['level']})")
        return "\n".join(tree_lines)

    def _calculate_insert_location(self, decision: InsertionDecision, doc_structure: Dict[str, Any]) -> Dict[str, Any]:
        """根据LLM的决策计算出具体的插入位置和操作。"""
        headings_map = {h['text'].strip(): h for h in doc_structure['headings']}
        doc_end_pos_raw = doc_structure['end_of_document']

        # 针对不同后端调整在文档末尾插入的位置
        if self.note_backend_name == 'google_docs':
            # Google Docs API要求插入点必须严格小于段落的endIndex
            doc_end_pos = max(1, doc_end_pos_raw - 1)
        else:
            # 对于Obsidian（基于行号），末尾位置是正确的
            doc_end_pos = doc_end_pos_raw

        decision_action = decision.decision
        
        if decision_action == "insert_under_leaf":
            target_heading_text = (decision.target_heading or "").strip()
            if target_heading_text in headings_map:
                insertion_pos = self._find_end_of_section(headings_map[target_heading_text], doc_structure)
                return { "action": "insert_under", "position": insertion_pos }

        elif decision_action == "insert_into_miscellaneous":
            parent_heading_text = (decision.parent_heading or "").strip()
            if parent_heading_text in headings_map:
                parent_heading = headings_map[parent_heading_text]
                
                # 如果父标题本身就是"其他"，直接在其末尾插入
                if parent_heading['text'].strip() in ["其他", "未分类", "Miscellaneous"]:
                    insertion_pos = self._find_end_of_section(parent_heading, doc_structure)
                    return { "action": "insert_under", "position": insertion_pos }

                # 否则，寻找或创建"其他"子标题
                existing_misc_heading = self._find_subheading(parent_heading, ["其他", "未分类", "Miscellaneous"], doc_structure)
                
                if existing_misc_heading:
                    insertion_pos = self._find_end_of_section(existing_misc_heading, doc_structure)
                    return { "action": "insert_under", "position": insertion_pos }
                else:
                    insertion_pos = self._find_end_of_section(parent_heading, doc_structure)
                    return {
                        "action": "create_new_heading",
                        "position": insertion_pos,
                        "new_heading_text": "其他",
                        "new_heading_level": parent_heading['level'] + 1
                    }

        elif decision_action == "create_new_subheading":
            parent_heading_text = (decision.parent_heading or "").strip()
            if parent_heading_text in headings_map:
                parent_heading = headings_map[parent_heading_text]
                insertion_pos = self._find_end_of_section(parent_heading, doc_structure)
                return {
                    "action": "create_new_heading",
                    "position": insertion_pos,
                    "new_heading_text": (decision.new_heading_text or "新分类").strip(),
                    "new_heading_level": parent_heading['level'] + 1
                }

        # Fallback for any failed/missing heading cases, or for empty docs
        logger.warning(f"LLM决策 '{decision.decision}' 的目标标题 '{decision.target_heading or decision.parent_heading}' 未找到，或出现其他回退情况。将在文档末尾创建新的一级标题。")
        return {
           "action": "create_new_heading",
           "position": doc_end_pos,
           "new_heading_text": (decision.new_heading_text or decision.thought[:30]).strip(),
           "new_heading_level": 1
        }

    def _find_end_of_section(self, target_heading: Dict[str, Any], doc_structure: Dict[str, Any]) -> int:
        """找到指定标题区域的末尾位置。"""
        headings = doc_structure['headings']
        target_level = target_heading['level']
        
        # 确定文档末尾的正确位置
        if self.note_backend_name == 'google_docs':
            doc_end_pos = max(1, doc_structure['end_of_document'] - 1)
        else:
            doc_end_pos = doc_structure['end_of_document']

        try:
            start_index = headings.index(target_heading)
            # 从目标标题之后开始寻找
            for i in range(start_index + 1, len(headings)):
                next_heading = headings[i]
                if next_heading['level'] <= target_level:
                    # 找到了下一个同级或更高级别的标题，在其开始处插入
                    # 对于Google Docs，需要-1来插入到前一个段落的末尾
                    return next_heading['startIndex'] - 1 if self.note_backend_name == 'google_docs' else next_heading['startIndex']
            # 如果没找到，说明目标标题是文档最后一个区域
            return doc_end_pos
        except ValueError:
            return doc_end_pos

    def _find_subheading(self, parent_heading: Dict[str, Any], subheading_texts: List[str], doc_structure: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """在父标题下寻找特定的子标题。"""
        headings = doc_structure['headings']
        parent_level = parent_heading['level']
        
        try:
            parent_index = headings.index(parent_heading)
            for i in range(parent_index + 1, len(headings)):
                subsequent_heading = headings[i]
                if subsequent_heading['level'] <= parent_level:
                    break # 已离开子标题范围
                if subsequent_heading['level'] == parent_level + 1 and subsequent_heading['text'].strip() in subheading_texts:
                    return subsequent_heading
            return None
        except ValueError:
            return None

    def get_note_files_config(self) -> List[Dict[str, Any]]:
        """返回当前后端的所有笔记文件配置。"""
        return self.note_files_config

    async def search_in_document(self, doc_config: Dict[str, Any], query: str, group_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取文档的纯文本内容，然后在其上执行通用的搜索和过滤逻辑。
        """
        if not self.backend_manager or not hasattr(self.backend_manager, 'get_document_text'):
            logger.warning(f"后端 {self.note_backend_name} 不支持 'get_document_text' 方法。")
            return []

        # 1. 从后端获取纯文本
        content = await self.backend_manager.get_document_text(doc_config)
        if not content:
            return []

        # 2. 根据后端类型，应用不同的解析和搜索策略
        if self.note_backend_name == 'obsidian':
            return self._search_in_obsidian_content(content, query, group_filter)
        elif self.note_backend_name == 'google_docs':
            return self._search_in_gdocs_content(content, query, group_filter)
        
        return []

    def _search_in_obsidian_content(self, content: str, query: str, group_filter: Optional[str]) -> List[Dict[str, Any]]:
        """在Obsidian的Markdown内容中搜索笔记条目。"""
        # 每个条目以加粗的日期标题开始
        entries = re.split(r'\n(?=\*\*[0-9])', content)
        results = []
        query_lower = query.lower()
        metadata_pattern = re.compile(r'<!-- metadata: (.*) -->')

        for entry in entries:
            if not entry.strip() or query_lower not in entry.lower():
                continue

            metadata = {}
            passes_filter = True
            metadata_match = metadata_pattern.search(entry)
            if metadata_match:
                try:
                    metadata = json.loads(metadata_match.group(1))
                    if group_filter and metadata.get('group_name') != group_filter:
                        passes_filter = False
                except json.JSONDecodeError:
                    pass # 忽略格式错误的元数据
            
            elif group_filter: # 需要过滤但没有元数据
                passes_filter = False

            if passes_filter:
                title_match = re.search(r'\*\*(.*?)\*\*', entry)
                title = title_match.group(1) if title_match else "无标题条目"
                results.append({'title': title, 'text': entry.strip(), 'metadata': metadata})
        
        return results

    def _search_in_gdocs_content(self, content: str, query: str, group_filter: Optional[str]) -> List[Dict[str, Any]]:
        """在Google Docs的纯文本内容中搜索段落。"""
        if group_filter:
            logger.warning("Google Docs后端的搜索当前不支持按群组过滤。")

        results = []
        paragraphs = content.split('\n\n')
        query_lower = query.lower()
        
        for i, paragraph in enumerate(paragraphs):
            if query_lower in paragraph.lower():
                # 尝试从段落中提取一个标题行
                first_line = paragraph.split('\n', 1)[0]
                results.append({
                    'text': paragraph[:500] + ('...' if len(paragraph) > 500 else ''),
                    'title': first_line if len(first_line) < 100 else '相关段落',
                    'position': i
                })
        
        return results

    async def _check_for_duplicates(self, content_data: Dict[str, Any]) -> bool:
        """遍历所有已配置的笔记文件，检查是否存在重复内容。"""
        logger.debug("开始全局查重...")
        for file_config in self.note_files_config:
            is_dup = await self.backend_manager.is_duplicate_in_document(file_config, content_data)
            if is_dup:
                return True
        logger.debug("全局查重完成，未发现重复内容。")
        return False 