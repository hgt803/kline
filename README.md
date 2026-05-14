# 项目环境说明

在项目根目录下可以使用 `Makefile` 快速创建虚拟环境并安装依赖：

```bash
make install
```

手动步骤：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

激活虚拟环境（在当前 shell 中）：

```bash
source .venv/bin/activate
```

验证 akshare 是否可用：

```bash
python -c "import akshare; print(akshare.__version__)"
```
