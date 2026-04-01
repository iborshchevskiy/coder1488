from setuptools import setup, find_packages

setup(
    name="crypto-accounting",
    version="2.0.0",
    description="A comprehensive cryptocurrency accounting, tax reporting, and portfolio system",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.110",
        "uvicorn[standard]>=0.27",
        "python-multipart>=0.0.9",
        "requests>=2.31",
        "jinja2>=3.1",
    ],
    entry_points={
        "console_scripts": [
            "crypto-accounting=crypto_accounting.cli:main",
            "crypto-accounting-web=crypto_accounting.web.server:main",
        ],
    },
)
