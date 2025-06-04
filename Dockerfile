FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir wechaty-puppet-service

# 复制项目文件
COPY . .

# 创建必要的目录
RUN mkdir -p data logs config

# 设置环境变量默认值
ENV PYTHONUNBUFFERED=1
ENV TZ=Asia/Shanghai

# 运行应用
CMD ["python", "app.py"] 