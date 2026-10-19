# -*- coding: utf-8 -*-
"""对象存储访问层（当前只有阿里云 OSS）。

刻意不 import rag_demo.config：config 会 import torch，而 mvp 的独立调试服务
要求毫秒级启动、不碰 torch，它也要上传图片。本包只读环境变量。
"""
