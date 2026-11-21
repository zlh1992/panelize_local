#!/usr/bin/env python3
import argparse
import getpass
import os
import tempfile
from pathlib import Path

p = argparse.ArgumentParser(description='在终端隐藏输入，写入本机私有密钥文件')
p.add_argument('name',choices=['deepseek','minimax'])
args = p.parse_args()
root = Path.home()/'.config/panelize-local'
root.mkdir(parents=True,mode=0o700,exist_ok=True)
secret = getpass.getpass(args.name+' key: ').strip()
if not secret: p.error('密钥为空')
with tempfile.NamedTemporaryFile('w',dir=root,delete=False) as f:
    f.write(secret+'\n')
os.replace(f.name,root/(args.name+'.key'))
print('已保存到本机。')
