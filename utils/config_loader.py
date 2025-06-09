#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
配置加载器
负责加载和验证配置文件
"""

import json
import os
from pathlib import Path
from typing import Dict, Any
from loguru import logger
from dotenv import load_dotenv, find_dotenv


class ConfigLoader:
    """配置加载器"""
    
    @staticmethod
    def load(config_path: Path) -> Dict[str, Any]:
        """
        加载配置文件，并从环境变量中合并敏感信息。
        """
        # 步骤1: 加载.env文件，使其内容可用于os.getenv
        load_dotenv(find_dotenv())
        logger.info(".env文件已加载（如果存在）。")
        
        try:
            # 步骤2: 从config.json加载基础配置
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 步骤3: 从环境变量覆盖或补充配置
            ConfigLoader._apply_env_vars(config)
            
            # 步骤4: 验证合并后的配置
            ConfigLoader._validate_config(config)
            
            # 步骤5: 处理路径转换
            ConfigLoader._process_paths(config)
            
            # 步骤6: 设置默认值
            ConfigLoader._set_defaults(config)
            
            return config
            
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}")
        except Exception as e:
            raise Exception(f"加载配置文件失败: {e}")
    
    @staticmethod
    def _apply_env_vars(config: Dict[str, Any]):
        """将环境变量中的值应用到配置字典中"""
        
        # OpenAI配置
        config.setdefault('openai', {})
        openai_key = os.getenv('OPENAI_API_KEY')
        openai_base_url = os.getenv('OPENAI_BASE_URL')
        if openai_key:
            config['openai']['api_key'] = openai_key
            logger.info("已从环境变量加载 OpenAI API Key。")
        if openai_base_url:
            config['openai']['base_url'] = openai_base_url
            logger.info("已从环境变量加载 OpenAI Base URL。")

        # Jina AI配置
        config.setdefault('jina', {})
        jina_key = os.getenv('JINA_API_KEY')
        if jina_key:
            config['jina']['api_key'] = jina_key
            logger.info("已从环境变量加载 Jina API Key。")

        # 代理配置
        config.setdefault('proxy', {})
        proxy_url = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')
        if proxy_url and not config['proxy'].get('https'):
            config['proxy']['https'] = proxy_url
            logger.info(f"已从环境变量加载 HTTPS 代理: {proxy_url}")
        
        # 确保代理设置能被其他库识别
        if config['proxy'].get('https'):
            os.environ['HTTPS_PROXY'] = config['proxy']['https']
            os.environ['https_proxy'] = config['proxy']['https']
    
    @staticmethod
    def _validate_config(config: Dict[str, Any]):
        """验证配置的必要字段"""
        # 检查 channel_type
        if 'channel_type' not in config:
            raise ValueError("配置缺少必要字段: channel_type (e.g., js_wechaty, wcf, mac_wechat)")
        
        valid_channels = ['js_wechaty', 'wcf', 'mac_wechat']
        if config['channel_type'] not in valid_channels:
            raise ValueError(f"不支持的 channel_type: '{config['channel_type']}'. 支持的类型: {valid_channels}")

        # 检查通用和特定后端的配置
        required_fields = {
            'openai': ['api_key'],
        }
        
        # 根据后端选择，添加特定的必填字段
        note_backend = config.get('note_backend')
        if note_backend == 'obsidian':
            required_fields['obsidian'] = ['vault_path', 'note_files']
        elif note_backend == 'google_docs':
            required_fields['google_docs'] = ['credentials_file', 'note_files']

        # 检查所有必需的字段
        for main_key, sub_keys in required_fields.items():
            if main_key not in config:
                raise ValueError(f"配置缺少必要部分: {main_key}")
            
            for field in sub_keys:
                if field not in config[main_key] or not config[main_key][field]:
                    raise ValueError(f"配置缺少必要字段: {main_key}.{field}")
                
                # 检查API Key是否为占位符
                if field == 'api_key' and config[main_key][field] in ['YOUR_OPENAI_API_KEY', 'your_openai_api_key_here']:
                    raise ValueError("请在配置文件或环境变量中设置有效的 OpenAI API Key")
    
    @staticmethod
    def _process_paths(config: Dict[str, Any]):
        """处理配置中的路径"""
        # 处理Obsidian vault路径
        if 'obsidian' in config and 'vault_path' in config['obsidian']:
            vault_path = config['obsidian']['vault_path']
            # 展开用户目录
            vault_path = os.path.expanduser(vault_path)
            # 转换为绝对路径
            vault_path = os.path.abspath(vault_path)
            config['obsidian']['vault_path'] = vault_path
    
    @staticmethod
    def _set_defaults(config: Dict[str, Any]):
        """设置默认值"""
        # OpenAI默认值
        openai_defaults = {
            'model': 'gpt-4o-mini',
            'temperature': 0.7,
            'max_tokens': 2000
        }
        # 移除旧的 'proxy' 默认值，因为我们将它移到了独立的 'proxy' 配置段
        if 'proxy' in openai_defaults:
            del openai_defaults['proxy']

        for key, value in openai_defaults.items():
            if key not in config['openai']:
                config['openai'][key] = value
        
        # 内容提取默认值
        if 'content_extraction' not in config:
            config['content_extraction'] = {}
        
        extraction_defaults = {
            'context_time_window': 60,
            'auto_extract_enabled': True,
            'extract_types': ['wechat_article', 'bilibili_video', 'arxiv_paper', 'web_link'],
            'silent_mode': True
        }
        for key, value in extraction_defaults.items():
            if key not in config['content_extraction']:
                config['content_extraction'][key] = value
        
        # RAG默认值
        if 'rag' not in config:
            config['rag'] = {}
        
        rag_defaults = {
            'enabled': True,
            'embedding_model': 'text-embedding-ada-002',
            'chunk_size': 1000,
            'chunk_overlap': 200,
            'top_k': 5,
            'similarity_threshold': 0.7
        }
        for key, value in rag_defaults.items():
            if key not in config['rag']:
                config['rag'][key] = value
        
        # 系统默认值
        if 'system' not in config:
            config['system'] = {}
        
        system_defaults = {
            'log_level': 'INFO',
            'message_queue_size': 100,
            'auto_save_interval': 300,
            'timezone': 'Asia/Shanghai'
        }
        for key, value in system_defaults.items():
            if key not in config['system']:
                config['system'][key] = value 