"""Compatibility build entry point for the Python 3.10 ROS Humble runtime."""

from setuptools import find_packages, setup


setup(
    name="rover-api",
    version="0.1.0",
    description="FastAPI backend scaffold for rover platform",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "fastapi>=0.111.0",
        "pydantic>=2.7.0",
        "pydantic-settings>=2.3.0",
        "uvicorn[standard]>=0.30.0",
        "httpx>=0.27.0",
    ],
    extras_require={
        "dev": ["httpx>=0.27.0", "pytest>=8.2.0"],
    },
)
