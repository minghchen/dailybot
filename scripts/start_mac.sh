#!/bin/bash
# Mac微信通道启动脚本

echo "==================================="
echo "DailyBot Mac微信通道启动器"
echo "==================================="

# 检查操作系统
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "❌ 此脚本仅支持macOS系统"
    exit 1
fi

# 检查微信是否运行
if ! pgrep -x "WeChat" > /dev/null; then
    echo "⚠️  请先启动微信并登录"
    exit 1
fi

# 检查sqlcipher
if ! command -v sqlcipher &> /dev/null; then
    echo "❌ 未安装sqlcipher，正在安装..."
    brew install sqlcipher
fi

# 检查Python
if ! command -v python3 &> /dev/null; then
    echo "❌ 未安装Python 3"
    exit 1
fi

# 检查配置文件
if [ ! -f "config/config.json" ]; then
    echo "📝 未找到配置文件，正在创建..."
    if [ -f "config/config.example.json" ]; then
        cp config/config.example.json config/config.json
        echo "✅ 已创建配置文件 config/config.json"
        echo "⚠️  请编辑配置文件设置你的Obsidian路径和群组白名单"
        exit 0
    else
        echo "❌ 未找到示例配置文件"
        exit 1
    fi
fi

# 询问运行模式
echo ""
echo "请选择运行模式："
echo "1. 静默模式（推荐）- 自动整理笔记"
echo "2. Hook模式 - 支持自动回复（需要关闭SIP）"
echo ""
read -p "请输入选择 [1]: " mode

if [ "$mode" == "2" ]; then
    export MAC_WECHAT_USE_HOOK=true
    echo "✅ 已启用Hook模式"
else
    echo "✅ 使用静默模式"
fi

# 启动
echo ""
echo "🚀 正在启动DailyBot..."
echo "提示：首次运行可能需要输入系统密码以访问微信数据库"
echo ""

python3 app.py 