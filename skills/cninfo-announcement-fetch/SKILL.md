---
name: cninfo-announcement-fetch
description: 当需要从巨潮资讯网自动检索、分类拉取、下载上市公司公告 PDF，并把公告作为 phoenix-main / xdev / agentic-extract 的本地输入数据时使用本 skill。适用于按公告类别、关键词、日期区间、股票代码批量获取公告元数据和 PDF。
---

# 巨潮网公告拉取

## 适用场景

使用本 skill 处理以下需求：

- 从巨潮资讯网按类别拉取公告，例如年报、半年报、季报、临时公告、董事监事高管变动公告。
- 按股票代码、关键词、日期区间筛选公告。
- 保存公告元数据、下载 PDF，并作为 Phoenix 后续抽取任务的输入。
- 将新下载的 PDF 导入已有 workspace，或创建新 workspace 后用 `agentic-extract auto` 处理。

默认项目根目录：

```text
D:\claude-test\phe\phoenix-main
```

## 数据源与边界

巨潮历史公告查询使用：

```text
POST http://www.cninfo.com.cn/new/hisAnnouncement/query
```

PDF 下载使用公告返回的 `adjunctUrl` 拼接：

```text
http://static.cninfo.com.cn/<adjunctUrl>
```

股票代码到 `orgId` 的解析使用：

```text
POST http://www.cninfo.com.cn/new/information/topSearch/query
```

注意：

- 巨潮网接口不是正式稳定开放 API，字段、类别编码、限流策略可能变化。每次批量任务开始前应先用小页数 smoke test。
- 不要高并发抓取。默认串行、分页、带 sleep；如遇 403、429、连接重置，应降低频率或暂停。
- 下载的公告仅作为公开披露文件的本地副本，后续使用要遵守巨潮网和交易所的使用条款。
- 巨潮网公告查询包含深沪京、港股、基金、债券等栏目。港股年报可以先从巨潮港股栏目快速检索和下载；如果用户要求 HKEX 原始披露文件，或巨潮港股栏目没有目标文件，再转到 HKEX 披露易。

## 港股 PDF 拉取规则

当用户明确要求“港股年报”“H 股年报”，或给出 `01211.HK`、`03968.HK`、`02196.HK` 这类港股代码时，优先使用巨潮港股栏目检索；不要拿同一公司的 A 股/科创板公告替代港股栏目文件。

### 判定规则

拉取前先判定任务类型：

- 港股代码通常为 5 位数字加 `.HK`，例如 `01211.HK`、`03968.HK`、`02196.HK`。
- 巨潮页面 URL 中港股栏目通常带 `#hke/1_hkeMain` 或 `#hke/1_hkeGem`。
- 港股主板使用 `column=hke`、`plate=hkmb`；港股创业板使用 `column=hke`、`plate=hkcy`。
- 港股公司的 `orgId` 常见格式为 `gshk0001211`，查询参数中的 `stock` 应为 `01211,gshk0001211`。
- 返回结果中 `pageColumn` 为 `HKZB` 等港股栏目值，可视为巨潮港股栏目文件。
- 如果返回结果的 `secCode` 是 A 股代码，或 `pageColumn` 为 `SHKCB`、`SZZB`、`SZSE`、`SSE` 等境内栏目，不要把它当港股年报。

### 巨潮港股接口参数

巨潮港股栏目仍使用历史公告接口：

```text
POST http://www.cninfo.com.cn/new/hisAnnouncement/query
```

关键参数：

```text
column=hke
tabName=fulltext
plate=hkmb        # 港主板；港创业板用 hkcy
stock=01211,gshk0001211
searchkey=年报     # 港股年报可用标题关键词筛选
category=         # 港股栏目通常不使用深沪京年报分类码
seDate=2025-03-20~2025-03-30
```

示例页面：

```text
http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search&code=01211&name=比亚迪股份&orgId=gshk0001211#hke/1_hkeMain
```

脚本调用示例：

```powershell
uv run python docs/skills/cninfo-announcement-fetch/scripts/fetch_cninfo_announcements.py `
  --market hke `
  --stock-code 01211 `
  --category annual_report `
  --start-date 2025-03-20 `
  --end-date 2025-03-30 `
  --page-size 50 `
  --max-pages 1 `
  --download `
  --output-dir local/hk_annual_report_tests/source_downloads/byd_01211_2024_cninfo_hke
```

说明：

- `--market hke` 会把 `column` 设置为 `hke`。
- 未显式传 `--plate` 时，港股默认使用 `hkmb`。
- 港股栏目下 `--category annual_report` 会自动转为标题关键词 `年报`，不再使用深沪京的 `category_ndbg_szsh`。
- 如需精确控制，也可以直接传 `--column hke --plate hkmb --keyword "年报"`。

### 保存目录

港股 PDF 不放入普通 `local/cninfo_announcements/` 目录。统一使用：

```text
local/hk_annual_report_tests/source_downloads/<company>_<hk-code>_<year>_cninfo_hke/
  metadata.json
  metadata.jsonl
  pdfs/
    <date>_<hk-code>_<announcementId>_<title>.pdf
```

进入某个 Phoenix 测试用例时，再复制或下载到：

```text
local/hk_annual_report_tests/<case-id>/
  input/
    <doc-id>.pdf
  logs/
    fetch_hkex_*.txt
    process_record.md
```

示例：

```text
local/hk_annual_report_tests/source_downloads/byd_01211_2024/
local/hk_annual_report_tests/byd_01211_2024_parent_cashflow/input/byd_01211_2024_annual.pdf
```

### PDF 验证规则

下载后必须验证它确实来自巨潮港股栏目且是年报：

- PDF 首页或前几页包含 `Annual Report`、`年報`、`年度报告` 等年报标题。
- PDF 正文或封面包含港股代码或 H 股信息，例如 `H shares: 01211`、`Stock Code: 01211`、`股份代號：01211`。
- 元数据中 `secCode` 为港股代码，`orgId` 类似 `gshk...`，`pageColumn` 为 `HKZB` 等港股栏目。
- PDF URL 通常是 `http://static.cninfo.com.cn/finalpage/<date>/<announcementId>.PDF`，这是巨潮静态文件地址；来源元数据必须保存为巨潮港股栏目。
- 如果公司同时有 A 股代码，过程记录必须区分港股代码和 A 股代码。

可使用 PyMuPDF、`pdftotext` 或 `pdf-ai-explorer` 保存验证证据。验证日志放在用例 `logs/` 下，例如：

```text
logs/verify_hkex_pdf.txt
```

### HKEX 兜底或交叉验证

如果用户明确要求“HKEX 原始披露文件”，或巨潮港股栏目没有目标年报，可再去 HKEX 披露易检索。HKEX PDF 链接常见形式：

```text
https://www.hkexnews.hk/listedco/listconews/sehk/<YYYY>/<MMDD>/<pdf-id>.pdf
```

HKEX 文件保存目录建议使用后缀 `_hkex`，例如：

```text
local/hk_annual_report_tests/source_downloads/byd_01211_2024_hkex/
```

过程记录中必须说明本次使用的是 `cninfo_hke` 还是 `hkex` 来源。

### 接入 Phoenix

巨潮港股 PDF 验证通过后，再按普通 PDF 导入：

```powershell
uv run xdev import-data `
  --add-pdf local/hk_annual_report_tests/<case-id>/input/<doc-id>.pdf `
  --data-dir local/workspaces/<workspace-name>/.xdev `
  --force
```

后续必须补齐 `.xdev/labels/<doc-id>.json`，再运行：

```powershell
uv run xdev run <doc-id> --data-dir local/workspaces/<workspace-name>/.xdev --workspace local/workspaces/<workspace-name>
uv run xdev eval <doc-id> --data-dir local/workspaces/<workspace-name>/.xdev --workspace local/workspaces/<workspace-name>
```

如果这是泛化测试且 eval 不通过，按 `phoenix-annual-report-extract` 的迭代规则修复 `program.py`，并保留 `.agent_state` 记录。

## 输出约定

默认保存到：

```text
local/cninfo_announcements/<run-id>/
```

如果任务明确是“港股年报测试”或需要和 Phoenix workspace、抽取结果、日志放在同一个测试目录，则优先使用：

```text
local/hk_annual_report_tests/<case-id>/
  input/
  workspace/
  outputs/
  logs/
```

不要把同一个测试的 PDF、workspace、抽取结果和过程日志分散到多个 `local/` 子目录。

目录结构：

```text
local/cninfo_announcements/<run-id>/
  metadata.json
  metadata.jsonl
  pdfs/
    <date>_<secCode>_<announcementId>_<title>.pdf
```

其中：

- `metadata.json`：完整公告列表和本次查询参数。
- `metadata.jsonl`：每行一条公告，方便增量处理。
- `pdfs/`：当启用下载时保存 PDF。

## 最短路径

先做 1 页 smoke test，只抓元数据：

```powershell
uv run python docs/skills/cninfo-announcement-fetch/scripts/fetch_cninfo_announcements.py `
  --category annual_report `
  --start-date 2024-01-01 `
  --end-date 2024-12-31 `
  --page-size 2 `
  --max-pages 1 `
  --output-dir local/cninfo_announcements/smoke_annual_2024
```

确认返回正常后下载 PDF：

```powershell
uv run python docs/skills/cninfo-announcement-fetch/scripts/fetch_cninfo_announcements.py `
  --category annual_report `
  --start-date 2024-01-01 `
  --end-date 2024-12-31 `
  --page-size 30 `
  --max-pages 5 `
  --download `
  --output-dir local/cninfo_announcements/annual_2024_sample
```

按股票代码拉取：

```powershell
uv run python docs/skills/cninfo-announcement-fetch/scripts/fetch_cninfo_announcements.py `
  --stock-code 000001 `
  --category annual_report `
  --start-date 2023-01-01 `
  --end-date 2024-12-31 `
  --download `
  --output-dir local/cninfo_announcements/000001_annual
```

按关键词拉取董事、监事辞职公告：

```powershell
uv run python docs/skills/cninfo-announcement-fetch/scripts/fetch_cninfo_announcements.py `
  --keyword "董事 监事 辞职" `
  --start-date 2024-01-01 `
  --end-date 2024-12-31 `
  --download `
  --output-dir local/cninfo_announcements/director_supervisor_resign_2024
```

## 常用类别

脚本内置了常用别名：

```text
annual_report        -> category_ndbg_szsh
semiannual_report    -> category_bndbg_szsh
quarterly_report     -> category_yjdbg_szsh
ipo                  -> category_szzb_szsh
bond                 -> category_zqgg_szsh
```

如果需要使用巨潮网页上的其他类别编码，直接传真实编码：

```powershell
--category category_ndbg_szsh
```

对于类别编码不确定的任务，优先使用 `--keyword` 加日期区间小批量检索，再从返回公告的 `announcementType`、`columnId`、`pageColumn` 中归纳需要的筛选规则。

## 接入 Phoenix

下载 PDF 后，有两条常用路径。

### 环境初始化

在运行 `xdev import-data`、`xdev sync-pdfs`、`agentic-extract auto/run` 之前，先确认 `ppx` 可以被当前进程找到。项目内置脚本：

```powershell
.\scripts\setup_phoenix_env.ps1
```

如果希望后续新 PowerShell 会话也能直接找到 `ppx`、`xdev` 和 `agentic-extract`，在本机手动执行一次：

```powershell
.\scripts\setup_phoenix_env.ps1 -PersistUserPath
```

该脚本会把 `D:\claude-test\phe\phoenix-main\.venv\Scripts` 追加到 Windows 用户级 `PATH`，设置当前进程的 UTF-8 环境变量，并创建/设置项目内 `UV_CACHE_DIR=local\uv-cache`。注意：直接运行 `.\.venv\Scripts\xdev.exe` 不会自动把同目录的 `ppx.exe` 加入 `PATH`，所以 `xdev` 内部调用 `ppx` 时仍可能报“找不到 ppx”。

### 新任务 bootstrap

```powershell
uv run agentic-extract auto `
  --workspace local/workspaces/<workspace-name> `
  --pdfs-dir local/cninfo_announcements/<run-id>/pdfs `
  --message "请基于这些巨潮公告 PDF 定义并抽取用户需要的字段。所有过程记录和最终总结使用中文。"
```

### 导入已有 workspace

```powershell
uv run xdev import-data `
  --add-pdf local/cninfo_announcements/<run-id>/pdfs `
  --data-dir local/workspaces/<workspace-name>/.xdev `
  --force
```

导入已有 workspace 后，仍需按该 workspace 的 schema 和业务文档补齐 labels，之后再运行：

```powershell
uv run xdev run <doc_id> --data-dir local/workspaces/<workspace-name>/.xdev --workspace local/workspaces/<workspace-name>
uv run xdev eval <doc_id> --data-dir local/workspaces/<workspace-name>/.xdev --workspace local/workspaces/<workspace-name>
```

## 质量控制

批量抓取时必须记录：

- 查询参数：日期、类别、关键词、股票代码、页数。
- 返回总数：`totalAnnouncement` / `totalRecordNum` / `totalpages`。
- 实际保存条数和下载成功/失败数量。
- 每个失败 PDF 的 URL、HTTP 状态和异常信息。

如果后续进入 Phoenix 抽取流程，最终回复用户时至少说明：

- 巨潮查询条件。
- 元数据目录。
- PDF 目录。
- 下载成功数量和失败数量。
- 是否已经导入 workspace。
- 下一步应补 labels、运行 `xdev eval`，还是启动 `agentic-extract auto/run`。
