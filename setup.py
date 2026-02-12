from setuptools import setup, find_packages
import os
import re

def get_version():
    init = open(os.path.join("logosai", "__init__.py")).read()
    return re.search("__version__ = \"([^\"]+)\"", init).group(1)

def get_requirements():
    with open('requirements.txt') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="logosai",
    version=get_version(),
    author="LogosAI Team",
    author_email="contact@logosai.com",
    description="AI Agent Development Framework",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/logosai/logosai",
    packages=find_packages(exclude=["logosai.examples", "logosai.examples.*"]),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.8",
    install_requires=get_requirements(),
    include_package_data=True,
) 