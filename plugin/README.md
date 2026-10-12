# YL 知识工作台 0.3.0

知识阅读、表达资产、作品资料、灵感和选题增强集中在一个桌面工作台。

## 安装

1. 安装 Python 3.12+，运行一次：`python -m pip install "PyYAML>=6,<7"`。
2. 将整个 yl-knowledge-workbench 文件夹放入库的 .obsidian/plugins/，包含 backend。
3. 在 Obsidian 第三方插件启用「知识工作台」，设置 Python 完整路径，点击「应用并打开」。
4. 日常点侧栏网络图标即可。Windows 自动使用 pythonw.exe，不依赖终端。

可选校验安装：`python install.py --vault "你的库目录" --dry-run`；去掉 --dry-run 安装，升级加 --upgrade。升级前等任务完成并关闭 Obsidian 和对应后台。安装器备份已登记文件并保留 data.json；修改过的核心拒绝覆盖。

## 使用

普通 Markdown 进入原始资料；笔记属性 type: OPI / SOL / CON / CAS 对应观点/方法/概念/案例，expression 对应表达，work 对应作品。domains 填领域，可多选。真实双向链接关联知识与作品。标签不等于已完成蒸馏。

问答、增强和初稿需要本机 Codex 已登录，使用自己的模型权限与额度。默认模型 ID gpt-6-astra，可在插件设置更改；推理经过 Codex 服务，不是离线 GPT。浏览和保存灵感不需要模型。

## 资料

原文件留在自己的库；新灵感在 03_选题库/灵感，初稿在 02_我的作品全集/工作台草稿。普通库的配置/分析/聊天保存在用户目录 .config/yl-workbench/<库标识>；已有 YL 配置沿用原位置。请同时备份库和运行目录。

默认排除隐藏目录、node_modules、80_私人档案、90_系统资料、符号链接，以及 privacy: P2/P3/private 或 index: false 的笔记。workbench.exclude_folders 可添加排除目录名。调用模型会发送本次所需材料和近期对话。

本包不含作者原文、头像、业务数据或凭据。正式蒸馏通过 YL Skills；实时热度、平台发布、公开分身服务未接入。播放档位是未校准的编辑暂估。

当前 Windows 桌面试用版，未上架社区市场，不支持手机；macOS/Linux 未实机验证。原创代码 MIT，第三方许可见 THIRD_PARTY_NOTICES.txt。

[完整教程和截图](https://github.com/LeoAI1988/yl-knowledge-workbench) · [问题反馈](https://github.com/LeoAI1988/yl-knowledge-workbench/issues)

