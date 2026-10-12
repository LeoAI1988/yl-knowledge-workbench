# 开发与验证

本仓库维护一份通用源码；个人 profile、头像、运行数据库与真实资料放在项目之外。已有本地目录采用默认排除、显式允许的 Git 清单，请检查新增文件是否应公开。

## 环境

Python 3.12+、Node.js 20+、pnpm 10。安装依赖并构建：

```text
python -m pip install -r plugin/requirements.txt
pnpm install --frozen-lockfile
pnpm build
python -B -m unittest test_workbench test_reading test_portable test_release -q
node tools/test_plugin.cjs
python -B package_plugin.py
```

`dist/` 是已构建前端，插件安装包会包含它。打包采用显式文件清单、固定时间戳和排序，输出逐文件 FILES.json 与 ZIP SHA-256。同一版本已有不同字节时拒绝重建，需增加版本。构建不联网发布。

## 目录职责

| 文件 | 职责 |
|---|---|
| ui/ | React 知识阅读、选题、聊天和资料库 |
| plugin/ | Obsidian 入口、设置、iframe 和无窗口后台启动 |
| server.py | 本机 HTTP、灵感、任务、对话与草稿保存 |
| markdown_vault.py | 普通 Markdown / 属性 / 双向链接适配 |
| knowledge.py | 已有 YL 数据格式适配与共用读取 |
| astra.py | 通过本机 Codex app-server 进行纯文本/JSON 推理 |
| tools/install.py | 清单验证、备份升级、配置保留 |
| tools/demo.py | 创建独立演示数据，不进行推理 |

## 运行演示

```text
python -B tools/demo.py --directory .local/demo
python -B server.py --profile .local/demo/profile.json --port 8877
```

浏览器访问 http://127.0.0.1:8877/ 。演示脚本只创建新目录，已有目录会拒绝覆盖。Markdown 来自 examples，选题分析、初稿和聊天是明确标注的预置内容；没有假装实际模型生成。运行时数据不进入 Git。

公开截图均来自这一真实前端，以本地浏览器的默认视口拍摄；阅读模式使用产品自身全屏功能。详见 [图册](gallery.md)。

## 发布检查

1. 审阅代码、文档、截图、示例和第三方许可，排除私人数据。
2. 构建前端，运行行为测试；隔离验证安装、幂等、升级保留与篡改拒绝。
3. 验证包内每个文件与源码字节一致，重复打包 SHA-256 一致。
4. Git diff / staged 清单复核，提交、推送、tag、Release 附件分别核对。
5. 匿名下载 ZIP 比较 SHA-256；检查 README 图片和文档链接。

AI 测试使用隔离替身，不消耗真实推理额度，不能证明不同账号与模型的输出质量。Windows 桌面行为已实机验证；其他系统仍需独立实机验证。当前发布未配置 GitHub Actions；上述脚本在本机执行。

[返回首页](../README.md)

