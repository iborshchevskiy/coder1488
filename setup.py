from setuptools import setup, find_packages

setup(
    name="crypto-accounting",
    version="1.0.0",
    description="A comprehensive cryptocurrency accounting and tax reporting system",
    packages=find_packages(),
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "crypto-accounting=crypto_accounting.cli:main",
        ],
    },
)
