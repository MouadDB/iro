#!/usr/bin/env python3
"""
Setup script for Incident Response Orchestrator (IRO).
"""

from setuptools import setup, find_packages
import pathlib

here = pathlib.Path(__file__).parent.resolve()

# Get the long description from the README file
long_description = (here / "README.md").read_text(encoding="utf-8")

setup(
    name="incident-response-orchestrator",
    version="1.0.0",
    description="Automated incident detection and remediation for Kubernetes",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/MouadDB/iro",
    author="Your Organization",
    author_email="support@yourorg.com",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
        "Topic :: System :: Monitoring",
        "Topic :: System :: Systems Administration",
    ],
    keywords="kubernetes, incident-response, automation, monitoring, sre",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    python_requires=">=3.9",
    install_requires=[
        "asyncio>=3.4.3",
        "aiohttp>=3.8.0",
        "aiohttp-cors>=0.7.0",
        "pydantic>=2.0.0",
        "PyYAML>=6.0",
        "kubernetes>=24.2.0",
        "google-generativeai>=0.3.0",
        "google-cloud-monitoring>=2.11.0",
        "numpy>=1.21.0",
        "pandas>=1.5.0",
        "python-dateutil>=2.8.0",
        "dataclasses-json>=0.6.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "pytest-cov>=4.0.0",
            "black>=22.0.0",
            "flake8>=5.0.0",
            "mypy>=1.0.0",
        ],
        "monitoring": [
            "prometheus-client>=0.15.0",
            "psutil>=5.9.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "iro=iro.main:main",
        ],
    },
    project_urls={
        "Bug Reports": "https://github.com/MouadDB/iro/issues",
        "Source": "https://github.com/MouadDB/iro",
        "Documentation": "https://iro.readthedocs.io/",
    },
)