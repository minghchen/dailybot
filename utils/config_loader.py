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
        加载配置文件
        
        Args:
            config_path: 配置文件路径
            
        Returns:
            配置字典
        """
        # 加载.env文件
        load_dotenv(find_dotenv())
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            # 从环境变量覆盖敏感配置
            ConfigLoader._load_env_vars(config)
            
            # 验证配置
            ConfigLoader._validate_config(config)
            
            # 处理路径
            ConfigLoader._process_paths(config)
            
            # 设置默认值
            ConfigLoader._set_defaults(config)
            
            return config
            
        except FileNotFoundError:
            raise FileNotFoundError(f"配置文件不存在: {config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"配置文件格式错误: {e}")
        except Exception as e:
            raise Exception(f"加载配置文件失败: {e}")
    
    @staticmethod
    def _load_env_vars(config: Dict[str, Any]):
        """从环境变量加载配置"""
        # OpenAI配置
        if 'openai' not in config:
            config['openai'] = {}
        
        # 从环境变量获取API密钥
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            config['openai']['api_key'] = api_key
            logger.info("从环境变量加载 OpenAI API Key")
        
        # 从环境变量获取base URL
        base_url = os.getenv('OPENAI_BASE_URL')
        if base_url:
            config['openai']['base_url'] = base_url
            logger.info("从环境变量加载 OpenAI Base URL")
        
        # --- 代理配置加载 ---
        # 优先从 config.json 的 'proxy' 部分加载
        proxy_config = config.get('proxy', {})
        https_proxy_from_config = proxy_config.get('https')

        # 如果配置文件中没有，则尝试从环境变量加载
        https_proxy_from_env = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy')

        # 确定最终使用的代理
        final_https_proxy = https_proxy_from_config or https_proxy_from_env

        if final_https_proxy:
            source = "配置文件(config.json)" if https_proxy_from_config else "环境变量"
            logger.info(f"从 {source} 加载了 HTTPS 代理: {final_https_proxy}")
            # 确保代理设置能被google-api-python-client等库识别
            os.environ['HTTPS_PROXY'] = final_https_proxy
            os.environ['https_proxy'] = final_https_proxy # 兼容某些库的大小写需求
    
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
        
        # 根据笔记后端检查特定字段
        note_backend = config.get('note_backend', 'obsidian')
        if note_backend == 'obsidian':
            required_fields['obsidian'] = ['vault_path']
        elif note_backend == 'google_docs':
            required_fields['google_docs'] = ['credentials_file', 'note_documents']

        for section, fields in required_fields.items():
            if section not in config:
                raise ValueError(f"配置缺少必要部分: {section}")
            
            for field in fields:
                if field not in config[section] or not config[section][field]:
                    raise ValueError(f"配置缺少必要字段: {section}.{field}")
                
                # 检查API Key是否为占位符
                if field == 'api_key' and config[section][field] in ['YOUR_OPENAI_API_KEY', 'your_openai_api_key_here']:
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