#!/bin/bash
# DailyBot 快速启动脚本

set -e

echo "======================================"
echo "DailyBot 快速启动脚本"
echo "======================================"

# 检查是否有 config.json
if [ ! -f config/config.json ]; then
    if [ -f config/config.example.json ]; then
        echo "正在从示例创建配置文件..."
        cp config/config.example.json config/config.json
        echo "已创建 config/config.json，请根据需要修改配置"
    else
        echo "错误：未找到配置文件"
        exit 1
    fi
fi

# 创建必要的目录
mkdir -p data logs config

# 使用 Docker Compose 启动
echo "使用 Docker Compose 启动..."

# 检查是否安装了 docker-compose
if command -v docker-compose &> /dev/null; then
    docker-compose up -d --build
elif docker compose version &> /dev/null; then
    docker compose up -d --build
else
    echo "错误：未安装 Docker Compose"
    echo "请先安装 Docker 和 Docker Compose"
    exit 1
fi

echo ""
echo "DailyBot 已在后台启动！"
echo "查看日志：docker-compose logs -f"
echo "停止服务：docker-compose down" 