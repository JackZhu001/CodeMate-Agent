#!/bin/bash
# CodeMate AI 启动脚本

CONDA_PATH="/Users/zyxsmac/miniconda3"
ENV_NAME="codemate"

cd "$(dirname "$0")"

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "❌ 未找到 .env 文件，正在创建..."
    cp .env.example .env
    echo "✅ 已创建 .env 文件"
    echo ""
    echo "请编辑 .env 文件，填入你的 API_KEY："
    echo "  vim .env  # 或 nano .env"
    echo ""
    exit 1
fi

# 检查 API Key 是否配置
if grep -q "your_api_key_here" .env; then
    echo "❌ 请先在 .env 文件中配置 API_KEY"
    echo "  vim .env"
    exit 1
fi

# 运行
echo "🚀 启动 CodeMate AI..."
$CONDA_PATH/bin/conda run -n $ENV_NAME python -m codemate_agent.cli "$@"
