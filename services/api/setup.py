from setuptools import find_packages, setup


setup(
    name="rover-api",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.111.0",
        "pydantic>=2.7.0",
        "pydantic-settings>=2.3.0",
        "uvicorn[standard]>=0.30.0",
    ],
)
