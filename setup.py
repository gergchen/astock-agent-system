"""Setup for astock-data package."""

from setuptools import setup, find_packages

with open("requirements.txt", encoding="utf-8") as f:
    install_requires = [line.strip() for line in f if line.strip() and not line.startswith("#")]

setup(
    name="astock-data",
    version="2.0.0",
    description="A股全栈数据工具包 — 6-layer, 15-endpoint A-share market data",
    long_description=open("README.md", encoding="utf-8").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="Simon Lin & gergchen",
    url="https://github.com/gergchen/a-stock-data",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=install_requires,
    entry_points={
        "console_scripts": [
            "astock=astock_data.cli:app",
            "astock-trade=astock_trade.cli:app",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Financial and Insurance Industry",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
    ],
)
