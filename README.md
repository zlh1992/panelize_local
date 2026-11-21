# panelize_local

在终端用同一份中文或英文问题并行调用四个助手，得到每一路的最终文本、耗时、状态和本地对比页。第一版面向文本问答和材料分析。各助手保留自己的系统提示、网页能力与工具策略，结果用于比较实际使用体验。

```bash
./compare.sh --query '用三句话说明自由现金流与净利润的区别'
./compare.sh --query-file question.md --targets codex,minimax,doubao,deepseek
printf '%s\n' '请列出材料中的三个假设。' | ./compare.sh --targets codex,deepseek
```

| 目标 | 默认配置 | 成功依据 |
| --- | --- | --- |
| codex | 本地 Codex CLI，ChatGPT 登录，gpt-6.2-sol，high | 进程正常退出、turn.completed、最终文本文件非空 |
| minimax | 本地 Claude Code，MiniMax 国内 Anthropic 兼容入口，MiniMax-M3 | Claude JSON 返回 success 和非空 result，另存服务端报告的 modelUsage 名称 |
| doubao | 当前安装本地扩展的 Chrome profile，打开豆包新会话 | 本轮用户文本匹配，随后有回复正文，观察到复制操作或已结束的生成状态，正文稳定，保存会话 URL |
| deepseek | 官方 DeepSeek Harness headless，deepseek-official，deepseek-flash | 进程正常退出并收到完成原因标记为 completed 的 final 事件和非空文本 |

每次在当前目录的 `runs/<时间>-<随机编号>/` 生成 `query.md`、各目标的 JSON、成功目标的 Markdown、`results.json` 和 `index.html`。终端先打印目录，随后逐路报告状态。全部成功退出 0，部分失败退出 1，已成功的答案可继续查看。按目标重新运行会创建新目录。模型参数表示请求的配置，网页未披露的底层模型记为未知。

## 第一次配置

支持 macOS、Python 3.9+、Bash 和 Google Chrome。本机已验证 macOS；Linux 提供了 Chrome Native Messaging 注册路径，尚未实机验证。DSH 需要 Node.js >=24.9 和 npm。CLI 依赖按需安装，只运行部分目标时只配置对应凭据。

1. **Codex**：使用支持本项目选项的 Codex CLI，并用 ChatGPT 订阅登录。项目优先使用终端 PATH 中的 `codex`。macOS 终端找不到命令时，会自动检查 `/Applications` 和 `~/Applications` 下的 ChatGPT 或 Codex 应用包。若安装在自定义位置，可用 `PANELIZE_CODEX` 显式指定 CLI 可执行文件的绝对路径，该设置优先于自动查找。默认读取 `~/.codex/auth.json`，可以用 `--codex-auth <文件>` 指定。worker 使用私有加锁运行目录、只读沙箱和临时任务目录。网络需要代理时，可把本机可用的 HTTP 代理 URL 单独写到 `~/.config/panelize-local/codex-proxy`。也支持 HTTP_PROXY 和 HTTPS_PROXY。指定代理文件只影响 Codex 子进程。
2. **Claude Code + MiniMax**：安装支持 `--bare`、`--tools` 和 JSON 输出的 Claude Code。执行 `python3 scripts/configure.py minimax`，输入可用于 Claude Code 的 MiniMax 套餐密钥。也支持环境变量 `MINIMAX_API_KEY`。默认使用 `https://api.minimaxi.com/anthropic`，海外套餐可设 `PANELIZE_MINIMAX_URL=https://api.minimax.io/anthropic`。每次启动独立进程与临时配置目录。实际计费由密钥绑定的套餐决定。
3. **DeepSeek**：运行 `bash scripts/install-dsh.sh`，安装固定版本 `@deepseek-ai/dsh@0.2.2-rc.5` 到 `~/.local/share/panelize-local/dsh`。运行 `python3 scripts/configure.py deepseek` 隐藏输入 API key，或设置 `DEEPSEEK_API_KEY`。如果已安装其他位置的 dsh，可用 `PANELIZE_DSH` 指定可执行文件。每次运行生成独立模型 patch、临时 DSH_HOME 和空工作目录，以只读模式调用官方 API。
4. **豆包网页**：在想使用的 Chrome profile 登录豆包，运行 `python3 scripts/setup-chrome.py`。进入 `chrome://extensions`，打开开发者模式，点「加载已解压的扩展程序」，选本仓库 `extension/`。扩展只声明豆包站点权限，使用 Chrome Native Messaging 与本用户的 Unix socket 通信。点击扩展图标可重新连接，也会定时重连。一次只在一个 profile 加载。移动仓库后，重新注册并从新路径加载扩展。
5. 用一个容易核对答案的短问题运行一次。豆包标签页保留供核验；若表现为登录页、验证码或挂起，可在该标签页处理登录，再单独运行 `--targets doubao`。发送后超时请先检查页面，以免重复消费。收集器依赖豆包当前 DOM，页面改版可能需要更新选择器。

密钥文件由配置脚本以 0600 写入仓库外。默认结果目录已被 Git 忽略。提问会被发送到选中的提供方。移除豆包集成时从 Chrome 移除扩展并删除 setup 脚本注册的 `local.panelize.compare.json`；私有密钥与本地历史由用户自行管理。

## 参数与 Magpie

```bash
./compare.sh --query-file question.md \
  --targets codex,minimax,deepseek,doubao \
  --codex-model gpt-6.2-sol --effort high \
  --minimax-model MiniMax-M3 --deepseek-model deepseek-v4-pro \
  --timeout 180 --out ./runs
```

Magpie 是可选依赖。已有 Magpie 网关、Claude 启动配置和已测试的 MiniMax 路由时，可传 `--magpie-model '提供方ID/模型ID'`。此时 MiniMax 分支运行 `magpie claude run` 并传递非交互参数。选显式模型、检查 model_usage，避免将有自动回退的模型组当作固定模型。该选项使用网关凭据，优先于直接订阅配置。本机验收覆盖直接 MiniMax 路线；Magpie 启动路线需要独立配置和验证。

## 复用和验证

- [Panelize](https://github.com/Manho/Panelize/tree/fb9cc70d4c38bf13a5ebb7bf4b76abad107ce2c1) 提供豆包输入框适配、富文本填充、发送按钮查找；抽取的代码放在 `extension/vendor/`，保留 MIT 许可证。本项目增加终端任务分发、逐轮回答回收、完整性判定和输出。运行豆包不依赖另行安装 Panelize 主扩展。
- [Magpie](https://github.com/yetone/magpie/blob/a53f08e11dede7319e785d7259b1d580f2c2c3bd/internal/cli/claude_launch_cli.go) 提供可选的隔离启动入口。默认 MiniMax 模式借鉴其按进程选上游的方式。Codex 两个 worker 文件复用本机 panelize-multi-agent 的文本运行时，并增加高推理力度与独立代理配置。
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness) 使用官方 npm 包、原生 headless 和 JSON 事件，不需要单独启动网页服务。
- 单元测试：`python3 -m unittest discover -s tests -v`。浏览器夹具测试（需要 Python Playwright 和 Chromium）：`python3 tests/browser_fixture.py [--executable Chromium路径]`，覆盖完整回复、既有会话保护等路径。夹具测试不消耗模型额度。真实四路验收须在已配置账号的机器上运行首段命令，并检查四条记录均为 completed。
