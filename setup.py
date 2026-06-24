# Legacy shim — 메타데이터는 전적으로 pyproject.toml 에서 읽는다.
# 존재 이유: setuptools < 64 (예: Ubuntu 22.04 기본 59.6.0) 은 PEP 660 의
# build_editable 훅이 없어 'pip install -e' 가 실패한다. setup.py 가 있으면
# pip 이 레거시 editable(develop) 경로로 폴백하여 구버전에서도 설치된다.
from setuptools import setup

setup()
