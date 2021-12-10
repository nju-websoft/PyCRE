FROM python:3.8.11
RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple \
	&& pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple 
COPY python3_analyze.py /scripts/dynamic_analyze.py